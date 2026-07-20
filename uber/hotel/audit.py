"""Room-data audit behind the hotel lottery admin's Room Issues report.

Cross-checks every live RoomAssignment (and the inventory / room-type
configuration) and produces two lists of issue dicts: room-level issues
(each tied to an assignment or application) and inventory-level issues
(configuration and capacity problems). The scan is intentionally all in
Python - no SQL view - so it's easy to add new checks: write a function
that takes the prebuilt audit context and returns issue dicts, then
register it in ROOM_CHECKS or INVENTORY_CHECKS.

Issues are recomputed on every page load, so admin hide-flags and notes
persist in HotelRoomIssueNote rows keyed to each issue's STABLE identity
(kind, target_type, target_id); the identity/annotate/filter/group
helpers here are shared by the report handler and the hide/unhide/note
POST handlers in uber.site_sections.hotel_lottery_admin.
"""
from collections import defaultdict
from datetime import timedelta

from uber.config import c
from uber.models import LotteryApplication
from uber.models.hotel import (HotelRoomInventory, HotelRoomIssueNote,
                               InventoryPartition, InventoryPartitionBlock,
                               LotteryHotel, LotteryRoomType, RoomAssignment)


def _room_issue(severity, kind, label, assignment, fix_url=None, extra=None):
    return {
        'severity': severity,
        'kind': kind,
        'label': label,
        'assignment': assignment,
        'fix_url': fix_url,
        'extra': extra or {},
    }


def _inv_issue(severity, kind, label, inventory=None, partition=None,
               room_type=None, fix_url=None, extra=None):
    return {
        'severity': severity,
        'kind': kind,
        'label': label,
        'inventory': inventory,
        'partition': partition,
        'room_type': room_type,
        'fix_url': fix_url,
        'extra': extra or {},
    }


def build_audit_context(session):
    """Prefetch everything the issue checks share into one lookup dict.

    Keys:
      session - kept for the two checks that resolve rare ids lazily
        (partition_unconfigured, insufficient_connectors_at_hotel).
      live - all live assignments; these are what we audit.
      by_id - {assignment_id: RoomAssignment} over the live set.
      children_of - group-by-parent for childless-parent detection.
      room_type_parents / room_type_children_needed - connector config:
        room_type_id -> (parent_type_id, qty) it must follow, and the
        reverse (parent -> [(child_id, qty, child_name), ...]). With the
        current single-parent model that's at most one entry per child,
        but we model the reverse as a list so the same code handles any
        future multi-parent extension.
      all_types_by_id - every LotteryRoomType.
      all_inventory - all active inventory.
      partition_blocks_by_inv - partition-block index keyed by
        inventory_id so the per-partition oversubscription check is a
        constant-time lookup per row.
      live_by_inv - live RAs grouped by inventory for the
        oversubscription scans.
      app_ids_with_rooms - application ids with at least one live room.
      mismatched_apps / awarded_apps - the status_mismatch populations.
      ci_start / co_end - the event window bounds (dates or None).
    """
    # All live assignments - these are what we audit.
    live = (session.query(RoomAssignment)
            .filter(RoomAssignment.is_live)
            .all())

    by_id = {ra.id: ra for ra in live}

    # Build group-by-parent for childless-parent detection.
    children_of = defaultdict(list)
    for ra in live:
        if ra.parent_assignment_id:
            children_of[ra.parent_assignment_id].append(ra)

    # Lookup: room_type_id -> list of (parent_type_id, qty) it must
    # follow. With the current single-parent model that's at most
    # one entry, but we model it as a list so the same code handles
    # any future multi-parent extension.
    room_type_parents = {}
    room_type_children_needed = defaultdict(list)
    all_types_by_id = {}
    for rt in session.query(LotteryRoomType).all():
        all_types_by_id[rt.id] = rt
        if rt.connects_to_type_id:
            room_type_parents[rt.id] = (rt.connects_to_type_id,
                                        rt.connector_quantity)
            room_type_children_needed[rt.connects_to_type_id].append(
                (rt.id, rt.connector_quantity, rt.name))

    # All active inventory, plus the partition-block index keyed by
    # inventory_id so the per-partition oversubscription check is a
    # constant-time lookup per row.
    all_inventory = (session.query(HotelRoomInventory)
                     .filter_by(active=True).all())
    partition_blocks_by_inv = defaultdict(list)
    for pb in session.query(InventoryPartitionBlock).all():
        partition_blocks_by_inv[str(pb.inventory_id)].append(pb)

    # Live RAs grouped by inventory for the oversubscription scans.
    live_by_inv = defaultdict(list)
    for ra in live:
        if ra.inventory_id:
            live_by_inv[str(ra.inventory_id)].append(ra)

    # Apps with rooms should be AWARDED; apps without any live rooms
    # should NOT be AWARDED. The listener flips these in real time,
    # so any hit here means data was edited around the listener.
    app_ids_with_rooms = {ra.lottery_application_id for ra in live
                          if ra.lottery_application_id}
    mismatched_apps = []
    if app_ids_with_rooms:
        mismatched_apps = (session.query(LotteryApplication)
                           .filter(LotteryApplication.id.in_(app_ids_with_rooms))
                           .filter(LotteryApplication.status != c.AWARDED)
                           .filter(LotteryApplication.status != c.PROCESSED)
                           .all())
    awarded_apps = (session.query(LotteryApplication)
                    .filter(LotteryApplication.status == c.AWARDED).all())

    ci_start = c.HOTEL_LOTTERY_CHECKIN_START.date() if c.HOTEL_LOTTERY_CHECKIN_START else None
    co_end = c.HOTEL_LOTTERY_CHECKOUT_END.date() if c.HOTEL_LOTTERY_CHECKOUT_END else None

    # Physical-room catalog: rooms by id, and live assignments grouped by
    # physical room for the double-booking scan.
    from uber.models.hotel import PhysicalRoom
    physical_rooms = {r.id: r for r in session.query(PhysicalRoom).all()}
    live_by_physical = defaultdict(list)
    for ra in live:
        if ra.physical_room_id:
            live_by_physical[ra.physical_room_id].append(ra)

    return {
        'session': session,
        'live': live,
        'by_id': by_id,
        'children_of': children_of,
        'room_type_parents': room_type_parents,
        'room_type_children_needed': room_type_children_needed,
        'all_types_by_id': all_types_by_id,
        'all_inventory': all_inventory,
        'partition_blocks_by_inv': partition_blocks_by_inv,
        'live_by_inv': live_by_inv,
        'app_ids_with_rooms': app_ids_with_rooms,
        'mismatched_apps': mismatched_apps,
        'awarded_apps': awarded_apps,
        'ci_start': ci_start,
        'co_end': co_end,
        'physical_rooms': physical_rooms,
        'live_by_physical': live_by_physical,
    }


