"""Room-assignment write path.

Shared create/edit helpers behind every admin surface that writes
RoomAssignment rows: the lottery admin's application form and standalone
edit page, the cross-section assign-room page, and the partition-scoped
dashboard. Validation failures raise RoomAssignmentError with a
user-facing message; each route handler maps that onto its own
redirect/re-render contract.

Transaction convention (see uber.hotel.__init__): helpers here flush and
never commit - the calling route handler / API method / cron owns the
transaction.
"""

from datetime import date

from uber.config import c
from uber.hotel.perms import record_partition_audit


class RoomAssignmentError(Exception):
    """User-facing validation failure in the room-assignment write path."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


def parse_date_param(raw, label):
    """Parse one submitted date field.

    '' or None -> None; a date instance passes through; an ISO 8601 date
    string ('YYYY-MM-DD', stripped first) -> date. Anything unparseable
    raises RoomAssignmentError - bad input must surface to the admin, never
    be silently dropped.
    """
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw
    raw = str(raw).strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise RoomAssignmentError(f'Could not parse the {label} date.')


def parse_payment_type(raw, default=None):
    """Resolve a submitted payment type to a [[payment_types]] key.

    '' or None falls back to `default`, or master bill. An unknown key raises
    rather than silently storing something no config entry describes.
    """
    raw = str(raw or '').strip()
    if not raw:
        return default or 'masterbill'
    if raw not in c.HOTEL_PAYMENT_TYPES:
        raise RoomAssignmentError(f'Unknown payment type: {raw}')
    return raw


def validate_physical_room(session, ra, room):
    """Why a physical room can't take this booking, or None if it can."""
    from uber.hotel.queries import physical_room_conflicts

    inv = ra.inventory
    if not inv or not inv.hotel_id:
        return 'This booking has no inventory block, so no hotel to match.'
    if room.hotel_id != inv.hotel_id:
        return (f'Room {room.room_number} is at a different hotel than '
                'this booking.')
    if room.out_of_service:
        return f'Room {room.room_number} is out of service.'
    conflicts = physical_room_conflicts(
        session, room.id, ra.assigned_check_in_date,
        ra.assigned_check_out_date, exclude_assignment_id=ra.id)
    if conflicts:
        other = conflicts[0]
        return (f'Room {room.room_number} is already booked '
                f'{other.assigned_check_in_date} -> '
                f'{other.assigned_check_out_date}.')
    return None


def assign_physical_room(session, ra, room, auto=False):
    """Place `ra` in `room`, taking its connector rooms along.

    A suite parent may only sit in a room whose physically connected
    neighbors can host every connector child for the same dates; the
    children are placed in those rooms by the same call, so the group
    is assigned all at once or not at all. Rooms that merely happen to
    be connected are left alone.

    Returns (placed_assignments, error). On error nothing is changed.
    """
    from uber.hotel import physical as hotel_physical

    error = validate_physical_room(session, ra, room)
    if error:
        return [], error

    children = hotel_physical.connector_children(session, ra)
    picks = []
    if children:
        placements = hotel_physical.connector_placements(
            session, ra, children=children)
        picks = next((p for candidate, p in placements
                      if candidate.id == room.id), None)
        if picks is None:
            return [], (
                f'Room {room.room_number} does not have {len(children)} '
                'connected room(s) free for these dates, so this suite '
                'and its connector room(s) cannot go there.')

    placed = []
    for assignment, target in [(ra, room)] + picks:
        assignment.physical_room_id = target.id
        assignment.physical_room_auto = auto
        session.add(assignment)
        placed.append(assignment)
    return placed, None


def create_room_assignment(session, *, attendee_id, inventory_id,
                           partition_id=None, lottery_application_id=None,
                           assignment_reason=None, status=None,
                           payment_type=None, assigned_check_in_date=None,
                           assigned_check_out_date=None,
                           deposit_cutoff_date=None, room_number='',
                           admin_notes='', enforce_partition_block=None,
                           audit_description=None, allow_room_number=True):
    """Create one RoomAssignment (added and flushed, NOT committed).

    Validates that the attendee and inventory exist, parses the date
    parameters (ISO strings or date instances; bad input raises
    RoomAssignmentError), and - whenever partition_id is set (or
    enforce_partition_block is passed as True) - requires an
    InventoryPartitionBlock allocating that inventory to that partition,
    so a partitioned assignment can never point outside its partition's
    blocks and corrupt the (partition, inventory) capacity accounting.

    Writes one partition audit row when partition_id is set, using
    `audit_description` or a generic default. Returns the new assignment.
    """
    from uber.models import Attendee
    from uber.models.hotel import (
        HotelRoomInventory, InventoryPartitionBlock, RoomAssignment)

    attendee_id = str(attendee_id or '').strip()
    inventory_id = str(inventory_id or '').strip()
    partition_id = str(partition_id or '').strip() or None

    if not attendee_id or not inventory_id:
        raise RoomAssignmentError('Attendee and inventory are required.')
    if not session.query(Attendee).get(attendee_id):
        raise RoomAssignmentError('Attendee not found.')
    if not session.query(HotelRoomInventory).get(inventory_id):
        raise RoomAssignmentError('Inventory not found.')

    if partition_id and enforce_partition_block is not False:
        block = session.query(InventoryPartitionBlock).filter_by(
            partition_id=partition_id, inventory_id=inventory_id).first()
        if not block:
            raise RoomAssignmentError(
                'That room block is not allocated to this partition.')

    ra = RoomAssignment(
        attendee_id=attendee_id,
        inventory_id=inventory_id,
        partition_id=partition_id,
        lottery_application_id=lottery_application_id or None,
        assignment_reason=(assignment_reason if assignment_reason is not None
                           else c.MANUAL),
        status=status if status is not None else c.ASSIGNED,
        payment_type=parse_payment_type(payment_type),
        assigned_check_in_date=parse_date_param(
            assigned_check_in_date, 'check-in'),
        assigned_check_out_date=parse_date_param(
            assigned_check_out_date, 'check-out'),
        deposit_cutoff_date=parse_date_param(
            deposit_cutoff_date, 'deposit cutoff'),
        room_number=((room_number or '').strip() or None) if allow_room_number else None,
        admin_notes=(admin_notes or '').strip(),
    )
    session.add(ra)
    session.flush()

    if partition_id:
        record_partition_audit(
            session, partition_id,
            action='assignment.created',
            description=f"{audit_description or 'Assigned room'}: "
                        f"{ra.room_summary}",
            target_type='assignment', target_id=ra.id,
            attendee_id=ra.attendee_id)
    return ra


