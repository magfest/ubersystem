from collections import OrderedDict
from datetime import datetime, timedelta

import pytz
from sqlalchemy import and_, cast, exists, func, not_
from sqlalchemy.ext.associationproxy import AssociationProxy, association_proxy
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.schema import UniqueConstraint
from sqlalchemy.sql import text
from sqlalchemy.sql.expression import bindparam
from sqlalchemy.types import Boolean, Integer, Uuid, String, DateTime
from typing import ClassVar

from uber.config import c
from uber.custom_tags import humanize_timedelta, location_event_name, location_room_name
from uber.decorators import presave_adjustment, render, classproperty
from uber.models import MagModel, Attendee
from uber.models.types import (default_relationship as relationship, Choice, DefaultColumn as Column, utcmin,
                               DefaultField as Field, DefaultRelationship as Relationship)
from uber.utils import evening_datetime, noon_datetime, localized_now, slugify, listify, groupify


__all__ = [
    'Attraction', 'AttractionFeature', 'AttractionEvent', 'AttractionSignup',
    'AttractionNotification', 'AttractionNotificationReply']


class AttractionMixin():
    populate_schedule: bool = Column(Boolean, default=True)
    no_notifications: bool = Column(Boolean, default=False)
    waitlist_available: bool = Column(Boolean, default=True)
    waitlist_slots: int = Column(Integer, default=10)
    signups_open_relative: int = Column(Integer, default=c.DEFAULT_ATTRACTIONS_SIGNUPS_MINUTES)
    signups_open_time: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True)
    slots: int = Column(Integer, default=1)

    @classproperty
    def inherited_cols(cls):
        return ['populate_schedule', 'no_notifications', 'waitlist_available', 'waitlist_slots',
                'signups_open_relative', 'signups_open_time', 'slots']

    @property
    def minimum_signups_open(self):
        return c.EPOCH - timedelta(days=365)

    @presave_adjustment
    def null_waitlist_slots(self):
        if self.waitlist_slots == '':
            self.waitlist_slots = 0

    @property
    def signups_open_type(self):
        if self.signups_open_relative:
            return 'relative'
        elif self.signups_open_time:
            return 'absolute'
        else:
            return 'not_open'

    def update_signup_times(self, value):
        if value in ['relative', 'not_open']:
            self.signups_open_time = None
        if value in ['absolute', 'not_open']:
            self.signups_open_relative = 0
    
    def get_updated_signup_vals(self):
        old_signups_open_relative = self.orig_value_of('signups_open_relative')
        old_signups_open_time = self.orig_value_of('signups_open_time')

        if old_signups_open_relative == self.signups_open_relative and old_signups_open_time == self.signups_open_time:
            return {}, {}
 
        if old_signups_open_relative:
            same_time_settings = {'signups_open_relative': old_signups_open_relative}
        elif old_signups_open_time:
            same_time_settings = {'signups_open_time': old_signups_open_time}
        else:
            same_time_settings = {'signups_open_time': None, 'signups_open_relative': 0}

        if self.signups_open_relative:
            update_attrs = {'signups_open_relative': self.signups_open_relative}
            if old_signups_open_time:
                update_attrs['signups_open_time'] = None
        elif self.signups_open_time:
            update_attrs = {'signups_open_time': self.signups_open_time}
            if old_signups_open_relative:
                update_attrs['signups_open_relative'] = 0
        else:
            if old_signups_open_relative:
                update_attrs = {'signups_open_relative': 0}
            else:
                update_attrs = {'signups_open_time': None}
        
        return same_time_settings, update_attrs