def _fix_url_for(ra):
    app_id = ra.lottery_application_id
    return f'form?id={app_id}' if app_id else None


def check_orphan_connectors(ctx):
    """orphan_connector: connector's parent_assignment_id doesn't resolve
    to a live assignment for the same attendee (or the parent's room type
    no longer requires this connector)."""
    issues = []
    by_id = ctx['by_id']
    room_type_parents = ctx['room_type_parents']
    for ra in ctx['live']:
        if not ra.parent_assignment_id:
            continue
        fix = _fix_url_for(ra)
        parent = by_id.get(ra.parent_assignment_id)
        if not parent or parent.attendee_id != ra.attendee_id:
            issues.append(_room_issue(
                'error', 'orphan_connector',
                "Connector room without a matching parent suite "
                "assigned to the same attendee.",
                ra, fix))
        elif not parent.is_live:
            issues.append(_room_issue(
                'error', 'orphan_connector',
                f"Connector's parent suite is in status "
                f"{parent.status_label}, not live.",
                ra, fix))
        else:
            # Parent exists and is live - but does it actually
            # require a connector of THIS type? If an admin edited
            # the parent's inventory to a different room type, the
            # connector is now hanging off something that doesn't
            # need it.
            child_inv = ra.inventory
            child_type_id = (child_inv.room_type_id
                             or child_inv.suite_type_id) if child_inv else None
            parent_inv = parent.inventory
            parent_type_id = (parent_inv.room_type_id
                              or parent_inv.suite_type_id) if parent_inv else None
            expected_parent_type_id = None
            if child_type_id and child_type_id in room_type_parents:
                expected_parent_type_id = room_type_parents[child_type_id][0]
            if not expected_parent_type_id:
                # This child's room type isn't configured as a
                # connector at all anymore - somebody removed the
                # `connects_to_type_id` mapping after the room
                # was awarded.
                issues.append(_room_issue(
                    'error', 'orphan_connector',
                    "Connector's room type is no longer "
                    "configured to follow any parent.",
                    ra, fix))
            elif expected_parent_type_id != parent_type_id:
                issues.append(_room_issue(
                    'error', 'orphan_connector',
                    "Connector's parent assignment is no longer "
                    "the correct room type to require this "
                    "connector.",
                    ra, fix))
    return issues


