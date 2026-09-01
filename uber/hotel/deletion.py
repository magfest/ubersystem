"""Deleting hotel lottery resources, and resolving what still points at them.

Two facts shape this. Most of the foreign keys involved carry no ondelete, so
Postgres refuses the delete outright and there is no "just delete it" path to
fall back on. And the section already has a retirement idiom: `active=False`,
which every picker and `get_inventory` honors, while the historical record
(LotteryRun filter CSVs, export logs, preference CSVs) refers to these rows by
value rather than by foreign key.

So deactivating is the default action for anything with an `active` column,
and permanent deletion is an escalation reached after every blocking conflict
has been resolved.

Severity:
    blocking  - must reach zero before a permanent delete is allowed
    advisory  - handled automatically by perform_delete, listed so the admin
                knows what they are agreeing to

Transaction convention matches the rest of the package: flush, never commit.
"""

import logging

from uber.config import c

log = logging.getLogger(__name__)

# Items listed per conflict group. A hotel's physical room catalog can run to
# hundreds, and the dialog only needs enough to show what kind of thing is in
# the way.
ITEM_LIMIT = 25


class DeletionError(Exception):
    def __init__(self, message):
        self.message = message


def _label_for_assignment(ra):
    who = ra.attendee.full_name if ra.attendee else 'Unknown guest'
    return f'{who} - {ra.room_summary}'


def _group(category, label, severity, note='', actions=(), items=(),
           item_total=None, reassign_choices=()):
    items = list(items)
    return {
        'category': category,
        'label': label,
        'severity': severity,
        'note': note,
        'actions': list(actions),
        'items': items[:ITEM_LIMIT],
        'item_total': len(items) if item_total is None else item_total,
        'truncated': len(items) > ITEM_LIMIT,
        'reassign_choices': list(reassign_choices),
    }


def _item(id, label, detail='', link=''):
    return {'id': str(id), 'label': label, 'detail': detail, 'link': link}


# ---------------------------------------------------------------------------
# per-resource conflict inspection
# ---------------------------------------------------------------------------

def _inventory_conflicts(session, inv):
    from uber.models.hotel import (InventoryPartitionBlock, PhysicalRoom,
                                   RoomAssignment)
    from uber.hotel.queries import block_availability

    groups = []

    live = session.query(RoomAssignment).filter(
        RoomAssignment.inventory_id == inv.id, RoomAssignment.is_live).all()
    if live:
        # Same hotel and same suite flag only: a suite booking dropped into a
        # room block silently loses its type, and moving a booking to another
        # hotel invalidates any confirmation number already exchanged.
        choices = _inventory_choices(session, inv)
        groups.append(_group(
            'live_assignments', 'Live room assignments', 'blocking',
            note='Move these to another block, or cancel them. There is no '
                 'option to simply unlink them: a room with no block has no '
                 'hotel, type, or price.',
            actions=['reassign', 'cancel'],
            items=[_item(ra.id, _label_for_assignment(ra),
                         detail='waitlisted' if ra.is_waitlisted else '',
                         link=f'edit_room_assignment?id={ra.id}')
                   for ra in live],
            reassign_choices=choices))

    dead = session.query(RoomAssignment).filter(
        RoomAssignment.inventory_id == inv.id, ~RoomAssignment.is_live).count()
    if dead:
        groups.append(_group(
            'dead_assignments', 'Cancelled or expired assignments', 'advisory',
            note='These keep their history but lose the link to this block.',
            item_total=dead))

    blocks = session.query(InventoryPartitionBlock).filter_by(
        inventory_id=inv.id).all()
    if blocks:
        groups.append(_group(
            'partition_blocks', 'Partition allocations', 'advisory',
            note='The partitions lose their allocation of this block.',
            items=[_item(b.id,
                         b.partition.name if b.partition else 'Unknown partition',
                         detail=f'{b.quantity} rooms',
                         link=f'edit_partition?id={b.partition_id}')
                   for b in blocks]))

    rooms = session.query(PhysicalRoom).filter_by(inventory_id=inv.id).all()
    if rooms:
        groups.append(_group(
            'physical_rooms', 'Catalogued physical rooms', 'advisory',
            note='These rooms stay in the catalog but become uncategorized.',
            items=[_item(r.id, f'Room {r.room_number}', link='physical_rooms')
                   for r in rooms]))

    return groups


