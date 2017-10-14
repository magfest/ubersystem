from datetime import datetime, timedelta

import cherrypy
from pytz import UTC
from sideboard.lib import cached_property
from sideboard.lib.sa import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy.orm import backref
from sqlalchemy.schema import ForeignKey, UniqueConstraint
from sqlalchemy.types import Boolean, Date, Float, Integer

from uber.config import c
from uber.decorators import presave_adjustment
from uber.models import MagModel
from uber.models.attendee import Attendee
from uber.models.types import default_relationship as relationship, utcnow, \
    Choice, DefaultColumn as Column, MultiChoice


__all__ = [
    'AdminAccount', 'PasswordReset', 'WatchList', 'DeptChecklistItem',
    'Job', 'Shift']


class AdminAccount(MagModel):
    attendee_id = Column(UUID, ForeignKey('attendee.id'), unique=True)
    hashed = Column(UnicodeText)
    access = Column(MultiChoice(c.ACCESS_OPTS))

    password_reset = relationship(
        'PasswordReset', backref='admin_account', uselist=False)

    def __repr__(self):
        return '<{}>'.format(self.attendee.full_name)

    @staticmethod
    def is_nick():
        return AdminAccount.admin_name() in c.JERKS

    @staticmethod
    def admin_name():
        try:
            from uber.models import Session
            with Session() as session:
                return session.admin_attendee().full_name
        except:
            return None

    @staticmethod
    def admin_email():
        try:
            from uber.models import Session
            with Session() as session:
                return session.admin_attendee().email
        except:
            return None

    @staticmethod
    def access_set(id=None):
        try:
            from uber.models import Session
            with Session() as session:
                id = id or cherrypy.session['account_id']
                return set(session.admin_account(id).access_ints)
        except:
            return set()


class PasswordReset(MagModel):
    account_id = Column(UUID, ForeignKey('admin_account.id'), unique=True)
    generated = Column(UTCDateTime, server_default=utcnow())
    hashed = Column(UnicodeText)

    @property
    def is_expired(self):
        return self.generated < datetime.now(UTC) - timedelta(days=7)


class WatchList(MagModel):
    first_names = Column(UnicodeText)
    last_name = Column(UnicodeText)
    email = Column(UnicodeText, default='')
    birthdate = Column(Date, nullable=True, default=None)
    reason = Column(UnicodeText)
    action = Column(UnicodeText)
    active = Column(Boolean, default=True)
    attendees = relationship(
        'Attendee', backref=backref('watch_list', load_on_pending=True))

    @presave_adjustment
    def _fix_birthdate(self):
        if self.birthdate == '':
            self.birthdate = None


class DeptChecklistItem(MagModel):
    attendee_id = Column(UUID, ForeignKey('attendee.id'))
    slug = Column(UnicodeText)
    comments = Column(UnicodeText, default='')

    __table_args__ = (
        UniqueConstraint(
            'attendee_id', 'slug', name='_dept_checklist_item_uniq'),
    )


class Job(MagModel):
    type = Column(Choice(c.JOB_TYPE_OPTS), default=c.REGULAR)
    name = Column(UnicodeText)
    description = Column(UnicodeText)
    location = Column(Choice(c.JOB_LOCATION_OPTS))
    start_time = Column(UTCDateTime)
    duration = Column(Integer)
    weight = Column(Float, default=1)
    slots = Column(Integer)
    restricted = Column(Boolean, default=False)
    extra15 = Column(Boolean, default=False)
    shifts = relationship('Shift', backref='job')

    _repr_attr_names = ['name']

    @property
    def hours(self):
        hours = set()
        for i in range(self.duration):
            hours.add(self.start_time + timedelta(hours=i))
        return hours

    @property
    def end_time(self):
        return self.start_time + timedelta(hours=self.duration)

    def no_overlap(self, attendee):
        before = self.start_time - timedelta(hours=1)
        after = self.start_time + timedelta(hours=self.duration)
        return (
            not self.hours.intersection(attendee.hours)
            and (
                before not in attendee.hour_map
                or not attendee.hour_map[before].extra15
                or self.location == attendee.hour_map[before].location)
            and (
                after not in attendee.hour_map
                or not self.extra15
                or self.location == attendee.hour_map[after].location))

    @property
    def slots_taken(self):
        return len(self.shifts)

    @property
    def slots_untaken(self):
        return max(0, self.slots - self.slots_taken)

    @property
    def is_setup(self):
        return self.start_time < c.EPOCH

    @property
    def is_teardown(self):
        return self.start_time >= c.ESCHATON

    @property
    def real_duration(self):
        return self.duration + (0.25 if self.extra15 else 0)

    @property
    def weighted_hours(self):
        return self.weight * self.real_duration

    @property
    def total_hours(self):
        return self.weighted_hours * self.slots

    def _potential_volunteers(
            self, staffing_only=False, order_by=Attendee.full_name):
        """
        Return a list of attendees who:

            1. Are assigned to this job's location.
            2. Are allowed to work this job (job is unrestricted, or they're
               trusted in this job's location).

        Args:
            staffing_only: Restrict result to attendees where staffing==True.
            order_by: Order by another Attendee attribute.
        """
        location = str(self.location)
        if self.restricted:
            trusted_depts_filter = [Attendee.trusted_depts.contains(location)]
        else:
            trusted_depts_filter = []

        return (self.session.query(Attendee)
                .filter(Attendee.assigned_depts.contains(location))
                .filter(*trusted_depts_filter)
                .filter_by(**{'staffing': True} if staffing_only else {})
                .order_by(order_by)
                .all())

    @property
    def capable_volunteers_opts(self):
        # format output for use with the {{ options() }} template decorator
        return [(a.id, a.full_name) for a in self.capable_volunteers]

    @property
    def capable_volunteers(self):
        """
        Return a list of volunteers who could sign up for this job.

        Important: Just because a volunteer is capable of working
        this job doesn't mean they are actually available to work it.
        They may have other shift hours during that time period.
        """
        return self._potential_volunteers(staffing_only=True)

    @cached_property
    def available_volunteers(self):
        """
        Returns a list of volunteers who are allowed to sign up for
        this Job and have the free time to work it.
        """
        return [
            s for s in self._potential_volunteers(order_by=Attendee.last_first)
            if self.no_overlap(s)]


class Shift(MagModel):
    job_id = Column(UUID, ForeignKey('job.id', ondelete='cascade'))
    attendee_id = Column(UUID, ForeignKey('attendee.id', ondelete='cascade'))
    worked = Column(Choice(c.WORKED_STATUS_OPTS), default=c.SHIFT_UNMARKED)
    rating = Column(Choice(c.RATING_OPTS), default=c.UNRATED)
    comment = Column(UnicodeText)

    @property
    def name(self):
        return "{self.attendee.full_name}'s {self.job.name!r} shift".format(
            self=self)

    @staticmethod
    def dump(shifts):
        return {shift.id: shift.to_dict() for shift in shifts}
