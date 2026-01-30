import logging
import random

import checkdigit.verhoeff as verhoeff
from datetime import timedelta, datetime
from pytz import UTC
from markupsafe import Markup
from residue import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy import Sequence, case
from sqlalchemy.dialects.postgresql.json import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import backref
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import Boolean, Date, Integer

from uber.config import c
from uber.custom_tags import readable_join, datetime_local_filter
from uber.decorators import presave_adjustment
from uber.models import MagModel
from uber.models.types import Choice, default_relationship as relationship, utcnow, DefaultColumn as Column, MultiChoice
from uber.utils import RegistrationCode

log = logging.getLogger(__name__)


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
    can_edit = Column(Boolean, default=False)
    final_status_hidden = Column(Boolean, default=True)
    booking_url_hidden = Column(Boolean, default=True)

    # If this is set then the above values are ignored
    parent_application_id = Column(UUID, ForeignKey('lottery_application.id'), nullable=True)
    parent_application = relationship(
        'LotteryApplication',
        foreign_keys='LotteryApplication.parent_application_id',
        backref=backref('group_members'),
        cascade='save-update,merge,refresh-expire,expunge',
        remote_side='LotteryApplication.id',
        single_parent=True)
    former_parent_id = Column(UUID, nullable=True)

    room_group_name = Column(UnicodeText)
    email_model_name = 'app'

    assigned_hotel = Column(Choice(c.HOTEL_LOTTERY_HOTELS_OPTS), nullable=True)
    assigned_room_type = Column(Choice(c.HOTEL_LOTTERY_ROOM_TYPES_OPTS), nullable=True)
    assigned_suite_type = Column(Choice(c.HOTEL_LOTTERY_SUITE_ROOM_TYPES_OPTS), nullable=True)
    assigned_check_in_date = Column(Date, nullable=True)
    assigned_check_out_date = Column(Date, nullable=True)
    deposit_cutoff_date = Column(Date, nullable=True)
    lottery_name = Column(UnicodeText)
    booking_url = Column(UnicodeText)

    @presave_adjustment
    def unset_entry_type(self):
        if self.entry_type == 0:
            self.entry_type = None

    @presave_adjustment
    def set_confirmation_num(self):
        if not self.confirmation_num and self.status not in [c.WITHDRAWN, c.DISQUALIFIED]:
            self.confirmation_num = self.generate_confirmation_num()

    @hybrid_property
    def assigned_room_or_suite_type(self):
        return self.assigned_suite_type or self.assigned_room_type

    @assigned_room_or_suite_type.expression
    def assigned_room_or_suite_type(cls):
        return case(
            [(cls.assigned_suite_type != None, cls.assigned_suite_type)],  # noqa: E711
            else_=cls.assigned_room_type)

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
    def birthdate(self):
        if self.attendee:
            return self.attendee.birthdate

    @property
    def attendee_name(self):
        return self.attendee.full_name if self.attendee else "[DISASSOCIATED]"

    @property
    def application_status_str(self):
        app_or_parent = self.parent_application if self.entry_type == c.GROUP_ENTRY else self
        if not app_or_parent.complete_or_processed:
            return "NOT entered in the hotel room or suite lottery"

        if app_or_parent.entry_type == c.SUITE_ENTRY:
            return f"entered into the suite lottery{'' if app_or_parent.room_opt_out else ' and room lottery'}"
        else:
            return "entered into the room lottery"
        
    @property
    def staff_award_status_str(self):
        # Allows special text to be shown for the staff lottery, in case
        # it works differently from the attendee lottery
        return ''

    @property
    def award_status_str(self):
        app_or_parent = self.parent_application if self.entry_type == c.GROUP_ENTRY else self
        if not c.HOTEL_LOTTERY_ROOM_INVENTORY or self.final_status_hidden and not self.status in [c.SECURED, c.CANCELLED]:
            return ''
        if not self.finalized and (
                not c.HOTEL_LOTTERY_FORM_WAITLIST or not self.qualifies_for_first_round or c.BEFORE_HOTEL_LOTTERY_FORM_WAITLIST):
            return ''
        if self.staff_award_status_str:
            return self.staff_award_status_str
        if self.status == c.REMOVED:
            return f"Unfortunately, your {c.HOTEL_LOTTERY_GROUP_TERM.lower()}'s awarded room does not have enough \
                capacity for all roommates, and you were removed from the group."
        if self.parent_application:
            you_str = f"Your {c.HOTEL_LOTTERY_GROUP_TERM.lower()}'s"
        else:
            you_str = "Your"

        room_type = 'suite' if app_or_parent.assigned_suite_type else 'room'

        if app_or_parent.status == c.CANCELLED:
            has_or_had_parent = self.parent_application or self.former_parent_id
            if not has_or_had_parent and self.declined:
                return f"You have declined your {room_type} and your lottery entry has been cancelled."

            base_str = f"Unfortunately, {you_str.lower()} {room_type} has been cancelled "
            if self.entry_started:
                if has_or_had_parent:
                    base_str = base_str + f"because your {c.HOTEL_LOTTERY_GROUP_TERM.lower()} leader "
                else:
                    base_str = base_str + "because you "
                return base_str + f"did not secure your room with a credit card before the deadline of {datetime_local_filter(self.guarantee_deadline, '%A, %B %-d')}."
            elif has_or_had_parent:
                return base_str + f"by your {c.HOTEL_LOTTERY_GROUP_TERM.lower()} leader."
        elif app_or_parent.assigned_hotel:
            return f"Congratulations! {you_str} entry for the {c.EVENT_NAME_AND_YEAR} {room_type} lottery was chosen."
        else:
            base_str = f"Unfortunately, {you_str.lower()} entry for the {c.EVENT_NAME_AND_YEAR} hotel lottery was not chosen"
            if c.HOTEL_LOTTERY_FORM_WAITLIST and not app_or_parent.finalized and c.AFTER_HOTEL_LOTTERY_FORM_WAITLIST:
                return base_str + " in the first round of the lottery."
            return base_str + "."

    @property
    def can_reenter(self):
        return self.status in [c.PARTIAL, c.WITHDRAWN, c.CANCELLED, c.REMOVED]

    @property
    def finalized(self):
        return self.status in [c.AWARDED, c.SECURED, c.REJECTED, c.CANCELLED, c.REMOVED]

    @property
    def locked(self):
        return self.current_lottery_closed or (
            self.qualifies_for_first_round and c.AFTER_HOTEL_LOTTERY_FORM_WAITLIST
        ) or (self.finalized and not self.final_status_hidden)

    @property
    def declined(self):
        return self.status == c.CANCELLED and not self.entry_started

    @property
    def complete_or_processed(self):
        return self.status in [c.COMPLETE, c.PROCESSED] or self.finalized

    @property
    def qualifies_for_first_round(self):
        if c.HOTEL_LOTTERY_FORM_WAITLIST:
            return self.complete_or_processed and self.last_submitted and self.last_submitted < c.HOTEL_LOTTERY_FORM_WAITLIST

    @property
    def booking_url_ready(self):
        app_or_parent = self.parent_application if self.entry_type == c.GROUP_ENTRY else self
        return app_or_parent.booking_url and not app_or_parent.booking_url_hidden

    @property
    def group_status_str(self):
        if self.parent_application:
            group_leader_name = self.parent_application.group_leader_name
            text = f'are in {group_leader_name}\'s {c.HOTEL_LOTTERY_GROUP_TERM.lower()} "{self.parent_application.room_group_name}"'
            if self.parent_application.is_staff_entry and not self.is_staff_entry and not c.STAFF_HOTEL_LOTTERY_OPEN:
                text = f'{text}. Your group leader must re-enter the attendee lottery before your entry becomes valid'
            return f'{text}. Your confirmation number is {self.confirmation_num}'
        elif self.room_group_name:
            return f'are the group leader for "{self.room_group_name}"'
        else:
            return f"are not part of a {c.HOTEL_LOTTERY_GROUP_TERM.lower()}"

    @property
    def group_member_names(self):
        return [f"{app.legal_first_name} {app.legal_last_name}" for app in self.valid_group_members]
    
    @property
    def valid_group_members(self):
        return [app for app in self.group_members if app.attendee and app.attendee.hotel_lottery_eligible and 
                app.status in ([c.COMPLETE, c.REJECTED] + c.HOTEL_LOTTERY_AWARD_STATUSES)]

    @property
    def qualifies_for_staff_lottery(self):
        return self.attendee and self.attendee.staff_hotel_lottery_eligible

    @property
    def current_lottery_deadline(self):
        if c.STAFF_HOTEL_LOTTERY_OPEN and self.qualifies_for_staff_lottery:
            return c.HOTEL_LOTTERY_STAFF_DEADLINE
        elif c.HOTEL_LOTTERY_OPEN:
            return c.HOTEL_LOTTERY_FORM_DEADLINE

    @property
    def current_lottery_closed(self):
        if self.can_edit:
            return False

        if self.is_staff_entry:
            return not c.STAFF_HOTEL_LOTTERY_OPEN
        elif self.qualifies_for_staff_lottery:
            return not c.STAFF_HOTEL_LOTTERY_OPEN and not c.HOTEL_LOTTERY_OPEN
        return not c.HOTEL_LOTTERY_OPEN

    @property
    def guarantee_deadline(self):
        if self.deposit_cutoff_date:
            return self.deposit_cutoff_date

        if c.HOTEL_LOTTERY_STAFF_GUARANTEE_DUE and (
                self.is_staff_entry or c.STAFF_HOTEL_LOTTERY_OPEN and self.qualifies_for_staff_lottery):
            return c.HOTEL_LOTTERY_STAFF_GUARANTEE_DUE
        return c.HOTEL_LOTTERY_GUARANTEE_DUE

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
        if self.status in [c.COMPLETE, c.PROCESSED] or self.finalized and self.final_status_hidden:
            prepend = "View " if c.ATTENDEE_ACCOUNTS_ENABLED else ""
            return f'index?attendee_id={self.attendee.id}', f'{prepend}{entry_text}'
        elif self.finalized:
            return f'index?attendee_id={self.attendee.id}', 'Hotel Lottery Results'
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
