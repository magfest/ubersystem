import logging
import random

import checkdigit.verhoeff as verhoeff
from datetime import timedelta, datetime, date
from pytz import UTC
from markupsafe import Markup
import sqlalchemy as sa
from sqlalchemy import Sequence, case
from sqlalchemy.dialects.postgresql.json import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.types import Date, Integer, DateTime, Uuid
from typing import Any, ClassVar

from uber.config import c
from uber.custom_tags import readable_join, datetime_local_filter
from uber.decorators import presave_adjustment
from uber.models import MagModel
from uber.models.types import Choice, DefaultColumn as Column, MultiChoice, DefaultField as Field, DefaultRelationship as Relationship
from uber.utils import RegistrationCode

log = logging.getLogger(__name__)


__all__ = ['NightsMixin', 'HotelRequests', 'Room', 'RoomAssignment', 'LotteryApplication',
           'HotelRoomInventory', 'InventoryNightQuantity', 'InventoryPartition', 'InventoryPartitionBlock',
           'LotteryRun', 'HotelExportLog',
           'LotteryHotel', 'LotteryRoomType']


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


class HotelRequests(MagModel, NightsMixin, table=True):
    attendee_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='attendee.id', ondelete='CASCADE', unique=True)
    attendee: 'Attendee' = Relationship(back_populates="hotel_requests")

    nights: str = Field(sa_type=MultiChoice(c.NIGHT_OPTS), default='')
    wanted_roommates: str = ''
    unwanted_roommates: str = ''
    special_needs: str = ''
    approved: bool = Field(default=False, admin_only=True)

    def decline(self):
        nights = [n for n in self.nights.split(',') if int(n) in c.CORE_NIGHTS]
        self.nights = ','.join(nights)

    @presave_adjustment
    def cascading_save(self):
        self.attendee.presave_adjustments()

    def __repr__(self):
        return '<{self.attendee.full_name} Hotel Requests>'.format(self=self)


class Room(MagModel, NightsMixin, table=True):
    notes: str = ''
    message: str = ''
    locked_in: bool = False
    nights: str = Field(sa_type=MultiChoice(c.NIGHT_OPTS), default='')
    created: datetime = Field(sa_type=DateTime(timezone=True), default_factory=lambda: datetime.now(UTC))

    assignments: list['RoomAssignment'] = Relationship(back_populates="room",
                                                       sa_relationship_kwargs={'cascade': 'all,delete-orphan', 'passive_deletes': True})

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


class RoomAssignment(MagModel, table=True):
    room_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='room.id', ondelete='CASCADE')
    room: 'Room' = Relationship(back_populates="assignments", sa_relationship_kwargs={'lazy': 'joined'})

    attendee_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='attendee.id', ondelete='CASCADE')
    attendee: 'Attendee' = Relationship(back_populates="room_assignments", sa_relationship_kwargs={'lazy': 'joined'})


