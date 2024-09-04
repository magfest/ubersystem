from datetime import timedelta, datetime
from markupsafe import Markup
from residue import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import backref
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import Boolean, Date

from uber.config import c
from uber.custom_tags import readable_join
from uber.decorators import presave_adjustment
from uber.models import MagModel
from uber.models.types import default_relationship as relationship, utcnow, DefaultColumn as Column, MultiChoice
from uber.utils import RegistrationCode


__all__ = ['NightsMixin', 'HotelRequests', 'Room', 'RoomAssignment', 'LotteryApplication']


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
    attendee_id = Column(UUID, ForeignKey('attendee.id'))
    attendee = relationship('Attendee', backref=backref('lottery_application', uselist=False),
                            cascade='save-update,merge,refresh-expire,expunge',
                            uselist=False)
    invite_code = Column(UnicodeText)

    wants_room = Column(Boolean, default=False)
    earliest_room_checkin_date = Column(Date, nullable=True)
    latest_room_checkin_date = Column(Date, nullable=True)
    earliest_room_checkout_date = Column(Date, nullable=True)
    latest_room_checkout_date = Column(Date, nullable=True)
    hotel_preference = Column(MultiChoice(c.HOTEL_LOTTERY_HOTELS_OPTS))
    room_type_preference = Column(MultiChoice(c.HOTEL_LOTTERY_ROOM_TYPES_OPTS))
    room_selection_priorities = Column(MultiChoice(c.HOTEL_LOTTERY_ROOM_PRIORITIES_OPTS))
    wants_ada = Column(Boolean, default=False)
    ada_requests = Column(UnicodeText)

    wants_suite = Column(Boolean, default=False)
    earliest_suite_checkin_date = Column(Date, nullable=True)
    latest_suite_checkin_date = Column(Date, nullable=True)
    earliest_suite_checkout_date = Column(Date, nullable=True)
    latest_suite_checkout_date = Column(Date, nullable=True)
    suite_type_preference = Column(MultiChoice(c.HOTEL_LOTTERY_SUITE_ROOM_TYPES_OPTS))
    suite_selection_priorities = Column(MultiChoice(c.HOTEL_LOTTERY_SUITE_PRIORITIES_OPTS))

    terms_accepted = Column(Boolean, default=False)
    suite_terms_accepted = Column(Boolean, default=False)

    # If this is set then the above values are ignored
    parent_application_id = Column(UUID, ForeignKey('lottery_application.id'), nullable=True)
    parent_application = relationship(
        'LotteryApplication',
        foreign_keys='LotteryApplication.parent_application_id',
        backref=backref('group_members'),
        cascade='save-update,merge,refresh-expire,expunge',
        remote_side='LotteryApplication.id',
        single_parent=True)

    room_group_name = Column(UnicodeText)

    @hybrid_property
    def normalized_code(self):
        return RegistrationCode.normalize_code(self.invite_code)

    @normalized_code.expression
    def normalized_code(cls):
        return RegistrationCode.sql_normalized_code(cls.invite_code)

    def generate_new_invite_code(self):
        return RegistrationCode.generate_random_code(LotteryApplication.invite_code)

    @property
    def group_leader_name(self):
        return f"{self.attendee.first_name[:1]}. {self.attendee.last_name[:1]}."

    @property
    def current_status_str(self):
        if not self.wants_room and not self.wants_suite and not self.parent_application:
            return "do NOT have an entry in the hotel room or suite lottery"

        plural = False
        have_str = ''
        app_or_parent = self.parent_application or self
        if self.parent_application:
            group_leader_name = self.parent_application.group_leader_name
            have_str = f'are in {group_leader_name}\'s "{self.parent_application.room_group_name}" room group, which '
        elif self.room_group_name:
            have_str = f'are the group leader for "{self.room_group_name}". Your group '
        else:
            plural = True

        if app_or_parent.wants_room and app_or_parent.wants_suite:
            have_str += '{} a room lottery entry and a suite lottery entry'.format(
                'have' if plural else 'has')
        elif app_or_parent.wants_room:
            have_str += '{} a room lottery entry. {} not have a suite lottery entry'.format(
                'have' if plural else 'has', 'You do' if plural else 'It does')
        elif app_or_parent.wants_suite:
            have_str += '{} NOT have a room lottery entry but {} have a suite lottery entry'.format(
                'do' if plural else 'does', 'you have' if plural else 'it does')

        return have_str
    
    @property
    def has_any_entry(self):
        return self.parent_application or self.wants_room or self.wants_suite

    @property
    def can_create_group(self):
        return self.wants_room or self.wants_suite

    def build_nights_map(self, check_in, check_out):
        if isinstance(check_in, datetime):
            check_in = check_in.date()
        if isinstance(check_out, datetime):
            check_out = check_out.date()
        if check_in > check_out:
            return {}

        date_map = []
        day = check_in
        while day != check_out:
            date_map.append(day.strftime('%A %Y-%m-%d'))
            day += timedelta(days=1)

        date_map.append(check_out.strftime('%A %Y-%m-%d'))
        return date_map
    
    @property
    def room_requirements_str(self):
        return "Standard rooms require a two-night minimum with at least one night on Friday or Saturday."
    
    @property
    def suite_requirements_str(self):
        return Markup("Suites require a three-night minimum, including <em>both</em> Friday <em>and</em> Saturday.")

    @property
    def shortest_room_check_in_out_dates(self):
        return (self.latest_room_checkin_date or self.earliest_room_checkin_date), (
            self.earliest_room_checkout_date or self.latest_room_checkout_date)

    @property
    def any_room_dates_different(self):
        return self.earliest_room_checkin_date != self.orig_value_of('earliest_room_checkin_date') or \
            self.latest_room_checkin_date != self.orig_value_of('latest_room_checkin_date') or \
            self.earliest_room_checkout_date != self.orig_value_of('latest_room_checkout_date') or \
            self.latest_room_checkout_date != self.orig_value_of('latest_room_checkout_date')

    @property
    def shortest_suite_check_in_out_dates(self):
        return (self.latest_suite_checkin_date or self.earliest_suite_checkin_date), (
            self.earliest_suite_checkout_date or self.latest_suite_checkout_date)

    @property
    def any_suite_dates_different(self):
        return self.earliest_suite_checkin_date != self.orig_value_of('earliest_suite_checkin_date') or \
            self.latest_suite_checkin_date != self.orig_value_of('latest_suite_checkin_date') or \
            self.earliest_suite_checkout_date != self.orig_value_of('latest_suite_checkout_date') or \
            self.latest_suite_checkout_date != self.orig_value_of('latest_suite_checkout_date')
