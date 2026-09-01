"""Deleting hotel lottery resources: what blocks, what resolves, and what the
delete cleans up on the way out."""

from datetime import date

import pytest

from uber.config import c
from uber.hotel.audit import purge_issue_notes
from uber.hotel.deletion import (DeletionError, has_blocking,
                                 inspect_conflicts, perform_delete,
                                 resolve_conflict)
from uber.models.hotel import (HotelRoomInventory, HotelRoomIssueNote,
                               LotteryRoomType, PartitionAuditLog,
                               PhysicalRoom, RoomAssignment)

from tests.hotel.factories import (make_application, make_assignment,
                                   make_attendee, make_hotel, make_inventory,
                                   make_partition, make_partition_block,
                                   make_room_type, make_run)


def _groups(session, kind, obj):
    _obj, _spec, groups = inspect_conflicts(session, kind, obj.id)
    return {g['category']: g for g in groups}


# ---------------------------------------------------------------------------
# inventory
# ---------------------------------------------------------------------------

def test_live_assignments_block_an_inventory_delete(session, no_cherrypy_session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel)
    make_assignment(session, attendee=make_attendee(session), inventory=inv)
    session.flush()

    groups = _groups(session, 'inventory', inv)
    assert groups['live_assignments']['severity'] == 'blocking'
    with pytest.raises(DeletionError):
        perform_delete(session, 'inventory', inv.id, mode='hard')


def test_cancelled_assignments_are_only_advisory(session, no_cherrypy_session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel)
    make_assignment(session, attendee=make_attendee(session), inventory=inv,
                    status=c.CANCELLED)
    session.flush()

    groups = _groups(session, 'inventory', inv)
    assert 'live_assignments' not in groups
    assert groups['dead_assignments']['severity'] == 'advisory'
    assert not has_blocking(list(groups.values()))


def test_reassigning_clears_the_block(session, no_cherrypy_session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel)
    other = make_inventory(session, hotel)
    ra = make_assignment(session, attendee=make_attendee(session), inventory=inv)
    session.flush()

    resolve_conflict(session, 'inventory', inv.id, 'live_assignments',
                     'reassign', target_id=str(other.id))
    assert ra.inventory_id == other.id
    assert not has_blocking(list(_groups(session, 'inventory', inv).values()))


def test_cancelling_clears_the_block(session, no_cherrypy_session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel)
    ra = make_assignment(session, attendee=make_attendee(session), inventory=inv)
    session.flush()

    resolve_conflict(session, 'inventory', inv.id, 'live_assignments', 'cancel')
    assert ra.status == c.CANCELLED


def test_inventory_reassign_refuses_another_hotel(session, no_cherrypy_session):
    """Moving a booking across hotels would invalidate any confirmation number
    already exchanged, so the other hotel is never offered."""
    hotel = make_hotel(session)
    elsewhere = make_inventory(session, make_hotel(session))
    inv = make_inventory(session, hotel)
    make_assignment(session, attendee=make_attendee(session), inventory=inv)
    session.flush()

    with pytest.raises(DeletionError):
        resolve_conflict(session, 'inventory', inv.id, 'live_assignments',
                         'reassign', target_id=str(elsewhere.id))


def test_inventory_reassign_refuses_across_the_suite_flag(session, no_cherrypy_session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel)
    suite_block = make_inventory(session, hotel)
    suite_block.is_suite = True
    make_assignment(session, attendee=make_attendee(session), inventory=inv)
    session.flush()

    with pytest.raises(DeletionError):
        resolve_conflict(session, 'inventory', inv.id, 'live_assignments',
                         'reassign', target_id=str(suite_block.id))


def test_unlinking_a_live_room_is_never_offered(session, no_cherrypy_session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel)
    make_assignment(session, attendee=make_attendee(session), inventory=inv)
    session.flush()

    groups = _groups(session, 'inventory', inv)
    assert 'clear' not in groups['live_assignments']['actions']


# ---------------------------------------------------------------------------
# room types
# ---------------------------------------------------------------------------