class Attraction(MagModel, AttractionMixin, table=True):
    """
    AttractionFeature: selectin
    """

    _NONE: ClassVar = 0
    _PER_FEATURE: ClassVar = 1
    _PER_ATTRACTION: ClassVar = 2
    _RESTRICTION_OPTS: ClassVar = [(
        _NONE,
        'Attendees can attend as many events as they wish '
        '(least restrictive)'
    ), (
        _PER_FEATURE,
        'Attendees can only attend one event in each feature'
    ), (
        _PER_ATTRACTION,
        'Attendees can only attend one event in this attraction '
        '(most restrictive)'
    )]
    _RESTRICTIONS: ClassVar = dict(_RESTRICTION_OPTS)

    _ADVANCE_CHECKIN_OPTS: ClassVar = [
        (-1, 'Anytime during event'),
        (0, 'When the event starts'),
        (5, '5 minutes before'),
        (10, '10 minutes before'),
        (15, '15 minutes before'),
        (20, '20 minutes before'),
        (30, '30 minutes before'),
        (45, '45 minutes before'),
        (60, '1 hour before')]

    _ADVANCE_NOTICES_OPTS: ClassVar = [
        ('', 'Never'),
        (0, 'When checkin starts'),
        (5, '5 minutes before checkin'),
        (15, '15 minutes before checkin'),
        (30, '30 minutes before checkin'),
        (60, '1 hour before checkin'),
        (120, '2 hours before checkin'),
        (1440, '1 day before checkin')]
    
    department_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='department.id', nullable=True)
    department: 'Department' = Relationship(back_populates="attractions", sa_relationship_kwargs={'order_by': 'Department.name'})
    
    owner_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='admin_account.id', nullable=True)
    owner: 'AdminAccount' = Relationship(back_populates="attractions")
    owner_attendee: 'Attendee' = Relationship(sa_relationship=relationship(
        'Attendee',
        cascade='merge',
        secondary='admin_account',
        viewonly=True))

    name: str = Column(String, unique=True)
    slug: str = Column(String, unique=True)
    description: str = Column(String)
    full_description: str = Column(String)
    is_public: bool = Column(Boolean, default=False)
    checkin_reminder: int | None = Column(Integer, default=None, nullable=True)
    advance_checkin: int = Column(Integer, default=0)
    restriction: int = Column(Choice(_RESTRICTION_OPTS), default=_NONE)
    badge_num_required: bool = Column(Boolean, default=False)
    
    features: list['AttractionFeature'] = Relationship(
        back_populates="attraction",
        sa_relationship_kwargs={'lazy': 'selectin', 'order_by': '[AttractionFeature.name, AttractionFeature.id]', 'passive_deletes': True})
    public_features: list['AttractionFeature'] = Relationship(sa_relationship=relationship(
        'AttractionFeature',
        primaryjoin='and_('
                    'AttractionFeature.attraction_id == Attraction.id,'
                    'AttractionFeature.is_public == True)',
        viewonly=True,
        order_by='[AttractionFeature.name, AttractionFeature.id]'))
    events: list['AttractionEvent'] = Relationship(
        back_populates="attraction",
        sa_relationship_kwargs={'order_by': '[AttractionEvent.start_time, AttractionEvent.id]', 'passive_deletes': True})
    signups: list['AttractionSignup'] = Relationship(
        back_populates="attraction",
        sa_relationship_kwargs={'viewonly': True, 'order_by': '[AttractionSignup.checkin_time, AttractionSignup.id]'})

    @presave_adjustment
    def slugify_name(self):
        if not self.slug:
            self.slug = slugify(self.name)

    @presave_adjustment
    def null_dept_id(self):
        if self.department_id == '':
            self.department_id = None

    @presave_adjustment
    def null_checkin_reminder(self):
        if self.checkin_reminder == '':
            self.checkin_reminder = None

    @property
    def feature_opts(self):
        return [(f.id, f.name) for f in self.features]

    @property
    def feature_names_by_id(self):
        return OrderedDict(self.feature_opts)

    @property
    def used_location_opts(self):
        locs = set(e.event_location_id for e in self.events)
        sorted_locs = sorted(locs, key=lambda l: c.SCHEDULE_LOCATIONS[l])
        return [(loc, c.SCHEDULE_LOCATIONS[loc]) for loc in sorted_locs]

    @property
    def unused_location_opts(self):
        locs = set(e.event_location_id for e in self.events)
        return sorted([(loc, s) for loc, s in c.SCHEDULE_LOCATION_OPTS if loc not in locs], key=lambda x: x[1])

    @property
    def advance_checkin_label(self):
        if self.advance_checkin < 0:
            return 'anytime during the event'
        return humanize_timedelta(
            minutes=self.advance_checkin,
            separator=' ',
            now='by the time the event starts',
            prefix='at least ',
            suffix=' before the event starts')

    @property
    def location_opts(self):
        locations = map(lambda e: (e.event_location_id, c.SCHEDULE_LOCATIONS[e.event_location_id]), self.events)
        return [(loc, s) for loc, s in sorted(locations, key=lambda l: l[1])]

    @property
    def locations(self):
        return OrderedDict(self.location_opts)

    @property
    def locations_by_feature_id(self):
        return groupify(self.features, 'id', lambda f: f.locations)

    def cascade_feature_event_attrs(self, session):
        schedule_synced = False
        same_time_settings, update_time_settings = self.get_updated_signup_vals()

        attr_changes = {}
        for attr in AttractionMixin.inherited_cols + ['badge_num_required']:
            if self.orig_value_of(attr) != getattr(self, attr):
                attr_changes[attr] = (self.orig_value_of(attr), getattr(self, attr))

        if not same_time_settings and not update_time_settings and not attr_changes:
            return
        
        def update_if_changed(item):
            item_updated = False
            if all([getattr(item, col_name) == val for col_name, val in same_time_settings.items()]):
                item_updated = True
                for col_name, new_val in update_time_settings.items():
                    setattr(item, col_name, new_val)
                if isinstance(item, AttractionEvent):
                    event.sync_with_schedule(session, update_desc=True)
                    schedule_synced = True
            for attr_name, (old_val, new_val) in attr_changes.items():
                if attr_name == 'slots':
                    if isinstance(item, AttractionFeature) or getattr(item, attr_name) < new_val:
                        setattr(item, attr_name, new_val)
                        item_updated = True
                elif hasattr(item, attr_name) and getattr(item, attr_name) == old_val:
                    setattr(item, attr_name, new_val)
                    item_updated = True
            if item_updated:
                setattr(item, 'last_updated', self.last_updated)
                session.add(item)

        for feature in self.features:
            update_if_changed(feature)

        for event in self.events:
            update_if_changed(event)
            if 'populate_schedule' in attr_changes and not schedule_synced:
                event.sync_with_schedule(session)


    def update_dept_ids(self, session):
        if self.department_id == self.orig_value_of('department_id'):
            return
        
        for event in self.events:
            if event.populate_schedule:
                event.schedule_item.department_id = self.department_id
                event.schedule_item.last_updated = datetime.now(pytz.UTC)
                session.add(event.schedule_item)

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
        checkin_reminder = [-1, self.checkin_reminder] if self.checkin_reminder else [-1]
        for advance_notice in sorted(checkin_reminder):
            event_filters = [AttractionEvent.attraction_id == self.id,
                             AttractionEvent.no_notifications == False]
            if advance_notice == -1:
                notice_ident = cast(AttractionSignup.attraction_event_id, String)
                notice_param = bindparam('confirm_notice', advance_notice).label('advance_notice')
            else:
                advance_notice = max(0, advance_notice) + advance_checkin
                notice_delta = timedelta(minutes=advance_notice)
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


