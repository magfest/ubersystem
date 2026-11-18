"""Rooms without an occupant list get one from the booker's lottery group."""

import pytest

from uber.hotel.service import materialize_implied_occupants, remove_room_occupant
from uber.models.hotel import room_assignment_occupant

from tests.hotel.factories import (N, make_application, make_assignment, make_attendee, make_hotel,
                                   make_inventory)


@pytest.fixture
def group_room(session):
    """A group leader's room whose occupant rows are gone, with one group member."""
    leader, member = make_attendee(session), make_attendee(session)
    app = make_application(session, leader)
    make_application(session, member, parent_application_id=app.id)
    ra = make_assignment(session, leader, make_inventory(session, make_hotel(session)), check_in=N[0],
                         check_out=N[2], lottery_application_id=app.id)
    session.execute(room_assignment_occupant.delete().where(
        room_assignment_occupant.c.room_assignment_id == ra.id))
    session.expire_all()
    return ra, leader, member


def _stored(session, ra):
    return {row.attendee_id for row in session.execute(room_assignment_occupant.select().where(
        room_assignment_occupant.c.room_assignment_id == ra.id))}


def test_backfill_writes_the_group_to_the_occupant_list(session, group_room):
    ra, leader, member = group_room
    assert _stored(session, ra) == set()
    assert materialize_implied_occupants(session) >= 1
    assert _stored(session, ra) == {leader.id, member.id}
    assert materialize_implied_occupants(session) == 0

    # From here the list is managed like any other room's.
    remove_room_occupant(session, ra, member.id)
    assert _stored(session, ra) == {leader.id}


def test_saving_a_room_keeps_its_implied_group(session, group_room):
    ra, leader, member = group_room
    ra.admin_notes = 'touched'
    session.add(ra)
    session.flush()
    assert _stored(session, ra) == {leader.id, member.id}
