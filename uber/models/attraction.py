from collections import OrderedDict
from datetime import datetime, timedelta

import pytz
from pockets import groupify, listify, sluggify
from residue import JSON, CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy import and_, cast, exists, func, not_
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import backref
from sqlalchemy.schema import ForeignKey, UniqueConstraint
from sqlalchemy.sql import text
from sqlalchemy.sql.expression import bindparam
from sqlalchemy.types import Boolean, Integer

from uber.config import c
from uber.custom_tags import humanize_timedelta, location_event_name, location_room_name
from uber.decorators import presave_adjustment
from uber.models import MagModel, Attendee
from uber.models.types import default_relationship as relationship, Choice, DefaultColumn as Column, utcmin
from uber.utils import evening_datetime, noon_datetime


__all__ = [
    'Attraction', 'AttractionFeature', 'AttractionEvent', 'AttractionSignup',
    'AttractionNotification', 'AttractionNotificationReply']


class Attraction(MagModel):
    _NONE = 0
    _PER_FEATURE = 1
    _PER_ATTRACTION = 2
    _RESTRICTION_OPTS = [(
        _NONE,
        'None – '
        'Attendees can attend as many events as they wish '
        '(least restrictive)'
    ), (
        _PER_FEATURE,
        'Once Per Feature – '
        'Attendees can only attend each feature once'
    ), (
        _PER_ATTRACTION,
        'Once Per Attraction – '
        'Attendees can only attend this attraction once '
        '(most restrictive)'
    )]
    _RESTRICTIONS = dict(_RESTRICTION_OPTS)

    _ADVANCE_CHECKIN_OPTS = [
        (-1, 'Anytime during event'),
        (0, 'When the event starts'),
        (300, '5 minutes before'),
        (600, '10 minutes before'),
        (900, '15 minutes before'),
        (1200, '20 minutes before'),
        (1800, '30 minutes before'),
        (2700, '45 minutes before'),
        (3600, '1 hour before')]

    _ADVANCE_NOTICES_OPTS = [
        ('', 'Never'),
        (0, 'When checkin starts'),
        (300, '5 minutes before checkin'),
        (900, '15 minutes before checkin'),
        (1800, '30 minutes before checkin'),
        (3600, '1 hour before checkin'),
        (7200, '2 hours before checkin'),
        (86400, '1 day before checkin')]

    name = Column(UnicodeText, unique=True)
    slug = Column(UnicodeText, unique=True)
    description = Column(UnicodeText)
    full_description = Column(UnicodeText)
    is_public = Column(Boolean, default=False)
    advance_notices = Column(JSON, default=[], server_default='[]')
    advance_checkin = Column(Integer, default=0)  # In seconds
    restriction = Column(Choice(_RESTRICTION_OPTS), default=_NONE)
    badge_num_required = Column(Boolean, default=False)
    department_id = Column(UUID, ForeignKey('department.id'), nullable=True)
    owner_id = Column(UUID, ForeignKey('admin_account.id'))

    owner = relationship(
        'AdminAccount',
        cascade='save-update,merge',
        backref=backref(
            'attractions',
            cascade='all,delete-orphan',
            uselist=True,
            order_by='Attraction.name'))
    owner_attendee = relationship(
        'Attendee',
        cascade='merge',
        secondary='admin_account',
        uselist=False,
        viewonly=True)
    department = relationship(
        'Department',
        cascade='save-update,merge',
        backref=backref(
            'attractions',
            cascade='save-update,merge',
            uselist=True),
        order_by='Department.name')
    features = relationship(
        'AttractionFeature',
        backref='attraction',
        order_by='[AttractionFeature.name, AttractionFeature.id]')
    public_features = relationship(
        'AttractionFeature',
        primaryjoin='and_('
                    'AttractionFeature.attraction_id == Attraction.id,'
                    'AttractionFeature.is_public == True)',
        viewonly=True,
        order_by='[AttractionFeature.name, AttractionFeature.id]')
    events = relationship(
        'AttractionEvent',
        backref='attraction',
        viewonly=True,
        order_by='[AttractionEvent.start_time, AttractionEvent.id]')
    signups = relationship(
        'AttractionSignup',
        backref='attraction',
        viewonly=True,
        order_by='[AttractionSignup.checkin_time, AttractionSignup.id]')

    @presave_adjustment
    def _sluggify_name(self):
        self.slug = sluggify(self.name)

    @property
    def feature_opts(self):
        return [(f.id, f.name) for f in self.features]

    @property
    def feature_names_by_id(self):
        return OrderedDict(self.feature_opts)

    @property
    def used_location_opts(self):
        locs = set(e.location for e in self.events)
        sorted_locs = sorted(locs, key=lambda l: c.EVENT_LOCATIONS[l])
        return [(loc, c.EVENT_LOCATIONS[loc]) for loc in sorted_locs]

    @property
    def unused_location_opts(self):
        locs = set(e.location for e in self.events)
        return sorted([(loc, s) for loc, s in c.EVENT_LOCATION_OPTS if loc not in locs], key=lambda x: x[1])

    @property
    def advance_checkin_label(self):
        if self.advance_checkin < 0:
            return 'anytime during the event'
        return humanize_timedelta(
            seconds=self.advance_checkin,
            separator=' ',
            now='by the time the event starts',
            prefix='at least ',
            suffix=' before the event starts')

    @property
    def location_opts(self):
        locations = map(lambda e: (e.location, c.EVENT_LOCATIONS[e.location]), self.events)
        return [(loc, s) for loc, s in sorted(locations, key=lambda l: l[1])]

    @property
    def locations(self):
        return OrderedDict(self.location_opts)

    @property
    def locations_by_feature_id(self):
        return groupify(self.features, 'id', lambda f: f.locations)

    def signups_requiring_notification(self, session, from_time, to_time, options=None):
        """
        Returns a dict of AttractionSignups that require notification.

        The keys of the returned dict are the amount of advanced notice, given
        in seconds. A key of -1 indicates confirmation notices after a signup.

        The query generated by this method looks horrific, but is surprisingly
        efficient.
        """
        advance_checkin = max(0, self.advance_checkin)
        subqueries = []
        for advance_notice in sorted(set([-1] + self.advance_notices)):
            event_filters = [AttractionEvent.attraction_id == self.id]
            if advance_notice == -1:
                notice_ident = cast(AttractionSignup.attraction_event_id, UnicodeText)
                notice_param = bindparam('confirm_notice', advance_notice).label('advance_notice')
            else:
                advance_notice = max(0, advance_notice) + advance_checkin
                notice_delta = timedelta(seconds=advance_notice)
                event_filters += [
                    AttractionEvent.start_time >= from_time + notice_delta,
                    AttractionEvent.start_time < to_time + notice_delta]
                notice_ident = func.concat(AttractionSignup.attraction_event_id, '_{}'.format(advance_notice))
                notice_param = bindparam(
                    'advance_notice_{}'.format(advance_notice), advance_notice).label('advance_notice')

            subquery = session.query(AttractionSignup, notice_param).filter(
                AttractionSignup.is_unchecked_in,
                AttractionSignup.attraction_event_id.in_(
                    session.query(AttractionEvent.id).filter(*event_filters)),
                not_(exists().where(and_(
                    AttractionNotification.ident == notice_ident,
                    AttractionNotification.attraction_event_id == AttractionSignup.attraction_event_id,
                    AttractionNotification.attendee_id == AttractionSignup.attendee_id)))).with_labels()
            subqueries.append(subquery)

        query = subqueries[0].union(*subqueries[1:])
        if options:
            query = query.options(*listify(options))
        query.order_by(AttractionSignup.id)
        return groupify(query, lambda x: x[0], lambda x: x[1])


