"""Read-only query layer shared by every hotel-room surface.

This module is the single definition of:

  * build_room_assignment_query - the room-list filter semantics shared
    by hotel_lottery_admin.rooms, staff_rooming, and partition_admin.
  * attendee_search_results - the JSON rows behind the admin
    attendee-picker widgets (hotel_lottery_admin + partition_admin).
  * clamp_page_size / paginate - the shared pagination behavior.
  * occupancy_by_block_night / capacity_for / capacity_night_map /
    block_availability - the capacity math. "How many rooms exist /
    are taken for (inventory, night, partition)" is the system's core
    invariant; every consumer (solver prep, admin pages, the attendee
    editor, the audit, exports) must go through these so the answer
    can't drift. Nights are always checkout-day EXCLUSIVE
    ([check_in, check_out)), and per-night quantities come from
    HotelRoomInventory.quantity_for_night.
  * overlaps / physical_room_conflicts / vacant_physical_rooms /
    vacant_rooms_map - the physical-room occupancy predicates.
  * live_assignments_for_hotel - the standard "all live bookings at a
    hotel" query.

Access control is intentionally NOT handled here: each section keeps its
own controller, ACL checks, and templates. Everything here is read-only;
writes live in uber.hotel.service / uber.hotel.waitlist.
"""

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import func, or_

from uber.models import Attendee
from uber.models.hotel import (HotelRoomInventory, InventoryPartitionBlock,
                               LotteryApplication, PhysicalRoom, RoomAssignment)


def build_room_assignment_query(session, *, status='live', hotel_id='',
                                partition_id='', search='', attendee_id='',
                                badge_types=None):
    """Build the standard RoomAssignment listing query.

    Filter semantics (mirrors the hotel_lottery_admin Rooms page):

      status      - 'live' (default) = ASSIGNED + SECURED via
                    RoomAssignment.is_live; 'all' (or '') = no status
                    filter; anything else is coerced to an exact status
                    int, silently ignored if not parseable.
      hotel_id    - restrict to assignments whose inventory block belongs
                    to this hotel (resolved via an inventory-id lookup).
      partition_id- exact partition match, or the sentinel 'none' for
                    rows with no partition.
      search      - case-insensitive substring match over the lottery
                    application's confirmation #, the hotel confirmation
                    #, and the attendee's email / first / last name.
                    Joins LotteryApplication and Attendee as outer joins
                    so rows missing either still match on other fields.
      attendee_id - scope to one attendee's rooms. In that case a 'live'
                    status filter is widened to 'all', since the caller
                    wants the attendee's full history.
      badge_types - optional list of badge-type consts; inner-joins
                    Attendee and requires the booker's badge_type to be
                    in the list (staff_rooming passes
                    [c.STAFF_BADGE, c.CONTRACTOR_BADGE]).

    Ordering is left to the caller. Additional caller-specific filters
    (e.g. staffer_rooms' billing filter) can be chained onto the returned
    query. When badge_types is passed, Attendee is inner-joined, so the
    caller may also order by / filter on Attendee columns.
    """
    q = session.query(RoomAssignment)

    # Scope to one attendee's rooms - show every status in that case,
    # since the admin wants the attendee's full history.
    if attendee_id:
        q = q.filter(RoomAssignment.attendee_id == attendee_id)
        if status == 'live':
            status = 'all'

    # `live` (default) = ASSIGNED + SECURED. `all` = no status filter.
    # Anything else = exact status int from the model's status enum.
    if status == 'live':
        q = q.filter(RoomAssignment.is_live)
    elif status and status != 'all':
        try:
            q = q.filter(RoomAssignment.status == int(status))
        except (TypeError, ValueError):
            pass

    attendee_joined = False
    if badge_types:
        q = (q.join(Attendee, Attendee.id == RoomAssignment.attendee_id)
              .filter(Attendee.badge_type.in_(badge_types)))
        attendee_joined = True

    if hotel_id:
        inv_ids = [str(inv.id) for inv in
                   session.query(HotelRoomInventory)
                   .filter_by(hotel_id=hotel_id).all()]
        q = q.filter(RoomAssignment.inventory_id.in_(inv_ids))

    if partition_id:
        if partition_id == 'none':
            q = q.filter(RoomAssignment.partition_id.is_(None))
        else:
            q = q.filter(RoomAssignment.partition_id == partition_id)

    # Search hits the application's confirmation #, attendee email/name,
    # and the hotel confirmation #. Outer joins so assignments without
    # an application (or, pathologically, an attendee) still match on
    # their other fields.
    search_term = (search or '').strip()
    if search_term:
        like = f'%{search_term}%'
        q = q.join(LotteryApplication,
                   LotteryApplication.id == RoomAssignment.lottery_application_id,
                   isouter=True)
        if not attendee_joined:
            q = q.join(Attendee,
                       Attendee.id == RoomAssignment.attendee_id,
                       isouter=True)
        q = q.filter(or_(
            LotteryApplication.confirmation_num.ilike(like),
            RoomAssignment.hotel_confirmation_number.ilike(like),
            Attendee.email.ilike(like),
            Attendee.first_name.ilike(like),
            Attendee.last_name.ilike(like),
        ))

    return q