class LotteryApplication(MagModel, table=True):
    attendee_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='attendee.id', nullable=True, unique=True)
    attendee: 'Attendee' = Relationship(back_populates="lottery_application", sa_relationship_kwargs={'lazy': 'joined', 'single_parent': True})

    invite_code: str = '' # Not used for now but we're keeping it for later
    confirmation_num: str = ''
    response_id_seq: ClassVar = Sequence('lottery_application_response_id_seq')
    response_id: int = Field(sa_column=Column(Integer, response_id_seq, server_default=response_id_seq.next_value(), unique=True))
    status: int = Field(sa_column=Column(Choice(c.HOTEL_LOTTERY_STATUS_OPTS), admin_only=True), default=c.PARTIAL)
    entry_started: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True)
    entry_metadata: dict[str, Any] = Field(sa_type=MutableDict.as_mutable(JSONB), default_factory=dict)
    entry_type: int | None = Field(sa_column=Column(Choice(c.HOTEL_LOTTERY_ENTRY_TYPE_OPTS), nullable=True))
    current_step: int = 0
    last_submitted: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True)
    admin_notes: str = ''
    is_staff_entry: bool = False

    legal_first_name: str = ''
    legal_last_name: str = ''
    cellphone: str = ''
    earliest_checkin_date: date | None = Field(sa_type=Date, nullable=True)
    latest_checkin_date: date | None = Field(sa_type=Date, nullable=True)
    earliest_checkout_date: date | None = Field(sa_type=Date, nullable=True)
    latest_checkout_date: date | None = Field(sa_type=Date, nullable=True)
    hotel_preference: str = ''  # Comma-separated LotteryHotel UUIDs
    room_type_preference: str = ''  # Comma-separated LotteryRoomType UUIDs
    wants_ada: bool = False
    ada_requests: str = ''

    room_opt_out: bool = False
    suite_type_preference: str = ''  # Comma-separated LotteryRoomType UUIDs (suites)

    terms_accepted: bool = False
    data_policy_accepted: bool = False
    suite_terms_accepted: bool = False
    guarantee_policy_accepted: bool = False
    can_edit: bool = False

    # If this is set then the above values are ignored
    parent_application_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='lottery_application.id', nullable=True)
    parent_application: 'LotteryApplication' = Relationship(
        back_populates="group_members",
        sa_relationship_kwargs={'lazy': 'joined', 'foreign_keys': 'LotteryApplication.parent_application_id',
                                'remote_side': 'LotteryApplication.id'})
    group_members: list['LotteryApplication'] = Relationship(
        back_populates="parent_application",
        sa_relationship_kwargs={'foreign_keys': 'LotteryApplication.parent_application_id'})
    former_parent_id: str | None = Field(sa_type=Uuid(as_uuid=False), nullable=True)

    room_group_name: str = ''
    email_model_name: ClassVar = 'app'

    assigned_inventory_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='hotel_room_inventory.id', nullable=True)
    assigned_inventory: 'HotelRoomInventory' = Relationship(
        sa_relationship_kwargs={'foreign_keys': 'LotteryApplication.assigned_inventory_id', 'lazy': 'joined',
                                'overlaps': 'assigned_applications'})
    partition_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='inventory_partition.id', nullable=True)
    partition: 'InventoryPartition' = Relationship(
        sa_relationship_kwargs={'foreign_keys': 'LotteryApplication.partition_id', 'lazy': 'joined'})
    export_locked: bool = False

    # Email-based room guest invite fields
    invite_token: str = ''
    invited_by_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='lottery_application.id', nullable=True)
    invited_by: 'LotteryApplication' = Relationship(
        sa_relationship_kwargs={'foreign_keys': 'LotteryApplication.invited_by_id',
                                'remote_side': 'LotteryApplication.id'})
    invite_status: int = Field(sa_column=Column(Choice(c.HOTEL_INVITE_STATUS_OPTS), default=c.NO_INVITE))
    invite_expires_at: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True)
    assigned_check_in_date: date | None = Field(sa_type=Date, nullable=True)
    assigned_check_out_date: date | None = Field(sa_type=Date, nullable=True)
    deposit_cutoff_date: date | None = Field(sa_type=Date, nullable=True)
    lottery_name: str = ''
    booking_url: str = ''

    # Credit card vaulting (PCI Vault tokens, NOT card data)
    cc_token: str | None = Field(nullable=True)
    cc_last_four: str | None = Field(nullable=True)
    cc_card_type: str | None = Field(nullable=True)
    cc_card_holder: str | None = Field(nullable=True)
    cc_card_expiry: str | None = Field(nullable=True)
    cc_issuer_brand: str | None = Field(nullable=True)
    cc_issuer_bank: str | None = Field(nullable=True)
    cc_issuer_country: str | None = Field(nullable=True)
    cc_issuer_card_type: str | None = Field(nullable=True)
    cc_issuer_card_level: str | None = Field(nullable=True)
    cc_captured_at: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True)

    # Billing address for hotel booking
    address1: str = ''
    address2: str = ''
    city: str = ''
    region: str = ''
    zip_code: str = ''
    country: str = ''

    # Hotel confirmation and post-award fields
    hotel_confirmation_number: str | None = Field(nullable=True)
    special_requests: str = ''
    hotel_rewards_number: str = ''
    last_modified_at: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True)

    # Link to the lottery run that assigned this room
    lottery_run_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='lottery_run.id', nullable=True)

    @presave_adjustment
    def update_last_modified(self):
        dominated_fields = ['assigned_check_in_date', 'assigned_check_out_date', 'special_requests',
                            'assigned_inventory_id',
                            'address1', 'address2', 'city', 'region', 'zip_code', 'country']
        if any(getattr(self, f) != self.orig_value_of(f) for f in dominated_fields):
            self.last_modified_at = datetime.now(UTC)

    @presave_adjustment
    def unset_entry_type(self):
        if self.entry_type == 0:
            self.entry_type = None

    @presave_adjustment
    def set_confirmation_num(self):
        if not self.confirmation_num and self.status not in [c.WITHDRAWN, c.DISQUALIFIED]:
            self.confirmation_num = self.generate_confirmation_num()

    @property
    def assigned_hotel(self):
        return self.assigned_inventory.hotel if self.assigned_inventory else None

    @property
    def assigned_hotel_id(self):
        return self.assigned_inventory.hotel_id if self.assigned_inventory else None

    @property
    def assigned_room_type(self):
        if self.assigned_inventory and not self.assigned_inventory.is_suite:
            return self.assigned_inventory.room_type
        return None

    @property
    def assigned_room_type_id(self):
        if self.assigned_inventory and not self.assigned_inventory.is_suite:
            return self.assigned_inventory.room_type_id
        return None

    @property
    def assigned_suite_type(self):
        if self.assigned_inventory and self.assigned_inventory.is_suite:
            return self.assigned_inventory.suite_type
        return None

    @property
    def assigned_suite_type_id(self):
        if self.assigned_inventory and self.assigned_inventory.is_suite:
            return self.assigned_inventory.suite_type_id
        return None

    @property
    def assigned_room_or_suite_type(self):
        return self.assigned_inventory.room_or_suite_type if self.assigned_inventory else None

    @property
    def assigned_room_or_suite_type_id(self):
        return self.assigned_inventory.room_or_suite_type_id if self.assigned_inventory else None

    @property
    def hotel_preference_labels(self):
        """Return list of hotel names from preference UUIDs."""
        from sqlalchemy import inspect as sa_inspect
        session = sa_inspect(self).session
        if not session or not self.hotel_preference:
            return []
        ids = [x.strip() for x in self.hotel_preference.split(',') if x.strip()]
        hotels = session.query(LotteryHotel).filter(LotteryHotel.id.in_(ids)).all()
        hotel_map = {str(h.id): h.name for h in hotels}
        return [hotel_map[i] for i in ids if i in hotel_map]

    @property
    def room_type_preference_labels(self):
        """Return list of room type names from preference UUIDs."""
        from sqlalchemy import inspect as sa_inspect
        session = sa_inspect(self).session
        if not session or not self.room_type_preference:
            return []
        ids = [x.strip() for x in self.room_type_preference.split(',') if x.strip()]
        room_types = session.query(LotteryRoomType).filter(LotteryRoomType.id.in_(ids)).all()
        rt_map = {str(rt.id): rt.name for rt in room_types}
        return [rt_map[i] for i in ids if i in rt_map]

    @property
    def suite_type_preference_labels(self):
        """Return list of suite type names from preference UUIDs."""
        from sqlalchemy import inspect as sa_inspect
        session = sa_inspect(self).session
        if not session or not self.suite_type_preference:
            return []
        ids = [x.strip() for x in self.suite_type_preference.split(',') if x.strip()]
        suite_types = session.query(LotteryRoomType).filter(LotteryRoomType.id.in_(ids)).all()
        st_map = {str(st.id): st.name for st in suite_types}
        return [st_map[i] for i in ids if i in st_map]

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
        if not self.finalized:
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
            return f"Unfortunately, {you_str.lower()} entry for the {c.EVENT_NAME_AND_YEAR} hotel lottery was not chosen."

    @property
    def can_reenter(self):
        return self.status in [c.PARTIAL, c.WITHDRAWN, c.CANCELLED, c.REMOVED]

    @property
    def finalized(self):
        return self.status in [c.AWARDED, c.SECURED, c.REJECTED, c.CANCELLED, c.REMOVED]

    @property
    def locked(self):
        return self.current_lottery_closed or self.finalized

    @property
    def declined(self):
        return self.status == c.CANCELLED and not self.entry_started

    @property
    def complete_or_processed(self):
        return self.status in [c.COMPLETE, c.PROCESSED] or self.finalized

    @property
    def booking_url_ready(self):
        app_or_parent = self.parent_application if self.entry_type == c.GROUP_ENTRY else self
        return bool(app_or_parent.booking_url)

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
        if self.status in [c.COMPLETE, c.PROCESSED]:
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
    def waitlisted_checkin_nights(self):
        if not self.earliest_checkin_date or not self.assigned_check_in_date:
            return 0
        return max(0, (self.assigned_check_in_date - self.earliest_checkin_date).days)

    @property
    def waitlisted_checkout_nights(self):
        if not self.latest_checkout_date or not self.assigned_check_out_date:
            return 0
        return max(0, (self.latest_checkout_date - self.assigned_check_out_date).days)

    @property
    def has_waitlist_request(self):
        return self.waitlisted_checkin_nights > 0 or self.waitlisted_checkout_nights > 0

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
               self.suite_type_preference != self.orig_value_of('suite_type_preference')