def check_assignment_dates(ctx):
    """missing_dates / inverted_dates / too_short / out_of_range."""
    issues = []
    ci_start = ctx['ci_start']
    co_end = ctx['co_end']
    for ra in ctx['live']:
        fix = _fix_url_for(ra)
        if not ra.assigned_check_in_date or not ra.assigned_check_out_date:
            issues.append(_room_issue(
                'error', 'missing_dates',
                "Assignment is missing check-in and/or check-out date.",
                ra, fix))
        else:
            if ra.assigned_check_in_date >= ra.assigned_check_out_date:
                issues.append(_room_issue(
                    'error', 'inverted_dates',
                    "Check-out date is on or before the check-in date.",
                    ra, fix))
            else:
                nights = (ra.assigned_check_out_date
                          - ra.assigned_check_in_date).days
                if nights < 1:
                    issues.append(_room_issue(
                        'error', 'too_short',
                        "Stay is less than one night long.",
                        ra, fix))
            if ci_start and ra.assigned_check_in_date < ci_start:
                issues.append(_room_issue(
                    'warning', 'out_of_range',
                    f"Check-in {ra.assigned_check_in_date} is before "
                    f"the event window opens ({ci_start}).",
                    ra, fix))
            if co_end and ra.assigned_check_out_date > co_end:
                issues.append(_room_issue(
                    'warning', 'out_of_range',
                    f"Check-out {ra.assigned_check_out_date} is after "
                    f"the event window closes ({co_end}).",
                    ra, fix))
    return issues


def check_occupancy(ctx):
    """empty_room / over_capacity / under_capacity.

    Occupants vs inventory capacity. The booker (attendee_id) is ALWAYS
    implicitly an occupant - they're the name on the reservation - even
    when the room_assignment_occupant M2M row is missing (the
    ensure_booker_is_occupant presave keeps it in sync, but
    older/imported rows may lack it). Fold the booker into the set so a
    room with a booker is never flagged "empty", and the booker still
    counts toward capacity.
    """
    issues = []
    for ra in ctx['live']:
        inv = ra.inventory
        if not inv:
            continue
        fix = _fix_url_for(ra)
        occupant_ids = {o.id for o in (getattr(ra, 'occupants', None) or [])}
        if ra.attendee_id:
            occupant_ids.add(ra.attendee_id)
        occupant_count = len(occupant_ids)
        cap = inv.capacity or 0
        min_cap = inv.min_capacity or 0
        if occupant_count == 0:
            issues.append(_room_issue(
                'error', 'empty_room',
                "No occupants assigned - the hotel needs a name "
                "on the reservation.",
                ra, fix))
        elif cap and occupant_count > cap:
            issues.append(_room_issue(
                'error', 'over_capacity',
                f"{occupant_count} occupants in a room with "
                f"capacity {cap}.",
                ra, fix))
        elif min_cap and occupant_count < min_cap:
            issues.append(_room_issue(
                'warning', 'under_capacity',
                f"{occupant_count} occupants in a room with "
                f"minimum {min_cap}.",
                ra, fix))
    return issues


def check_secured_without_payment(ctx):
    """secured_without_payment: status flipped to SECURED on a self-pay
    room but no CC vault token was ever captured. The secure flow
    normally requires the token before flipping, so this means the row
    was edited around the flow (admin override, imported state, etc.).
    Master-bill rooms (require_cc=False) are exempt - they have no
    payment info by design."""
    issues = []
    for ra in ctx['live']:
        if ra.status == c.SECURED and ra.require_cc and not ra.cc_token:
            issues.append(_room_issue(
                'error', 'secured_without_payment',
                "Room is marked Secured but has no credit card on "
                "file - the hotel will treat the reservation as "
                "unguaranteed.",
                ra, _fix_url_for(ra)))
    return issues


def check_childless_parents(ctx):
    """childless_parent: for each live primary whose room type is a
    connector parent, tally the live children by type and warn when any
    required type is short."""
    issues = []
    children_of = ctx['children_of']
    room_type_children_needed = ctx['room_type_children_needed']
    for parent_ra in ctx['live']:
        if parent_ra.parent_assignment_id:
            continue  # only check primaries
        inv = parent_ra.inventory
        if not inv:
            continue
        parent_type_id = inv.room_type_id or inv.suite_type_id
        specs = room_type_children_needed.get(parent_type_id, [])
        if not specs:
            continue
        kids_by_type = defaultdict(int)
        for child in children_of.get(parent_ra.id, []):
            ci = child.inventory
            if ci:
                kt = ci.room_type_id or ci.suite_type_id
                kids_by_type[kt] += 1
        for child_type_id, needed_qty, child_type_name in specs:
            got = kids_by_type.get(child_type_id, 0)
            if got < needed_qty:
                fix = f'form?id={parent_ra.lottery_application_id}' if parent_ra.lottery_application_id else None
                issues.append(_room_issue(
                    'error', 'childless_parent',
                    f"Suite is missing required connector "
                    f"'{child_type_name}': has {got}, needs "
                    f"{needed_qty}.",
                    parent_ra, fix))
    return issues


