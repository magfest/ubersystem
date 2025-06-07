import random

import checkdigit.verhoeff as verhoeff
from datetime import timedelta, datetime
from pytz import UTC
from markupsafe import Markup
from pockets.autolog import log
from residue import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy import Sequence
from sqlalchemy.dialects.postgresql.json import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import backref
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import Boolean, Date, Integer

from uber.config import c
from uber.custom_tags import readable_join
from uber.decorators import presave_adjustment
from uber.models import MagModel
from uber.models.types import Choice, default_relationship as relationship, utcnow, DefaultColumn as Column, MultiChoice
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
    attendee_id = Column(UUID, ForeignKey('attendee.id'), unique=True, nullable=True)
    attendee = relationship('Attendee', backref=backref('lottery_application', uselist=False),
                            cascade='save-update,merge,refresh-expire,expunge',
                            uselist=False)
    invite_code = Column(UnicodeText) # Not used for now but we're keeping it for later
    confirmation_num = Column(UnicodeText)

    response_id_seq = Sequence('lottery_application_response_id_seq')
    response_id = Column(Integer, response_id_seq, server_default=response_id_seq.next_value(), unique=True)
    status = Column(Choice(c.HOTEL_LOTTERY_STATUS_OPTS), default=c.PARTIAL, admin_only=True)
    entry_started = Column(UTCDateTime, nullable=True)
    entry_metadata = Column(MutableDict.as_mutable(JSONB), server_default='{}', default={})
    entry_type = Column(Choice(c.HOTEL_LOTTERY_ENTRY_TYPE_OPTS), nullable=True)
    current_step = Column(Integer, default=0)
    last_submitted = Column(UTCDateTime, nullable=True)
    admin_notes = Column(UnicodeText)
    is_staff_entry = Column(Boolean, default=False)

    legal_first_name = Column(UnicodeText)
    legal_last_name = Column(UnicodeText)
    cellphone = Column(UnicodeText)
    earliest_checkin_date = Column(Date, nullable=True)
    latest_checkin_date = Column(Date, nullable=True)
    earliest_checkout_date = Column(Date, nullable=True)
    latest_checkout_date = Column(Date, nullable=True)
    selection_priorities = Column(MultiChoice(c.HOTEL_LOTTERY_PRIORITIES_OPTS))

    hotel_preference = Column(MultiChoice(c.HOTEL_LOTTERY_HOTELS_OPTS))
    room_type_preference = Column(MultiChoice(c.HOTEL_LOTTERY_ROOM_TYPES_OPTS))
    wants_ada = Column(Boolean, default=False)
    ada_requests = Column(UnicodeText)

    room_opt_out = Column(Boolean, default=False)
    suite_type_preference = Column(MultiChoice(c.HOTEL_LOTTERY_SUITE_ROOM_TYPES_OPTS))

    terms_accepted = Column(Boolean, default=False)
    data_policy_accepted = Column(Boolean, default=False)
    suite_terms_accepted = Column(Boolean, default=False)
    guarantee_policy_accepted = Column(Boolean, default=False)

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
    email_model_name = 'app'

    @presave_adjustment
    def unset_entry_type(self):
        if self.entry_type == 0:
            self.entry_type = None

    @presave_adjustment
    def set_confirmation_num(self):
        if not self.confirmation_num and self.status not in [c.WITHDRAWN, c.DISQUALIFIED]:
            self.confirmation_num = self.generate_confirmation_num()

    @hybrid_property
    def normalized_code(self):
        return RegistrationCode.normalize_code(self.invite_code)

    @normalized_code.expression
    def normalized_code(cls):
        return RegistrationCode.sql_normalized_code(cls.invite_code)

    def generate_new_invite_code(self):
        return RegistrationCode.generate_random_code(LotteryApplication.invite_code)
    
    def _generate_conf_num(self, generator):
        from uber.models import Session
        with Session() as session:
            # Kind of inefficient, but doing one big query for all the existing
            # codes will be faster than a separate query for each new code.
            old_codes = set(s for (s,) in session.query(LotteryApplication.confirmation_num).all())

        # Set an upper limit on the number of collisions we'll allow,
        # otherwise this loop could potentially run forever.
        max_collisions = 10000
        collisions = 0
        while 0 < 1:
            code = generator()
            if not code:
                break
            if code in old_codes:
                collisions += 1
                if collisions >= max_collisions:
                    log.error("WARNING: We couldn't manage to generate a unique hotel lottery confirmation number in 10,000 tries!")
                    return 0
            else:
                return code

    def generate_confirmation_num(self):
        # The actual generator function, called repeatedly by `_generate_conf_num`
        def _generate_random_conf():
            base_num = ''.join(str(random.randint(0,9)) for _ in range(9))
            checkdigit = verhoeff.calculate(base_num)
            return f"{base_num}{checkdigit}"

        return self._generate_conf_num(_generate_random_conf)

    @property
    def group_leader_name(self):
        return f"{self.attendee.first_name[:1]}. {self.attendee.last_name[:1]}."
    
    @property
    def email(self):
        if self.attendee:
            return self.attendee.email
        
    @property
    def attendee_name(self):
        return self.attendee.full_name if self.attendee else "[DISASSOCIATED]"

    @property
    def current_status_str(self):
        app_or_parent = self.parent_application or self
        if not app_or_parent.entry_type:
            return "do NOT have an entry in the hotel room or suite lottery"
        
        if app_or_parent.entry_type == c.SUITE_ENTRY:
            return f"are entered into the suite lottery{'' if app_or_parent.room_opt_out else ' and room lottery'}"
        else:
            return "are entered into the room lottery"

    @property
    def group_status_str(self):
        if self.parent_application:
            group_leader_name = self.parent_application.group_leader_name
            text = f'are in {group_leader_name}\'s room group "{self.parent_application.room_group_name}"'
            if self.parent_application.is_staff_entry and not self.is_staff_entry and not c.STAFF_HOTEL_LOTTERY_OPEN:
                text = f'{text}. Your group leader must re-enter the attendee lottery before your entry becomes valid'
            return f'{text}. Your confirmation number is {self.confirmation_num}'
        elif self.room_group_name:
            return f'are the group leader for "{self.room_group_name}". Your group has {len(self.group_members) + 1} group members, including yourself'

    @property
    def qualifies_for_staff_lottery(self):
        return self.attendee.staff_hotel_lottery_eligible
    
    @property
    def current_lottery_deadline(self):
        return c.HOTEL_LOTTERY_STAFF_DEADLINE if c.STAFF_HOTEL_LOTTERY_OPEN and self.qualifies_for_staff_lottery \
            else c.HOTEL_LOTTERY_FORM_DEADLINE

    @property
    def entry_form_completed(self):
        return self.current_step >= self.last_step
    
    @property
    def last_step(self):
        if self.entry_type == c.SUITE_ENTRY:
            return c.HOTEL_LOTTERY_FORM_STEPS['suite_final_step']
        return c.HOTEL_LOTTERY_FORM_STEPS['room_final_step']

    @property
    def homepage_link(self):
        entry_text = 'Suite Lottery Entry' if self.entry_type == c.SUITE_ENTRY else 'Room Lottery Entry'
        if self.status == c.COMPLETE:
            return f'index?attendee_id={self.attendee.id}', f'View {entry_text}'
        elif self.entry_form_completed:
            return f'guarantee_confirm?id={self.id}', f"Finish {entry_text}"
        elif self.entry_type == c.SUITE_ENTRY:
            return f'suite_lottery?id={self.id}', f"Finish {entry_text}"
        elif self.entry_type == c.ROOM_ENTRY:
            f'room_lottery?id={self.id}', f"Finish {entry_text}"
        return f'start?attendee_id={self.attendee.id}', "Enter Hotel Lottery"

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
    def shortest_check_in_out_dates(self):
        return (self.latest_checkin_date or self.earliest_checkin_date), (
            self.earliest_checkout_date or self.latest_checkout_date)

    @property
    def any_dates_different(self):
        return self.earliest_checkin_date != self.orig_value_of('earliest_checkin_date') or \
            self.latest_checkin_date != self.orig_value_of('latest_checkin_date') or \
            self.earliest_checkout_date != self.orig_value_of('earliest_checkout_date') or \
            self.latest_checkout_date != self.orig_value_of('latest_checkout_date')

    @property
    def update_group_members(self):
        # Group members can't see ADA info or check-in name, so we don't want to email them if those are the only changes
        return self.any_dates_different or self.hotel_preference != self.orig_value_of('hotel_preference') or \
               self.room_type_preference != self.orig_value_of('room_type_preference') or \
               self.suite_type_preference != self.orig_value_of('suite_type_preference') or \
               self.selection_priorities != self.orig_value_of('selection_priorities')