def _inventory_choices(session, inv):
    """Blocks a booking in `inv` may be moved to, with a capacity warning."""
    from uber.models.hotel import HotelRoomInventory
    from uber.hotel.queries import block_availability

    candidates = session.query(HotelRoomInventory).filter(
        HotelRoomInventory.id != inv.id,
        HotelRoomInventory.hotel_id == inv.hotel_id,
        HotelRoomInventory.is_suite == inv.is_suite,
        HotelRoomInventory.active == True).all()  # noqa: E712
    if not candidates:
        return []

    avail, _partitions = block_availability(session, candidates)
    choices = []
    for block in candidates:
        open_rooms = (avail.get(str(block.id)) or {}).get('', 0)
        choices.append({
            'id': str(block.id),
            'label': block.display_name,
            # Not a hard block: an emergency move should not be forbidden by
            # an audit rule, but the admin should see the cost.
            'warning': '' if open_rooms > 0 else 'no rooms free',
        })
    return choices


def _room_type_conflicts(session, room_type):
    from uber.models.hotel import HotelRoomInventory, LotteryRoomType
    from uber.models import LotteryApplication

    groups = []
    fk = (HotelRoomInventory.suite_type_id if room_type.is_suite
          else HotelRoomInventory.room_type_id)

    active_blocks = session.query(HotelRoomInventory).filter(
        fk == room_type.id, HotelRoomInventory.active == True).all()  # noqa: E712
    if active_blocks:
        groups.append(_group(
            'active_blocks', 'Active inventory using this type', 'blocking',
            note='A block with no type is a broken block: it has no display '
                 'name and fails the room issues report.',
            actions=['reassign', 'clear'],
            items=[_item(b.id, b.display_name,
                         link=f'edit_inventory_item?id={b.id}')
                   for b in active_blocks],
            reassign_choices=_room_type_choices(session, room_type)))

    inactive_blocks = session.query(HotelRoomInventory).filter(
        fk == room_type.id, HotelRoomInventory.active == False).count()  # noqa: E712
    if inactive_blocks:
        groups.append(_group(
            'inactive_blocks', 'Inactive inventory using this type', 'advisory',
            note='These are already retired, so they simply lose the type.',
            item_total=inactive_blocks))

    children = session.query(LotteryRoomType).filter(
        LotteryRoomType.connects_to_type_id == room_type.id).all()
    if children:
        groups.append(_group(
            'connector_children', 'Connector types pointing at this one', 'blocking',
            note='A connector whose parent is gone breaks the connector '
                 'configuration check.',
            actions=['reassign', 'clear'],
            items=[_item(rt.id, rt.name, link=f'edit_room_type?id={rt.id}')
                   for rt in children],
            reassign_choices=_room_type_choices(session, room_type)))

    field = (LotteryApplication.suite_type_preference if room_type.is_suite
             else LotteryApplication.room_type_preference)
    referencing = [app for app in session.query(LotteryApplication).filter(
        field.contains(str(room_type.id))).all()]
    if referencing:
        # Stripping rather than blocking: retiring a type mid-lottery is
        # routine, and requiring hand-edits across every entry would mean
        # types simply never get retired. The solver reads the raw CSV, so a
        # stale id makes an entry look servable when it is not.
        emptied = [app for app in referencing
                   if _preference_after_removal(app, room_type) == '']
        groups.append(_group(
            'preferences', 'Entries ranking this type', 'advisory',
            note='The type is removed from their rankings, keeping the order '
                 'of the rest.',
            items=[_item(app.id, app.attendee.full_name if app.attendee
                         else 'Unknown entrant',
                         link=f'form?id={app.id}')
                   for app in referencing]))
        if emptied:
            groups.append(_group(
                'emptied_preferences', 'Entries left with no ranked types',
                'advisory',
                note='These entries will have nothing ranked and cannot win a '
                     'room until they pick something else.',
                items=[_item(app.id, app.attendee.full_name if app.attendee
                             else 'Unknown entrant',
                             link=f'form?id={app.id}')
                       for app in emptied]))

    return groups


def _preference_after_removal(app, room_type):
    field = ('suite_type_preference' if room_type.is_suite
             else 'room_type_preference')
    current = (getattr(app, field) or '').split(',')
    return ','.join([t for t in current if t and t != str(room_type.id)])