def check_status_mismatch(ctx):
    """status_mismatch: app.status doesn't match its rooms (e.g. has
    rooms but status==COMPLETE; no rooms but status==AWARDED). Caught by
    the model listener under normal use; this is the audit backstop."""
    issues = []
    for app in ctx['mismatched_apps']:
        issues.append(_room_issue(
            'warning', 'status_mismatch',
            f"Application has live rooms but status is "
            f"{app.status_label}.",
            None,
            fix_url=f'form?id={app.id}',
            extra={'application': app}))

    # Apps marked AWARDED with zero live rooms - same story, other side.
    app_ids_with_rooms = ctx['app_ids_with_rooms']
    for app in ctx['awarded_apps']:
        if app.id not in app_ids_with_rooms:
            issues.append(_room_issue(
                'warning', 'status_mismatch',
                "Application is marked AWARDED but has no live rooms.",
                None,
                fix_url=f'form?id={app.id}',
                extra={'application': app}))
    return issues


def check_double_booked(ctx):
    """double_booked: an attendee listed as occupant of two assignments
    whose dates overlap. We check across `occupants` (the M2M), not
    `attendee_id` - the booker can hold many rooms intentionally, but an
    occupant can't be in two rooms on the same night."""
    issues = []
    occupant_rooms = defaultdict(list)
    for ra in ctx['live']:
        if not ra.assigned_check_in_date or not ra.assigned_check_out_date:
            continue
        for occ in (getattr(ra, 'occupants', None) or []):
            occupant_rooms[occ.id].append(ra)
    for occ_id, ras in occupant_rooms.items():
        if len(ras) < 2:
            continue
        # Pairwise overlap check (n is small in practice).
        for i, a in enumerate(ras):
            for b in ras[i+1:]:
                if (a.assigned_check_in_date < b.assigned_check_out_date
                        and b.assigned_check_in_date < a.assigned_check_out_date):
                    # Connector + its own parent overlapping doesn't count
                    # - the connector is part of the same block.
                    if (a.parent_assignment_id == b.id
                            or b.parent_assignment_id == a.id):
                        continue
                    fix = f'form?id={a.lottery_application_id}' if a.lottery_application_id else None
                    issues.append(_room_issue(
                        'warning', 'double_booked',
                        f"Occupant is on two overlapping rooms "
                        f"({a.assigned_check_in_date}->"
                        f"{a.assigned_check_out_date} and "
                        f"{b.assigned_check_in_date}->"
                        f"{b.assigned_check_out_date}).",
                        a, fix,
                        extra={'other_assignment': b}))
    return issues


