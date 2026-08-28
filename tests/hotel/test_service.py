"""uber.hotel.service: date parsing, the create path's partition-block
guard, and the shared sparse edit path."""

from datetime import date

import pytest

from uber.config import c
from uber.hotel.service import (RoomAssignmentError,
                                apply_room_assignment_edits,
                                create_room_assignment, parse_date_param)

from tests.hotel.factories import (N, make_attendee, make_hotel,
                                   make_inventory, make_partition,
                                   make_partition_block)


# ---------------------------------------------------------------------------
# parse_date_param
# ---------------------------------------------------------------------------

def test_parse_date_param_variants():
    assert parse_date_param(None, 'check-in') is None
    assert parse_date_param('', 'check-in') is None
    assert parse_date_param('   ', 'check-in') is None
    assert parse_date_param(date(2026, 1, 8), 'check-in') == date(2026, 1, 8)
    assert parse_date_param('2026-01-08', 'check-in') == date(2026, 1, 8)
    assert parse_date_param(' 2026-01-08 ', 'check-in') == date(2026, 1, 8)

    with pytest.raises(RoomAssignmentError) as exc:
        parse_date_param('garbage', 'check-in')
    assert 'check-in' in exc.value.message


# ---------------------------------------------------------------------------
# create_room_assignment
# ---------------------------------------------------------------------------

def test_create_room_assignment_happy_path(session, no_cherrypy_session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel, quantity=5)
    attendee = make_attendee(session)

    ra = create_room_assignment(
        session,
        attendee_id=attendee.id,
        inventory_id=inv.id,
        assigned_check_in_date='2026-01-08',
        assigned_check_out_date='2026-01-10',
        room_number='  1204  ',
        admin_notes='  note  ')

    assert ra.id
    assert ra.attendee_id == attendee.id
    assert ra.inventory_id == inv.id
    assert ra.status == c.ASSIGNED
    assert ra.assignment_reason == c.MANUAL
    assert ra.assigned_check_in_date == date(2026, 1, 8)
    assert ra.assigned_check_out_date == date(2026, 1, 10)
    assert ra.room_number == '1204'
    assert ra.admin_notes == 'note'
    assert ra.payment_type == 'masterbill'
    assert ra.require_cc is False


def test_create_room_assignment_validations(session, no_cherrypy_session):
    import uuid

    hotel = make_hotel(session)
    inv = make_inventory(session, hotel, quantity=5)
    attendee = make_attendee(session)

    with pytest.raises(RoomAssignmentError):
        create_room_assignment(session, attendee_id='', inventory_id=inv.id)
    with pytest.raises(RoomAssignmentError):
        create_room_assignment(session, attendee_id=str(uuid.uuid4()),
                               inventory_id=inv.id)
    with pytest.raises(RoomAssignmentError):
        create_room_assignment(session, attendee_id=attendee.id,
                               inventory_id=str(uuid.uuid4()))
    with pytest.raises(RoomAssignmentError):
        create_room_assignment(session, attendee_id=attendee.id,
                               inventory_id=inv.id,
                               assigned_check_in_date='not-a-date')


def test_create_room_assignment_partition_requires_block(session,
                                                         no_cherrypy_session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel, quantity=5)
    attendee = make_attendee(session)
    partition = make_partition(session)

    with pytest.raises(RoomAssignmentError) as exc:
        create_room_assignment(session, attendee_id=attendee.id,
                               inventory_id=inv.id,
                               partition_id=partition.id)
    assert 'not allocated' in exc.value.message

    # With a block in place the same call succeeds and writes an audit row.
    make_partition_block(session, partition, inv, quantity=2)
    ra = create_room_assignment(session, attendee_id=attendee.id,
                                inventory_id=inv.id,
                                partition_id=partition.id)
    assert ra.partition_id == partition.id

    from uber.models.hotel import PartitionAuditLog
    # create_room_assignment flushes before writing the audit row and the
    # test sessions run with autoflush off, so flush to make it queryable.
    session.flush()
    audits = session.query(PartitionAuditLog).filter_by(
        partition_id=partition.id, target_id=ra.id).all()
    assert len(audits) == 1
    assert audits[0].action == 'assignment.created'


# ---------------------------------------------------------------------------
# apply_room_assignment_edits
# ---------------------------------------------------------------------------

class _Fail(Exception):
    pass


def _fail(message):
    raise _Fail(message)


def test_apply_edits_sparse_params_touch_only_submitted_fields(
        session, no_cherrypy_session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel, quantity=5)
    attendee = make_attendee(session)
    ra = create_room_assignment(
        session, attendee_id=attendee.id, inventory_id=inv.id,
        assigned_check_in_date=N[1], assigned_check_out_date=N[3],
        room_number='500')

    message = apply_room_assignment_edits(
        session, ra, {'assigned_check_in_date': N[2].isoformat()},
        audit_prefix='Edited', fail=_fail)

    assert 'check-in' in message
    assert ra.assigned_check_in_date == N[2]
    assert ra.assigned_check_out_date == N[3], 'unsubmitted fields untouched'
    assert ra.room_number == '500', 'unsubmitted fields untouched'

    # No-op edit reports no changes.
    message = apply_room_assignment_edits(
        session, ra, {'assigned_check_in_date': N[2].isoformat()},
        audit_prefix='Edited', fail=_fail)
    assert message == 'No changes.'

    # Bad date input goes through the fail hook.
    with pytest.raises(_Fail):
        apply_room_assignment_edits(
            session, ra, {'assigned_check_out_date': 'bogus'},
            audit_prefix='Edited', fail=_fail)


def test_apply_edits_allowed_inventory_ids_gate(session, no_cherrypy_session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel, quantity=5)
    other_inv = make_inventory(session, hotel, quantity=5)
    attendee = make_attendee(session)
    ra = create_room_assignment(
        session, attendee_id=attendee.id, inventory_id=inv.id)

    with pytest.raises(_Fail) as exc:
        apply_room_assignment_edits(
            session, ra, {'inventory_id': other_inv.id},
            audit_prefix='Edited', fail=_fail,
            allowed_inventory_ids={inv.id})
    assert 'not allocated' in str(exc.value)
    assert ra.inventory_id == inv.id

    # The same change with the id allowed goes through.
    message = apply_room_assignment_edits(
        session, ra, {'inventory_id': other_inv.id},
        audit_prefix='Edited', fail=_fail,
        allowed_inventory_ids={inv.id, other_inv.id})
    assert 'inventory' in message
    assert ra.inventory_id == other_inv.id