def attendee_search_results(session, q, limit=25):
    """JSON-ready rows for the admin attendee-picker widgets
    (`attendee_search_widget` + static/js/hotel-attendee-search.js).

    Reuses Session.search() so every field the normal admin search
    covers (names, legal name, email, badge ID, badge number, UUID,
    promo group, etc.) works here too. Returns a list of dicts with
    exactly the keys the picker JS expects: id, name, email, badge_num,
    badge_type. Access control is the caller's job - both consuming
    routes keep their own gates.
    """
    q = (q or '').strip()
    if len(q) < 2:
        return []

    try:
        results, _ = session.search(q)
    except Exception:
        return []

    out = []
    for a in results.limit(limit).all():
        badge = ''
        try:
            badge = str(a.badge_num) if a.badge_num else ''
        except Exception:
            pass
        out.append({
            'id': a.id,
            'name': a.full_name,
            'email': a.email or '',
            'badge_num': badge,
            'badge_type': a.badge_type_label or '',
        })
    return out


def clamp_page_size(page_size, default_size=50, min_size=10, max_size=500):
    """Coerce a request's page_size param to a sane int.

    Unparseable values fall back to default_size; parseable values are
    clamped into [min_size, max_size]. Exposed separately from paginate
    because handlers echo the clamped size back into their template
    context (per-page picker, "Showing X-Y of Z" summary).
    """
    try:
        return max(min_size, min(max_size, int(page_size)))
    except (TypeError, ValueError):
        return default_size


