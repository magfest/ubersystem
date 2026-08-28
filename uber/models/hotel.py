import logging
import random

import checkdigit.verhoeff as verhoeff
from datetime import timedelta, datetime, date, time
from decimal import Decimal
from pytz import UTC
from markupsafe import Markup
import sqlalchemy as sa
from sqlalchemy import Sequence
from sqlalchemy.dialects.postgresql.json import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.types import Date, Integer, DateTime, Numeric, Uuid
from typing import Any, ClassVar

from uber.config import c
from uber.custom_tags import datetime_local_filter
from uber.decorators import presave_adjustment
from uber.models import MagModel
from uber.models.types import Choice, RankedList, UniqueList, DefaultColumn as Column, DefaultField as Field, DefaultRelationship as Relationship
from uber.utils import RegistrationCode

log = logging.getLogger(__name__)


__all__ = ['LotteryApplication',
           'HotelRoomInventory', 'InventoryNightQuantity', 'InventoryPartition', 'InventoryPartitionBlock',
           'InventoryPrice', 'ImportMappingTemplate',
           'LotteryRun', 'RoomAssignment', 'RoomAssignmentInvite',
           'PartitionOwner', 'PartitionAuditLog', 'NightShiftRequirement',
           'PhysicalRoom', 'PhysicalRoomConnection',
           'WaitlistReveal', 'WaitlistRevealLink', 'HotelExportLog', 'HotelImportFile',
           'HotelRoomIssueNote',
           'LotteryHotel', 'LotteryRoomType']


# RoomAssignment to Attendee many-to-many for occupants. RoomAssignment.attendee_id
# is the booker (legal name on the reservation); the M2M tracks *who's sleeping
# in the room*. The solver pre-populates this with the room group's members
# (leader + valid_group_members); the leader can edit per-room afterwards.
room_assignment_occupant = sa.Table(
    'room_assignment_occupant',
    MagModel.metadata,
    sa.Column('room_assignment_id', Uuid(as_uuid=False),
              sa.ForeignKey('room_assignment.id', ondelete='CASCADE'),
              primary_key=True),
    sa.Column('attendee_id', Uuid(as_uuid=False),
              sa.ForeignKey('attendee.id', ondelete='CASCADE'),
              primary_key=True),
    sa.Index('ix_room_assignment_occupant_attendee_id', 'attendee_id'),
)