def test_active_blocks_block_a_room_type_delete(session, no_cherrypy_session):
    hotel = make_hotel(session)
    room_type = make_room_type(session)
    make_inventory(session, hotel, room_type=room_type)
    session.flush()

    groups = _groups(session, 'room_type', room_type)
    assert groups['active_blocks']['severity'] == 'blocking'


def test_connector_children_block_a_room_type_delete(session, no_cherrypy_session):
    parent = make_room_type(session)
    child = make_room_type(session)
    child.connects_to_type_id = parent.id
    child.connector_quantity = 1
    session.flush()

    groups = _groups(session, 'room_type', parent)
    assert groups['connector_children']['severity'] == 'blocking'

    resolve_conflict(session, 'room_type', parent.id, 'connector_children', 'clear')
    assert child.connects_to_type_id is None
    assert child.connector_quantity == 0


def test_room_type_delete_strips_preferences_and_keeps_order(session, no_cherrypy_session):
    hotel = make_hotel(session)
    doomed = make_room_type(session)
    keep_a = make_room_type(session)
    keep_b = make_room_type(session)
    attendee = make_attendee(session)
    app = make_application(session, attendee)
    app.room_type_preference = f'{keep_a.id},{doomed.id},{keep_b.id}'
    session.flush()

    perform_delete(session, 'room_type', doomed.id, mode='hard')
    session.flush()
    assert app.room_type_preference == f'{keep_a.id},{keep_b.id}'


def test_entries_left_with_nothing_are_named(session, no_cherrypy_session):
    doomed = make_room_type(session)
    attendee = make_attendee(session)
    app = make_application(session, attendee)
    app.room_type_preference = str(doomed.id)
    session.flush()

    groups = _groups(session, 'room_type', doomed)
    assert groups['emptied_preferences']['item_total'] == 1


def test_entries_ranking_the_resource_are_named(session, no_cherrypy_session):
    doomed = make_room_type(session)
    attendee = make_attendee(session)
    app = make_application(session, attendee)
    app.room_type_preference = str(doomed.id)
    session.flush()

    groups = _groups(session, 'room_type', doomed)
    prefs = groups['preferences']
    assert prefs['item_total'] == 1
    assert prefs['items'][0]['label'] == attendee.full_name
    assert prefs['items'][0]['link'] == f'form?id={app.id}'


# ---------------------------------------------------------------------------
# hotels
# ---------------------------------------------------------------------------

def test_physical_rooms_block_a_hotel_delete(session, no_cherrypy_session):
    """The FK cascades, so without this the catalog would be destroyed
    silently."""
    hotel = make_hotel(session)
    session.add(PhysicalRoom(hotel_id=hotel.id, room_number='1204'))
    session.flush()

    groups = _groups(session, 'hotel', hotel)
    assert groups['physical_rooms']['severity'] == 'blocking'
    assert 'delete_all' in groups['physical_rooms']['actions']


def test_moving_rooms_refuses_a_number_collision(session, no_cherrypy_session):
    hotel = make_hotel(session)
    other = make_hotel(session)
    session.add(PhysicalRoom(hotel_id=hotel.id, room_number='1204'))
    session.add(PhysicalRoom(hotel_id=other.id, room_number='1204'))
    session.flush()

    with pytest.raises(DeletionError) as exc:
        resolve_conflict(session, 'hotel', hotel.id, 'physical_rooms',
                         'reassign', target_id=str(other.id))
    assert '1204' in exc.value.message


def test_hotel_delete_keeps_export_records(session, no_cherrypy_session):
    from uber.models.hotel import HotelExportLog

    hotel = make_hotel(session)
    log = HotelExportLog(hotel_id=hotel.id, export_type='room_export',
                         record_count=3)
    session.add(log)
    session.flush()

    perform_delete(session, 'hotel', hotel.id, mode='hard')
    session.flush()
    assert log.hotel_id is None, 'the retained bytes must outlive the hotel row'


# ---------------------------------------------------------------------------
# partitions
# ---------------------------------------------------------------------------