def _room_type_choices(session, room_type):
    from uber.models.hotel import LotteryRoomType
    return [{'id': str(rt.id), 'label': rt.name, 'warning': ''}
            for rt in session.query(LotteryRoomType).filter(
                LotteryRoomType.id != room_type.id,
                LotteryRoomType.is_suite == room_type.is_suite,
                LotteryRoomType.active == True).all()]  # noqa: E712


def _hotel_conflicts(session, hotel):
    from uber.models.hotel import (HotelExportLog, HotelImportFile,
                                   HotelRoomInventory, LotteryHotel,
                                   PhysicalRoom)
    from uber.models import LotteryApplication

    groups = []
    choices = [{'id': str(h.id), 'label': h.name, 'warning': ''}
               for h in session.query(LotteryHotel).filter(
                   LotteryHotel.id != hotel.id,
                   LotteryHotel.active == True).all()]  # noqa: E712

    blocks = session.query(HotelRoomInventory).filter_by(hotel_id=hotel.id).all()
    if blocks:
        groups.append(_group(
            'inventory', 'Inventory blocks at this hotel', 'blocking',
            note='A block with no hotel is broken inventory: the export and '
                 'every price lookup assume it has one.',
            actions=['reassign'],
            items=[_item(b.id, b.display_name,
                         link=f'edit_inventory_item?id={b.id}')
                   for b in blocks],
            reassign_choices=choices))

    rooms = session.query(PhysicalRoom).filter_by(hotel_id=hotel.id).all()
    if rooms:
        # The FK cascades, so deleting the hotel would silently destroy the
        # imported catalog and its connection edges. That is exactly what a
        # confirmation dialog is for, so it blocks until acknowledged.
        groups.append(_group(
            'physical_rooms', 'Catalogued physical rooms', 'blocking',
            note='Moving them to another hotel keeps the catalog. Deleting '
                 'them discards the imported floor map data as well.',
            actions=['reassign', 'delete_all'],
            items=[_item(r.id, f'Room {r.room_number}', link='physical_rooms')
                   for r in rooms],
            reassign_choices=choices))

    referencing = session.query(LotteryApplication).filter(
        LotteryApplication.hotel_preference.contains(str(hotel.id))).all()
    if referencing:
        emptied = [app for app in referencing
                   if ','.join([h for h in (app.hotel_preference or '').split(',')
                                if h and h != str(hotel.id)]) == '']
        groups.append(_group(
            'preferences', 'Entries ranking this hotel', 'advisory',
            note='The hotel is removed from their rankings.',
            items=[_item(app.id, app.attendee.full_name if app.attendee
                         else 'Unknown entrant',
                         link=f'form?id={app.id}')
                   for app in referencing]))
        if emptied:
            groups.append(_group(
                'emptied_preferences', 'Entries left with no ranked hotels',
                'advisory',
                note='These entries cannot win a room until they pick another '
                     'hotel.',
                items=[_item(app.id, app.attendee.full_name if app.attendee
                             else 'Unknown entrant',
                             link=f'form?id={app.id}')
                       for app in emptied]))

    logs = session.query(HotelExportLog).filter_by(hotel_id=hotel.id).count()
    imports = session.query(HotelImportFile).filter_by(hotel_id=hotel.id).count()
    if logs or imports:
        groups.append(_group(
            'files', 'Retained export and import files', 'advisory',
            note='These keep the exact bytes exchanged with the hotel, so the '
                 'records are kept and only the hotel link is cleared.',
            item_total=logs + imports))

    if hotel.map_yaml or hotel.map_svg:
        groups.append(_group(
            'floor_map', 'Floor map', 'advisory',
            note='The uploaded map is deleted along with the hotel. It and '
                 'the physical room catalog come from the same upload.',
            item_total=1))

    return groups


