"""uber.hotel.physical board operations: auto-assign flagging, scoped
clearing, and connector-group placement."""

import pytest

from uber.hotel.physical import (auto_assign_physical_rooms,
                                 clear_physical_assignments,
                                 connector_placements, set_connections)
from uber.hotel.service import assign_physical_room
from uber.models.hotel import PhysicalRoom

from tests.hotel.factories import (N, make_assignment, make_attendee,
                                   make_hotel, make_inventory)


def _hotel_with_rooms(session, count=2):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel, name='Kings')
    rooms = []
    for i in range(count):
        room = PhysicalRoom(hotel_id=hotel.id, inventory_id=inv.id,
                            room_number=str(400 + i), floor='4')
        session.add(room)
        rooms.append(room)
    session.flush()
    return hotel, inv, rooms


def test_auto_assign_marks_placements_auto(session):
    hotel, inv, rooms = _hotel_with_rooms(session)
    ra = make_assignment(session, make_attendee(session), inventory=inv,
                         check_in=N[1], check_out=N[3])

    result = auto_assign_physical_rooms(session, hotel.id)
    session.flush()

    assert result['assigned'] == 1
    assert ra.physical_room_id in {r.id for r in rooms}
    assert ra.physical_room_auto is True


def test_clear_auto_only_keeps_manual_placements(session):
    hotel, inv, rooms = _hotel_with_rooms(session)
    auto_ra = make_assignment(session, make_attendee(session),
                              inventory=inv, check_in=N[1], check_out=N[2],
                              physical_room_id=rooms[0].id,
                              physical_room_auto=True)
    manual_ra = make_assignment(session, make_attendee(session),
                                inventory=inv, check_in=N[1],
                                check_out=N[2],
                                physical_room_id=rooms[1].id)

    cleared = clear_physical_assignments(session, hotel.id, auto_only=True)
    session.flush()

    assert cleared == 1
    assert auto_ra.physical_room_id is None
    assert auto_ra.physical_room_auto is False
    assert manual_ra.physical_room_id == rooms[1].id

    cleared = clear_physical_assignments(session, hotel.id)
    session.flush()

    assert cleared == 1
    assert manual_ra.physical_room_id is None


@pytest.fixture
def suite_setup(session):
    """A suite booking with one connector child, and a catalog where
    only room 401 has a connected room in the connector's block.

        401 (suite)  -- connected -- 402 (connector block)
        403 (suite)  -- connected -- 404 (suite block, wrong block)
        405 (suite)  -- no connections
    """
    hotel = make_hotel(session)
    suites = make_inventory(session, hotel, name='Suites', is_suite=True)
    connectors = make_inventory(session, hotel, name='Connectors')

    rooms = {}
    for number, inv in [('401', suites), ('402', connectors),
                        ('403', suites), ('404', suites),
                        ('405', suites)]:
        room = PhysicalRoom(hotel_id=hotel.id, inventory_id=inv.id,
                            room_number=number, floor='4')
        session.add(room)
        rooms[number] = room
    session.flush()
    assert not set_connections(session, rooms['401'], ['402'])
    assert not set_connections(session, rooms['403'], ['404'])
    session.flush()

    parent = make_assignment(session, make_attendee(session),
                             inventory=suites, check_in=N[1], check_out=N[3])
    child = make_assignment(session, make_attendee(session),
                            inventory=connectors, check_in=N[1],
                            check_out=N[3], parent_assignment_id=parent.id)
    session.flush()
    return hotel, rooms, parent, child


def test_only_rooms_with_a_free_connector_are_offered(session, suite_setup):
    _hotel, rooms, parent, _child = suite_setup

    placements = connector_placements(session, parent)
    offered = {room.room_number for room, _picks in placements}

    # 403 connects only to a suite-block room, and 405 to nothing.
    assert offered == {'401'}
    picks = placements[0][1]
    assert [r.room_number for _ra, r in picks] == ['402']


def test_assigning_a_suite_takes_its_connector_along(session, suite_setup):
    _hotel, rooms, parent, child = suite_setup

    placed, error = assign_physical_room(session, parent, rooms['401'])
    session.flush()

    assert error is None
    assert {a.physical_room.room_number for a in placed} == {'401', '402'}
    assert parent.physical_room_id == rooms['401'].id
    assert child.physical_room_id == rooms['402'].id


def test_suite_refused_when_no_connector_is_free(session, suite_setup):
    _hotel, rooms, parent, child = suite_setup

    # Someone else takes 402 for overlapping dates.
    make_assignment(session, make_attendee(session),
                    inventory=rooms['402'].inventory, check_in=N[1],
                    check_out=N[2], physical_room_id=rooms['402'].id)
    session.flush()

    assert connector_placements(session, parent) == []
    placed, error = assign_physical_room(session, parent, rooms['401'])
    assert placed == []
    assert 'connected room' in error
    assert parent.physical_room_id is None
    assert child.physical_room_id is None


def test_connected_rooms_outside_the_type_are_left_alone(session, suite_setup):
    """403's neighbour 404 is in the suite block, not the connector
    block, so it is neither offered nor swept into an assignment."""
    _hotel, rooms, parent, child = suite_setup

    placed, error = assign_physical_room(session, parent, rooms['403'])
    assert error and placed == []

    # A plain booking with no connector children may still take 403,
    # and 404 stays free.
    plain = make_assignment(session, make_attendee(session),
                            inventory=rooms['403'].inventory,
                            check_in=N[1], check_out=N[3])
    placed, error = assign_physical_room(session, plain, rooms['403'])
    session.flush()

    assert error is None
    assert [a.physical_room.room_number for a in placed] == ['403']
    assert rooms['404'].id not in {
        a.physical_room_id for a in placed}