def test_partition_offers_clearing_rooms_to_the_general_pool(session, no_cherrypy_session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel)
    partition = make_partition(session)
    make_partition_block(session, partition, inv, quantity=5)
    ra = make_assignment(session, attendee=make_attendee(session), inventory=inv,
                         partition_id=partition.id)
    session.flush()

    groups = _groups(session, 'partition', partition)
    assert groups['live_assignments']['actions'][0] == 'clear'

    resolve_conflict(session, 'partition', partition.id, 'live_assignments', 'clear')
    assert ra.partition_id is None


def test_partition_delete_keeps_its_audit_trail(session, no_cherrypy_session):
    partition = make_partition(session)
    entry = PartitionAuditLog(partition_id=partition.id, action='assignment.created',
                              description='did a thing')
    session.add(entry)
    session.flush()
    name = partition.name

    perform_delete(session, 'partition', partition.id, mode='hard')
    session.flush()

    assert entry.partition_id is None
    assert entry.partition_name == name, 'the log must still say where this happened'


def test_partition_reassignment_writes_audit_rows_on_both_sides(session, no_cherrypy_session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel)
    partition = make_partition(session)
    other = make_partition(session)
    ra = make_assignment(session, attendee=make_attendee(session), inventory=inv,
                         partition_id=partition.id)
    session.flush()

    resolve_conflict(session, 'partition', partition.id, 'live_assignments',
                     'reassign', target_id=str(other.id))

    moved_out = session.query(PartitionAuditLog).filter_by(
        partition_id=partition.id, action='assignment.partition_changed').all()
    moved_in = session.query(PartitionAuditLog).filter_by(
        partition_id=other.id, action='assignment.partition_changed').all()
    assert len(moved_out) == 1
    assert len(moved_in) == 1
    assert moved_out[0].attendee_id == ra.attendee_id


def test_partition_clear_and_delete_write_audit_rows(session, no_cherrypy_session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel)
    partition = make_partition(session)
    ra = make_assignment(session, attendee=make_attendee(session), inventory=inv,
                         partition_id=partition.id)
    session.flush()

    resolve_conflict(session, 'partition', partition.id, 'live_assignments', 'clear')
    cleared = session.query(PartitionAuditLog).filter_by(
        partition_id=partition.id, action='assignment.partition_cleared').all()
    assert len(cleared) == 1
    assert cleared[0].attendee_id == ra.attendee_id

    name = partition.name
    perform_delete(session, 'partition', partition.id, mode='hard')
    session.flush()

    entry = session.query(PartitionAuditLog).filter_by(
        action='partition.deleted', partition_name=name).one()
    assert entry.partition_id is None, 'detached but retained'


def test_partition_run_filters_null_only_for_pending_runs(session, no_cherrypy_session):
    partition = make_partition(session)
    pid = str(partition.id)

    pending = make_run(session, status=c.LOTTERY_PENDING, partition_filter=pid)
    awarded = make_run(session, status=c.LOTTERY_AWARDED, partition_filter=pid)
    session.flush()

    perform_delete(session, 'partition', partition.id, mode='hard')
    session.flush()

    assert pending.partition_filter is None
    assert awarded.partition_filter == pid, \
        'an awarded run records what was actually run'


# ---------------------------------------------------------------------------
# waitlist reveals
# ---------------------------------------------------------------------------

def _reveal(session, **kwargs):
    from uber.models.hotel import WaitlistReveal
    reveal = WaitlistReveal(name='Test reveal', **kwargs)
    session.add(reveal)
    session.flush()
    return reveal


def test_emailed_links_block_a_reveal_delete_until_forced(session, no_cherrypy_session):
    from datetime import datetime
    from pytz import UTC
    from uber.models.hotel import WaitlistRevealLink

    reveal = _reveal(session)
    session.add(WaitlistRevealLink(waitlist_reveal_id=reveal.id,
                                   attendee_id=make_attendee(session).id,
                                   token='tok', emailed_at=datetime.now(UTC)))
    session.flush()

    groups = _groups(session, 'waitlist_reveal', reveal)
    assert groups['emailed_links']['severity'] == 'blocking'

    with pytest.raises(DeletionError):
        perform_delete(session, 'waitlist_reveal', reveal.id, mode='hard')

    # Only an explicit acknowledgement gets past it.
    perform_delete(session, 'waitlist_reveal', reveal.id, mode='hard', force=True)


