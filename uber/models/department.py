from datetime import timedelta

from sideboard.lib import cached_property
from sideboard.lib.sa import CoerceUTF8 as UnicodeText, \
    UTCDateTime, UUID
from sqlalchemy import select
from sqlalchemy.orm import column_property
from sqlalchemy.schema import ForeignKey, Table, UniqueConstraint
from sqlalchemy.types import Boolean, Float, Integer

from uber.config import c
from uber.models import MagModel
from uber.models.attendee import Attendee
from uber.models.types import default_relationship as relationship, \
    Choice, DefaultColumn as Column


__all__ = [
    'department_membership_job_role', 'department_membership_request',
    'job_required_job_role', 'Department', 'DepartmentMembership', 'Job',
    'JobRole', 'Shift']


department_membership_job_role = Table(
    'department_membership_job_role',
    MagModel.metadata,
    Column('department_membership_id', UUID,
           ForeignKey('department_membership.id')),
    Column('job_role_id', UUID, ForeignKey('job_role.id')))


department_membership_request = Table(
    'department_membership_request',
    MagModel.metadata,
    Column('attendee_id', UUID, ForeignKey('attendee.id')),
    Column('department_id', UUID, ForeignKey('department.id'), nullable=True),
    UniqueConstraint('attendee_id', 'department_id'))


job_required_job_role = Table(
    'job_required_job_role',
    MagModel.metadata,
    Column('job_id', UUID, ForeignKey('job.id')),
    Column('job_role_id', UUID, ForeignKey('job_role.id')))


class DepartmentMembership(MagModel):

    DEPARTMENT_HEAD = 100
    TRUSTED = 200
    REGULAR = 300
    BANNED = 500

    STATUS_OPTS = [
        (DEPARTMENT_HEAD, 'Department Head'),
        (TRUSTED, 'Trusted'),
        (REGULAR, 'Regular'),
        (BANNED, 'Banned')]
    STATUSES = dict(STATUS_OPTS)

    status = Column(Choice(STATUS_OPTS), default=REGULAR)
    attendee_id = Column(UUID, ForeignKey('attendee.id'))
    department_id = Column(UUID, ForeignKey('department.id'))

    job_roles = relationship(
        'JobRole',
        backref='department_memberships',
        secondary='department_membership_job_role',
        cascade=False)

    __table_args__ = (UniqueConstraint('attendee_id', 'department_id'),)


class Department(MagModel):
    name = Column(UnicodeText)
    description = Column(UnicodeText)
    accepts_volunteers = Column(Boolean, default=True)
    parent_id = Column(UUID, ForeignKey('department.id'), nullable=True)

    jobs = relationship('Job', backref='department')
    job_roles = relationship('JobRole', backref='department')
    department_heads = relationship(
        'Attendee',
        backref='headed_depts',
        primaryjoin='and_('
                    'Department.id==DepartmentMembership.department_id, '
                    'DepartmentMembership.status=={})'.format(
                        DepartmentMembership.DEPARTMENT_HEAD),
        secondaryjoin='DepartmentMembership.attendee_id==Attendee.id',
        secondary='department_membership',
        viewonly=True,
        cascade=False)
    members = relationship(
        'Attendee',
        backref='assigned_depts',
        secondary='department_membership',
        cascade=False)
    membership_requests = relationship(
        'Attendee',
        backref='requested_depts',
        secondary='department_membership_request',
        cascade=False)
    sub_departments = relationship(
        'Department',
        backref='parent',
        remote_side='Department.id',
        single_parent=True)
    trusted_members = relationship(
        'Attendee',
        backref='trusted_depts',
        primaryjoin='and_('
                    'Department.id==DepartmentMembership.department_id, '
                    'DepartmentMembership.status<={})'.format(
                        DepartmentMembership.TRUSTED),
        secondaryjoin='DepartmentMembership.attendee_id==Attendee.id',
        secondary='department_membership',
        viewonly=True,
        cascade=False)

    # all_jobs
    # all_roles
    # all_members
    # all_sub_departments


class JobRole(MagModel):
    name = Column(UnicodeText)
    description = Column(UnicodeText)
    department_id = Column(UUID, ForeignKey('department.id'))


class Job(MagModel):
    type = Column(Choice(c.JOB_TYPE_OPTS), default=c.REGULAR)
    name = Column(UnicodeText)
    description = Column(UnicodeText)
    start_time = Column(UTCDateTime)
    duration = Column(Integer)
    weight = Column(Float, default=1)
    slots = Column(Integer)
    restricted = Column(Boolean, default=False)
    extra15 = Column(Boolean, default=False)
    department_id = Column(UUID, ForeignKey('department.id'))

    location = column_property(
        select([Department.name]).where(Department.id == department_id))

    required_job_roles = relationship(
        'JobRole',
        backref='jobs',
        secondary='job_required_job_role',
        cascade=False)
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

        return self.session.query(Attendee) \
            .filter(Attendee.assigned_depts.contains(location)) \
            .filter(*trusted_depts_filter) \
            .filter_by(**{'staffing': True} if staffing_only else {}) \
            .order_by(order_by) \
            .all()

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
        return "{}'s {!r} shift".format(self.attendee.full_name, self.job.name)