def _partition_conflicts(session, partition):
    from uber.models.hotel import (PartitionAuditLog, PartitionOwner,
                                   RoomAssignment, InventoryPartition)
    from uber.models import LotteryApplication

    groups = []
    choices = [{'id': str(p.id), 'label': p.name, 'warning': ''}
               for p in session.query(InventoryPartition).filter(
                   InventoryPartition.id != partition.id,
                   InventoryPartition.active == True).all()]  # noqa: E712

    live = session.query(RoomAssignment).filter(
        RoomAssignment.partition_id == partition.id, RoomAssignment.is_live).all()
    if live:
        groups.append(_group(
            'live_assignments', 'Live room assignments', 'blocking',
            note='Clearing returns a room to the general pool, which is a '
                 'normal state; the partition owners simply stop seeing it.',
            actions=['clear', 'reassign'],
            items=[_item(ra.id, _label_for_assignment(ra),
                         link=f'edit_room_assignment?id={ra.id}')
                   for ra in live],
            reassign_choices=choices))

    owners = session.query(PartitionOwner).filter_by(partition_id=partition.id).count()
    blocks = len(partition.blocks or [])
    if owners or blocks:
        groups.append(_group(
            'grants_and_blocks', 'Owner grants and block allocations', 'advisory',
            note='Deleted with the partition.',
            item_total=owners + blocks))

    apps = session.query(LotteryApplication).filter_by(
        partition_id=partition.id).count()
    if apps:
        groups.append(_group(
            'applications', 'Entries pinned to this partition', 'advisory',
            note='They lose the pin and return to the general pool.',
            item_total=apps))

    audit = session.query(PartitionAuditLog).filter_by(
        partition_id=partition.id).count()
    if audit:
        groups.append(_group(
            'audit_log', 'Audit history', 'advisory',
            note='Entries are kept and stamped with this partition\'s name, so '
                 'the record of what was done here survives the delete.',
            item_total=audit))

    return groups


def _waitlist_reveal_conflicts(session, reveal):
    from uber.models.hotel import WaitlistRevealLink

    groups = []
    emailed = session.query(WaitlistRevealLink).filter(
        WaitlistRevealLink.waitlist_reveal_id == reveal.id,
        WaitlistRevealLink.emailed_at.isnot(None)).count()
    unsent = session.query(WaitlistRevealLink).filter(
        WaitlistRevealLink.waitlist_reveal_id == reveal.id,
        WaitlistRevealLink.emailed_at.is_(None)).count()

    if emailed:
        # Those URLs are in inboxes. Deleting makes every one fail the token
        # lookup and render the deliberately uninformative expired page, with
        # nothing for support to look up. Deactivating looks the same to the
        # attendee while keeping the rows.
        groups.append(_group(
            'emailed_links', 'Links already emailed', 'blocking',
            note='Deactivating stops the reveal without breaking these links. '
                 'Deleting makes them fail with no explanation to the '
                 'attendee and no record for support.',
            actions=['acknowledge'],
            item_total=emailed))
    if unsent:
        groups.append(_group(
            'unsent_links', 'Links generated but not emailed', 'advisory',
            note='Deleted with the reveal.',
            item_total=unsent))
    return groups


RESOURCE_SPECS = {
    'inventory': {
        'model': 'HotelRoomInventory',
        'title': 'inventory block',
        'list_page': 'manage_inventory',
        'soft_delete': True,
        'conflicts': _inventory_conflicts,
        'soft_delete_note': 'Deactivating hides the block everywhere but stops '
                            'the room issues report from auditing rooms still '
                            'in it.',
    },
    'room_type': {
        'model': 'LotteryRoomType',
        'title': 'room type',
        'list_page': 'manage_room_types',
        'soft_delete': True,
        'conflicts': _room_type_conflicts,
    },
    'hotel': {
        'model': 'LotteryHotel',
        'title': 'hotel',
        'list_page': 'manage_hotels',
        'soft_delete': True,
        'conflicts': _hotel_conflicts,
    },
    'partition': {
        'model': 'InventoryPartition',
        'title': 'partition',
        'list_page': 'manage_partitions',
        'soft_delete': True,
        'conflicts': _partition_conflicts,
    },
    'waitlist_reveal': {
        'model': 'WaitlistReveal',
        'title': 'waitlist reveal',
        'list_page': 'waitlist_reveals',
        'soft_delete': True,
        'conflicts': _waitlist_reveal_conflicts,
    },
}


def _resolve(session, kind, obj_id):
    from uber.models import hotel as hotel_models

    spec = RESOURCE_SPECS.get(kind)
    if not spec:
        raise DeletionError(f'Unknown resource type: {kind}')
    model = getattr(hotel_models, spec['model'])
    obj = session.query(model).filter_by(id=obj_id).first()
    if not obj:
        raise DeletionError(f'That {spec["title"]} no longer exists.')
    return spec, obj