def apply_room_assignment_edits(session, ra, params, *, audit_prefix, fail,
                                allowed_inventory_ids=None,
                                allow_room_number=True):
    """Shared save path for the RoomAssignment edit surfaces (the
    application form's per-room modal, the standalone edit page, the
    assign-room page's edit mode, and the partition dashboard modal).

    Only touches fields actually present in `params`, so each surface
    keeps its own field set: the modal posts inventory / partition /
    billing / dates; the standalone page additionally posts status,
    deposit cutoff, confirmation numbers, and special requests.

    `fail(message)` is called on invalid input and must raise (callers
    redirect back to their own page with the message).

    `allowed_inventory_ids`, when given, bounds any inventory change to
    that set of ids (partition-scoped callers pass their partition's
    block inventory ids); a change outside the set calls `fail`.

    `allow_room_number=False` ignores both room_number and
    physical_room_id. Both, because linking a physical room re-stamps
    room_number via a presave, so dropping only the text field would
    still let the caller set the number indirectly.

    Returns the user-facing result message; flushes (never commits - the
    caller owns the transaction) and writes one partition audit row
    prefixed with `audit_prefix` when anything changed.
    """
    changes = []

    if 'inventory_id' in params:
        new_inv = params.get('inventory_id', '').strip()
        if new_inv and new_inv != ra.inventory_id:
            if allowed_inventory_ids is not None \
                    and new_inv not in allowed_inventory_ids:
                fail('That room block is not allocated to this partition.')
            changes.append('inventory'); ra.inventory_id = new_inv
    if 'partition_id' in params:
        new_part = params.get('partition_id', '').strip() or None
        if new_part != ra.partition_id:
            changes.append('partition'); ra.partition_id = new_part
    if 'payment_type' in params:
        try:
            new_payment_type = parse_payment_type(params.get('payment_type'),
                                                  default=ra.payment_type)
        except RoomAssignmentError as e:
            fail(e.message)
        if new_payment_type != ra.payment_type:
            changes.append('billing'); ra.payment_type = new_payment_type

    for name, label in (('assigned_check_in_date', 'check-in'),
                        ('assigned_check_out_date', 'check-out'),
                        ('deposit_cutoff_date', 'deposit cutoff')):
        if name not in params:
            continue
        raw = (params.get(name, '') or '').strip()
        if raw:
            try:
                new_val = date.fromisoformat(raw)
            except ValueError:
                fail(f"Could not parse the {label} date.")
        else:
            new_val = None
        if new_val != getattr(ra, name):
            changes.append(label); setattr(ra, name, new_val)

    raw_status = (params.get('status', '') or '').strip()
    if raw_status:
        try:
            new_status = int(raw_status)
        except ValueError:
            fail("Invalid status.")
        if new_status != ra.status:
            changes.append('status'); ra.status = new_status

    if 'physical_room_id' in params and allow_room_number:
        from uber.models.hotel import PhysicalRoom
        new_room_id = params.get('physical_room_id', '').strip() or None
        if new_room_id != (ra.physical_room_id or None):
            if new_room_id:
                room = session.query(PhysicalRoom).get(new_room_id)
                if not room:
                    fail('Physical room not found.')
                error = validate_physical_room(session, ra, room)
                if error:
                    fail(error)
            # Unlinking keeps the room_number text for reference; the
            # presave re-stamps it whenever a room is linked.
            changes.append('physical room')
            ra.physical_room_id = new_room_id
            ra.physical_room_auto = False

    for field, nullable in (('hotel_confirmation_number', True),
                            ('cancellation_confirmation_number', True),
                            ('room_number', True),
                            ('special_requests', False),
                            ('admin_notes', False)):
        if field not in params:
            continue
        if field == 'room_number' and not allow_room_number:
            continue
        raw = (params.get(field, '') or '').strip()
        if raw != (getattr(ra, field) or ''):
            changes.append(field.replace('_', ' '))
            # NOT NULL string columns clear to '' rather than None.
            setattr(ra, field, raw or (None if nullable else ''))

    if changes:
        session.add(ra)
        if ra.partition_id:
            record_partition_audit(
                session, ra.partition_id,
                action='assignment.updated',
                description=f"{audit_prefix} {', '.join(changes)}: "
                            f"{ra.room_summary}",
                target_type='assignment', target_id=ra.id,
                attendee_id=ra.attendee_id)
        session.flush()
        return f"Updated {', '.join(changes)}."
    return 'No changes.'