class AttractionFeature(MagModel):
    name = Column(UnicodeText)
    slug = Column(UnicodeText)
    description = Column(UnicodeText)
    is_public = Column(Boolean, default=False)
    badge_num_required = Column(Boolean, default=False)
    attraction_id = Column(UUID, ForeignKey('attraction.id'))

    events = relationship(
        'AttractionEvent', backref='feature', order_by='[AttractionEvent.start_time, AttractionEvent.id]')

    __table_args__ = (
        UniqueConstraint('name', 'attraction_id'),
        UniqueConstraint('slug', 'attraction_id'),
    )

    @presave_adjustment
    def _sluggify_name(self):
        self.slug = sluggify(self.name)

    @property
    def location_opts(self):
        locations = map(lambda e: (e.location, c.EVENT_LOCATIONS[e.location]), self.events)
        return [(loc, s) for loc, s in sorted(locations, key=lambda l: l[1])]

    @property
    def locations(self):
        return OrderedDict(self.location_opts)

    @property
    def events_by_location(self):
        events = sorted(self.events, key=lambda e: (c.EVENT_LOCATIONS[e.location], e.start_time))
        return groupify(events, 'location')

    @property
    def events_by_location_by_day(self):
        events = sorted(self.events, key=lambda e: (c.EVENT_LOCATIONS[e.location], e.start_time))
        return groupify(events, ['location', 'start_day_local'])

    @property
    def available_events(self):
        return [e for e in self.events if not (e.is_started and e.is_checkin_over)]

    @property
    def available_events_summary(self):
        summary = OrderedDict()
        for event in self.available_events:
            start_time = event.start_time_local
            day = start_time.strftime('%A')
            if day not in summary:
                summary[day] = OrderedDict()

            time_of_day = 'Evening'
            if start_time < noon_datetime(start_time):
                time_of_day = 'Morning'
            elif start_time < evening_datetime(start_time):
                time_of_day = 'Afternoon'
            if time_of_day not in summary[day]:
                summary[day][time_of_day] = 0

            summary[day][time_of_day] += event.remaining_slots

        return summary

    @property
    def available_events_by_day(self):
        return groupify(self.available_events, 'start_day_local')