class LotteryApplication(MagModel, table=True):
    attendee_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='attendee.id', nullable=True, unique=True)
    attendee: 'Attendee' = Relationship(back_populates="lottery_application", sa_relationship_kwargs={'lazy': 'joined', 'single_parent': True})

    invite_code: str = ''
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

    # Hotel legal names live on `Attendee` as `hotel_first_name` /
    # `hotel_last_name` (stored override), with
    # `effective_hotel_first_name` / `effective_hotel_last_name`
    # properties that fall back through `legal_first_name` to
    # `first_name`. One hotel-legal-name per attendee, not per app.
    cellphone: str = ''
    earliest_checkin_date: date | None = Field(sa_type=Date, nullable=True)
    latest_checkin_date: date | None = Field(sa_type=Date, nullable=True)
    earliest_checkout_date: date | None = Field(sa_type=Date, nullable=True)
    latest_checkout_date: date | None = Field(sa_type=Date, nullable=True)
    hotel_preference: str = Field(sa_type=RankedList, default='')  # LotteryHotel UUIDs, ranked
    room_type_preference: str = Field(sa_type=RankedList, default='')  # LotteryRoomType UUIDs, ranked
    wants_ada: bool = False
    ada_requests: str = ''

    room_opt_out: bool = False
    suite_type_preference: str = Field(sa_type=RankedList, default='')  # LotteryRoomType UUIDs (suites), ranked

    # Ranked priority keys (e.g. hotel/dates/room) when the optional
    # HOTEL_LOTTERY_PRIORITIES_ENABLED step is on. See HOTEL_LOTTERY_PRIORITIES_OPTS.
    selection_priorities: str = Field(sa_type=RankedList, default='')

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
    # `default` belongs on the Field, not inside Column: a Column default is
    # only applied by an INSERT, so an unflushed LotteryApplication() (and
    # therefore `to_dict()`, which _clear_application resets from) read back
    # None here and wrote NULL into this NOT NULL column.
    invite_status: int = Field(sa_column=Column(Choice(c.HOTEL_INVITE_STATUS_OPTS)), default=c.NO_INVITE)
    invite_expires_at: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True)

    # The application owns lottery preferences and lifecycle only. Per-room
    # booking data (CC vault, billing address, confirmation #, check-in/out
    # dates, deposit cutoff, booking URL) lives on each RoomAssignment row.
    special_requests: str = ''
    hotel_rewards_number: str = ''
    last_modified_at: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True)

    # Confirmation gate. When an admin sets confirmation_requested_at on an
    # application, the status page shows Confirm / Withdraw buttons and the
    # reconfirm email fires. Hitting Confirm sets last_confirmed_at;
    # LotteryRun.confirmation_window_start filters runs by this value.
    confirmation_requested_at: datetime | None = Field(
        sa_type=DateTime(timezone=True), nullable=True)
    last_confirmed_at: datetime | None = Field(
        sa_type=DateTime(timezone=True), nullable=True)

    # Link to the lottery run that assigned this room
    lottery_run_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='lottery_run.id', nullable=True)

    @presave_adjustment
    def update_last_modified(self):
        # Per-room state lives on RoomAssignment; this application only
        # tracks special_requests and the lifecycle fields here.
        dominated_fields = ['special_requests']
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


    def _preference_labels(self, model, csv_field):
        """Ranked display names for a CSV-of-UUIDs preference column:
        split the stored ids, look up their names in one query, and
        return the names in stored (ranked) order, dropping ids whose
        rows were deleted."""
        from sqlalchemy import inspect as sa_inspect
        session = sa_inspect(self).session
        value = getattr(self, csv_field)
        if not session or not value:
            return []
        ids = [x.strip() for x in value.split(',') if x.strip()]
        rows = session.query(model).filter(model.id.in_(ids)).all()
        names = {str(row.id): row.name for row in rows}
        return [names[i] for i in ids if i in names]

    @property
    def hotel_preference_labels(self):
        """Return list of hotel names from preference UUIDs."""
        return self._preference_labels(LotteryHotel, 'hotel_preference')

    @property
    def room_type_preference_labels(self):
        """Return list of room type names from preference UUIDs."""
        return self._preference_labels(LotteryRoomType, 'room_type_preference')

    @property
    def selection_priorities_labels(self):
        """Return ranked priority names from the stored priority keys."""
        if not self.selection_priorities:
            return []
        opts = dict(c.HOTEL_LOTTERY_PRIORITIES_OPTS)
        keys = [x.strip() for x in self.selection_priorities.split(',') if x.strip()]
        return [opts[k]['name'] for k in keys if k in opts]

    @property
    def suite_type_preference_labels(self):
        """Return list of suite type names from preference UUIDs."""
        return self._preference_labels(LotteryRoomType, 'suite_type_preference')

    @hybrid_property
    def normalized_code(self):
        return RegistrationCode.normalize_code(self.invite_code)

    @normalized_code.expression
    def normalized_code(cls):
        return RegistrationCode.sql_normalized_code(cls.invite_code)

    def generate_confirmation_num(self):
        """A collision-checked 10-digit confirmation number (9 random
        digits + a Verhoeff check digit), via the shared
        RegistrationCode collision helper."""
        def _generate_random_conf():
            base_num = ''.join(str(random.randint(0, 9)) for _ in range(9))
            checkdigit = verhoeff.calculate(base_num)
            return f"{base_num}{checkdigit}"

        return RegistrationCode._generate_code(
            _generate_random_conf, LotteryApplication.confirmation_num)

    @property
    def group_leader_name(self):
        return f"{self.attendee.first_name[:1]}. {self.attendee.last_name[:1]}."

    @property
    def email(self):
        return self.attendee.email if self.attendee else ''

    @property
    def gets_emails(self):
        return self.attendee and self.attendee.is_valid and self.status != c.DISQUALIFIED

    @property
    def birthdate(self):
        if self.attendee:
            return self.attendee.birthdate

    @property
    def attendee_name(self):
        return self.attendee.full_name if self.attendee else "[DISASSOCIATED]"

    @property
    def app_or_parent(self):
        # A group member (GROUP_ENTRY with a parent) defers to its leader for
        # award/room data; everyone else - including the group leader - is its
        # own application. Guarding on parent_application keeps a mislabeled or
        # orphaned GROUP_ENTRY (e.g. a leader whose entry_type is wrong, or a
        # member whose leader was deleted) from blowing up the attendee page.
        if self.entry_type == c.GROUP_ENTRY and self.parent_application:
            return self.parent_application
        return self

    @property
    def application_status_str(self):
        app_or_parent = self.app_or_parent
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
        app_or_parent = self.app_or_parent
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

        # Multi-room: derive room/suite phrasing and award presence from
        # the attendee's RoomAssignment rows. A "suite" wins if any
        # awarded room is a suite. "Chosen" = any non-cancelled awarded row.
        _attendee = app_or_parent.attendee
        _existing = [
            ra for ra in (_attendee.room_assignments if _attendee else [])
            if ra.status in (c.ASSIGNED, c.SECURED, c.CANCELLED, c.EXPIRED)
        ]
        _live = [ra for ra in _existing if ra.is_live]
        _has_suite = any(ra.inventory and ra.inventory.is_suite for ra in _existing)
        room_type = 'suite' if _has_suite else 'room'

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
        elif _live:
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

    def sync_award_status(self, session):
        """Recompute this application's COMPLETE <-> AWARDED state from its
        live room assignments: AWARDED requires at least one live room, and
        with none left an AWARDED/PROCESSED app returns to COMPLETE (and
        drops its lottery_run_id) so it re-enters future runs. Terminal app
        states (WITHDRAWN, DISQUALIFIED, ...) are never overridden.

        The RoomAssignment after_insert/after_delete listeners at the
        bottom of this module apply the same rule at the SQL layer during
        flush; call this from ORM code paths (the expiry cron, admin status
        changes) that flip assignment status without inserting or deleting
        rows."""
        live = session.query(RoomAssignment).filter(
            RoomAssignment.lottery_application_id == self.id,
            RoomAssignment.is_live).count()
        if live and self.status == c.COMPLETE:
            self.status = c.AWARDED
            session.add(self)
        elif not live and self.status in (c.AWARDED, c.PROCESSED):
            self.status = c.COMPLETE
            self.lottery_run_id = None
            session.add(self)

    @property
    def booking_url_ready(self):
        # Multi-room: "ready" = at least one of the attendee's RoomAssignment
        # rows has its booking URL populated. The URL is per-assignment:
        # each room has its own booking link from the hotel (LotteryHotel
        # deliberately has no hotel-wide booking link column).
        app_or_parent = self.app_or_parent
        attendee = app_or_parent.attendee
        if not attendee:
            return False
        return any(ra.booking_url for ra in attendee.active_room_assignments)

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
        # Reads the attendee's hotel name, with fallback to legal/first/last.
        return [f"{app.attendee.effective_hotel_first_name} {app.attendee.effective_hotel_last_name}"
                if app.attendee else ''
                for app in self.valid_group_members]
    
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
            return not c.STAFF_HOTEL_LOTTERY_OPEN \
                and not self._late_run_open('staff')
        elif self.qualifies_for_staff_lottery:
            return (not c.STAFF_HOTEL_LOTTERY_OPEN
                    and not c.HOTEL_LOTTERY_OPEN
                    and not self._late_run_open('staff')
                    and not self._late_run_open('attendee'))
        return not c.HOTEL_LOTTERY_OPEN \
            and not self._late_run_open('attendee')

    def _late_run_open(self, lottery_group):
        """True iff there's a pending LotteryRun for this group with
        apply_cutoff=False - i.e. the admin has explicitly opened a late
        round that accepts new entries past the global form deadline.
        Post-cutoff entries get the late-round confirmation email.

        Memoized per instance (effectively per request): templates
        evaluate current_lottery_closed several times per render, and
        each un-cached check costs a LotteryRun query."""
        cache = getattr(self, '_late_run_open_cache', None)
        if cache is None:
            cache = self._late_run_open_cache = {}
        if lottery_group not in cache:
            from sqlalchemy import inspect as sa_inspect
            session = sa_inspect(self).session
            if not session:
                return False
            cache[lottery_group] = session.query(LotteryRun).filter(
                LotteryRun.lottery_group == lottery_group,
                LotteryRun.apply_cutoff == False,  # noqa: E712
                LotteryRun.status == c.LOTTERY_PENDING,
            ).first() is not None
        return cache[lottery_group]

    @property
    def guarantee_deadline(self):
        # Multi-room: the earliest unsecured RoomAssignment.deposit_cutoff_date
        # across this application's attendee - that's the date the
        # reminder/award emails reference. Fall back to the global staff
        # / attendee guarantee deadline when nothing per-room is set yet
        # (e.g. pre-award, or master-bill rooms exempted from the cron).
        #
        # Always returns a tz-aware datetime: the per-room cutoff is a bare
        # date column, but consumers (`days_before` email filters,
        # `|datetime_local`) require a datetime, so a date-based deadline
        # means end of that day, event-local.
        if self.attendee:
            unsecured_cutoffs = [
                ra.deposit_cutoff_date for ra in (self.attendee.room_assignments or [])
                if ra.status == c.ASSIGNED and ra.require_cc and ra.deposit_cutoff_date
            ]
            if unsecured_cutoffs:
                cutoff = min(unsecured_cutoffs)
                return c.EVENT_TIMEZONE.localize(
                    datetime.combine(cutoff, time(23, 59)))

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
            return f'room_lottery?id={self.id}', f"Finish {entry_text}"
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

    # Waitlist state is per-RoomAssignment (waitlisted_check_in_date /
    # waitlisted_check_out_date / is_waitlisted); the application only
    # records the originally-requested date range.

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

    # Floor map for the room picker: map_yaml is the uploaded source
    # (schema in uber.hotel.floormap), map_svg the SVG rendered from it
    # at upload time. Empty = no map.
    map_yaml: str = ''
    map_svg: str = ''

    # Preselected when parsing this hotel's room-list uploads.
    default_import_template_id: str | None = Field(
        sa_type=Uuid(as_uuid=False), foreign_key='import_mapping_template.id',
        ondelete='SET NULL', nullable=True)
    default_import_template: 'ImportMappingTemplate' = Relationship(
        sa_relationship_kwargs={'foreign_keys': 'LotteryHotel.default_import_template_id'})


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

    # Type-level mandatory connector model: a *child* type points at its
    # parent and declares how many of itself must be awarded with each
    # instance of the parent. One parent can have multiple child types
    # (e.g. Executive Suite has 2 Standard Kings AND 1 Standard Double).
    # Chaining is disallowed: a type that is itself pointed at (i.e. has
    # children) can't also have a non-null connects_to_type_id.
    connects_to_type_id: str | None = Field(
        sa_type=Uuid(as_uuid=False), foreign_key='lottery_room_type.id', nullable=True)
    parent_type: 'LotteryRoomType' = Relationship(
        sa_relationship_kwargs={'foreign_keys': 'LotteryRoomType.connects_to_type_id',
                                'remote_side': 'LotteryRoomType.id'})
    connector_quantity: int = 0

    @property
    def children(self):
        """Return the LotteryRoomType rows whose connects_to_type_id == self.id."""
        from sqlalchemy import inspect as sa_inspect
        session = sa_inspect(self).session
        if not session or not self.id:
            return []
        return session.query(LotteryRoomType).filter_by(
            connects_to_type_id=self.id).order_by(LotteryRoomType.name).all()

    @property
    def is_parent(self):
        """True if at least one other type follows this type."""
        return bool(self.children)

    @property
    def is_connector(self):
        """True if this type follows another (has a non-null parent)."""
        return bool(self.connects_to_type_id)