class AttractionFeature(MagModel, AttractionMixin, table=True):
    """
    Attraction: joined
    AttractionEvent: selectin
    """

    attraction_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='attraction.id', ondelete='CASCADE')
    attraction: 'Attraction' = Relationship(back_populates="features", sa_relationship_kwargs={'lazy': 'joined'})

    name: str = Column(String)
    slug: str = Column(String)
    description: str = Column(String)
    is_public: bool = Column(Boolean, default=False)
    badge_num_required: bool = Column(Boolean, default=False)

    events: list['AttractionEvent'] = Relationship(
        back_populates="feature",
        sa_relationship_kwargs={'lazy': 'selectin', 'order_by': '[AttractionEvent.start_time, AttractionEvent.id]', 'passive_deletes': True})

    __table_args__: ClassVar = (
        UniqueConstraint('name', 'attraction_id'),
        UniqueConstraint('slug', 'attraction_id'),
    )

    @presave_adjustment
    def slugify_name(self):
        if not self.slug:
            self.slug = slugify(self.name)

    @property
    def default_params(self):
        params = {}
        if not self.is_new:
            return params
        for field_name in AttractionMixin.inherited_cols + ['badge_num_required', 'signups_open_type']:
            if hasattr(self.attraction, field_name):
                params[field_name] = getattr(self.attraction, field_name)

        return params

    def cascade_event_attrs(self, session):
        same_time_settings, update_time_settings = self.get_updated_signup_vals()
        schedule_synced = False

        attr_changes = {}
        for attr in AttractionMixin.inherited_cols:
            if self.orig_value_of(attr) != getattr(self, attr):
                attr_changes[attr] = (self.orig_value_of(attr), getattr(self, attr))

        if not same_time_settings and not update_time_settings and not attr_changes:
            return

        for event in self.events:
            event_updated = False
            if all([getattr(event, col_name) == val for col_name, val in same_time_settings.items()]):
                event_updated = True
                for col_name, new_val in update_time_settings.items():
                    setattr(event, col_name, new_val)
                event.sync_with_schedule(session, update_desc=True)
                schedule_synced = True
            for attr_name, (old_val, new_val) in attr_changes.items():
                if attr_name == 'slots' and event.slots < new_val:
                    event.slots = new_val
                    event_updated = True
                elif hasattr(event, attr_name) and getattr(event, attr_name) == old_val:
                    setattr(event, attr_name, new_val)
                    event_updated = True
            if event_updated:
                setattr(event, 'last_updated', self.last_updated)
                session.add(event)
            if 'populate_schedule' in attr_changes and not schedule_synced:
                event.sync_with_schedule(session)

    def update_name_desc(self, session):
        if self.name == self.orig_value_of('name') and self.description == self.orig_value_of('description'):
            return
        
        for event in self.events:
            if event.populate_schedule:
                event.schedule_item.name = self.name
                event.schedule_item.description = event.schedule_description
                event.schedule_item.last_updated = datetime.now(pytz.UTC)
                session.add(event.schedule_item)

    @property
    def location_opts(self):
        locations = map(lambda e: (e.event_location_id, c.SCHEDULE_LOCATIONS[e.event_location_id]), self.events)
        return [(loc, s) for loc, s in sorted(locations, key=lambda l: l[1])]

    @property
    def locations(self):
        return OrderedDict(self.location_opts)

    @property
    def events_by_location(self):
        events = sorted(self.events, key=lambda e: (c.SCHEDULE_LOCATIONS[e.event_location_id], e.start_time))
        return groupify(events, 'event_location_id')

    @property
    def events_by_location_by_day(self):
        events = sorted(self.events, key=lambda e: (c.SCHEDULE_LOCATIONS[e.event_location_id], e.start_time))
        return groupify(events, ['event_location_id', 'start_day_local'])

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