def test_unsent_links_do_not_block(session, no_cherrypy_session):
    from uber.models.hotel import WaitlistRevealLink

    reveal = _reveal(session)
    session.add(WaitlistRevealLink(waitlist_reveal_id=reveal.id,
                                   attendee_id=make_attendee(session).id,
                                   token='tok2'))
    session.flush()

    groups = _groups(session, 'waitlist_reveal', reveal)
    assert groups['unsent_links']['severity'] == 'advisory'
    perform_delete(session, 'waitlist_reveal', reveal.id, mode='hard')


# ---------------------------------------------------------------------------
# shared behavior
# ---------------------------------------------------------------------------

def test_soft_delete_just_deactivates(session, no_cherrypy_session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel)
    make_assignment(session, attendee=make_attendee(session), inventory=inv)
    session.flush()

    # Deactivating is allowed even with live rooms in the block.
    perform_delete(session, 'inventory', inv.id, mode='soft')
    assert inv.active is False


def test_a_bogus_reassign_target_is_rejected(session, no_cherrypy_session):
    """The dialog offers a fixed set of destinations; a hand-built POST must
    not reach anything else."""
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel)
    make_assignment(session, attendee=make_attendee(session), inventory=inv)
    session.flush()

    with pytest.raises(DeletionError):
        resolve_conflict(session, 'inventory', inv.id, 'live_assignments',
                         'reassign', target_id='not-a-real-id')


def test_an_unoffered_action_is_rejected(session, no_cherrypy_session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel)
    make_assignment(session, attendee=make_attendee(session), inventory=inv)
    session.flush()

    with pytest.raises(DeletionError):
        resolve_conflict(session, 'inventory', inv.id, 'live_assignments', 'clear')


def test_pending_run_filters_are_stripped_but_awarded_ones_are_not(session, no_cherrypy_session):
    hotel = make_hotel(session)
    doomed = make_room_type(session)
    keep = make_room_type(session)

    pending = make_run(session, status=c.LOTTERY_PENDING,
                       room_type_filter=f'{doomed.id},{keep.id}')
    awarded = make_run(session, status=c.LOTTERY_AWARDED,
                       room_type_filter=f'{doomed.id},{keep.id}')
    session.flush()

    perform_delete(session, 'room_type', doomed.id, mode='hard')
    session.flush()

    assert pending.room_type_filter == str(keep.id)
    assert str(doomed.id) in awarded.room_type_filter, \
        'an awarded run records what was actually run'


def test_issue_notes_are_purged_including_composite_keys(session, no_cherrypy_session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel)
    partition = make_partition(session)

    session.add(HotelRoomIssueNote(issue_kind='zero_quantity', target_type='inventory',
                                   target_id=str(inv.id), hidden=True))
    session.add(HotelRoomIssueNote(issue_kind='oversubscribed_partition',
                                   target_type='inventory',
                                   target_id=f'{inv.id}|{partition.id}', hidden=True))
    session.add(HotelRoomIssueNote(issue_kind='zero_quantity', target_type='inventory',
                                   target_id='some-other-block', hidden=True))
    session.flush()

    removed = purge_issue_notes(session, 'inventory', str(inv.id))
    session.flush()
    assert removed == 2, 'both the plain and the partition-scoped key'
    assert session.query(HotelRoomIssueNote).count() == 1


def test_partition_purge_matches_the_suffix_key(session, no_cherrypy_session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel)
    partition = make_partition(session)

    session.add(HotelRoomIssueNote(issue_kind='oversubscribed_partition',
                                   target_type='inventory',
                                   target_id=f'{inv.id}|{partition.id}', hidden=True))
    session.add(HotelRoomIssueNote(issue_kind='partition_unconfigured',
                                   target_type='partition',
                                   target_id=str(partition.id), hidden=True))
    session.flush()

    removed = purge_issue_notes(session, 'partition', str(partition.id))
    session.flush()
    assert removed == 2
    assert session.query(HotelRoomIssueNote).count() == 0