class LotteryHotel(MagModel, table=True):
    name: str = ''
    export_name: str = ''
    description: str = ''
    description_right: str = ''
    footnote: str = ''
    active: bool = True


class LotteryRoomType(MagModel, table=True):
    name: str = ''
    export_name: str = ''
    description: str = ''
    description_right: str = ''
    footnote: str = ''
    capacity: int = 4
    min_capacity: int = 1
    is_suite: bool = False
    active: bool = True


class InventoryPartition(MagModel, table=True):
    name: str = ''
    description: str = ''
    active: bool = True

    blocks: list['InventoryPartitionBlock'] = Relationship(
        back_populates="partition",
        sa_relationship_kwargs={'cascade': 'all,delete-orphan', 'passive_deletes': True})


class InventoryPartitionBlock(MagModel, table=True):
    __table_args__ = (
        sa.UniqueConstraint('partition_id', 'inventory_id', name='uq_partition_inventory'),
    )

    partition_id: str = Field(sa_type=Uuid(as_uuid=False), foreign_key='inventory_partition.id')
    partition: 'InventoryPartition' = Relationship(
        back_populates="blocks",
        sa_relationship_kwargs={'foreign_keys': 'InventoryPartitionBlock.partition_id'})
    inventory_id: str = Field(sa_type=Uuid(as_uuid=False), foreign_key='hotel_room_inventory.id')
    inventory: 'HotelRoomInventory' = Relationship(
        sa_relationship_kwargs={'foreign_keys': 'InventoryPartitionBlock.inventory_id'})
    quantity: int = 0


