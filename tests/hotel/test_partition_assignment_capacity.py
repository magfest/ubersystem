"""No one - partition owner or lottery admin - can assign or extend rooms
past a partition's allocation of a block."""

from datetime import date

import pytest

from uber.config import c
from uber.errors import HTTPRedirect
from uber.hotel.service import (RoomAssignmentError, apply_room_assignment_edits,
                                check_partition_capacity, create_room_assignment)

from tests.hotel.factories import (make_assignment, make_attendee, make_hotel, make_inventory,
                                   make_partition, make_partition_block)

FRI, SAT, SUN = date(2027, 1, 8), date(2027, 1, 9), date(2027, 1, 10)


@pytest.fixture
def full_partition(session):
    """A partition with 2 rooms of a block; both booked Friday night."""
    inv = make_inventory(session, make_hotel(session), quantity=10)
    partition = make_partition(session)
    make_partition_block(session, partition, inv, 2)
    for _ in range(2):
        make_assignment(session, make_attendee(session), inventory=inv, partition_id=partition.id,
                        check_in=FRI, check_out=SAT)
    return inv, partition


def _create(session, inv, partition, check_in, check_out, **kwargs):
    return create_room_assignment(
        session, attendee_id=make_attendee(session).id, inventory_id=inv.id,
        partition_id=partition.id, assigned_check_in_date=check_in,
        assigned_check_out_date=check_out, **kwargs)


def test_create_refuses_a_full_night(session, no_cherrypy_session, full_partition):
    inv, partition = full_partition

    with pytest.raises(RoomAssignmentError) as exc:
        _create(session, inv, partition, FRI, SUN)
    assert '2 of 2 booked' in exc.value.message


def test_create_allows_open_nights(session, no_cherrypy_session, full_partition):
    inv, partition = full_partition

    ra = _create(session, inv, partition, SAT, SUN)
    assert ra.partition_id == partition.id


def test_dead_rows_and_other_partitions_do_not_count(session, no_cherrypy_session, full_partition):
    inv, partition = full_partition
    other = make_partition(session)
    make_partition_block(session, other, inv, 2)
    make_assignment(session, make_attendee(session), inventory=inv, partition_id=other.id,
                    check_in=SAT, check_out=SUN)
    make_assignment(session, make_attendee(session), inventory=inv, partition_id=partition.id,
                    status=c.CANCELLED, check_in=SAT, check_out=SUN)
    make_assignment(session, make_attendee(session), inventory=inv, partition_id=partition.id,
                    check_in=SAT, check_out=SUN)

    assert _create(session, inv, partition, SAT, SUN).id


def _edit(session, ra, **params):
    def fail(msg):
        raise RoomAssignmentError(msg)
    return apply_room_assignment_edits(session, ra, params, audit_prefix='Test', fail=fail)


def test_extending_into_a_full_night_is_refused(session, no_cherrypy_session, full_partition):
    inv, partition = full_partition
    ra = make_assignment(session, make_attendee(session), inventory=inv, partition_id=partition.id,
                         check_in=SAT, check_out=SUN)

    with pytest.raises(RoomAssignmentError):
        _edit(session, ra, assigned_check_in_date=FRI.isoformat())
    assert ra.assigned_check_in_date == SAT


def test_reviving_into_a_full_night_is_refused(session, no_cherrypy_session, full_partition):
    inv, partition = full_partition
    ra = make_assignment(session, make_attendee(session), inventory=inv, partition_id=partition.id,
                         status=c.CANCELLED, check_in=FRI, check_out=SAT)

    with pytest.raises(RoomAssignmentError):
        _edit(session, ra, status=str(c.ASSIGNED))
    assert ra.status == c.CANCELLED


def test_over_allocated_rooms_can_still_shrink(session, no_cherrypy_session, full_partition):
    inv, partition = full_partition
    ra = make_assignment(session, make_attendee(session), inventory=inv, partition_id=partition.id,
                         check_in=FRI, check_out=SUN)

    assert _edit(session, ra, assigned_check_out_date=SAT.isoformat()) == 'Updated check-out.'
    assert _edit(session, ra, payment_type='masterbill') == 'Updated billing.'


def test_check_ignores_unpartitioned_and_undated_rows(session, no_cherrypy_session, full_partition):
    inv, partition = full_partition
    check_partition_capacity(session, make_assignment(
        session, make_attendee(session), inventory=inv, check_in=FRI, check_out=SAT))
    check_partition_capacity(session, make_assignment(
        session, make_attendee(session), inventory=inv, partition_id=partition.id))


@pytest.fixture
def partition_admin(post_request, monkeypatch):
    import uber.site_sections.partition_admin as site

    monkeypatch.setattr(site, 'check_csrf', lambda *a, **k: None)
    monkeypatch.setattr(site, 'can_edit_room_numbers_in', lambda *a, **k: False)

    def call(name, session, lottery_admin=False, **kwargs):
        monkeypatch.setattr(site, 'is_lottery_admin', lambda *a, **k: lottery_admin)
        func = getattr(site.Root, name)
        while hasattr(func, '__wrapped__'):
            func = func.__wrapped__
        with pytest.raises(HTTPRedirect) as excinfo:
            func(site.Root(), session, **kwargs)
        return excinfo.value.urls[0]
    return call


def _partition_rooms(session, partition):
    from uber.models import RoomAssignment
    return session.query(RoomAssignment).filter_by(partition_id=partition.id).count()


def test_owner_assign_room_refused_when_full(session, partition_admin, full_partition):
    inv, partition = full_partition

    url = partition_admin('assign_room', session, partition_id=partition.id,
                          attendee_id=make_attendee(session).id, inventory_id=inv.id,
                          assigned_check_in_date=FRI.isoformat(),
                          assigned_check_out_date=SAT.isoformat())
    assert 'booked' in url
    assert _partition_rooms(session, partition) == 2


def test_lottery_admin_assign_room_refused_when_full(session, partition_admin, full_partition):
    inv, partition = full_partition

    url = partition_admin('assign_room', session, lottery_admin=True, partition_id=partition.id,
                          attendee_id=make_attendee(session).id, inventory_id=inv.id,
                          assigned_check_in_date=FRI.isoformat(),
                          assigned_check_out_date=SAT.isoformat())
    assert 'booked' in url
    assert _partition_rooms(session, partition) == 2


def test_owner_update_assignment_refused_when_full(session, partition_admin, full_partition):
    inv, partition = full_partition
    ra = make_assignment(session, make_attendee(session), inventory=inv, partition_id=partition.id,
                         check_in=SAT, check_out=SUN)

    url = partition_admin('update_assignment', session, assignment_id=ra.id,
                          assigned_check_in_date=FRI.isoformat())
    assert 'booked' in url
    assert ra.assigned_check_in_date == SAT