# =====================================================================
# TODO: This, along with the panels.models.Event class, should be
#       refactored into a more generic "SchedulableMixin". Any model
#       class that has a location, a start time, and a duration would
#       inherit from the SchedulableMixin. Unfortunately the
#       panels.models.Event stores its duration as an integer number
#       of half hours, thus is not usable by Attractions.
# =====================================================================
class AttractionEvent(MagModel):
    attraction_feature_id = Column(UUID, ForeignKey('attraction_feature.id'))
    attraction_id = Column(UUID, ForeignKey('attraction.id'), index=True)

    location = Column(Choice(c.EVENT_LOCATION_OPTS))
    start_time = Column(UTCDateTime, default=c.EPOCH)
    duration = Column(Integer, default=900)  # In seconds
    slots = Column(Integer, default=1)
    signups_open = Column(Boolean, default=True)

    signups = relationship('AttractionSignup', backref='event', order_by='AttractionSignup.checkin_time')

    attendee_signups = association_proxy('signups', 'attendee')

    notifications = relationship('AttractionNotification', backref='event', order_by='AttractionNotification.sent_time')

    notification_replies = relationship(
        'AttractionNotificationReply', backref='event', order_by='AttractionNotificationReply.sid')

    attendees = relationship(
        'Attendee',
        backref='attraction_events',
        cascade='save-update,merge,refresh-expire,expunge',
        secondary='attraction_signup',
        order_by='attraction_signup.c.signup_time')

    @presave_adjustment
    def _fix_attraction_id(self):
        if not self.attraction_id and self.feature:
            self.attraction_id = self.feature.attraction_id

    @classmethod
    def get_ident(cls, id, advance_notice):
        if advance_notice == -1:
            return str(id)
        return '{}_{}'.format(id, advance_notice)

    @hybrid_property
    def end_time(self):
        return self.start_time + timedelta(seconds=self.duration)

    @end_time.expression
    def end_time(cls):
        return cls.start_time + (cls.duration * text("interval '1 second'"))

    @property
    def start_day_local(self):
        return self.start_time_local.strftime('%A')

    @property
    def start_time_label(self):
        if self.start_time:
            return self.start_time_local.strftime('%-I:%M %p %A')
        return 'unknown start time'

    @property
    def checkin_start_time(self):
        advance_checkin = self.attraction.advance_checkin
        if advance_checkin < 0:
            return self.start_time
        else:
            return self.start_time - timedelta(seconds=advance_checkin)

    @property
    def checkin_end_time(self):
        advance_checkin = self.attraction.advance_checkin
        if advance_checkin < 0:
            return self.end_time
        else:
            return self.start_time

    @property
    def checkin_start_time_label(self):
        checkin = self.checkin_start_time_local
        today = datetime.now(c.EVENT_TIMEZONE).date()
        if checkin.date() == today:
            return checkin.strftime('%-I:%M %p')
        return checkin.strftime('%-I:%M %p %a')

    @property
    def checkin_end_time_label(self):
        checkin = self.checkin_end_time_local
        today = datetime.now(c.EVENT_TIMEZONE).date()
        if checkin.date() == today:
            return checkin.strftime('%-I:%M %p')
        return checkin.strftime('%-I:%M %p %a')

    @property
    def time_remaining_to_checkin(self):
        return self.checkin_start_time - datetime.now(pytz.UTC)

    @property
    def time_remaining_to_checkin_label(self):
        return humanize_timedelta(self.time_remaining_to_checkin, granularity='minutes', separator=' ')

    @property
    def is_checkin_over(self):
        return self.checkin_end_time < datetime.now(pytz.UTC)

    @property
    def is_sold_out(self):
        return self.slots <= len(self.attendees)

    @property
    def is_started(self):
        return self.start_time < datetime.now(pytz.UTC)

    @property
    def remaining_slots(self):
        return max(self.slots - len(self.attendees), 0)

    @property
    def time_span_label(self):
        if self.start_time:
            end_time = self.end_time.astimezone(c.EVENT_TIMEZONE)
            start_time = self.start_time.astimezone(c.EVENT_TIMEZONE)
            if start_time.date() == end_time.date():
                return '{} – {}'.format(start_time.strftime('%-I:%M %p'), end_time.strftime('%-I:%M %p %A'))
            return '{} – {}'.format(start_time.strftime('%-I:%M %p %A'), end_time.strftime('%-I:%M %p %A'))
        return 'unknown time span'

    @property
    def duration_label(self):
        if self.duration:
            return humanize_timedelta(seconds=self.duration, separator=' ')
        return 'unknown duration'

    @property
    def location_event_name(self):
        return location_event_name(self.location)

    @property
    def location_room_name(self):
        return location_room_name(self.location)

    @property
    def name(self):
        return self.feature.name

    @property
    def label(self):
        return '{} at {}'.format(self.name, self.start_time_label)

    def overlap(self, event):
        if not event:
            return 0
        latest_start = max(self.start_time, event.start_time)
        earliest_end = min(self.end_time, event.end_time)
        if earliest_end < latest_start:
            return -int((latest_start - earliest_end).total_seconds())
        elif self.start_time < event.start_time and self.end_time > event.end_time:
            return int((self.end_time - event.start_time).total_seconds())
        elif self.start_time > event.start_time and self.end_time < event.end_time:
            return int((event.end_time - self.start_time).total_seconds())
        else:
            return int((earliest_end - latest_start).total_seconds())


