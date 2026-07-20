"""Physical-room catalog and assignment logic for the hotel lottery.

The catalog (PhysicalRoom / PhysicalRoomConnection) maps the real rooms
in a hotel building; RoomAssignment.physical_room_id links a booking to
one. Assignment is optional per hotel - anything without a catalog keeps
working off the free-text room_number. Pure logic lives here; the
hotel_lottery_admin section provides the routes, mirroring the rest of
the uber.hotel package (see the package docstring for the transaction
convention).
"""

from collections import defaultdict

import sqlalchemy as sa

from uber.hotel.queries import vacant_physical_rooms
from uber.models.hotel import (
    PhysicalRoom, PhysicalRoomConnection, RoomAssignment)


def rooms_by_floor(session, hotel_id):
    """[(floor, [PhysicalRoom, ...]), ...] in natural order."""
    rooms = (session.query(PhysicalRoom)
             .filter_by(hotel_id=hotel_id).all())
    floors = defaultdict(list)
    for room in rooms:
        floors[room.floor or ''].append(room)
    out = []
    for floor in sorted(floors, key=lambda f: (f == '', f)):
        out.append((floor, sorted(floors[floor], key=lambda r: r.sort_key)))
    return out


def connection_map(session, hotel_id):
    """{room_id: [connected room_number, ...]} for one hotel, in bulk."""
    rooms = {r.id: r for r in session.query(PhysicalRoom)
             .filter_by(hotel_id=hotel_id).all()}
    edges = (session.query(PhysicalRoomConnection)
             .filter(PhysicalRoomConnection.room_a_id.in_(rooms))
             .all()) if rooms else []
    out = defaultdict(list)
    for edge in edges:
        a, b = rooms.get(edge.room_a_id), rooms.get(edge.room_b_id)
        if a and b:
            out[a.id].append(b.room_number)
            out[b.id].append(a.room_number)
    return {k: sorted(v) for k, v in out.items()}


def live_bookings_by_room(session, hotel_id):
    """{physical_room_id: [live RoomAssignment, ...]} for one hotel."""
    room_ids = [r.id for r in session.query(PhysicalRoom.id)
                .filter_by(hotel_id=hotel_id).all()]
    if not room_ids:
        return {}
    out = defaultdict(list)
    for ra in session.query(RoomAssignment).filter(
            RoomAssignment.physical_room_id.in_(room_ids),
            RoomAssignment.is_live).all():
        out[ra.physical_room_id].append(ra)
    return out


def set_connections(session, room, numbers):
    """Replace `room`'s connection edges with the given room numbers
    (same hotel). Returns an error message, or None on success."""
    numbers = [n.strip() for n in numbers if n.strip()]
    targets = []
    for number in numbers:
        target = session.query(PhysicalRoom).filter_by(
            hotel_id=room.hotel_id, room_number=number).first()
        if not target:
            return f'No room numbered "{number}" exists at this hotel.'
        if target.id == room.id:
            return 'A room cannot connect to itself.'
        targets.append(target)

    for edge in session.query(PhysicalRoomConnection).filter(sa.or_(
            PhysicalRoomConnection.room_a_id == room.id,
            PhysicalRoomConnection.room_b_id == room.id)).all():
        session.delete(edge)
    session.flush()
    seen = set()
    for target in targets:
        pair = tuple(sorted([str(room.id), str(target.id)]))
        if pair in seen:
            continue
        seen.add(pair)
        # Normalized ordering matches the model presave, and we dodge
        # duplicating an edge the target already declared.
        existing = session.query(PhysicalRoomConnection).filter_by(
            room_a_id=pair[0], room_b_id=pair[1]).first()
        if not existing:
            session.add(PhysicalRoomConnection(
                room_a_id=pair[0], room_b_id=pair[1]))
    return None


def bulk_add_rooms(session, hotel_id, floor, start, end,
                   prefix='', pad=0, inventory_id=None):
    """Create rooms prefix+NNN for NNN in [start, end], skipping numbers
    that already exist. Returns (created, skipped)."""
    existing = {r.room_number for r in session.query(PhysicalRoom)
                .filter_by(hotel_id=hotel_id).all()}
    created = skipped = 0
    for n in range(start, end + 1):
        number = f'{prefix}{str(n).zfill(pad)}'
        if number in existing:
            skipped += 1
            continue
        session.add(PhysicalRoom(
            hotel_id=hotel_id, inventory_id=inventory_id or None,
            room_number=number, floor=floor or ''))
        created += 1
    return created, skipped