class InventoryPartition(MagModel, table=True):
    name: str = ''
    description: str = ''
    active: bool = True

    # The hotel's billing account reference for this partition. Lottery admins
    # only; partition owners see it read-only. Included in the booking export.
    bill_reference: str = ''

    blocks: list['InventoryPartitionBlock'] = Relationship(
        back_populates="partition",
        sa_relationship_kwargs={'cascade': 'all,delete-orphan', 'passive_deletes': True})
    owners: list['PartitionOwner'] = Relationship(
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


class InventoryPrice(MagModel, table=True):
    """One nightly rate for a block, optionally scoped to a night and/or an
    occupancy. NULL means "applies to all", so a block with neither
    price_per_night nor price_per_occupancy set needs no rows here at all and
    falls back to the block's base price. See uber.hotel.pricing."""

    __table_args__ = (
        sa.UniqueConstraint('inventory_id', 'is_staff', 'night_date', 'occupancy',
                            name='uq_inventory_price_scope',
                            postgresql_nulls_not_distinct=True),
    )

    inventory_id: str = Field(sa_type=Uuid(as_uuid=False), foreign_key='hotel_room_inventory.id',
                              ondelete='CASCADE', index=True)
    inventory: 'HotelRoomInventory' = Relationship(
        back_populates="prices",
        sa_relationship_kwargs={'foreign_keys': 'InventoryPrice.inventory_id'})
    night_date: date | None = Field(sa_type=Date, nullable=True)
    occupancy: int | None = Field(default=None, nullable=True)
    is_staff: bool = False
    price: Decimal = Field(sa_type=Numeric(10, 2))


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

    # Nightly rate when neither dimension varies, and the fallback for any
    # scope the InventoryPrice rows do not cover. The two flags decide which
    # dimensions the admin grid collects and which scopes are consulted.
    base_price: Decimal | None = Field(default=None, sa_type=Numeric(10, 2), nullable=True)
    base_staff_price: Decimal | None = Field(default=None, sa_type=Numeric(10, 2), nullable=True)
    price_per_night: bool = False
    price_per_occupancy: bool = False
    pricing_notes: str = ''

    # Physical-room type codes this block sells (comma-separated, e.g.
    # "T2, T2A, T2H"). Used to resolve catalog imports to a block and to
    # filter the floor-map picker; empty = no type-based filtering.
    physical_room_types: str = ''

    # Per-type connector pairing lives on LotteryRoomType
    # (connects_to_type_id + connector_quantity).

    night_quantities: list['InventoryNightQuantity'] = Relationship(
        back_populates="inventory",
        sa_relationship_kwargs={'cascade': 'all,delete-orphan', 'passive_deletes': True})
    # selectin because the price-range helpers walk every block of a hotel.
    prices: list['InventoryPrice'] = Relationship(
        back_populates="inventory",
        sa_relationship_kwargs={'cascade': 'all,delete-orphan', 'passive_deletes': True,
                                'lazy': 'selectin'})
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
    def physical_type_codes(self):
        """The declared physical-room type codes as an uppercase list."""
        return [code.strip().upper()
                for code in self.physical_room_types.split(',')
                if code.strip()]

    @property
    def display_name(self):
        """Human-facing type name: the suite/room type's name, falling
        back to this inventory row's own name when no type is linked."""
        room_or_suite_type = self.room_or_suite_type
        return room_or_suite_type.name if room_or_suite_type else self.name

    @property
    def night_quantity_map(self):
        """Return {date: quantity} dict from night_quantities."""
        return {nq.night_date: nq.quantity for nq in self.night_quantities}

    def quantity_for_night(self, night_date):
        """Per-night sellable quantity - the single source of truth for
        "how many rooms of this block exist on night N".

        A night missing from night_quantities falls back to the block's
        flat quantity (the admin form's "leave blank to use the default
        quantity above"); an explicit 0 row means the night is closed."""
        return self.night_quantity_map.get(night_date, self.quantity)

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

    def all_prices(self, is_staff=False):
        """Every rate this block can charge for the given scope: the base plus
        any per-night or per-occupancy overrides."""
        amounts = [p.price for p in self.prices if p.is_staff == is_staff and p.price is not None]
        base = self.base_staff_price if is_staff else self.base_price
        if base is not None:
            amounts.append(base)
        return amounts

    @staticmethod
    def _compute_price_range(items):
        from uber.hotel.pricing import format_price_range

        prices = [amount for inv in items for amount in inv.all_prices()]
        staff_prices = [amount for inv in items for amount in inv.all_prices(is_staff=True)]
        return (format_price_range(prices), format_price_range(staff_prices))


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
    hotel_filter: str | None = Field(sa_type=UniqueList, nullable=True)  # LotteryHotel UUIDs
    room_type_filter: str | None = Field(sa_type=UniqueList, nullable=True)  # LotteryRoomType UUIDs
    inventory_filter: str | None = Field(sa_type=UniqueList, nullable=True)  # HotelRoomInventory UUIDs
    partition_filter: str | None = Field(nullable=True)  # single InventoryPartition UUID

    # Default secure-card deadline stamped on every RoomAssignment produced
    # by this run. Per-assignment overrides live on RoomAssignment.
    card_deadline: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True)
    # When False, the global application cutoff is ignored for this run -
    # post-cutoff entries are still considered and get a different
    # confirmation email.
    apply_cutoff: bool = True
    # When set, only applications whose last_confirmed_at >= this datetime
    # are eligible to be awarded by this run.
    confirmation_window_start: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True)

    # Results summary
    entries_considered: int = 0
    rooms_assigned: int = 0
    rooms_available_before: int = 0

    applications: list['LotteryApplication'] = Relationship(
        sa_relationship_kwargs={'backref': 'lottery_run'})


