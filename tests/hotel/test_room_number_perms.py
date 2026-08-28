"""The per-partition room-number permission and the write-path gate that
backs it."""

import pytest

from uber.hotel.perms import can_edit_room_numbers_in, can_view_room_numbers_in
from uber.hotel.service import apply_room_assignment_edits, create_room_assignment
from uber.models import AdminAccount, Attendee
from uber.models.hotel import PartitionOwner, PhysicalRoom

from tests.hotel.factories import (make_assignment, make_attendee, make_hotel,
                                   make_inventory, make_partition)


def _fail(msg):
    raise AssertionError(f'unexpected failure: {msg}')


def _grant(session, partition, **flags):
    """A partition owner with no site-section access, so the capability
    helpers read the grant's flags rather than short-circuiting on the
    lottery-admin check."""
    account = AdminAccount(attendee=make_attendee(session), hashed='x')
    session.add(account)
    session.flush()
    owner = PartitionOwner(partition_id=partition.id,
                           admin_account_id=account.id, **flags)
    session.add(owner)
    session.flush()
    return account, owner


# ---------------------------------------------------------------------------
# capability helpers
# ---------------------------------------------------------------------------

def test_room_number_flags_default_off(session, no_cherrypy_session):
    """Partition owners cannot see room numbers today, so the new flags must
    default off to preserve that."""
    partition = make_partition(session)
    _account, owner = _grant(session, partition)
    assert owner.can_view_room_numbers is False
    assert owner.can_edit_room_numbers is False


def test_helpers_read_the_grant(session, no_cherrypy_session):
    partition = make_partition(session)
    account, _owner = _grant(session, partition, can_view_room_numbers=True)

    assert can_view_room_numbers_in(session, partition.id, admin_account=account) is True
    assert can_edit_room_numbers_in(session, partition.id, admin_account=account) is False


def test_helpers_deny_without_a_grant(session, no_cherrypy_session):
    partition = make_partition(session)
    other = make_partition(session)
    account, _owner = _grant(session, other, can_view_room_numbers=True,
                             can_edit_room_numbers=True)

    assert can_view_room_numbers_in(session, partition.id, admin_account=account) is False
    assert can_edit_room_numbers_in(session, partition.id, admin_account=account) is False


# ---------------------------------------------------------------------------
# write-path gate
# ---------------------------------------------------------------------------

def test_create_ignores_room_number_when_not_allowed(session, no_cherrypy_session):
    hotel = make_hotel(session)
    inventory = make_inventory(session, hotel)
    attendee = make_attendee(session)

    ra = create_room_assignment(
        session, attendee_id=attendee.id, inventory_id=inventory.id,
        room_number='1204', allow_room_number=False)
    session.flush()
    assert ra.room_number is None


def test_create_keeps_room_number_when_allowed(session, no_cherrypy_session):
    hotel = make_hotel(session)
    inventory = make_inventory(session, hotel)
    attendee = make_attendee(session)

    ra = create_room_assignment(
        session, attendee_id=attendee.id, inventory_id=inventory.id,
        room_number='1204', allow_room_number=True)
    session.flush()
    assert ra.room_number == '1204'


def test_edit_ignores_both_room_number_and_physical_room(session, no_cherrypy_session):
    """physical_room_id must be gated too: linking a physical room re-stamps
    room_number via a presave, so gating only the text field would leave a
    way to set the number indirectly."""
    hotel = make_hotel(session)
    inventory = make_inventory(session, hotel)
    attendee = make_attendee(session)
    ra = make_assignment(session, attendee=attendee, inventory=inventory)

    room = PhysicalRoom(hotel_id=hotel.id, inventory_id=inventory.id,
                        room_number='0909')
    session.add(room)
    session.flush()

    apply_room_assignment_edits(
        session, ra, {'room_number': '1204', 'physical_room_id': str(room.id)},
        audit_prefix='test', fail=_fail, allow_room_number=False)
    session.flush()

    assert ra.room_number is None
    assert ra.physical_room_id is None


def test_edit_applies_room_number_when_allowed(session, no_cherrypy_session):
    hotel = make_hotel(session)
    inventory = make_inventory(session, hotel)
    attendee = make_attendee(session)
    ra = make_assignment(session, attendee=attendee, inventory=inventory)

    apply_room_assignment_edits(
        session, ra, {'room_number': '1204'},
        audit_prefix='test', fail=_fail, allow_room_number=True)
    session.flush()

    assert ra.room_number == '1204'


def test_gate_does_not_disturb_other_fields(session, no_cherrypy_session):
    hotel = make_hotel(session)
    inventory = make_inventory(session, hotel)
    attendee = make_attendee(session)
    ra = make_assignment(session, attendee=attendee, inventory=inventory)

    apply_room_assignment_edits(
        session, ra, {'room_number': '1204', 'admin_notes': 'kept'},
        audit_prefix='test', fail=_fail, allow_room_number=False)
    session.flush()

    assert ra.room_number is None
    assert ra.admin_notes == 'kept'