class AttractionEvent(MagModel, AttractionMixin, table=True):
    """
    Attraction: joined
    AttractionFeature: joined
    EventLocation: joined
    Event: joined
    """

    attraction_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='attraction.id', ondelete='CASCADE', index=True)
    attraction: 'Attraction' = Relationship(back_populates="events", sa_relationship_kwargs={'lazy': 'joined'})

    attraction_feature_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='attraction_feature.id', ondelete='CASCADE')
    feature: 'AttractionFeature' = Relationship(back_populates="events", sa_relationship_kwargs={'lazy': 'joined'})

    event_location_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='event_location.id', nullable=True)
    location: 'EventLocation' = Relationship(
        back_populates="attractions", sa_relationship_kwargs={'lazy': 'joined', 'cascade': 'save-update,merge,refresh-expire,expunge'})

    start_time: datetime = Field(sa_type=DateTime(timezone=True), default=c.EPOCH)
    duration: int = Column(Integer, default=60)

    schedule_item: 'Event' = Relationship(
        back_populates="attraction", sa_relationship_kwargs={'cascade': 'save-update,merge,refresh-expire,expunge'})
    signups: list['AttractionSignup'] = Relationship(
        back_populates="event", sa_relationship_kwargs={'order_by': 'AttractionSignup.checkin_time', 'passive_deletes': True})
    attendee_signups: ClassVar = association_proxy('signups', 'attendee')
    notifications: list['AttractionNotification'] = Relationship(
        back_populates="event", sa_relationship_kwargs={'order_by': 'AttractionNotification.sent_time', 'passive_deletes': True})
    notification_replies: list['AttractionNotificationReply'] = Relationship(
        back_populates="event",
        sa_relationship_kwargs={'order_by': 'AttractionNotificationReply.sid', 'cascade': 'save-update,merge,refresh-expire,expunge'})
    attendees: list['Attendee'] = Relationship(
        back_populates="attraction_events",
        sa_relationship_kwargs={
            'cascade': 'save-update,merge,refresh-expire,expunge', 'secondary': 'attraction_signup',
            'order_by': 'attraction_signup.c.signup_time', 'overlaps': 'signups,event,attraction_signups,attendee'})

    @presave_adjustment
    def _fix_attraction_id(self):
        if not self.attraction_id and self.feature:
            self.attraction_id = self.feature.attraction_id

    @presave_adjustment
    def update_signups_open_time(self):
        if self.populate_schedule and self.schedule_item and self.session and (
                self.orig_value_of('signups_open_relative') != self.signups_open_relative or
                self.orig_value_of('signups_open_time') != self.signups_open_time):
            self.schedule_item.description = self.schedule_description
            self.schedule_item.last_updated = datetime.now(pytz.UTC)
            self.session.add(self.schedule_item)


    @classmethod
    def get_ident(cls, id, advance_notice):
        if advance_notice == -1:
            return str(id)
        return '{}_{}'.format(id, advance_notice)

    @hybrid_property
    def end_time(self):
        return self.start_time + timedelta(minutes=self.duration)

    @end_time.expression
    def end_time(cls):
        return cls.start_time + (cls.duration * text("interval '1 minute'"))

    @property
    def start_day_local(self):
        return self.start_time_local.strftime('%A')

    @property
    def start_time_label(self):
        if self.start_time:
            return self.start_time_local.strftime('%-I:%M %p %A')
        return 'unknown start time'
    
    @property
    def signups_open(self):
        if not self.signups_open_time and not self.signups_open_relative:
            return False
        if not self.signups_open_relative:
            return localized_now() > self.signups_open_time
        return localized_now() > self.start_time - timedelta(minutes=self.signups_open_relative)

    @property
    def checkin_start_time(self):
        advance_checkin = self.attraction.advance_checkin
        if advance_checkin < 0:
            return self.start_time
        else:
            return self.start_time - timedelta(minutes=advance_checkin)

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
    def signed_up_attendees(self):
        return [signup.attendee for signup in self.signups if not signup.on_waitlist]
    
    @property
    def waitlist_attendees(self):
        return [signup.attendee for signup in self.signups if signup.on_waitlist]
    
    @property
    def waitlist_signups(self):
        return sorted([signup for signup in self.signups if signup.on_waitlist], key=lambda s: s.signup_time)

    @property
    def is_sold_out(self):
        return self.slots <= len(self.signed_up_attendees)
    
    @property
    def waitlist_open(self):
        if not self.waitlist_available:
            return False
        elif self.waitlist_slots == 0:
            return True
        return self.waitlist_slots > len(self.waitlist_attendees)

    @property
    def is_started(self):
        return self.start_time < datetime.now(pytz.UTC)

    @property
    def remaining_slots(self):
        return max(self.slots - len(self.signed_up_attendees), 0)

    @property
    def remaining_waitlist_slots(self):
        return max(self.waitlist_slots - len(self.waitlist_attendees), 0)

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
            return humanize_timedelta(minutes=self.duration, separator=' ')
        return 'unknown duration'

    @property
    def location_event_name(self):
        return location_event_name(self.event_location_id)

    @property
    def location_room_name(self):
        return location_room_name(self.event_location_id)

    @property
    def name(self):
        return self.feature.name

    @property
    def description(self):
        return self.feature.description

    @property
    def label(self):
        return '{} at {}'.format(self.name, self.start_time_label)

    @property
    def sign_up_link(self):
        return f"{c.URL_BASE}/attractions/{self.attraction.slug}?feature={self.feature.slug}#{self.id}"

    @property
    def default_params(self):
        params = {}
        if not self.is_new:
            return params
        for field_name in AttractionMixin.inherited_cols + ['signups_open_type']:
            params[field_name] = getattr(self.feature, field_name)
        return params

    def add_next_waitlist(self, session):
        from uber.tasks.attractions import send_waitlist_notification
        next_signup = self.waitlist_signups[0] if self.waitlist_signups else None
        if next_signup:
            next_signup.on_waitlist = False
            session.add(next_signup)
            if not self.no_notifications:
                send_waitlist_notification.delay(next_signup.id)

    @property
    def signup_time_str(self):
        signups_open = ""
        if self.signups_open_time:
            lowercase_time = self.signups_open_time_local.strftime('%-I:%M%p').lower()
            signups_open = f"{lowercase_time} {self.signups_open_time_local.strftime('%Z on %A, %B %-d')}"
        elif self.signups_open_relative:
            if self.signups_open_relative:
                signups_open += f"{self.signups_open_relative // 60} hour{'s' if self.signups_open_relative // 60 > 1 else ''}"
                if self.signups_open_relative // 60 * 60 != self.signups_open_relative:
                    signups_open += f"and {self.signups_open_relative % 60} minutes{'s' if self.signups_open_relative % 60 > 1 else ''}"
                signups_open += " before the event starts"
        return signups_open

    @property
    def schedule_description(self):
        signups_open = ""
        if self.signup_time_str:
            signups_open = f" Signups open {self.signup_time_str}."
        return self.description + \
            f"""\n\n<a href="{self.sign_up_link}" target="_blank">View details and sign up here!</a>{signups_open}"""

    def sync_with_schedule(self, session, update_desc=False):
        from uber.models import Event
        if not self.populate_schedule:
            if not self.schedule_item:
                return
            session.delete(self.schedule_item)
            return
        
        updated = False

        if not self.schedule_item:
            event = Event(attraction_event_id=self.id,
                          department_id=self.attraction.department_id)
            updated = True
        else:
            event = self.schedule_item
        
        for key in ['event_location_id', 'start_time', 'duration', 'name']:
            current_attr = getattr(self, key, '')
            if getattr(event, key, '') != current_attr:
                updated = True
                setattr(event, key, current_attr)
        
        if update_desc or self.description not in event.description:
            event.description = self.schedule_description
            updated = True
        
        if updated:
            event.last_updated = datetime.now(pytz.UTC)
            session.add(event)

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