class RoomAssignment(MagModel, table=True):
    attendee_id: str = Field(
        sa_type=Uuid(as_uuid=False), foreign_key='attendee.id', ondelete='CASCADE',
        nullable=False)
    attendee: 'Attendee' = Relationship(
        back_populates="room_assignments",
        sa_relationship_kwargs={'lazy': 'joined',
                                'foreign_keys': 'RoomAssignment.attendee_id'})

    inventory_id: str | None = Field(
        sa_type=Uuid(as_uuid=False), foreign_key='hotel_room_inventory.id', nullable=True)
    inventory: 'HotelRoomInventory' = Relationship(
        sa_relationship_kwargs={'lazy': 'joined',
                                'foreign_keys': 'RoomAssignment.inventory_id'})

    lottery_application_id: str | None = Field(
        sa_type=Uuid(as_uuid=False), foreign_key='lottery_application.id', nullable=True)
    lottery_application: 'LotteryApplication' = Relationship(
        sa_relationship_kwargs={'foreign_keys': 'RoomAssignment.lottery_application_id'})

    lottery_run_id: str | None = Field(
        sa_type=Uuid(as_uuid=False), foreign_key='lottery_run.id', nullable=True)
    lottery_run: 'LotteryRun' = Relationship(
        sa_relationship_kwargs={'foreign_keys': 'RoomAssignment.lottery_run_id'})

    # Connector rooms point at their parent suite assignment. When the suite is
    # awarded, the solver creates child RoomAssignment rows for each connector
    # (assignment_reason=SUITE_CONNECTOR). Attendee-facing UI groups these under
    # the parent; the hotel export lists them as separate line items.
    parent_assignment_id: str | None = Field(
        sa_type=Uuid(as_uuid=False), foreign_key='room_assignment.id', nullable=True)
    parent_assignment: 'RoomAssignment' = Relationship(
        back_populates="child_assignments",
        sa_relationship_kwargs={'foreign_keys': 'RoomAssignment.parent_assignment_id',
                                'remote_side': 'RoomAssignment.id'})
    child_assignments: list['RoomAssignment'] = Relationship(
        back_populates="parent_assignment",
        sa_relationship_kwargs={'foreign_keys': 'RoomAssignment.parent_assignment_id'})

    partition_id: str | None = Field(
        sa_type=Uuid(as_uuid=False), foreign_key='inventory_partition.id', nullable=True)
    partition: 'InventoryPartition' = Relationship(
        sa_relationship_kwargs={'foreign_keys': 'RoomAssignment.partition_id'})

    assignment_reason: int = Field(
        sa_column=Column(Choice(c.HOTEL_ASSIGNMENT_REASON_OPTS), default=c.MANUAL))
    status: int = Field(
        sa_column=Column(Choice(c.HOTEL_ASSIGNMENT_STATUS_OPTS), default=c.ASSIGNED))

    # A [hotel_lottery] [[payment_types]] section name, not an export_name, so
    # export codes stay editable. Master bill types need no CC and the deadline
    # cron does not expire them; see the require_cc hybrid below.
    payment_type: str = Field(default=c.DEFAULT_HOTEL_PAYMENT_TYPE)

    assigned_check_in_date: date | None = Field(sa_type=Date, nullable=True)
    assigned_check_out_date: date | None = Field(sa_type=Date, nullable=True)

    # Per-room waitlist: the broader range the attendee asked for when
    # they edited their dates. If today the room only has availability
    # for nights N..M but the attendee wants N-2..M+1, we keep the
    # confirmed nights on `assigned_check_in_date` / `assigned_check_out_date`
    # and stash the requested range here. The waitlist cron compares
    # waitlisted_* to assigned_* per RoomAssignment to figure out which
    # rooms are waiting on which nights.
    #
    # Both NULL = no waitlist (the attendee got exactly what they asked
    # for, or never requested a wider window). When the cron narrows the
    # gap to zero (assigned_* fully covers waitlisted_*) it clears these
    # back to NULL so the row drops out of future waitlist scans.
    waitlisted_check_in_date: date | None = Field(sa_type=Date, nullable=True)
    waitlisted_check_out_date: date | None = Field(sa_type=Date, nullable=True)

    # When this assignment first entered the waitlist queue. Stamped
    # the moment `waitlisted_*` transitions from both-NULL to either
    # non-NULL; cleared back to NULL when the queue exits (the model
    # presave below keeps these three columns in sync). The waitlist
    # cron sorts FIFO on this field so earlier entrants get first crack
    # at newly-freed nights, and the attendee-side editor uses it to
    # tell whether a given block already has *someone else* queued
    # ahead (in which case any extension nights the attendee adds also
    # get waitlisted rather than confirmed).
    waitlist_started_at: datetime | None = Field(
        sa_type=DateTime(timezone=True), nullable=True)

    # Per-assignment override of LotteryRun.card_deadline.
    deposit_cutoff_date: date | None = Field(sa_type=Date, nullable=True)

    booking_url: str = ''
    hotel_confirmation_number: str | None = Field(nullable=True)
    cancellation_confirmation_number: str | None = Field(nullable=True)
    # Physical room number at the hotel. Free text when no catalog exists;
    # stamped from the linked PhysicalRoom when one is assigned (see the
    # sync_room_number_from_physical presave).
    room_number: str | None = Field(nullable=True)

    # Optional link into the per-hotel physical-room catalog. Exported to
    # the hotel with the booking; they may reassign at check-in and we
    # don't receive that back.
    physical_room_id: str | None = Field(
        sa_type=Uuid(as_uuid=False), foreign_key='physical_room.id',
        nullable=True)
    physical_room: 'PhysicalRoom' = Relationship(
        sa_relationship_kwargs={'foreign_keys': 'RoomAssignment.physical_room_id'})
    # True while physical_room_id was set by the auto-assign pass (and
    # not touched by hand since), so "clear auto placements" can leave
    # manual placements alone.
    physical_room_auto: bool = False
    special_requests: str = ''
    hotel_rewards_number: str = ''

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

    # Billing address for the hotel booking
    address1: str = ''
    address2: str = ''
    city: str = ''
    region: str = ''
    zip_code: str = ''
    country: str = ''

    last_modified_at: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True)
    last_confirmed_at: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True)
    admin_notes: str = ''

    # Occupants (who's sleeping in the room). Distinct from `attendee` which
    # is the booker / name on the reservation. Group leaders edit this per
    # room from the rooms UI; the solver pre-populates with all valid
    # group members on every awarded room.
    occupants: list['Attendee'] = Relationship(
        back_populates="occupied_rooms",
        sa_relationship_kwargs={'secondary': 'room_assignment_occupant',
                                'lazy': 'selectin'})

    @hybrid_property
    def is_live(self):
        """True while this assignment still holds inventory - i.e. it has
        not been cancelled, expired, or removed. The canonical "counts as
        a room" predicate for capacity math, exports, and attendee-facing
        views; usable in queries via RoomAssignment.is_live."""
        return self.status in c.HOTEL_LIVE_ASSIGNMENT_STATUSES

    @is_live.expression
    def is_live(cls):
        return cls.status.in_(c.HOTEL_LIVE_ASSIGNMENT_STATUSES)

    @property
    def export_locked(self):
        # Locking is currently per-application - once any of an app's rooms
        # are exported the whole app gets the flag, so all of its
        # RoomAssignments inherit it. If we ever need per-row locking we
        # can promote this to a real column without breaking the
        # template/API contract (everything reads through this property).
        return bool(self.lottery_application and self.lottery_application.export_locked)

    @property
    def effective_occupants(self):
        """Attendees sleeping in this room: the managed occupants list when
        set, else the booker plus their group members (the solver's default
        before anyone edits the list). Always a list of Attendee records."""
        if self.occupants:
            return list(self.occupants)
        occupants = [self.attendee] if self.attendee else []
        app = self.lottery_application
        if app:
            occupants.extend(m.attendee for m in (app.valid_group_members or [])
                             if m.attendee)
        return occupants

    @property
    def payment_type_config(self):
        """This room's [[payment_types]] entry. Falls back to a stub naming the
        raw stored key so a renamed config section shows up as an orphaned row
        rather than blanking out."""
        return c.HOTEL_PAYMENT_TYPES.get(
            self.payment_type,
            {'name': self.payment_type or '', 'export_name': '',
             'require_cc': True, 'event_pays_parking': False})

    @property
    def payment_type_label(self):
        return self.payment_type_config['name']

    @property
    def payment_code(self):
        """The code the hotel expects on the rooming list, e.g. RT or IPOP."""
        return self.payment_type_config['export_name']

    @property
    def event_pays_parking(self):
        return self.payment_type_config['event_pays_parking']

    @hybrid_property
    def require_cc(self):
        """True when the guest guarantees the room with their own card, False
        when it is on the master bill. Derived from payment_type so there is one
        source of truth; both sides read HOTEL_PAYMENT_TYPES_REQUIRING_CC.

        Read-only on purpose: MagModel allows extra attributes, so a writable
        alias would let RoomAssignment(require_cc=True) silently do nothing.
        Set payment_type instead."""
        return self.payment_type in c.HOTEL_PAYMENT_TYPES_REQUIRING_CC

    @require_cc.expression
    def require_cc(cls):
        return cls.payment_type.in_(c.HOTEL_PAYMENT_TYPES_REQUIRING_CC)

    @hybrid_property
    def needs_card(self):
        """True iff this room still requires a credit-card guarantee
        and none has been captured yet - i.e. a self-pay room that's
        ASSIGNED (awaiting a card) with no token on file. Once secured
        (cc_token set, status SECURED) or on master bill, this is False.

        The single definition of "unsecured" - templates use it to flag
        rooms and surface the card deadline, and the expiry cron filters
        on the SQL expression, so the room the cron would expire is
        always the room the UI shows as needing a card."""
        return bool(self.require_cc
                    and self.status == c.ASSIGNED
                    and not self.cc_token)

    @needs_card.expression
    def needs_card(cls):
        return sa.and_(cls.require_cc,
                       cls.status == c.ASSIGNED,
                       sa.or_(cls.cc_token.is_(None), cls.cc_token == ''))

    # The vaulted-card columns (nullable) and the billing-address columns
    # (NOT NULL strings) that travel together whenever a card is copied
    # between rooms or stripped from one. Single source for the field
    # lists so adding a column can't miss a copy/strip site.
    CC_FIELDS: ClassVar[tuple] = (
        'cc_token', 'cc_last_four', 'cc_card_type', 'cc_card_holder',
        'cc_card_expiry', 'cc_issuer_brand', 'cc_issuer_bank',
        'cc_issuer_country', 'cc_issuer_card_type', 'cc_issuer_card_level',
        'cc_captured_at')
    ADDRESS_FIELDS: ClassVar[tuple] = (
        'address1', 'address2', 'city', 'region', 'zip_code', 'country')

    def clear_card(self):
        """Remove the vaulted card and billing address; a SECURED room
        drops back to ASSIGNED (awaiting a new card). Returns True if a
        token was on file."""
        had_card = bool(self.cc_token)
        for field in self.CC_FIELDS:
            setattr(self, field, None)
        for field in self.ADDRESS_FIELDS:
            setattr(self, field, '')
        if self.status == c.SECURED:
            self.status = c.ASSIGNED
        return had_card

    def copy_card_from(self, source):
        """Copy the vaulted card, billing address, and rewards number
        from another assignment, then flip to SECURED if this room was
        awaiting exactly that. Callers are responsible for checking the
        two rooms share a vault scope - a token is only valid within its
        own vault reference."""
        for field in self.CC_FIELDS + self.ADDRESS_FIELDS + ('hotel_rewards_number',):
            setattr(self, field, getattr(source, field))
        self.secure_if_carded()

    def secure_if_carded(self):
        """The ASSIGNED -> SECURED flip: a room that requires a card and
        now has a token on file counts as secured. Master-bill rooms
        (require_cc False) are never flipped here."""
        if self.status == c.ASSIGNED and self.cc_token and self.require_cc:
            self.status = c.SECURED

    @property
    def is_connector(self):
        """True for a connector room - one awarded as part of a suite
        block, whose dates and lifecycle follow its parent. The single
        definition of "is this a connector?" so surfaces don't each
        re-derive it from the raw FK (and disagree on how to treat an
        empty string)."""
        return bool(self.parent_assignment_id)

    @property
    def room_summary(self):
        """"Hotel - Room Type, check-in to check-out" for log lines and
        audit descriptions, so every surface words a room the same way.
        """
        inv = self.inventory
        parts = []
        if inv:
            hotel = inv.hotel
            parts.append(' - '.join(
                filter(None, [hotel.name if hotel else '',
                              inv.display_name])))
        if self.assigned_check_in_date and self.assigned_check_out_date:
            parts.append(f'{self.assigned_check_in_date} to '
                         f'{self.assigned_check_out_date}')
        return ', '.join(parts) or 'room'

    @property
    def is_orphan_connector(self):
        """True for a connector room whose parent suite is no longer held
        live by the same attendee (deleted, cancelled, or transferred) -
        the suite-plus-connector pairing this room was awarded with has
        broken, and the attendee-facing pages flag it."""
        if not self.parent_assignment_id:
            return False
        parent = self.parent_assignment
        return not (parent and parent.is_live
                    and parent.attendee_id == self.attendee_id)

    @property
    def card_deadline(self):
        """The date by which a card must be put down before the expiry
        cron cancels this room (`deposit_cutoff_date`). None when no
        deadline is set (e.g. master-bill rooms, or manual grants that
        never got a run deadline)."""
        return self.deposit_cutoff_date

    @property
    def is_waitlisted(self):
        """True iff the attendee asked for a wider window than they
        currently hold confirmed - i.e. the waitlisted_* range strictly
        extends the assigned_* range on at least one end. The cron uses
        this to scope its work; templates use it to surface a
        "waitlisted for N more night(s)" chip."""
        return bool(self.waitlisted_gap_nights)

    @property
    def effective_waitlist_window(self):
        """(wl_ci, wl_co): the requested window, with each end coalesced
        to the assigned date when only the other end is waitlisted.
        (None, None) when neither waitlist column is set."""
        if not (self.waitlisted_check_in_date or self.waitlisted_check_out_date):
            return None, None
        return (self.waitlisted_check_in_date or self.assigned_check_in_date,
                self.waitlisted_check_out_date or self.assigned_check_out_date)

    @property
    def waitlisted_gap_nights(self):
        """Sorted list of the nights this assignment is waiting on: the
        front gap [wl_ci, assigned_check_in) plus the back gap
        [assigned_check_out, wl_co). Empty when not waitlisted or when
        the assigned range is incomplete. The single definition of
        "which nights does this row want" - the waitlist engine, demand
        reports, and exports all iterate this."""
        wl_ci, wl_co = self.effective_waitlist_window
        ci, co = self.assigned_check_in_date, self.assigned_check_out_date
        if not (wl_ci and wl_co and ci and co):
            return []
        nights = []
        d = wl_ci
        while d < ci:
            nights.append(d)
            d += timedelta(days=1)
        d = co
        while d < wl_co:
            nights.append(d)
            d += timedelta(days=1)
        return nights

    @presave_adjustment
    def sync_room_number_from_physical(self):
        """A linked PhysicalRoom is the source of truth for room_number,
        so exports and reports keep working off the plain text column
        whether or not a hotel has a catalog."""
        if self.physical_room_id and self.physical_room:
            self.room_number = self.physical_room.room_number

    @presave_adjustment
    def clear_waitlist_when_satisfied(self):
        """When the cron extends assigned_* to fully cover waitlisted_*,
        zero the waitlist columns AND `waitlist_started_at` so the row
        drops out of future scans and a later re-entry starts a fresh
        FIFO position. Doing this at the model layer means every code
        path that updates assigned_* (waitlist cron, manual admin
        accept, attendee edit, solver re-runs) gets the cleanup for
        free."""
        if not (self.waitlisted_check_in_date or self.waitlisted_check_out_date):
            # Belt-and-braces: if waitlist dates are gone but the start
            # timestamp lingers (e.g. an admin manually cleared one
            # column), clear the timestamp too so the model stays
            # consistent.
            if self.waitlist_started_at:
                self.waitlist_started_at = None
            return
        if not (self.assigned_check_in_date and self.assigned_check_out_date):
            return
        wl_ci, wl_co = self.effective_waitlist_window
        if (self.assigned_check_in_date <= wl_ci
                and self.assigned_check_out_date >= wl_co):
            self.waitlisted_check_in_date = None
            self.waitlisted_check_out_date = None
            self.waitlist_started_at = None

    @presave_adjustment
    def stamp_waitlist_start(self):
        """Stamp `waitlist_started_at` the first time this row gets a
        non-NULL waitlisted_* range. Idempotent - if the timestamp is
        already set we leave it alone (the cron uses it as the FIFO
        sort key, and we don't want a same-row edit to bump someone
        back to the front of the queue).

        Note this runs *after* `clear_waitlist_when_satisfied` (alphabetical
        method-name order isn't guaranteed by SQLAlchemy, but the two are
        independent: clear runs when waitlist is satisfied -> start
        timestamp also clears; stamp runs when waitlist becomes non-NULL
        -> timestamp populates). They never race on the same edit."""
        if (self.waitlisted_check_in_date or self.waitlisted_check_out_date) \
                and not self.waitlist_started_at:
            from datetime import datetime as _dt, timezone as _tz
            self.waitlist_started_at = _dt.now(_tz.utc)

    @presave_adjustment
    def cancellation_flips_status(self):
        if self.cancellation_confirmation_number and self.status != c.CANCELLED:
            self.status = c.CANCELLED

    @presave_adjustment
    def ensure_booker_is_occupant(self):
        """The booker (the attendee on `attendee_id`, i.e. the name on the
        reservation) is always one of the room's occupants. We enforce
        the invariant at the model layer so it holds across every entry
        point - solver, manual admin add, partition grant, seed data,
        import - without each call site having to remember.

        The group leader can still swap occupants per-room in the UI, but
        the booker themselves always counts; removing them would mean
        the hotel's record of who's checking in doesn't match anyone in
        the room.
        """
        if not self.attendee_id or not self.attendee:
            return
        if self.attendee not in self.occupants:
            self.occupants.append(self.attendee)

    @presave_adjustment
    def update_last_modified(self):
        tracked = ['attendee_id', 'inventory_id', 'partition_id', 'assignment_reason',
                   'status', 'payment_type', 'assigned_check_in_date', 'assigned_check_out_date',
                   'deposit_cutoff_date', 'booking_url', 'hotel_confirmation_number',
                   'cancellation_confirmation_number', 'special_requests', 'hotel_rewards_number',
                   'cc_token', 'cc_captured_at',
                   'address1', 'address2', 'city', 'region', 'zip_code', 'country']
        if any(getattr(self, f) != self.orig_value_of(f) for f in tracked):
            self.last_modified_at = datetime.now(UTC)