class AttractionSignup(MagModel):
    attraction_event_id = Column(UUID, ForeignKey('attraction_event.id'))
    attraction_id = Column(UUID, ForeignKey('attraction.id'))
    attendee_id = Column(UUID, ForeignKey('attendee.id'))

    signup_time = Column(UTCDateTime, default=lambda: datetime.now(pytz.UTC))
    checkin_time = Column(UTCDateTime, default=lambda: utcmin.datetime, index=True)

    notifications = relationship(
        'AttractionNotification',
        backref=backref(
            'signup',
            cascade='merge',
            uselist=False,
            viewonly=True),
        primaryjoin='and_('
                    'AttractionSignup.attendee_id == foreign(AttractionNotification.attendee_id),'
                    'AttractionSignup.attraction_event_id == foreign(AttractionNotification.attraction_event_id))',
        order_by='AttractionNotification.sent_time',
        viewonly=True)

    __mapper_args__ = {'confirm_deleted_rows': False}
    __table_args__ = (UniqueConstraint('attraction_event_id', 'attendee_id'),)

    def __init__(self, attendee=None, event=None, **kwargs):
        super(AttractionSignup, self).__init__(**kwargs)
        if attendee:
            self.attendee = attendee
        if event:
            self.event = event
        if not self.attraction_id and self.event:
            self.attraction_id = self.event.attraction_id

    @presave_adjustment
    def _fix_attraction_id(self):
        if not self.attraction_id and self.event:
            self.attraction_id = self.event.attraction_id

    @property
    def checkin_time_local(self):
        if self.is_checked_in:
            return self.checkin_time.astimezone(c.EVENT_TIMEZONE)
        return None

    @property
    def checkin_time_label(self):
        if self.is_checked_in:
            return self.checkin_time_local.strftime('%-I:%M %p %A')
        return 'Not checked in'

    @property
    def signup_time_label(self):
        return self.signup_time_local.strftime('%-I:%M %p %A')

    @property
    def email(self):
        return self.attendee.email

    @property
    def email_model_name(self):
        return 'signup'

    @hybrid_property
    def is_checked_in(self):
        return self.checkin_time > utcmin.datetime

    @is_checked_in.expression
    def is_checked_in(cls):
        return cls.checkin_time > utcmin.datetime

    @hybrid_property
    def is_unchecked_in(self):
        return self.checkin_time <= utcmin.datetime

    @is_unchecked_in.expression
    def is_unchecked_in(cls):
        return cls.checkin_time <= utcmin.datetime