class AttractionSignup(MagModel, table=True):
    """
    Attendee: joined
    Attraction: joined
    AttractionEvent: joined
    """

    attraction_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='attraction.id', ondelete='CASCADE')
    attraction: 'Attraction' = Relationship(
        back_populates="signups", sa_relationship_kwargs={'lazy': 'joined', 'cascade': 'save-update,merge,refresh-expire,expunge'})
    
    attraction_event_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='attraction_event.id', ondelete='CASCADE')
    event: 'AttractionEvent' = Relationship(back_populates="signups", sa_relationship_kwargs={'lazy': 'joined'})

    attendee_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='attendee.id', ondelete='CASCADE')
    attendee: 'Attendee' = Relationship(back_populates="attraction_signups", sa_relationship_kwargs={'lazy': 'joined'})

    signup_time: datetime = Field(sa_type=DateTime(timezone=True), default_factory=lambda: datetime.now(pytz.UTC))
    checkin_time: datetime = Field(sa_type=DateTime(timezone=True), default_factory=lambda: utcmin.datetime, index=True)
    on_waitlist: bool = Column(Boolean, default=False)

    notifications: list['AttractionNotification'] = Relationship(
        back_populates="signup",
        sa_relationship_kwargs={
            'order_by': 'AttractionNotification.sent_time', 'viewonly': True,
            'primaryjoin': 'and_(AttractionSignup.attendee_id == foreign(AttractionNotification.attendee_id),'
                                'AttractionSignup.attraction_event_id == foreign(AttractionNotification.attraction_event_id))'})

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

    @property
    def waitlist_position(self):
        for index, signup in enumerate(self.event.waitlist_signups):
            if signup == self:
                return index + 1

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
    
    def notify_waitlist(self):
        from uber.tasks.email import send_email
        TEXT_TEMPLATE = "You've been signed up from the waitlist for {signup.event.name} in {signup.event.location_room_name}, {signup.event.time_span_label}! Reply N to drop out"

        if self.attendee.notification_pref == Attendee._NOTIFICATION_EMAIL:
            send_email.delay(
                c.ATTRACTIONS_EMAIL,
                self.email,
                'Signed up from waitlist',
                render('emails/panels/attractions_waitlist.html', {'signup': self}, encoding=None),
                model=self.to_dict('id'))
            # TODO: Handle text notifs too