class RoomAssignmentInvite(MagModel, table=True):
    """A pending invitation to join a specific RoomAssignment as an occupant.

    Intentionally minimal: the *existence* of a row means the invite is
    valid. Accept = delete this row and insert into
    `room_assignment_occupant` in the same transaction. Cancel = delete
    this row. Any lookup miss (cancelled, redeemed, never-existed,
    wrong token) renders the same "Invite has expired or been
    cancelled" page on the attendee side, which is intentional - we
    don't leak distinguishing information about whether a given token
    was ever real.

    `invite_token` is the short URL-safe code that doubles as the
    out-of-band redeem code shown to the room leader (so they can text
    it to a friend) and the URL token embedded in the email magic link.
    `email` is optional and only set for the email-invite flow; it's
    used to pre-fill the recipient on the email and shows up in the
    leader's pending-invite list.

    `created` comes from MagModel.
    """
    __table_args__ = (
        sa.UniqueConstraint('invite_token', name='uq_room_assignment_invite_token'),
    )

    room_assignment_id: str = Field(
        sa_type=Uuid(as_uuid=False),
        foreign_key='room_assignment.id', nullable=False)
    room_assignment: 'RoomAssignment' = Relationship(
        sa_relationship_kwargs={'foreign_keys': 'RoomAssignmentInvite.room_assignment_id'})
    invite_token: str = ''
    email: str = ''