def _display_name(obj):
    return getattr(obj, 'name', None) or getattr(obj, 'display_name', None) or 'this item'


def inspect_conflicts(session, kind, obj_id):
    """(obj, spec, groups) describing everything that still points at this
    resource."""
    spec, obj = _resolve(session, kind, obj_id)
    return obj, spec, spec['conflicts'](session, obj)


def has_blocking(groups):
    return any(g['severity'] == 'blocking' for g in groups)


# ---------------------------------------------------------------------------
# resolving one conflict
# ---------------------------------------------------------------------------

def resolve_conflict(session, kind, obj_id, category, action, item_id='',
                     target_id=''):
    """Apply one resolution and return a message.

    The action and target are validated against what the group actually
    offered, so a hand-built POST cannot reassign to an arbitrary row.
    """
    obj, spec, groups = inspect_conflicts(session, kind, obj_id)
    group = next((g for g in groups if g['category'] == category), None)
    if not group:
        raise DeletionError('That conflict is already resolved.')
    if action not in group['actions']:
        raise DeletionError(f'Cannot {action} these items.')
    if action == 'reassign':
        allowed = {choice['id'] for choice in group['reassign_choices']}
        if target_id not in allowed:
            raise DeletionError('Pick a valid destination.')

    handler = _RESOLVERS.get((kind, category))
    if not handler:
        raise DeletionError('That conflict cannot be resolved automatically.')
    return handler(session, obj, action, item_id, target_id)


def _resolve_assignments(session, obj, action, item_id, target_id, field):
    """Shared resolver for the assignment groups: move to another parent,
    unlink, or cancel."""
    from uber.models.hotel import RoomAssignment

    targets = session.query(RoomAssignment).filter(
        getattr(RoomAssignment, field) == obj.id, RoomAssignment.is_live)
    if item_id:
        targets = targets.filter(RoomAssignment.id == item_id)
    rows = targets.all()
    if not rows:
        return 'Nothing left to move.'

    for ra in rows:
        if action == 'reassign':
            setattr(ra, field, target_id)
        elif action == 'clear':
            setattr(ra, field, None)
        elif action == 'cancel':
            ra.status = c.CANCELLED
    session.flush()

    verb = {'reassign': 'moved', 'clear': 'unlinked', 'cancel': 'cancelled'}[action]
    return f'{len(rows)} room assignment(s) {verb}.'


def _resolve_inventory_assignments(session, inv, action, item_id, target_id):
    return _resolve_assignments(session, inv, action, item_id, target_id,
                                'inventory_id')


def _resolve_partition_assignments(session, partition, action, item_id, target_id):
    from uber.hotel.perms import record_partition_audit
    from uber.models.hotel import RoomAssignment

    targets = session.query(RoomAssignment).filter(
        RoomAssignment.partition_id == partition.id, RoomAssignment.is_live)
    if item_id:
        targets = targets.filter(RoomAssignment.id == item_id)
    rows = targets.all()

    message = _resolve_assignments(session, partition, action, item_id,
                                   target_id, 'partition_id')

    for ra in rows:
        if action == 'reassign':
            record_partition_audit(
                session, partition.id,
                action='assignment.partition_changed',
                description=f'Moved to another partition: {ra.room_summary}',
                target_type='assignment', target_id=ra.id,
                attendee_id=ra.attendee_id)
            record_partition_audit(
                session, target_id,
                action='assignment.partition_changed',
                description=f'Moved from {partition.name}: {ra.room_summary}',
                target_type='assignment', target_id=ra.id,
                attendee_id=ra.attendee_id)
        elif action == 'clear':
            record_partition_audit(
                session, partition.id,
                action='assignment.partition_cleared',
                description=f'Returned to the general pool: {ra.room_summary}',
                target_type='assignment', target_id=ra.id,
                attendee_id=ra.attendee_id)
    session.flush()
    return message


def _resolve_type_blocks(session, room_type, action, item_id, target_id):
    from uber.models.hotel import HotelRoomInventory

    field = 'suite_type_id' if room_type.is_suite else 'room_type_id'
    query = session.query(HotelRoomInventory).filter(
        getattr(HotelRoomInventory, field) == room_type.id)
    if item_id:
        query = query.filter(HotelRoomInventory.id == item_id)
    blocks = query.all()
    for block in blocks:
        setattr(block, field, target_id if action == 'reassign' else None)
    session.flush()
    return f'{len(blocks)} inventory block(s) updated.'