def import_rows(session, hotel, blocks, rows, apply_changes=False):
    """Preview/apply a spreadsheet of physical rooms for one hotel.

    Expected (normalized) columns: room_number required; floor, type,
    ada, connects_to, notes optional. `type` matches a block by block
    name or by room/suite type name, case-insensitively; unmatched
    types import as uncategorized. Keyed by room_number, so re-imports
    update in place. Connection edges are resolved after all rows exist
    and REPLACE each mentioned room's edges.
    """
    by_type_name = {}
    for block in blocks:
        by_type_name[(block.name or '').strip().lower()] = block
        rst = block.room_or_suite_type
        if rst:
            by_type_name.setdefault((rst.name or '').strip().lower(), block)

    existing = {r.room_number: r for r in session.query(PhysicalRoom)
                .filter_by(hotel_id=hotel.id).all()}

    # Key names avoid dict-method collisions (Jinja's attribute lookup
    # would find dict.update before the item).
    preview = {'created': [], 'updated': [], 'uncategorized': [],
               'errors': [], 'connections': 0}
    parsed = []
    seen = set()
    for idx, row in enumerate(rows, start=2):
        number = (row.get('room_number') or '').strip()
        if not number:
            preview['errors'].append(f'Row {idx}: missing room_number.')
            continue
        if number in seen:
            preview['errors'].append(f'Row {idx}: duplicate room_number {number}.')
            continue
        seen.add(number)
        type_raw = (row.get('type') or '').strip()
        block = by_type_name.get(type_raw.lower()) if type_raw else None
        if type_raw and not block:
            preview['uncategorized'].append(number)
        connects = [n.strip() for n in (row.get('connects_to') or '').split(',')
                    if n.strip()]
        parsed.append(dict(
            number=number, floor=(row.get('floor') or '').strip(),
            block=block,
            ada=(row.get('ada') or '').strip().lower() in
                ('1', 'true', 'yes', 'y', 'x'),
            notes=(row.get('notes') or '').strip(),
            connects=connects))
        (preview['updated'] if number in existing
         else preview['created']).append(number)
        preview['connections'] += len(connects)

    # Connection targets must exist after this import.
    known = set(existing) | {p['number'] for p in parsed}
    for p in parsed:
        for target in p['connects']:
            if target not in known:
                preview['errors'].append(
                    f"Room {p['number']} connects to unknown room {target}.")

    if not apply_changes or preview['errors']:
        return preview

    for p in parsed:
        room = existing.get(p['number'])
        if not room:
            room = PhysicalRoom(hotel_id=hotel.id, room_number=p['number'])
            session.add(room)
            existing[p['number']] = room
        room.floor = p['floor']
        room.inventory_id = p['block'].id if p['block'] else None
        room.ada = p['ada']
        room.notes = p['notes']
    session.flush()
    for p in parsed:
        if p['connects']:
            error = set_connections(session, existing[p['number']], p['connects'])
            if error:  # unreachable given the pre-check, but stay safe
                preview['errors'].append(error)
    return preview


def _overlaps(a_ci, a_co, b_ci, b_co):
    # Checkout day is exclusive, so back-to-back turnover is fine.
    return a_ci < b_co and b_ci < a_co