class PhysicalRoom(MagModel, table=True):
    """One real room in a hotel building - the physical counterpart to a
    HotelRoomInventory *block* (which is just a sellable quantity).

    The catalog is optional per hotel: hotels we never fully catalog keep
    working off free-text RoomAssignment.room_number. Inventory quantities
    are deliberately NOT derived from the physical count - an audit check
    flags mismatches instead, since hotels often sell us a block without
    handing over a complete room list.
    """
    __table_args__ = (
        sa.UniqueConstraint('hotel_id', 'room_number',
                            name='uq_physical_room_number'),
    )

    hotel_id: str = Field(
        sa_type=Uuid(as_uuid=False), foreign_key='lottery_hotel.id',
        ondelete='CASCADE', nullable=False)
    hotel: 'LotteryHotel' = Relationship(
        sa_relationship_kwargs={'foreign_keys': 'PhysicalRoom.hotel_id'})

    # Which sellable block this room belongs to (gives type/price/vault
    # scope). Nullable = catalogued but not yet categorized.
    inventory_id: str | None = Field(
        sa_type=Uuid(as_uuid=False), foreign_key='hotel_room_inventory.id',
        nullable=True)
    inventory: 'HotelRoomInventory' = Relationship(
        sa_relationship_kwargs={'foreign_keys': 'PhysicalRoom.inventory_id'})

    room_number: str = ''
    floor: str = ''  # free text: hotels have floors like "M" and "PH"
    # Hotel's own type code for the room (T1, T2A, ...); matched against
    # HotelRoomInventory.physical_room_types by imports and the picker.
    type_code: str = ''
    ada: bool = False
    # Comma-separated accessibility feature tags ("roll-in shower,
    # visual alarm"); free-form, shown in the picker tooltip.
    accessibility: str = ''
    out_of_service: bool = False
    notes: str = ''

    # Floor-map shapes are matched to rooms by name (LotteryHotel.map_svg),
    # so a room needs no placement columns here.

    # Connected-room lookups are bulk-only: controllers build the
    # {room_id: [room_number, ...]} map via uber.hotel.physical
    # .connection_map and pass it to templates, so there is no per-row
    # accessor here (a per-room property cost two queries per room).

    @property
    def accessibility_list(self):
        return [tag.strip() for tag in self.accessibility.split(',')
                if tag.strip()]

    @property
    def sort_key(self):
        """Natural-ish ordering: numeric floors and room numbers sort
        numerically, text ones alphabetically after."""
        from uber.hotel.physical import floor_sort_key
        num = ''.join(ch for ch in self.room_number if ch.isdigit())
        return (floor_sort_key(self.floor), 0 if num else 1,
                int(num) if num else 0, self.room_number)


class PhysicalRoomConnection(MagModel, table=True):
    """An undirected connecting-door edge between two physical rooms.

    Room ids are normalized so room_a_id < room_b_id, making the pair
    unique regardless of insertion order.
    """
    __table_args__ = (
        sa.UniqueConstraint('room_a_id', 'room_b_id',
                            name='uq_physical_room_connection'),
    )

    room_a_id: str = Field(
        sa_type=Uuid(as_uuid=False), foreign_key='physical_room.id',
        ondelete='CASCADE', nullable=False)
    room_b_id: str = Field(
        sa_type=Uuid(as_uuid=False), foreign_key='physical_room.id',
        ondelete='CASCADE', nullable=False)

    @presave_adjustment
    def normalize_pair(self):
        if self.room_a_id and self.room_b_id \
                and str(self.room_a_id) > str(self.room_b_id):
            self.room_a_id, self.room_b_id = self.room_b_id, self.room_a_id