class InventoryNightQuantity(MagModel, table=True):
    __table_args__ = (
        sa.UniqueConstraint('inventory_id', 'night_date', name='uq_inventory_night'),
    )

    inventory_id: str = Field(sa_type=Uuid(as_uuid=False), foreign_key='hotel_room_inventory.id')
    inventory: 'HotelRoomInventory' = Relationship(
        back_populates="night_quantities",
        sa_relationship_kwargs={'foreign_keys': 'InventoryNightQuantity.inventory_id'})
    night_date: date = Field(sa_type=Date)
    quantity: int = 0


class HotelRoomInventory(MagModel, table=True):
    hotel_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='lottery_hotel.id', nullable=True)
    hotel: 'LotteryHotel' = Relationship(
        sa_relationship_kwargs={'foreign_keys': 'HotelRoomInventory.hotel_id', 'lazy': 'joined'})
    room_type_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='lottery_room_type.id', nullable=True)
    room_type: 'LotteryRoomType' = Relationship(
        sa_relationship_kwargs={'foreign_keys': 'HotelRoomInventory.room_type_id', 'lazy': 'joined'})
    suite_type_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='lottery_room_type.id', nullable=True)
    suite_type: 'LotteryRoomType' = Relationship(
        sa_relationship_kwargs={'foreign_keys': 'HotelRoomInventory.suite_type_id', 'lazy': 'joined'})
    quantity: int = 0  # Default quantity; per-night overrides in night_quantities
    capacity: int = 2
    min_capacity: int = 1
    name: str = ''
    is_suite: bool = False
    active: bool = True
    vault_reference: str | None = Field(nullable=True)
    info_url: str = ''
    price: str = ''
    staff_price: str = ''

    night_quantities: list['InventoryNightQuantity'] = Relationship(
        back_populates="inventory",
        sa_relationship_kwargs={'cascade': 'all,delete-orphan', 'passive_deletes': True})
    assigned_applications: list['LotteryApplication'] = Relationship(
        sa_relationship_kwargs={'foreign_keys': 'LotteryApplication.assigned_inventory_id',
                                'overlaps': 'assigned_inventory'})
    partition_blocks: list['InventoryPartitionBlock'] = Relationship(
        sa_relationship_kwargs={'foreign_keys': 'InventoryPartitionBlock.inventory_id',
                                'overlaps': 'inventory'})

    @property
    def room_or_suite_type(self):
        return self.suite_type if self.is_suite else self.room_type

    @property
    def room_or_suite_type_id(self):
        return self.suite_type_id if self.is_suite else self.room_type_id

    @property
    def night_quantity_map(self):
        """Return {date: quantity} dict from night_quantities."""
        return {nq.night_date: nq.quantity for nq in self.night_quantities}

    def quantity_for_night(self, night_date):
        """Return quantity for a specific night, falling back to default quantity."""
        nq_map = self.night_quantity_map
        if nq_map:
            return nq_map.get(night_date, 0)
        return self.quantity

    def to_inventory_dict(self):
        nq_map = self.night_quantity_map
        return {
            "id": str(self.id),
            "hotel_id": str(self.hotel_id),
            "capacity": self.capacity,
            "min_capacity": self.min_capacity,
            "room_type": str(self.room_or_suite_type_id),
            "quantity": self.quantity,
            "night_quantities": {d.isoformat(): q for d, q in nq_map.items()} if nq_map else {},
            "name": self.name,
        }

    @staticmethod
    def get_inventory(session, is_suite=False, active_only=True):
        query = session.query(HotelRoomInventory).filter_by(is_suite=is_suite)
        if active_only:
            query = query.filter_by(active=True)
        return [inv.to_inventory_dict() for inv in query.all()]

    @staticmethod
    def price_range_for_hotel(session, hotel_id, is_suite=False):
        """Return (price_range, staff_price_range) strings for all active inventory at a hotel."""
        items = session.query(HotelRoomInventory).filter_by(
            hotel_id=hotel_id, active=True, is_suite=is_suite
        ).all()
        return HotelRoomInventory._compute_price_range(items)

    @staticmethod
    def price_range_for_room_type(session, room_type_id, is_suite=False):
        """Return (price_range, staff_price_range) strings for all active inventory of a room type."""
        fk = HotelRoomInventory.suite_type_id if is_suite else HotelRoomInventory.room_type_id
        items = session.query(HotelRoomInventory).filter(
            fk == room_type_id, HotelRoomInventory.active == True
        ).all()
        return HotelRoomInventory._compute_price_range(items)

    @staticmethod
    def _compute_price_range(items):
        prices = [inv.price for inv in items if inv.price]
        staff_prices = [inv.staff_price for inv in items if inv.staff_price]
        return (
            HotelRoomInventory._format_range(prices),
            HotelRoomInventory._format_range(staff_prices),
        )

    @staticmethod
    def _format_range(values):
        if not values:
            return ''
        unique = sorted(set(values))
        if len(unique) == 1:
            return unique[0]
        return f"{unique[0]}\u2013{unique[-1]}"