def _resolve_connector_children(session, room_type, action, item_id, target_id):
    from uber.models.hotel import LotteryRoomType

    query = session.query(LotteryRoomType).filter(
        LotteryRoomType.connects_to_type_id == room_type.id)
    if item_id:
        query = query.filter(LotteryRoomType.id == item_id)
    children = query.all()
    for child in children:
        if action == 'reassign':
            child.connects_to_type_id = target_id
        else:
            child.connects_to_type_id = None
            child.connector_quantity = 0
    session.flush()
    return f'{len(children)} connector type(s) updated.'


def _resolve_hotel_inventory(session, hotel, action, item_id, target_id):
    from uber.models.hotel import HotelRoomInventory

    query = session.query(HotelRoomInventory).filter_by(hotel_id=hotel.id)
    if item_id:
        query = query.filter(HotelRoomInventory.id == item_id)
    blocks = query.all()
    for block in blocks:
        block.hotel_id = target_id
    session.flush()
    return f'{len(blocks)} inventory block(s) moved.'


def _resolve_hotel_physical_rooms(session, hotel, action, item_id, target_id):
    from uber.models.hotel import PhysicalRoom

    query = session.query(PhysicalRoom).filter_by(hotel_id=hotel.id)
    if item_id:
        query = query.filter(PhysicalRoom.id == item_id)
    rooms = query.all()

    if action == 'delete_all':
        for room in rooms:
            session.delete(room)
        session.flush()
        return f'{len(rooms)} catalogued room(s) deleted.'

    # A room number is unique per hotel, so a move can collide.
    taken = {r.room_number for r in session.query(PhysicalRoom).filter_by(
        hotel_id=target_id).all()}
    clashes = [r.room_number for r in rooms if r.room_number in taken]
    if clashes:
        raise DeletionError(
            'The destination hotel already has room(s) numbered '
            + ', '.join(sorted(clashes)[:5])
            + '. Renumber or delete them first.')

    for room in rooms:
        room.hotel_id = target_id
    session.flush()
    return f'{len(rooms)} catalogued room(s) moved.'


def _resolve_emailed_links(session, reveal, action, item_id, target_id):
    """Acknowledging is a decision, not a data change; perform_delete rechecks
    it via its force flag."""
    return ('Acknowledged. You can now delete this reveal, which will break '
            'the links already sent.')


_RESOLVERS = {
    ('inventory', 'live_assignments'): _resolve_inventory_assignments,
    ('partition', 'live_assignments'): _resolve_partition_assignments,
    ('room_type', 'active_blocks'): _resolve_type_blocks,
    ('room_type', 'connector_children'): _resolve_connector_children,
    ('hotel', 'inventory'): _resolve_hotel_inventory,
    ('hotel', 'physical_rooms'): _resolve_hotel_physical_rooms,
    ('waitlist_reveal', 'emailed_links'): _resolve_emailed_links,
}


# ---------------------------------------------------------------------------
# the delete itself
# ---------------------------------------------------------------------------

def perform_delete(session, kind, obj_id, mode='soft', force=False):
    """Deactivate or permanently delete, after re-checking conflicts.

    The re-check is the point: a dialog left open while someone else books a
    room would otherwise authorize a delete that is no longer safe.
    """
    obj, spec, groups = inspect_conflicts(session, kind, obj_id)
    name = _display_name(obj)

    if mode == 'soft':
        if not spec.get('soft_delete'):
            raise DeletionError(f'A {spec["title"]} cannot be deactivated.')
        obj.active = False
        session.flush()
        return f'{name} deactivated.'

    blocking = [g for g in groups if g['severity'] == 'blocking']
    # A reveal with sent links stays blocking until explicitly acknowledged,
    # since no amount of resolution makes those links work again.
    if force:
        blocking = [g for g in blocking if g['category'] != 'emailed_links']
    if blocking:
        raise DeletionError(
            'Resolve these first: '
            + ', '.join(g['label'].lower() for g in blocking) + '.')

    _cleanup_before_delete(session, kind, obj)
    session.delete(obj)
    session.flush()
    return f'{name} deleted.'