def paginate(query, page, page_size=None,
             default_size=50, min_size=10, max_size=500):
    """Run the standard count/clamp/offset/limit dance.

    Returns (rows, total, page, page_count).

      * page is coerced via int() (falling back to 1), floored at 1, and
        clamped down to the last page when it overshoots.
      * page_size is clamped via clamp_page_size with the same bounds.
      * page_count is always >= 1, even with zero rows.

    Accepts either a SQLAlchemy query (count/offset/limit) or a plain
    list/tuple (len/slice) - compliance_report paginates an in-Python
    list of result tuples. Ordering is the caller's job: apply order_by
    (or pre-sort the list) before calling.
    """
    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1
    size = clamp_page_size(page_size, default_size=default_size,
                           min_size=min_size, max_size=max_size)

    if isinstance(query, (list, tuple)):
        total = len(query)
    else:
        total = query.count()

    page_count = max(1, (total + size - 1) // size)
    if page > page_count:
        page = page_count

    offset = (page - 1) * size
    if isinstance(query, (list, tuple)):
        rows = list(query[offset:offset + size])
    else:
        rows = query.offset(offset).limit(size).all()
    return rows, total, page, page_count


def overlaps(a_check_in, a_check_out, b_check_in, b_check_out):
    """True when two [check_in, check_out) stay ranges share a night.
    Checkout day is exclusive, so back-to-back turnover (A checks out
    the morning B checks in) does not overlap. Ranges missing either
    date never overlap - they can't be placed on specific nights."""
    if not (a_check_in and a_check_out and b_check_in and b_check_out):
        return False
    return a_check_in < b_check_out and b_check_in < a_check_out


def occupancy_by_block_night(assignments, *, iso_keys=False,
                             by_partition=False):
    """The canonical per-block-per-night occupancy histogram.

    Walks RoomAssignment rows (the caller filters to the population it
    cares about - usually live rows) and counts each night of
    [assigned_check_in_date, assigned_check_out_date), checkout-day
    exclusive. Rows missing either date are skipped.

    Returns {inventory_id(str): {night: count}} - or, with
    by_partition=True, {(inventory_id, partition_id_or_None): {night:
    count}}. iso_keys=True keys nights as ISO strings (the solver's
    interchange format) instead of dates.
    """
    hist = defaultdict(lambda: defaultdict(int))
    for ra in assignments:
        if not (ra.assigned_check_in_date and ra.assigned_check_out_date):
            continue
        if by_partition:
            key = (str(ra.inventory_id),
                   str(ra.partition_id) if ra.partition_id else None)
        else:
            key = str(ra.inventory_id)
        day = ra.assigned_check_in_date
        while day < ra.assigned_check_out_date:
            hist[key][day.isoformat() if iso_keys else day] += 1
            day += timedelta(days=1)
    return hist


def capacity_for(session, inv, night, partition_id=None,
                 exclude_assignment_id=None):
    """Effective capacity and live-assignment count for one
    (inventory, night, partition) cell.

    With partition_id set, capacity is the partition's block allocation
    (bounded by the night's quantity) and only same-partition live rows
    count; with partition_id None, capacity is the night's quantity minus
    every partition carve-out, counting only unpartitioned live rows.
    exclude_assignment_id drops one row from the count - the attendee
    editor evaluates a resize as if its own booking weren't there.

    Returns (capacity, assigned_count, open_slots). For whole-grid
    dashboards use capacity_night_map, which answers the same question
    without two queries per cell.
    """
    block_qty = inv.quantity_for_night(night)

    base_filters = [
        RoomAssignment.inventory_id == str(inv.id),
        RoomAssignment.is_live,
        RoomAssignment.assigned_check_in_date <= night,
        RoomAssignment.assigned_check_out_date > night,
    ]
    if exclude_assignment_id:
        base_filters.append(RoomAssignment.id != exclude_assignment_id)

    if partition_id:
        pb = session.query(InventoryPartitionBlock).filter_by(
            partition_id=partition_id, inventory_id=inv.id).first()
        capacity = min(pb.quantity, block_qty) if pb else 0
        assigned_count = session.query(RoomAssignment).filter(
            *base_filters,
            RoomAssignment.partition_id == partition_id,
        ).count()
    else:
        total_partitioned = session.query(
            func.coalesce(func.sum(InventoryPartitionBlock.quantity), 0)
        ).filter(
            InventoryPartitionBlock.inventory_id == str(inv.id),
        ).scalar()
        capacity = max(0, block_qty - total_partitioned)
        assigned_count = session.query(RoomAssignment).filter(
            *base_filters,
            RoomAssignment.partition_id == None,  # noqa: E711
        ).count()

    return capacity, assigned_count, max(0, capacity - assigned_count)


def capacity_night_map(session, inventories, nights, partition_id=None):
    """Batched capacity_for: one InventoryPartitionBlock query plus one
    grouped live-assignment scan for the whole (inventories x nights)
    grid, instead of two queries per cell.

    Returns {(inventory_id(str), night): (capacity, assigned, open)}
    with the same semantics as capacity_for (partition_id None means the
    unpartitioned main pool).
    """
    inv_ids = [str(inv.id) for inv in inventories]
    if not inv_ids:
        return {}

    blocks = session.query(InventoryPartitionBlock).filter(
        InventoryPartitionBlock.inventory_id.in_(inv_ids)).all()
    partitioned_total = defaultdict(int)
    block_qty = {}
    for b in blocks:
        iid = str(b.inventory_id)
        partitioned_total[iid] += b.quantity
        block_qty[(iid, str(b.partition_id))] = b.quantity

    ras = session.query(RoomAssignment).filter(
        RoomAssignment.inventory_id.in_(inv_ids),
        RoomAssignment.is_live,
        RoomAssignment.assigned_check_in_date.isnot(None),
        RoomAssignment.assigned_check_out_date.isnot(None)).all()
    scope = str(partition_id) if partition_id else None
    hist = occupancy_by_block_night(
        (ra for ra in ras
         if (str(ra.partition_id) if ra.partition_id else None) == scope),
        by_partition=False)

    result = {}
    for inv in inventories:
        iid = str(inv.id)
        for night in nights:
            night_qty = inv.quantity_for_night(night)
            if partition_id:
                pb_qty = block_qty.get((iid, str(partition_id)))
                capacity = min(pb_qty, night_qty) if pb_qty is not None else 0
            else:
                capacity = max(0, night_qty - partitioned_total[iid])
            assigned = hist.get(iid, {}).get(night, 0)
            result[(iid, night)] = (capacity, assigned,
                                    max(0, capacity - assigned))
    return result


def block_availability(session, inventory_blocks):
    """Whole-block (night-agnostic) open-slot accounting for assignment
    pickers: capacity minus live assignments per scope, where scope '' is
    the unpartitioned main pool and each partition id is its carve-out.

    Returns (avail_map, inventory_partitions_map):
      avail_map               - {inventory_id: {'': open, partition_id:
                                open, ...}}
      inventory_partitions_map- {inventory_id: [partition_id, ...]} (the
                                partitions holding a block on that
                                inventory - pickers use it to restrict
                                the partition dropdown).
    """
    live = {}
    for inv_id, part_id, n in (
            session.query(RoomAssignment.inventory_id,
                          RoomAssignment.partition_id,
                          func.count(RoomAssignment.id))
            .filter(RoomAssignment.is_live,
                    RoomAssignment.inventory_id.isnot(None))
            .group_by(RoomAssignment.inventory_id,
                      RoomAssignment.partition_id)):
        live[(str(inv_id), str(part_id) if part_id else '')] = n

    block_qty, partitioned_total, inventory_partitions_map = {}, {}, {}
    for b in session.query(InventoryPartitionBlock).all():
        iid, pid = str(b.inventory_id), str(b.partition_id)
        block_qty[(iid, pid)] = b.quantity
        partitioned_total[iid] = partitioned_total.get(iid, 0) + b.quantity
        inventory_partitions_map.setdefault(iid, []).append(pid)

    avail_map = {}
    for inv in inventory_blocks:
        iid = str(inv.id)
        scopes = {'': max(0, (inv.quantity or 0)
                          - partitioned_total.get(iid, 0)
                          - live.get((iid, ''), 0))}
        for pid in inventory_partitions_map.get(iid, []):
            scopes[pid] = max(0, block_qty[(iid, pid)]
                              - live.get((iid, pid), 0))
        avail_map[iid] = scopes
    return avail_map, inventory_partitions_map


def live_assignments_for_hotel(session, hotel_id):
    """All live RoomAssignments whose inventory block belongs to the
    given hotel, via a join (no fetch-ids-then-IN round trip). Ordering
    is the caller's job."""
    return (session.query(RoomAssignment)
            .join(HotelRoomInventory,
                  HotelRoomInventory.id == RoomAssignment.inventory_id)
            .filter(HotelRoomInventory.hotel_id == str(hotel_id),
                    RoomAssignment.is_live))


def physical_room_conflicts(session, physical_room_id, check_in, check_out,
                            exclude_assignment_id=None):
    """Live RoomAssignments already occupying a physical room for any night
    in [check_in, check_out).

    One booking per room per night: two bookings conflict when their date
    ranges overlap, with checkout day exclusive so back-to-back turnover
    (A checks out the morning B checks in) is allowed. Assignments with no
    dates never conflict - they can't be placed on specific nights.
    """
    if not (physical_room_id and check_in and check_out):
        return []
    q = session.query(RoomAssignment).filter(
        RoomAssignment.physical_room_id == physical_room_id,
        RoomAssignment.is_live,
        RoomAssignment.assigned_check_in_date.isnot(None),
        RoomAssignment.assigned_check_out_date.isnot(None),
        RoomAssignment.assigned_check_in_date < check_out,
        RoomAssignment.assigned_check_out_date > check_in,
    )
    if exclude_assignment_id:
        q = q.filter(RoomAssignment.id != exclude_assignment_id)
    return q.all()


def vacant_physical_rooms(session, hotel_id, check_in, check_out,
                          inventory_id=None, ada_only=False):
    """In-service physical rooms at a hotel with no live booking on any
    night of [check_in, check_out), optionally limited to one sellable
    block. Returns rooms in floor/room-number order."""
    rooms = session.query(PhysicalRoom).filter(
        PhysicalRoom.hotel_id == hotel_id,
        PhysicalRoom.out_of_service.is_(False))
    if inventory_id:
        rooms = rooms.filter(PhysicalRoom.inventory_id == inventory_id)
    if ada_only:
        rooms = rooms.filter(PhysicalRoom.ada.is_(True))
    rooms = rooms.all()

    if check_in and check_out:
        # Scope the busy-set to this hotel's rooms - a physical_room_id
        # always belongs to one hotel, so scanning every dated live
        # assignment in the database was pure waste.
        busy = {row[0] for row in session.query(
            RoomAssignment.physical_room_id)
            .join(PhysicalRoom, PhysicalRoom.id == RoomAssignment.physical_room_id)
            .filter(
                PhysicalRoom.hotel_id == hotel_id,
                RoomAssignment.is_live,
                RoomAssignment.assigned_check_in_date.isnot(None),
                RoomAssignment.assigned_check_out_date.isnot(None),
                RoomAssignment.assigned_check_in_date < check_out,
                RoomAssignment.assigned_check_out_date > check_in).all()}
        rooms = [r for r in rooms if r.id not in busy]
    return sorted(rooms, key=lambda r: r.sort_key)


def vacant_rooms_map(session, hotel_id, bookings):
    """Bulk vacant_physical_rooms: {assignment_id: [PhysicalRoom, ...]}
    for many bookings at one hotel.

    Each booking's list matches what vacant_physical_rooms(session,
    hotel_id, ra.assigned_check_in_date, ra.assigned_check_out_date,
    inventory_id=ra.inventory_id) would return, but the hotel's room
    list and per-room busy intervals are fetched once (two queries
    total) instead of twice per booking - the rooming board calls this
    for every unroomed booking on the page.
    """
    from uber.models.hotel import PhysicalRoom, RoomAssignment

    rooms = sorted(
        session.query(PhysicalRoom).filter(
            PhysicalRoom.hotel_id == hotel_id,
            PhysicalRoom.out_of_service.is_(False)).all(),
        key=lambda r: r.sort_key)

    busy = defaultdict(list)
    for room_id, b_ci, b_co in (
            session.query(RoomAssignment.physical_room_id,
                          RoomAssignment.assigned_check_in_date,
                          RoomAssignment.assigned_check_out_date)
            .join(PhysicalRoom,
                  PhysicalRoom.id == RoomAssignment.physical_room_id)
            .filter(PhysicalRoom.hotel_id == hotel_id,
                    RoomAssignment.is_live,
                    RoomAssignment.assigned_check_in_date.isnot(None),
                    RoomAssignment.assigned_check_out_date.isnot(None))):
        busy[room_id].append((b_ci, b_co))

    out = {}
    for ra in bookings:
        check_in = ra.assigned_check_in_date
        check_out = ra.assigned_check_out_date
        options = [r for r in rooms
                   if not ra.inventory_id or r.inventory_id == ra.inventory_id]
        if check_in and check_out:
            options = [r for r in options
                       if not any(overlaps(check_in, check_out, b_ci, b_co)
                                  for b_ci, b_co in busy.get(r.id, []))]
        out[ra.id] = options
    return out


def active_inventory_type_map(session, is_suite=None):
    """{hotel_id: [room_or_suite_type_id, ...]} over active inventory.

    Lets the entry form gray out room types no selected hotel actually
    offers; the ranking choices themselves are event-wide.
    """
    query = session.query(HotelRoomInventory).filter(
        HotelRoomInventory.active == True)  # noqa: E712
    if is_suite is not None:
        query = query.filter(HotelRoomInventory.is_suite == is_suite)

    out = {}
    for inv in query.all():
        type_id = inv.room_or_suite_type_id
        if not inv.hotel_id or not type_id:
            continue
        out.setdefault(str(inv.hotel_id), [])
        if str(type_id) not in out[str(inv.hotel_id)]:
            out[str(inv.hotel_id)].append(str(type_id))
    return out