class AttractionNotification(MagModel, table=True):
    """
    Attendee: joined
    AttractionEvent: joined
    AttractionSignup: joined
    """

    attraction_event_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='attraction_event.id', ondelete='CASCADE')
    event: 'AttractionEvent' = Relationship(back_populates="notifications", sa_relationship_kwargs={'lazy': 'joined'})

    attraction_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='attraction.id', ondelete='CASCADE')

    attendee_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='attendee.id', ondelete='CASCADE')
    attendee: 'Attendee' = Relationship(back_populates="attraction_notifications", sa_relationship_kwargs={'lazy': 'joined'})

    notification_type: int = Column(Choice(Attendee._NOTIFICATION_PREF_OPTS))
    ident: str = Column(String, index=True)
    sid: str = Column(String)
    sent_time: datetime = Field(sa_type=DateTime(timezone=True), default=lambda: datetime.now(pytz.UTC))
    subject: str = Column(String)
    body: str = Column(String)

    signup: 'AttractionSignup' = Relationship(
        back_populates="notifications",
        sa_relationship_kwargs={
            'lazy': 'joined', 'viewonly': True,
            'primaryjoin': 'and_(AttractionSignup.attendee_id == foreign(AttractionNotification.attendee_id),'
                                'AttractionSignup.attraction_event_id == foreign(AttractionNotification.attraction_event_id))'})

    @presave_adjustment
    def _fix_attraction_id(self):
        if not self.attraction_id and self.event:
            self.attraction_id = self.event.attraction_id


class AttractionNotificationReply(MagModel, table=True):
    """
    AttractionEvent: joined
    """

    attraction_event_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='attraction_event.id', nullable=True)
    event: 'AttractionEvent' = Relationship(back_populates="notification_replies", sa_relationship_kwargs={'lazy': 'joined'})
    
    attraction_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='attraction.id', nullable=True)
    attendee_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='attendee.id', nullable=True)

    notification_type: int = Column(Choice(Attendee._NOTIFICATION_PREF_OPTS))
    from_phonenumber: str = Column(String)
    to_phonenumber: str = Column(String)
    sid: str = Column(String, index=True)
    received_time: datetime = Field(sa_type=DateTime(timezone=True), default_factory=lambda: datetime.now(pytz.UTC))
    sent_time: datetime = Field(sa_type=DateTime(timezone=True), default_factory=lambda: datetime.now(pytz.UTC))
    body: str = Column(String)

    @presave_adjustment
    def _fix_attraction_id(self):
        if not self.attraction_id and self.event:
            self.attraction_id = self.event.attraction_id
