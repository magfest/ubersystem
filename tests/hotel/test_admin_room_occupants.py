"""Lottery admins add and remove roommates from the edit_room_assignment
page. The booker can't be removed."""

from datetime import date

import pytest

from uber.config import c
from uber.errors import HTTPRedirect
from uber.models.hotel import room_assignment_occupant

from tests.hotel.factories import (make_application, make_assignment, make_attendee,
                                   make_hotel, make_inventory)


@pytest.fixture
def admin(post_request, monkeypatch):
    import uber.site_sections.hotel_lottery_admin as admin_site

    monkeypatch.setattr(admin_site, 'check_csrf', lambda *a, **k: None)

    def call(name, session, **kwargs):
        func = getattr(admin_site.Root, name)
        while hasattr(func, '__wrapped__'):
            func = func.__wrapped__
        with pytest.raises(HTTPRedirect) as excinfo:
            func(admin_site.Root(), session, **kwargs)
        return excinfo.value.urls[0]
    return call


def _room(session, capacity=2):
    inventory = make_inventory(session, make_hotel(session), capacity=capacity)
    return make_assignment(session, make_attendee(session), inventory=inventory,
                           status=c.ASSIGNED, check_in=date(2027, 1, 6),
                           check_out=date(2027, 1, 10))


def test_add_roommate(session, admin):
    ra = _room(session)
    guest = make_attendee(session)

    admin('add_room_occupant', session, assignment_id=ra.id, attendee_id=guest.id)

    assert guest in ra.occupants
    assert ra.attendee in ra.occupants


def test_add_roommate_twice_is_a_no_op(session, admin):
    ra = _room(session)
    guest = make_attendee(session)
    ra.occupants.append(guest)
    session.flush()

    url = admin('add_room_occupant', session, assignment_id=ra.id, attendee_id=guest.id)

    assert 'already' in url
    assert len(ra.occupants) == 2


def test_add_roommate_to_a_full_room_is_refused(session, admin):
    ra = _room(session, capacity=1)
    guest = make_attendee(session)

    url = admin('add_room_occupant', session, assignment_id=ra.id, attendee_id=guest.id)

    assert guest not in ra.occupants
    assert 'full' in url


def test_remove_roommate(session, admin):
    ra = _room(session)
    guest = make_attendee(session)
    ra.occupants.append(guest)
    session.flush()

    admin('remove_room_occupant', session, assignment_id=ra.id, attendee_id=guest.id)

    assert guest not in ra.occupants


def test_booker_cannot_be_removed(session, admin):
    ra = _room(session)

    admin('remove_room_occupant', session, assignment_id=ra.id, attendee_id=ra.attendee_id)

    assert ra.attendee in ra.occupants


def test_editing_an_unmanaged_room_keeps_group_members(session, admin):
    ra = _room(session, capacity=4)
    app = make_application(session, ra.attendee)
    ra.lottery_application = app
    member = make_attendee(session)
    make_application(session, member, entry_type=c.GROUP_ENTRY,
                     parent_application_id=app.id)
    session.flush()
    session.refresh(app)
    # A row with no managed occupants, as loaded from the DB (clearing in-session
    # would let the booker presave refill it on the next autoflush).
    session.execute(room_assignment_occupant.delete().where(
        room_assignment_occupant.c.room_assignment_id == ra.id))
    session.expire(ra, ['occupants'])
    guest = make_attendee(session)

    admin('add_room_occupant', session, assignment_id=ra.id, attendee_id=guest.id)

    assert set(ra.occupants) == {ra.attendee, member, guest}


def _invite(session, ra, token='DEMO-INVITE'):
    from uber.models.hotel import RoomAssignmentInvite

    invite = RoomAssignmentInvite(room_assignment_id=ra.id, invite_token=token)
    session.add(invite)
    session.flush()
    return invite


def test_pending_invites_count_against_capacity(session, admin):
    ra = _room(session, capacity=2)
    _invite(session, ra)
    guest = make_attendee(session)

    url = admin('add_room_occupant', session, assignment_id=ra.id, attendee_id=guest.id)

    assert guest not in ra.occupants
    assert 'full' in url


def test_add_roommate_fills_the_last_spot(session, admin):
    ra = _room(session, capacity=3)
    _invite(session, ra)
    guest = make_attendee(session)

    admin('add_room_occupant', session, assignment_id=ra.id, attendee_id=guest.id)

    assert guest in ra.occupants


def test_cancel_invite(session, admin):
    from uber.models.hotel import RoomAssignmentInvite

    ra = _room(session)
    invite = _invite(session, ra)

    admin('cancel_room_occupant_invite', session, assignment_id=ra.id, invite_id=invite.id)

    assert session.get(RoomAssignmentInvite, invite.id) is None


def test_cancel_invite_from_another_room_is_refused(session, admin):
    from uber.models.hotel import RoomAssignmentInvite

    invite = _invite(session, _room(session))

    admin('cancel_room_occupant_invite', session, assignment_id=_room(session).id,
          invite_id=invite.id)

    assert session.get(RoomAssignmentInvite, invite.id) is not None