def check_inventory_blocks(ctx):
    """Per-inventory configuration and capacity checks: zero_quantity,
    inactive_parent, type_mismatch, partition_overallocated,
    oversubscribed_inventory, partition_unconfigured, and
    oversubscribed_partition."""
    session = ctx['session']
    partition_blocks_by_inv = ctx['partition_blocks_by_inv']
    live_by_inv = ctx['live_by_inv']
    inv_issues = []

    for inv in ctx['all_inventory']:
        inv_id = str(inv.id)
        ras = live_by_inv.get(inv_id, [])
        fix = f'edit_inventory_item?id={inv.id}'

        # Static config sanity:
        #   - active inventory at quantity 0 = mistake
        #   - active inventory whose hotel/type is inactive = stranded
        if inv.quantity == 0:
            inv_issues.append(_inv_issue(
                'warning', 'zero_quantity',
                "Active inventory configured with quantity zero - "
                "either deactivate it or set a non-zero quantity.",
                inventory=inv, fix_url=fix))
        if inv.hotel and not inv.hotel.active:
            inv_issues.append(_inv_issue(
                'warning', 'inactive_parent',
                f"Inventory points at inactive hotel "
                f"'{inv.hotel.name}'.",
                inventory=inv, fix_url=fix))
        rt = inv.suite_type if inv.is_suite else inv.room_type
        if rt and not rt.active:
            inv_issues.append(_inv_issue(
                'warning', 'inactive_parent',
                f"Inventory points at inactive room type "
                f"'{rt.name}'.",
                inventory=inv, fix_url=fix))
        if inv.is_suite and not inv.suite_type:
            inv_issues.append(_inv_issue(
                'warning', 'type_mismatch',
                "Inventory is flagged as a suite but has no "
                "suite_type set.",
                inventory=inv, fix_url=fix))
        if not inv.is_suite and not inv.room_type:
            inv_issues.append(_inv_issue(
                'warning', 'type_mismatch',
                "Inventory is flagged as a standard room but has "
                "no room_type set.",
                inventory=inv, fix_url=fix))

        # Partition blocks summing to more than the inventory's cap:
        # a configuration bug, not a runtime overlap.
        blocks = partition_blocks_by_inv.get(inv_id, [])
        partition_total = sum(pb.quantity for pb in blocks)
        if inv.quantity and partition_total > inv.quantity:
            inv_issues.append(_inv_issue(
                'error', 'partition_overallocated',
                f"Partition blocks sum to {partition_total} rooms "
                f"but this inventory only has {inv.quantity}.",
                inventory=inv, fix_url=fix,
                extra={'partition_total': partition_total}))

        # Night-level oversubscription: walk every night in the
        # event window covered by an assignment and tally occupancy
        # vs. inv.quantity_for_night (per-night rows override the flat
        # quantity; an explicit 0 row closes the night).
        if not ras:
            continue
        night_occupancy = defaultdict(int)
        night_partition_occupancy = defaultdict(lambda: defaultdict(int))
        for ra in ras:
            if not ra.assigned_check_in_date or not ra.assigned_check_out_date:
                continue
            d = ra.assigned_check_in_date
            while d < ra.assigned_check_out_date:
                night_occupancy[d] += 1
                if ra.partition_id:
                    night_partition_occupancy[ra.partition_id][d] += 1
                d = d + timedelta(days=1)

        # Inventory-wide oversubscription.
        bad_nights = []
        for night, used in sorted(night_occupancy.items()):
            cap = inv.quantity_for_night(night)
            if used > cap:
                bad_nights.append((night, used, cap))
        if bad_nights:
            inv_issues.append(_inv_issue(
                'error', 'oversubscribed_inventory',
                f"Inventory is oversubscribed on "
                f"{len(bad_nights)} night(s). First: "
                f"{bad_nights[0][0]} ({bad_nights[0][1]} "
                f"assigned vs cap {bad_nights[0][2]}).",
                inventory=inv, fix_url=fix,
                extra={'bad_nights': bad_nights}))

        # Per-partition oversubscription. Each partition block has a
        # carve-out quantity, so an inventory can be fine in aggregate
        # but still exceed a single partition's slice.
        blocks_by_partition = {str(pb.partition_id): pb for pb in blocks}
        for part_id, by_night in night_partition_occupancy.items():
            pb = blocks_by_partition.get(str(part_id))
            if not pb:
                # Live RAs assigned to a partition that has no block
                # on this inventory - also a configuration issue.
                bad_partition = session.query(InventoryPartition).get(part_id)
                part_name = (bad_partition.name
                             if bad_partition else f"id {part_id}")
                inv_issues.append(_inv_issue(
                    'error', 'partition_unconfigured',
                    f"Partition '{part_name}' has live "
                    f"assignments on this inventory but no "
                    f"matching partition block. Add a block "
                    f"(or move the assignments).",
                    inventory=inv,
                    partition=bad_partition,
                    fix_url=(f'edit_partition?id={part_id}'
                             if bad_partition else fix)))
                continue
            bad = []
            for night, used in sorted(by_night.items()):
                cap = pb.quantity
                if used > cap:
                    bad.append((night, used, cap))
            if bad:
                inv_issues.append(_inv_issue(
                    'error', 'oversubscribed_partition',
                    f"Partition '{pb.partition.name}' is "
                    f"oversubscribed on {len(bad)} night(s). "
                    f"First: {bad[0][0]} ({bad[0][1]} "
                    f"assigned vs cap {bad[0][2]}).",
                    inventory=inv, partition=pb.partition,
                    fix_url=fix, extra={'bad_nights': bad}))

    return inv_issues