class LotteryRun(MagModel, table=True):
    name: str = ''
    status: int = Field(sa_column=Column(Choice(c.LOTTERY_RUN_STATUS_OPTS), default=c.LOTTERY_PENDING))
    run_at: datetime | None = Field(sa_type=DateTime(timezone=True), default_factory=lambda: datetime.now(UTC))
    awarded_at: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True)
    reverted_at: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True)

    # Run parameters stored for audit
    lottery_group: str = 'attendee'
    lottery_type: str = 'room'
    cutoff: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True)
    hotel_filter: str | None = Field(nullable=True)
    room_type_filter: str | None = Field(nullable=True)
    inventory_filter: str | None = Field(nullable=True)
    partition_filter: str | None = Field(nullable=True)

    # Results summary
    entries_considered: int = 0
    rooms_assigned: int = 0
    rooms_available_before: int = 0

    applications: list['LotteryApplication'] = Relationship(
        sa_relationship_kwargs={'backref': 'lottery_run'})


class HotelExportLog(MagModel, table=True):
    hotel_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='lottery_hotel.id', nullable=True)
    hotel: 'LotteryHotel' = Relationship(
        sa_relationship_kwargs={'foreign_keys': 'HotelExportLog.hotel_id', 'lazy': 'joined'})
    export_type: str = ''
    exported_at: datetime | None = Field(sa_type=DateTime(timezone=True), default_factory=lambda: datetime.now(UTC))
    exported_by: str = ''
    record_count: int = 0
    notes: str = ''