def auto_assign_physical_rooms(session, hotel_id):
    """Greedy pass placing this hotel's unroomed live bookings onto vacant
    physical rooms. Deterministic; only touches bookings with no physical
    room yet, so it's safely re-runnable.

    Order: suite parents with connector children first (they need
    connected room groups, the scarcest resource), then ADA requests,
    then everything else. ADA rooms are held back from non-ADA bookings
    until nothing else fits. Returns a summary dict.
    """
    from uber.models.hotel import HotelRoomInventory

    rooms = (session.query(PhysicalRoom)
             .filter_by(hotel_id=hotel_id, out_of_service=False)
             .filter(PhysicalRoom.inventory_id.isnot(None)).all())
    rooms_by_block = defaultdict(list)
    for room in sorted(rooms, key=lambda r: r.sort_key):
        rooms_by_block[room.inventory_id].append(room)

    edges = set()
    room_ids = {r.id for r in rooms}
    if room_ids:
        for e in session.query(PhysicalRoomConnection).filter(
                PhysicalRoomConnection.room_a_id.in_(room_ids)).all():
            edges.add(frozenset((e.room_a_id, e.room_b_id)))

    def connected(a, b):
        return frozenset((a.id, b.id)) in edges

    # Occupancy intervals per room: existing + what we assign below.
    busy = defaultdict(list)
    for ra in session.query(RoomAssignment).filter(
            RoomAssignment.physical_room_id.isnot(None),
            RoomAssignment.is_live).all():
        if ra.assigned_check_in_date and ra.assigned_check_out_date:
            busy[ra.physical_room_id].append(
                (ra.assigned_check_in_date, ra.assigned_check_out_date))

    def free(room, ci, co):
        return not any(_overlaps(ci, co, b_ci, b_co)
                       for b_ci, b_co in busy[room.id])

    from uber.hotel.queries import live_assignments_for_hotel
    pending = (live_assignments_for_hotel(session, hotel_id).filter(
        RoomAssignment.physical_room_id.is_(None),
        RoomAssignment.assigned_check_in_date.isnot(None),
        RoomAssignment.assigned_check_out_date.isnot(None),
    ).all())
    by_id = {ra.id: ra for ra in pending}
    children_of = defaultdict(list)
    for ra in pending:
        if ra.parent_assignment_id and ra.parent_assignment_id in by_id:
            children_of[ra.parent_assignment_id].append(ra)

    def wants_ada(ra):
        app = ra.lottery_application
        return bool(app and app.wants_ada)

    def take(ra, room):
        ra.physical_room_id = room.id
        session.add(ra)
        busy[room.id].append((ra.assigned_check_in_date,
                              ra.assigned_check_out_date))

    def candidates(ra, prefer_ada):
        opts = [r for r in rooms_by_block.get(ra.inventory_id, [])
                if free(r, ra.assigned_check_in_date,
                        ra.assigned_check_out_date)]
        # Hold ADA rooms back from bookings that don't need them.
        return (sorted(opts, key=lambda r: (not r.ada, r.sort_key))
                if prefer_ada else
                sorted(opts, key=lambda r: (r.ada, r.sort_key)))

    assigned = 0
    skipped = []

    def sort_key(ra):
        return (ra.assigned_check_in_date, str(ra.id))

    # 1. Suite parents with connector children: all-or-nothing groups.
    parents = sorted((ra for ra in pending
                      if children_of.get(ra.id)
                      and not ra.parent_assignment_id), key=sort_key)
    placed_in_group = set()
    for parent in parents:
        kids = children_of[parent.id]
        placed = None
        for suite_room in candidates(parent, wants_ada(parent)):
            neighbors = [r for r in rooms
                         if connected(suite_room, r)
                         and free(r, parent.assigned_check_in_date,
                                  parent.assigned_check_out_date)]
            picks = []
            pool = list(neighbors)
            for kid in kids:
                match = next((r for r in pool
                              if r.inventory_id == kid.inventory_id), None)
                if not match:
                    break
                picks.append((kid, match))
                pool.remove(match)
            if len(picks) == len(kids):
                placed = (suite_room, picks)
                break
        if placed:
            suite_room, picks = placed
            take(parent, suite_room)
            for kid, room in picks:
                take(kid, room)
            assigned += 1 + len(picks)
            placed_in_group.update([parent.id] + [k.id for k, _ in picks])
        else:
            skipped.append((parent, 'no connected room group available'))
            placed_in_group.update([parent.id] + [k.id for k in kids])

    # 2. ADA requests, then 3. everyone else.
    rest = [ra for ra in pending if ra.id not in placed_in_group]
    for ra in (sorted([r for r in rest if wants_ada(r)], key=sort_key)
               + sorted([r for r in rest if not wants_ada(r)], key=sort_key)):
        opts = candidates(ra, wants_ada(ra))
        if opts:
            take(ra, opts[0])
            assigned += 1
        else:
            skipped.append((ra, 'no vacant room in block'))

    session.commit()
    return {'assigned': assigned,
            'skipped': [(ra.id, reason) for ra, reason in skipped]}


def assignable_rooms(session, ra):
    """Vacant physical rooms an admin may pick for one assignment: the
    assignment's block at its hotel, free for its dates, plus whatever
    room is currently linked."""
    inv = ra.inventory
    if not inv or not inv.hotel_id:
        return []
    rooms = vacant_physical_rooms(
        session, inv.hotel_id, ra.assigned_check_in_date,
        ra.assigned_check_out_date, inventory_id=inv.id)
    if ra.physical_room_id and ra.physical_room \
            and ra.physical_room not in rooms:
        rooms = [ra.physical_room] + rooms
    return rooms