def check_connector_capacity(ctx):
    """broken_connector_config / insufficient_connectors /
    insufficient_connectors_at_hotel.

    If a room type follows another, the lottery (when it awards a full
    parent inventory) needs enough child inventory to satisfy the
    coupling. Check at two granularities: globally and per-hotel (so an
    Exec Suite that's only offered at hotel X must have its Standard
    King connectors also at hotel X)."""
    session = ctx['session']
    all_types_by_id = ctx['all_types_by_id']
    inv_issues = []

    inv_qty_by_type = defaultdict(int)
    inv_qty_by_hotel_type = defaultdict(lambda: defaultdict(int))
    for inv in ctx['all_inventory']:
        tid = inv.suite_type_id if inv.is_suite else inv.room_type_id
        if not tid:
            continue
        inv_qty_by_type[tid] += inv.quantity or 0
        inv_qty_by_hotel_type[inv.hotel_id][tid] += inv.quantity or 0

    for rt in all_types_by_id.values():
        if not rt.connects_to_type_id or rt.connector_quantity <= 0:
            continue
        parent = all_types_by_id.get(rt.connects_to_type_id)
        if not parent:
            inv_issues.append(_inv_issue(
                'error', 'broken_connector_config',
                f"Room type '{rt.name}' follows a parent that "
                "no longer exists.",
                room_type=rt,
                fix_url=f'edit_room_type?id={rt.id}'))
            continue

        parent_total = inv_qty_by_type.get(parent.id, 0)
        child_total = inv_qty_by_type.get(rt.id, 0)
        needed = parent_total * rt.connector_quantity
        if parent_total > 0 and child_total < needed:
            inv_issues.append(_inv_issue(
                'error', 'insufficient_connectors',
                f"Configured inventory of connector '{rt.name}' "
                f"({child_total}) is below what parent "
                f"'{parent.name}' would need if fully awarded "
                f"({parent_total} x {rt.connector_quantity} = "
                f"{needed}).",
                room_type=rt,
                fix_url=f'edit_room_type?id={rt.id}',
                extra={'parent_total': parent_total,
                       'child_total': child_total,
                       'needed': needed}))

        # Per-hotel: every hotel offering the parent needs the
        # child inventory locally too - connectors are physical
        # neighbors, they can't follow across properties.
        for hotel_id, types_at_hotel in inv_qty_by_hotel_type.items():
            p_here = types_at_hotel.get(parent.id, 0)
            if p_here <= 0:
                continue
            c_here = types_at_hotel.get(rt.id, 0)
            local_needed = p_here * rt.connector_quantity
            if c_here < local_needed:
                hotel = session.query(LotteryHotel).get(hotel_id)
                inv_issues.append(_inv_issue(
                    'error', 'insufficient_connectors_at_hotel',
                    f"Hotel '{hotel.name if hotel else hotel_id}' "
                    f"offers {p_here} '{parent.name}' rooms but "
                    f"only has {c_here} '{rt.name}' connector "
                    f"rooms (needs {local_needed}).",
                    room_type=rt,
                    fix_url=f'edit_room_type?id={rt.id}',
                    extra={'hotel': hotel,
                           'parent_total_here': p_here,
                           'child_total_here': c_here,
                           'needed_here': local_needed}))

    return inv_issues


# The registries the collector iterates. Room checks attach to a
# RoomAssignment (or an application, for status_mismatch); inventory
# checks describe a mismatch between configured inventory and the
# lottery's load (or static configuration mistakes) and are collected
# into a separate list so the template can put them on their own tab.
# Order matters only for display: per-assignment groups list their
# issues in registry order.

def check_physical_double_booked(ctx):
    """physical_double_booked: two live assignments on the same physical
    room with overlapping nights (checkout day exclusive, so back-to-back
    turnover is fine)."""
    issues = []
    for room_id, ras in ctx['live_by_physical'].items():
        if len(ras) < 2:
            continue
        room = ctx['physical_rooms'].get(room_id)
        number = room.room_number if room else '?'
        dated = [ra for ra in ras
                 if ra.assigned_check_in_date and ra.assigned_check_out_date]
        for i, a in enumerate(dated):
            for b in dated[i + 1:]:
                if (a.assigned_check_in_date < b.assigned_check_out_date
                        and b.assigned_check_in_date < a.assigned_check_out_date):
                    issues.append(_room_issue(
                        'error', 'physical_double_booked',
                        f"Physical room {number} is double-booked "
                        f"({a.assigned_check_in_date}->{a.assigned_check_out_date} "
                        f"overlaps {b.assigned_check_in_date}->"
                        f"{b.assigned_check_out_date}).",
                        a, fix_url=_fix_url_for(a)))
    return issues


def check_physical_block_mismatch(ctx):
    """physical_block_mismatch: an assignment whose physical room belongs
    to a different inventory block than the assignment itself - the guest
    would get a different room category than they were awarded."""
    issues = []
    for ra in ctx['live']:
        if not ra.physical_room_id:
            continue
        room = ctx['physical_rooms'].get(ra.physical_room_id)
        if room and room.inventory_id and ra.inventory_id \
                and room.inventory_id != ra.inventory_id:
            issues.append(_room_issue(
                'warning', 'physical_block_mismatch',
                f"Physical room {room.room_number} is in a different "
                f"inventory block than this booking.",
                ra, fix_url=_fix_url_for(ra)))
    return issues


