"""Partition owners with can_edit_assignments manage roommates on their
partition's rooms from the dashboard; no one else can."""

import pytest

from uber.config import c
from uber.errors import HTTPRedirect

from tests.hotel.factories import (make_assignment, make_attendee, make_hotel, make_inventory,
                                   make_partition, make_partition_block)


@pytest.fixture
def owner(session, post_request, monkeypatch):
    """Drive partition_admin handlers through the capability gate as an
    AdminAccount whose grant flags the test sets."""
    import uber.site_sections.partition_admin as site
    from uber.hotel.perms import requires_partition_capability
    from uber.models import AdminAccount, PartitionOwner

    account = AdminAccount(attendee=make_attendee(session), hashed='')
    session.add(account)
    session.flush()
    monkeypatch.setattr(session, 'current_admin_account', lambda: account, raising=False)
    monkeypatch.setattr(site, 'check_csrf', lambda *a, **k: None)
    gate_code = requires_partition_capability('x')(lambda self, session: None).__code__

    def grant(partition, **flags):
        session.add(PartitionOwner(admin_account_id=account.id, partition_id=partition.id, **flags))
        session.flush()

    def call(name, **kwargs):
        func = getattr(site.Root, name)
        while hasattr(func, '__wrapped__') and func.__code__ is not gate_code:
            func = func.__wrapped__
        with pytest.raises(HTTPRedirect) as excinfo:
            func(site.Root(), session, **kwargs)
        return excinfo.value.urls[0]

    call.grant = grant
    return call


@pytest.fixture
def room(session):
    inv = make_inventory(session, make_hotel(session), capacity=2)
    partition = make_partition(session)
    make_partition_block(session, partition, inv, 2)
    return make_assignment(session, make_attendee(session), inventory=inv,
                           partition_id=partition.id, status=c.ASSIGNED)


def test_owner_adds_and_removes_a_roommate(session, owner, room):
    owner.grant(room.partition, can_edit_assignments=True)
    guest = make_attendee(session)

    url = owner('add_occupant', assignment_id=room.id, attendee_id=guest.id, page='2')
    assert guest in room.occupants
    assert f'edit={room.attendee_id}' in url and 'page=2' in url

    owner('remove_occupant', assignment_id=room.id, attendee_id=guest.id)
    assert guest not in room.occupants


def test_owner_cancels_an_invite(session, owner, room):
    from uber.models.hotel import RoomAssignmentInvite

    owner.grant(room.partition, can_edit_assignments=True)
    invite = RoomAssignmentInvite(room_assignment_id=room.id, invite_token='DEMO-INVITE')
    session.add(invite)
    session.flush()

    owner('cancel_occupant_invite', assignment_id=room.id, invite_id=invite.id)

    assert session.get(RoomAssignmentInvite, invite.id) is None


def test_owner_cannot_overfill_a_room(session, owner, room):
    owner.grant(room.partition, can_edit_assignments=True)
    room.occupants.append(make_attendee(session))
    session.flush()
    guest = make_attendee(session)

    url = owner('add_occupant', assignment_id=room.id, attendee_id=guest.id)

    assert guest not in room.occupants
    assert 'full' in url


def test_view_only_owner_is_refused(session, owner, room):
    owner.grant(room.partition, can_edit_assignments=False)
    guest = make_attendee(session)

    url = owner('add_occupant', assignment_id=room.id, attendee_id=guest.id)

    assert guest not in room.occupants
    assert 'permission' in url


def test_owner_of_another_partition_is_refused(session, owner, room):
    owner.grant(make_partition(session), can_edit_assignments=True)
    guest = make_attendee(session)
    room.occupants.append(guest)
    session.flush()

    owner('remove_occupant', assignment_id=room.id, attendee_id=guest.id)

    assert guest in room.occupants