class PartitionOwner(MagModel, table=True):
    """Per-partition admin permissions for the lottery system.

    Granted by hotel-lottery admins (anyone with HAS_HOTEL_LOTTERY_ADMIN_ACCESS)
    to admin accounts that need scoped access to manage one partition's rooms
    and assignments. Each row is one (admin, partition) grant with a set of
    independently-toggleable capabilities. See uber.hotel.perms for
    resolution logic: HAS_HOTEL_LOTTERY_ADMIN_ACCESS short-circuits to True,
    otherwise the relevant PartitionOwner row gates the action.
    """
    __table_args__ = (
        sa.UniqueConstraint('admin_account_id', 'partition_id',
                            name='uq_partition_owner_admin_partition'),
    )

    admin_account_id: str = Field(
        sa_type=Uuid(as_uuid=False), foreign_key='admin_account.id',
        ondelete='CASCADE', nullable=False)
    admin_account: 'AdminAccount' = Relationship(
        back_populates="partition_grants",
        sa_relationship_kwargs={'foreign_keys': 'PartitionOwner.admin_account_id'})

    partition_id: str = Field(
        sa_type=Uuid(as_uuid=False), foreign_key='inventory_partition.id',
        ondelete='CASCADE', nullable=False)
    partition: 'InventoryPartition' = Relationship(
        back_populates="owners",
        sa_relationship_kwargs={'foreign_keys': 'PartitionOwner.partition_id'})

    # Inventory: counts and metadata for blocks in this partition.
    can_view_inventory: bool = True
    can_edit_inventory: bool = False

    # Assignments: roster of RoomAssignment rows in this partition, payment
    # type changes, and the assign/unassign UI.
    can_view_assignments: bool = True
    can_edit_assignments: bool = False

    # Room numbers: the physical room number on this partition's assignments,
    # and the physical room link that stamps it.
    can_view_room_numbers: bool = False
    can_edit_room_numbers: bool = False

    # Display (preferred) names of attendees holding rooms in this partition.
    # Legal-name visibility is gated separately by
    # AdminAccount.view_guest_legal_names.
    can_view_guest_names: bool = False

    # RESERVED, not enforced anywhere and not exposed in the UI: kept as
    # columns so already-migrated databases stay in sync with the model.
    # Wire real checks before granting either of these any meaning.
    can_edit_guest_names: bool = False
    can_send_emails: bool = False


class NightShiftRequirement(MagModel, table=True):
    """One row per convention date that has a shift-compliance requirement.

    Staff with a RoomAssignment covering this night must meet the requirement
    or they show up as non-compliant on reports / nag emails / status pages.
    The admin "Staff Rooming" page populates this table with sensible
    defaults on first load.

    - kind=NONE: this date imposes no requirement (skipped during compliance).
    - kind=SETUP/TEARDOWN: staffer must have at least one shift that overlaps
      [shift_window_start, shift_window_end]; any overlap satisfies.
    - kind=CORE: staffer's total weighted hours across the whole con must be
      >= required_weighted_hours; all assigned hours count.
    """
    __table_args__ = (
        sa.UniqueConstraint('night_date', name='uq_night_shift_requirement_date'),
    )

    night_date: date = Field(sa_type=Date, nullable=False)
    kind: int = Field(sa_column=Column(Choice(c.NIGHT_KIND_OPTS), default=c.NONE))
    shift_window_start: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True)
    shift_window_end: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True)
    required_weighted_hours: int = 0


class PartitionAuditLog(MagModel, table=True):
    """Append-only log of partition-relevant edits (assignments, billing
    flips, inventory edits, ownership changes). Scoped to a partition so
    the partition dashboard can render a "Recent activity" tab cheaply.

    `action` is a free-text short label (e.g. 'assignment.created',
    'assignment.billing_flipped', 'inventory.quantity_changed').
    `description` is the human-readable line shown on the dashboard.
    """
    # SET NULL rather than CASCADE, and partition_name snapshotted alongside,
    # for the same reason attendee_id is below: deleting a partition must not
    # destroy the record of what was done in it.
    partition_id: str | None = Field(
        sa_type=Uuid(as_uuid=False), foreign_key='inventory_partition.id',
        ondelete='SET NULL', nullable=True, index=True)
    partition: 'InventoryPartition' = Relationship(
        sa_relationship_kwargs={'foreign_keys': 'PartitionAuditLog.partition_id'})
    partition_name: str = ''

    admin_account_id: str | None = Field(
        sa_type=Uuid(as_uuid=False), foreign_key='admin_account.id',
        ondelete='SET NULL', nullable=True)
    admin_account: 'AdminAccount' = Relationship(
        sa_relationship_kwargs={'foreign_keys': 'PartitionAuditLog.admin_account_id'})

    # Whose room the entry is about, when the entry is about one. Kept
    # separate from target_id so the log still names the attendee after
    # the assignment row itself is deleted.
    attendee_id: str | None = Field(
        sa_type=Uuid(as_uuid=False), foreign_key='attendee.id',
        ondelete='SET NULL', nullable=True)
    attendee: 'Attendee' = Relationship(
        sa_relationship_kwargs={'foreign_keys': 'PartitionAuditLog.attendee_id'})

    when: datetime = Field(
        sa_type=DateTime(timezone=True), default_factory=lambda: datetime.now(UTC))
    action: str = ''
    description: str = ''
    target_type: str = ''  # 'assignment', 'inventory_block', 'partition_owner', etc.
    target_id: str | None = Field(sa_type=Uuid(as_uuid=False), nullable=True)


class HotelRoomIssueNote(MagModel, table=True):
    """Admin hide-flag + free-text notes for a single validation issue on
    the `room_issues` report.

    The report recomputes issues on every load, so there's nothing to
    attach a row to directly. Instead we key a note to the issue's STABLE
    identity - (issue_kind, target_type, target_id) - so the same logical
    issue (e.g. "over_capacity on room X") matches the same note across
    reloads. Hiding moves every issue matching that key into the report's
    hidden list and surfaces the note; the note text persists whether or
    not the issue is currently hidden.

    `target_type` in {'room_assignment', 'lottery_application',
    'inventory', 'room_type', 'partition', 'other'}; `target_id` is the
    matching object id stored as a string (or a synthetic key for the
    rare target-less issue).
    """
    __table_args__ = (
        sa.UniqueConstraint('issue_kind', 'target_type', 'target_id',
                            name='uq_hotel_room_issue_note'),
    )

    issue_kind: str = ''
    target_type: str = ''
    target_id: str = ''
    hidden: bool = False
    admin_notes: str = ''

    admin_account_id: str | None = Field(
        sa_type=Uuid(as_uuid=False), foreign_key='admin_account.id',
        ondelete='SET NULL', nullable=True)
    admin_account: 'AdminAccount' = Relationship(
        sa_relationship_kwargs={'foreign_keys': 'HotelRoomIssueNote.admin_account_id'})


class WaitlistReveal(MagModel, table=True):
    """A time-delayed external-link reveal for attendees who didn't get a
    room from the lottery. Admin configures the target URL and reveal time;
    each eligible attendee gets a unique WaitlistRevealLink emailed to them.
    The ubersystem page shows a countdown until reveal_at and only renders
    the real URL after that moment, giving lottery losers a small head
    start over the general scalping population.
    """
    __table_args__ = (
        sa.Index('uq_waitlist_reveal_shared_token', 'shared_token', unique=True,
                 postgresql_where=sa.text("shared_token <> ''")),
    )

    name: str = ''
    external_url: str = ''
    reveal_at: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True)
    audience_description: str = ''
    active: bool = True

    # False hands everyone the same shared_token instead of a per-attendee one.
    # Link rows are still created either way; they are the send ledger that
    # keeps the sender idempotent. Shared views have no row to stamp, so their
    # clicks are only counted in aggregate.
    use_unique_links: bool = True
    shared_token: str = ''
    shared_clicks: int = 0

    # Requires the viewer to be signed in to an attendee account. Only
    # meaningful when attendee accounts are enabled.
    require_login: bool = False

    links: list['WaitlistRevealLink'] = Relationship(
        back_populates="waitlist_reveal",
        sa_relationship_kwargs={'cascade': 'all,delete-orphan', 'passive_deletes': True})