def check_physical_catalog_counts(ctx):
    """catalog_count_mismatch: for blocks that HAVE a physical-room
    catalog, the in-service room count differs from the block quantity.
    Quantities are deliberately independent of the catalog - this is an
    advisory warning, not an enforcement."""
    issues = []
    per_block = defaultdict(int)
    for room in ctx['physical_rooms'].values():
        if room.inventory_id and not room.out_of_service:
            per_block[room.inventory_id] += 1
    for inv in ctx['all_inventory']:
        count = per_block.get(inv.id)
        if count is not None and count != inv.quantity:
            issues.append(_inv_issue(
                'warning', 'catalog_count_mismatch',
                f"Block quantity is {inv.quantity} but the physical-room "
                f"catalog has {count} in-service room(s).",
                inventory=inv,
                fix_url=f'physical_rooms?hotel_id={inv.hotel_id}'))
    return issues


def check_physical_room_wrong_hotel(ctx):
    """physical_room_wrong_hotel: a physical room categorized into an
    inventory block that belongs to a different hotel."""
    issues = []
    inv_by_id = {inv.id: inv for inv in ctx['all_inventory']}
    for room in ctx['physical_rooms'].values():
        inv = inv_by_id.get(room.inventory_id) if room.inventory_id else None
        if inv and inv.hotel_id and inv.hotel_id != room.hotel_id:
            issues.append(_inv_issue(
                'error', 'physical_room_wrong_hotel',
                f"Physical room {room.room_number} belongs to a block at a "
                f"different hotel.",
                inventory=inv,
                fix_url=f'edit_physical_room?id={room.id}'))
    return issues


ROOM_CHECKS = [
    check_orphan_connectors,
    check_assignment_dates,
    check_occupancy,
    check_secured_without_payment,
    check_childless_parents,
    check_status_mismatch,
    check_double_booked,
    check_physical_double_booked,
    check_physical_block_mismatch,
]

INVENTORY_CHECKS = [
    check_inventory_blocks,
    check_connector_capacity,
    check_physical_catalog_counts,
    check_physical_room_wrong_hotel,
]


def collect_issues(session):
    """Run every registered check. Returns (room_issues, inv_issues)."""
    ctx = build_audit_context(session)
    issues = []
    for check in ROOM_CHECKS:
        issues.extend(check(ctx))
    inv_issues = []
    for check in INVENTORY_CHECKS:
        inv_issues.extend(check(ctx))
    return issues, inv_issues


def load_issue_notes(session):
    """Admin hide-flags + notes, keyed by each issue's stable identity
    (kind, target_type, target_id)."""
    return {
        (n.issue_kind, n.target_type, n.target_id): n
        for n in session.query(HotelRoomIssueNote).all()
    }


def issue_identity(iss):
    """The stable (target_type, target_id) identity for an issue dict,
    used to key HotelRoomIssueNote rows across recomputes."""
    ra = iss.get('assignment')
    inv = iss.get('inventory')
    rt = iss.get('room_type')
    part = iss.get('partition')
    extra_app = (iss.get('extra') or {}).get('application')
    if ra is not None:
        return ('room_assignment', str(ra.id))
    if inv is not None:
        # Pair inventory + partition for partition-scoped issues so
        # hiding one partition's oversubscription doesn't hide the
        # whole block's.
        tid = str(inv.id)
        if part is not None:
            tid += '|' + str(part.id)
        return ('inventory', tid)
    if rt is not None:
        return ('room_type', str(rt.id))
    if part is not None:
        return ('partition', str(part.id))
    if extra_app is not None:
        return ('lottery_application', str(extra_app.id))
    return ('other', iss.get('kind') or 'unknown')


def annotate_issues(issue_list, notes_by_key):
    """Annotate every issue in place with its stable identity plus its
    note + hidden flag (so the caller can split shown vs hidden)."""
    for iss in issue_list:
        ttype, tid = issue_identity(iss)
        iss['target_type'] = ttype
        iss['target_id'] = tid
        note = notes_by_key.get((iss.get('kind'), ttype, tid))
        iss['note'] = note
        iss['admin_notes'] = note.admin_notes if note else ''
        iss['hidden'] = bool(note and note.hidden)