class AttractionNotification(MagModel):
    attraction_event_id = Column(UUID, ForeignKey('attraction_event.id'))
    attraction_id = Column(UUID, ForeignKey('attraction.id'))
    attendee_id = Column(UUID, ForeignKey('attendee.id'))

    notification_type = Column(Choice(Attendee._NOTIFICATION_PREF_OPTS))
    ident = Column(UnicodeText, index=True)
    sid = Column(UnicodeText)
    sent_time = Column(UTCDateTime, default=lambda: datetime.now(pytz.UTC))
    subject = Column(UnicodeText)
    body = Column(UnicodeText)

    @presave_adjustment
    def _fix_attraction_id(self):
        if not self.attraction_id and self.event:
            self.attraction_id = self.event.attraction_id


class AttractionNotificationReply(MagModel):
    attraction_event_id = Column(UUID, ForeignKey('attraction_event.id'), nullable=True)
    attraction_id = Column(UUID, ForeignKey('attraction.id'), nullable=True)
    attendee_id = Column(UUID, ForeignKey('attendee.id'), nullable=True)

    notification_type = Column(Choice(Attendee._NOTIFICATION_PREF_OPTS))
    from_phonenumber = Column(UnicodeText)
    to_phonenumber = Column(UnicodeText)
    sid = Column(UnicodeText, index=True)
    received_time = Column(UTCDateTime, default=lambda: datetime.now(pytz.UTC))
    sent_time = Column(UTCDateTime, default=lambda: datetime.now(pytz.UTC))
    body = Column(UnicodeText)

    @presave_adjustment
    def _fix_attraction_id(self):
        if not self.attraction_id and self.event:
            self.attraction_id = self.event.attraction_id