class WaitlistRevealLink(MagModel, table=True):
    """One per (reveal, attendee). Token is the only thing the attendee
    sees in the email URL; we look up the reveal and metadata from it."""
    __table_args__ = (
        sa.UniqueConstraint('waitlist_reveal_id', 'attendee_id',
                            name='uq_waitlist_reveal_attendee'),
        sa.UniqueConstraint('token', name='uq_waitlist_reveal_link_token'),
    )

    waitlist_reveal_id: str = Field(
        sa_type=Uuid(as_uuid=False), foreign_key='waitlist_reveal.id',
        ondelete='CASCADE', nullable=False)
    waitlist_reveal: 'WaitlistReveal' = Relationship(
        back_populates="links",
        sa_relationship_kwargs={'foreign_keys': 'WaitlistRevealLink.waitlist_reveal_id'})

    attendee_id: str = Field(
        sa_type=Uuid(as_uuid=False), foreign_key='attendee.id',
        ondelete='CASCADE', nullable=False)
    attendee: 'Attendee' = Relationship(
        sa_relationship_kwargs={'foreign_keys': 'WaitlistRevealLink.attendee_id'})

    token: str = Field(nullable=False)
    emailed_at: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True)
    clicked_at: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True)


class HotelExportLog(MagModel, table=True):
    """One export handed to a hotel (or one import summary).

    Exports retain the exact bytes we sent (on disk under
    UPLOADED_FILES_DIR) so the file a hotel saw can be reproduced later;
    `source` says where the export came from ('admin' for a dashboard
    download, 'api' for the hotel portal pull).
    """
    hotel_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='lottery_hotel.id', nullable=True)
    hotel: 'LotteryHotel' = Relationship(
        sa_relationship_kwargs={'foreign_keys': 'HotelExportLog.hotel_id', 'lazy': 'joined'})
    export_type: str = ''
    exported_at: datetime | None = Field(sa_type=DateTime(timezone=True), default_factory=lambda: datetime.now(UTC))
    exported_by: str = ''
    record_count: int = 0
    notes: str = ''

    source: str = ''  # 'admin' | 'api' | '' for older rows
    filename: str = ''
    content_type: str = ''
    filepath: str = ''
    size: int = 0


class HotelImportFile(MagModel, table=True):
    """A raw confirmation/cancellation file uploaded for a hotel.

    Retained verbatim (on disk under UPLOADED_FILES_DIR) so odd hotel
    formats can be inspected and re-applied after the fact. Files arrive
    either from the uber-vault hotel portal (source='portal') or the admin
    upload (source='admin'); both appear in the exports page list.
    """
    hotel_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='lottery_hotel.id', nullable=True)
    hotel: 'LotteryHotel' = Relationship(
        sa_relationship_kwargs={'foreign_keys': 'HotelImportFile.hotel_id', 'lazy': 'joined'})
    filename: str = ''
    content_type: str = ''
    filepath: str = ''
    size: int = 0
    source: str = ''
    uploaded_by: str = ''
    uploaded_at: datetime | None = Field(sa_type=DateTime(timezone=True), default_factory=lambda: datetime.now(UTC))
    updated_count: int = 0
    unchanged_count: int = 0
    note: str = ''

    # The window during which this file's rows were applied. The change
    # feed has no link back to the file, so this is what scopes "which
    # room changes did this import cause" (see uber.hotel.exports
    # .import_changes).
    applied_from: datetime | None = Field(
        sa_type=DateTime(timezone=True), nullable=True)
    applied_to: datetime | None = Field(
        sa_type=DateTime(timezone=True), nullable=True)

    # 'pending', 'processed', or 'ignored'. Read effective_status instead, which
    # covers rows predating this column.
    status: str = Field(default='', index=True)
    processed_at: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True)
    processed_by: str = ''

    template_id: str | None = Field(
        sa_type=Uuid(as_uuid=False), foreign_key='import_mapping_template.id',
        ondelete='SET NULL', nullable=True)
    template: 'ImportMappingTemplate' = Relationship(
        sa_relationship_kwargs={'foreign_keys': 'HotelImportFile.template_id'})

    # The rows as parsed and mapped at upload time. Frozen because templates
    # stay editable: an admin fixing a template mid-review must not silently
    # change what this file is recorded as having said. The comparison against
    # live bookings is recomputed on every view instead.
    parsed_rows: list = Field(sa_type=MutableList.as_mutable(JSONB), default_factory=list)
    parse_error: str = ''
    matched_count: int = 0
    ambiguous_count: int = 0
    unmatched_count: int = 0

    @property
    def effective_status(self):
        if self.status:
            return self.status
        return 'processed' if self.applied_to else 'pending'


class ImportMappingTemplate(MagModel, table=True):
    """How to read one hotel's room-list format: which source column feeds
    which booking field, how its enum-ish values spell ours, and what date
    formats it uses. Matched to an upload by source_signature (the sorted,
    normalized header names) when no template is chosen explicitly."""

    name: str = ''
    description: str = ''
    source_signature: str = ''
    sheet_name: str = ''
    header_row: int = 1
    active: bool = True

    column_map: dict[str, Any] = Field(sa_type=MutableDict.as_mutable(JSONB), default_factory=dict)
    enum_map: dict[str, Any] = Field(sa_type=MutableDict.as_mutable(JSONB), default_factory=dict)
    format_map: dict[str, Any] = Field(sa_type=MutableDict.as_mutable(JSONB), default_factory=dict)


#
# RoomAssignment insert/delete events drive the parent LotteryApplication's
# COMPLETE <-> AWARDED transition. The application status tracks lottery
# eligibility only - per-room SECURED/EXPIRED/CANCELLED lifecycle stays on
# RoomAssignment.status.

from sqlalchemy import event as _sa_event  # noqa: E402


# Both listeners apply the same live-only predicate as the canonical
# `LotteryApplication.sync_award_status`: only rows whose status is in
# HOTEL_LIVE_ASSIGNMENT_STATUSES count toward "this app holds a room".
# (The listeners run on raw connections, so they use the status tuple
# directly rather than the `is_live` hybrid.)

@_sa_event.listens_for(RoomAssignment, 'after_insert')
def _ra_after_insert_promote_app(mapper, connection, target):
    if not target.lottery_application_id:
        return
    if target.status not in c.HOTEL_LIVE_ASSIGNMENT_STATUSES:
        # Inserting an already-cancelled/expired row (imports, seeds)
        # must not promote the application.
        return
    connection.execute(
        sa.update(LotteryApplication.__table__)
        .where(LotteryApplication.__table__.c.id == target.lottery_application_id)
        .where(LotteryApplication.__table__.c.status == c.COMPLETE)
        .values(status=c.AWARDED)
    )


@_sa_event.listens_for(RoomAssignment, 'after_delete')
def _ra_after_delete_demote_app(mapper, connection, target):
    if not target.lottery_application_id:
        return
    remaining_live = connection.execute(
        sa.select(sa.func.count())
        .select_from(RoomAssignment.__table__)
        .where(RoomAssignment.__table__.c.lottery_application_id == target.lottery_application_id)
        .where(RoomAssignment.__table__.c.id != target.id)
        .where(RoomAssignment.__table__.c.status.in_(c.HOTEL_LIVE_ASSIGNMENT_STATUSES))
    ).scalar() or 0
    if remaining_live == 0:
        # Mirrors sync_award_status: deleting the last live row demotes
        # AWARDED or PROCESSED back to COMPLETE and detaches the run, even
        # when cancelled/expired siblings linger (the common case, since
        # expired rows are retained).
        connection.execute(
            sa.update(LotteryApplication.__table__)
            .where(LotteryApplication.__table__.c.id == target.lottery_application_id)
            .where(LotteryApplication.__table__.c.status.in_((c.AWARDED, c.PROCESSED)))
            .values(status=c.COMPLETE, lottery_run_id=None)
        )