def issue_haystack(iss):
    """Free-text search matches a lowercase haystack per issue built
    from the human-relevant context (hotel, room type, attendee, conf #,
    partition) plus the issue kind/label, so admins can search by any of
    them."""
    parts = [iss.get('kind') or '', iss.get('label') or '',
             iss.get('severity') or '']
    ra = iss.get('assignment')
    if ra is not None:
        inv = ra.inventory
        if inv:
            parts.append(inv.name or '')
            if inv.hotel:
                parts.append(inv.hotel.name or '')
            rt = inv.suite_type if inv.is_suite else inv.room_type
            if rt:
                parts.append(rt.name or '')
        if ra.attendee:
            parts.append(ra.attendee.full_name or '')
            parts.append(ra.attendee.email or '')
        app = ra.lottery_application
        if app and app.confirmation_num:
            parts.append(app.confirmation_num)
    # Inventory-level issue context.
    inv2 = iss.get('inventory')
    if inv2 is not None:
        parts.append(inv2.name or '')
        if inv2.hotel:
            parts.append(inv2.hotel.name or '')
    rt2 = iss.get('room_type')
    if rt2 is not None:
        parts.append(rt2.name or '')
    part = iss.get('partition')
    if part is not None:
        parts.append(part.name or '')
    # status_mismatch and friends stash the application in extra.
    extra_app = (iss.get('extra') or {}).get('application')
    if extra_app is not None:
        if extra_app.confirmation_num:
            parts.append(extra_app.confirmation_num)
        if extra_app.attendee:
            parts.append(extra_app.attendee.full_name or '')
    return ' '.join(parts).lower()


def filter_issues(issue_list, severity, kind, needle):
    """Apply the report's severity / kind / free-text filters. `needle`
    is the already-lowercased search term ('' for no search)."""
    def _passes(iss):
        if severity in ('error', 'warning') and iss['severity'] != severity:
            return False
        if kind not in ('all', '', None) and iss.get('kind') != kind:
            return False
        if needle and needle not in issue_haystack(iss):
            return False
        return True

    return [i for i in issue_list if _passes(i)]


# Room issues group by RA id (or `app:<id>` for application-level
# issues); inventory issues group by inventory (or room type).
# Each group inherits the worst severity of its issues. The same
# helpers group the shown and hidden lists.
def _group_sort_key(g):
    sev = 0 if g['severity'] == 'error' else 1
    ra = g['assignment']
    hotel_name = (ra.inventory.hotel.name
                  if ra and ra.inventory and ra.inventory.hotel else '~')
    conf = (g['application'].confirmation_num
            if g['application'] else '~')
    return (sev, hotel_name, conf or '~')


def _inv_group_sort_key(g):
    sev = 0 if g['severity'] == 'error' else 1
    inv = g['inventory']
    rt = g['room_type']
    hotel_name = (inv.hotel.name if inv and inv.hotel else '~')
    inv_name = (inv.name if inv else (rt.name if rt else '~'))
    return (sev, hotel_name, inv_name)


def group_room_issues(issue_list):
    by_key = {}
    order = []
    for iss in issue_list:
        ra = iss.get('assignment')
        app = (iss.get('extra') or {}).get('application')
        if ra:
            key = ra.id
            group_app = app or ra.lottery_application
        elif app:
            key = f'app:{app.id}'
            group_app = app
        else:
            key = f'orphaned-issue-{len(order)}'
            group_app = None
        if key not in by_key:
            by_key[key] = {
                'key': key, 'assignment': ra, 'application': group_app,
                'issues': [], 'severity': 'warning',
            }
            order.append(key)
        by_key[key]['issues'].append(iss)
        if iss['severity'] == 'error':
            by_key[key]['severity'] = 'error'
    return sorted([by_key[k] for k in order], key=_group_sort_key)


def group_inventory_issues(issue_list):
    by_key = {}
    order = []
    for iss in issue_list:
        inv = iss.get('inventory')
        rt = iss.get('room_type')
        if inv:
            key = f'inv:{inv.id}'
        elif rt:
            key = f'rt:{rt.id}'
        else:
            key = f'other:{len(order)}'
        if key not in by_key:
            by_key[key] = {
                'key': key, 'inventory': inv, 'room_type': rt,
                'issues': [], 'severity': 'warning',
            }
            order.append(key)
        by_key[key]['issues'].append(iss)
        if iss['severity'] == 'error':
            by_key[key]['severity'] = 'error'
    return sorted([by_key[k] for k in order], key=_inv_group_sort_key)


def get_or_make_issue_note(session, issue_kind, target_type, target_id):
    """Fetch (or create, unsaved) the HotelRoomIssueNote for an
    issue's stable identity. Stamps the acting admin so we know who
    last touched it."""
    from uber.hotel.perms import _current_admin_account
    note = (session.query(HotelRoomIssueNote)
            .filter_by(issue_kind=issue_kind, target_type=target_type,
                       target_id=str(target_id))
            .one_or_none())
    if not note:
        note = HotelRoomIssueNote(
            issue_kind=issue_kind, target_type=target_type,
            target_id=str(target_id))
    admin = _current_admin_account(session)
    if admin:
        note.admin_account_id = admin.id
    return note
