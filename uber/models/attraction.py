from collections import OrderedDict
from datetime import timedelta

from sideboard.lib.sa import JSON, CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy.orm import backref
from sqlalchemy.schema import ForeignKey, UniqueConstraint
from sqlalchemy.types import Integer

from uber.config import c
from uber.custom_tags import humanize_timedelta
from uber.models import MagModel
from uber.models.types import default_relationship as relationship, Choice, \
    DefaultColumn as Column
from uber.utils import ceil_datetime, floor_datetime


__all__ = [
    'Attraction', 'AttractionFeature', 'AttractionEvent', 'AttractionSignup']


class Attraction(MagModel):
    SLOT_DURATION = 15 * 60  # 15 minutes expressed in seconds
    START_TIME_SLOT = ceil_datetime(
        c.EPOCH, timedelta(seconds=SLOT_DURATION))
    END_TIME_SLOT = floor_datetime(
        c.ESCHATON, timedelta(seconds=SLOT_DURATION))
    TIME_SLOT_COUNT = int(
        (END_TIME_SLOT - START_TIME_SLOT).total_seconds() // SLOT_DURATION)

    name = Column(UnicodeText, unique=True)
    description = Column(UnicodeText)
    notifications = Column(JSON, default=[], server_default='[]')
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
        backref='queue',
        order_by='[AttractionFeature.name, AttractionFeature.id]')
    events = relationship(
        'AttractionEvent',
        cascade='save-update,merge',
        secondary='attraction_feature',
        viewonly=True,
        order_by='AttractionEvent.start_time')

    @property
    def feature_opts(self):
        return [(f.id, f.name) for f in self.features]

    @property
    def used_location_opts(self):
        locs = set(e.location for e in self.events)
        sorted_locs = sorted(locs, key=lambda l: c.EVENT_LOCATIONS[l])
        return [(l, c.EVENT_LOCATIONS[l]) for l in sorted_locs]

    @property
    def unused_location_opts(self):
        locs = set(e.location for e in self.events)
        return [(l, s) for l, s in c.EVENT_LOCATION_OPTS if l not in locs]

    @property
    def start_times(self):
        return [
            self.START_TIME_SLOT + timedelta(seconds=i * self.SLOT_DURATION)
            for i in range(self.TIME_SLOT_COUNT)]

    @property
    def start_time_opts(self):
        return [(time, time.strftime('%-I:%M %p %A'))
                for time in self.start_times]

    @property
    def start_time_opts_by_day(self):
        time_slots_by_day = OrderedDict()
        for time in self.start_times:
            day = time.strftime('%A')
            if day not in time_slots_by_day:
                time_slots_by_day[day] = []
            time_slots_by_day[day].append(
                (time, time.strftime('%-I:%M %p %A')))
        return time_slots_by_day

    @property
    def duration_opts(self):
        ts = [i * self.SLOT_DURATION for i in range(1, 33)]
        return [(t, humanize_timedelta(seconds=t, separator=' ')) for t in ts]

    @property
    def location_opts(self):
        locations = map(
            lambda e: (e.location, c.EVENT_LOCATIONS[e.location]), self.events)
        return [(l, s) for l, s in sorted(locations, key=lambda l: l[1])]

    @property
    def locations(self):
        return OrderedDict(self.location_opts)

    @property
    def events_by_location(self):
        events = sorted(
            self.events, key=lambda e: c.EVENT_LOCATIONS[e.location])
        events_by_location = OrderedDict()
        for event in events:
            if event.location not in events_by_location:
                events_by_location[event.location] = []
            events_by_location[event.location].append(event)
        return events_by_location


class AttractionFeature(MagModel):
    name = Column(UnicodeText)
    description = Column(UnicodeText)
    attraction_id = Column(UUID, ForeignKey('attraction.id'))

    events = relationship('AttractionEvent', backref='feature')

    __table_args__ = (UniqueConstraint('name', 'attraction_id'),)


# =====================================================================
# TODO: This, along with the panels.models.Event class, should be
#       refactored into a more generic "SchedulableMixin". Any model
#       class that has a location, a start time, and a duration would
#       inherit from the SchedulableMixin. I have discovered a truly
#       remarkable implementation of this design, which this pull-
#       request is too small to contain.
# =====================================================================
class AttractionEvent(MagModel):
    attraction_feature_id = Column(UUID, ForeignKey('attraction_feature.id'))
    location = Column(Choice(c.EVENT_LOCATION_OPTS))
    start_time = Column(UTCDateTime, default=Attraction.START_TIME_SLOT)
    duration = Column(Integer, default=Attraction.SLOT_DURATION)  # In seconds
    slots = Column(Integer, default=1)

    attendees = relationship(
        'Attendee',
        backref='attraction_events',
        cascade='save-update,merge,refresh-expire,expunge',
        secondary='attraction_signup')

    @property
    def end_time(self):
        return self.start_time + timedelta(seconds=self.duration)

    @property
    def start_time_label(self):
        if self.start_time:
            start_time = self.start_time.astimezone(c.EVENT_TIMEZONE)
            return start_time.strftime('%-I:%M %p %A')
        return 'unknown start time'

    @property
    def time_span_label(self):
        if self.start_time:
            end_time = self.end_time.astimezone(c.EVENT_TIMEZONE)
            end_day = end_time.strftime('%A')
            start_time = self.start_time.astimezone(c.EVENT_TIMEZONE)
            start_day = start_time.strftime('%A')
            if start_day == end_day:
                return '{} – {} {}'.format(
                    start_time.strftime('%-I:%M %p'),
                    end_time.strftime('%-I:%M %p'),
                    end_day)
            return '{} – {}'.format(
                start_time.strftime('%-I:%M %p %A'),
                end_time.strftime('%-I:%M %p %A'))
        return 'unknown time span'

    @property
    def duration_label(self):
        if self.duration:
            return humanize_timedelta(seconds=self.duration, separator=' ')
        return 'unknown duration'

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
        else:
            return int((earliest_end - latest_start).total_seconds())


class AttractionSignup(MagModel):
    attraction_event_id = Column(UUID, ForeignKey('attraction_event.id'))
    attendee_id = Column(UUID, ForeignKey('attendee.id'))

    checkin_time = Column(UTCDateTime, nullable=True)

    __mapper_args__ = {'confirm_deleted_rows': False}
    __table_args__ = (UniqueConstraint('attraction_event_id', 'attendee_id'),)