def _cleanup_before_delete(session, kind, obj):
    """Apply every advisory consequence, then drop the issue notes keyed to
    this row."""
    from uber.hotel.audit import purge_issue_notes
    from uber.models.hotel import (HotelExportLog, HotelImportFile,
                                   InventoryPartitionBlock, LotteryRun,
                                   PartitionAuditLog, PhysicalRoom,
                                   RoomAssignment)
    from uber.models import LotteryApplication

    obj_id = str(obj.id)

    if kind == 'inventory':
        session.query(RoomAssignment).filter_by(inventory_id=obj.id).update(
            {'inventory_id': None}, synchronize_session='fetch')
        session.query(PhysicalRoom).filter_by(inventory_id=obj.id).update(
            {'inventory_id': None}, synchronize_session='fetch')
        for block in session.query(InventoryPartitionBlock).filter_by(
                inventory_id=obj.id).all():
            session.delete(block)
        _strip_run_filter(session, 'inventory_filter', obj_id)
        purge_issue_notes(session, 'inventory', obj_id)

    elif kind == 'room_type':
        field = 'suite_type_id' if obj.is_suite else 'room_type_id'
        session.query(type(obj)).filter_by(connects_to_type_id=obj.id).update(
            {'connects_to_type_id': None, 'connector_quantity': 0},
            synchronize_session='fetch')
        from uber.models.hotel import HotelRoomInventory
        session.query(HotelRoomInventory).filter(
            getattr(HotelRoomInventory, field) == obj.id).update(
            {field: None}, synchronize_session='fetch')
        _strip_preferences(
            session,
            'suite_type_preference' if obj.is_suite else 'room_type_preference',
            obj_id)
        _strip_run_filter(session, 'room_type_filter', obj_id)
        purge_issue_notes(session, 'room_type', obj_id)

    elif kind == 'hotel':
        session.query(HotelExportLog).filter_by(hotel_id=obj.id).update(
            {'hotel_id': None}, synchronize_session='fetch')
        session.query(HotelImportFile).filter_by(hotel_id=obj.id).update(
            {'hotel_id': None}, synchronize_session='fetch')
        _strip_preferences(session, 'hotel_preference', obj_id)
        _strip_run_filter(session, 'hotel_filter', obj_id)

    elif kind == 'partition':
        from uber.hotel.perms import record_partition_audit
        record_partition_audit(
            session, obj.id,
            action='partition.deleted',
            description=f'Permanently deleted partition {obj.name}',
            target_type='partition', target_id=obj.id)
        session.flush()
        # Stamp the name before the FK goes null, so the log still says where
        # each entry happened.
        session.query(PartitionAuditLog).filter_by(partition_id=obj.id).update(
            {'partition_name': obj.name or '', 'partition_id': None},
            synchronize_session='fetch')
        session.query(RoomAssignment).filter_by(partition_id=obj.id).update(
            {'partition_id': None}, synchronize_session='fetch')
        session.query(LotteryApplication).filter_by(partition_id=obj.id).update(
            {'partition_id': None}, synchronize_session='fetch')
        session.query(LotteryRun).filter(
            LotteryRun.partition_filter == obj_id,
            LotteryRun.status == c.LOTTERY_PENDING).update(
            {'partition_filter': None}, synchronize_session='fetch')
        purge_issue_notes(session, 'partition', obj_id)

    session.flush()


def _strip_run_filter(session, field, obj_id):
    """Remove an id from pending runs' filter CSVs. Awarded and reverted runs
    keep theirs: they are a record of what was actually run."""
    from uber.models.hotel import LotteryRun

    for run in session.query(LotteryRun).filter(
            LotteryRun.status == c.LOTTERY_PENDING).all():
        current = getattr(run, field) or ''
        if obj_id not in current:
            continue
        remaining = ','.join([v for v in current.split(',') if v and v != obj_id])
        setattr(run, field, remaining or None)


def _strip_preferences(session, field, obj_id):
    """Remove an id from every entry's ranked list, keeping the order of the
    rest."""
    from uber.models import LotteryApplication

    column = getattr(LotteryApplication, field)
    for app in session.query(LotteryApplication).filter(
            column.contains(obj_id)).all():
        current = (getattr(app, field) or '').split(',')
        setattr(app, field, ','.join([v for v in current if v and v != obj_id]))
