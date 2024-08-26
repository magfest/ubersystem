from datetime import timedelta

from residue import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import Boolean, Date

from uber.config import c
from uber.decorators import presave_adjustment
from uber.models import MagModel
from uber.models.types import default_relationship as relationship, utcnow, DefaultColumn as Column, MultiChoice


__all__ = ['NightsMixin', 'HotelRequests', 'Room', 'RoomAssignment']


def _night(name):
    day = getattr(c, name.upper())

    def lookup(self):
        return day if day in self.nights_ints else ''

    lookup.__name__ = name
    lookup = property(lookup)

    def setter(self, val):
        if val:
            self.nights = '{},{}'.format(self.nights, day).strip(',')
        else:
            self.nights = ','.join([str(night) for night in self.nights_ints if night != day])
    setter.__name__ = name

    return lookup.setter(setter)


class NightsMixin(object):
    @property
    def nights_labels(self):
        ordered = sorted(self.nights_ints, key=c.NIGHT_DISPLAY_ORDER.index)
        return [c.NIGHTS[val] for val in ordered]

    @property
    def nights_display(self):
        return ' / '.join(self.nights_labels)

    @property
    def setup_teardown(self):
        return any(n for n in self.nights_ints if n not in c.CORE_NIGHTS)

    locals().update({
        mutate(night): _night(mutate(night))
        for night in c.NIGHT_NAMES
        for mutate in [str.upper, str.lower]})


class HotelRequests(MagModel, NightsMixin):
    attendee_id = Column(UUID, ForeignKey('attendee.id'), unique=True)
    nights = Column(MultiChoice(c.NIGHT_OPTS))
    wanted_roommates = Column(UnicodeText)
    unwanted_roommates = Column(UnicodeText)
    special_needs = Column(UnicodeText)
    approved = Column(Boolean, default=False, admin_only=True)

    def decline(self):
        nights = [n for n in self.nights.split(',') if int(n) in c.CORE_NIGHTS]
        self.nights = ','.join(nights)

    @presave_adjustment
    def cascading_save(self):
        self.attendee.presave_adjustments()

    def __repr__(self):
        return '<{self.attendee.full_name} Hotel Requests>'.format(self=self)


class Room(MagModel, NightsMixin):
    notes = Column(UnicodeText)
    message = Column(UnicodeText)
    locked_in = Column(Boolean, default=False)
    nights = Column(MultiChoice(c.NIGHT_OPTS))
    created = Column(UTCDateTime, server_default=utcnow(), default=lambda: datetime.now(UTC))
    assignments = relationship('RoomAssignment', backref='room')

    @property
    def email(self):
        return [ra.attendee.email for ra in self.assignments]

    @property
    def first_names(self):
        return [ra.attendee.first_name for ra in self.assignments]

    @property
    def check_in_date(self):
        return c.NIGHT_DATES[self.nights_labels[0]]

    @property
    def check_out_date(self):
        # TODO: Undo this kludgy workaround by fully implementing:
        #       https://github.com/magfest/hotel/issues/39
        if self.nights_labels[-1] == 'Monday':
            return c.ESCHATON.date() + timedelta(days=1)
        else:
            return c.NIGHT_DATES[self.nights_labels[-1]] + timedelta(days=1)


class RoomAssignment(MagModel):
    room_id = Column(UUID, ForeignKey('room.id'))
    attendee_id = Column(UUID, ForeignKey('attendee.id'))


class LotteryApplication(MagModel):
    # If this is null then the claim_code should be set and this is an invite waiting to be claimed
    attendee_id = Column(UUID, ForeignKey('attendee.id'), nullable=True)
    selection_priorities = Column(MultiChoice(c.HOTEL_LOTTERY_HOTEL_PRIORITIES_OPTS))
    
    wants_room = Column(Boolean, default=False)
    earliest_room_checkin_date = Column(Date)
    latest_room_checkin_date = Column(Date)
    earliest_room_checkout_date = Column(Date)
    latest_room_checkout_date = Column(Date)
    hotel_preference = Column(MultiChoice(c.HOTEL_LOTTERY_HOTELS_OPTS))
    room_type_preference = Column(MultiChoice(c.HOTEL_LOTTERY_ROOM_TYPES_OPTS))
    
    wants_suite = Column(Boolean, default=False)
    earliest_suite_checkin_date = Column(Date)
    latest_suite_checkin_date = Column(Date)
    earliest_suite_checkout_date = Column(Date)
    latest_suite_checkout_date = Column(Date)
    suite_type_preference = Column(MultiChoice(c.HOTEL_LOTTERY_SUITE_ROOM_TYPES_OPTS))
    
    terms_accepted = Column(Boolean, default=False)
    
    # If this is set to another application then the above values are overridden by the parent application
    # If this is not set then this application is the group leader.
    parent_application = Column(UUID, ForeignKey('lottery_application.id'), nullable=True)
    
    # This is a name for this group set by the owner so everyone else knows what they are joining
    application_group_name = Column(UnicodeText)
    
    # This is an attendee name shared with the group leader so they can see who is in their group
    public_attendee_name = Column(UnicodeText)
    
    # If set then this application is an invite to join the parent application
    claim_code = Column(UUID, nullable=True)