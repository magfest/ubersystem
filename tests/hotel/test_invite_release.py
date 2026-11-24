"""Releasing room group invites before a lottery entry is deleted or withdrawn."""
import pytest

from uber.config import c
from uber.errors import HTTPRedirect
from uber.models.hotel import LotteryApplication

from tests.hotel.factories import make_application, make_attendee


def _invitee(session, leader_app, invite_status, token=''):
    return make_application(session, make_attendee(session, 'Ivy', 'Invitee'),
                            status=c.PARTIAL, entry_type=c.GROUP_ENTRY,
                            invited_by_id=leader_app.id, invite_status=invite_status,
                            invite_token=token)


def test_leader_entry_deletes_after_releasing_an_accepted_invite(session):
    leader_app = make_application(session, make_attendee(session, 'Lee', 'Leader'))
    invitee_app = _invitee(session, leader_app, c.INVITE_ACCEPTED)

    leader_app.release_invites(session)
    session.delete(leader_app)
    session.flush()

    session.refresh(invitee_app)
    assert invitee_app.invited_by_id is None
    assert invitee_app.invite_status == c.INVITE_ACCEPTED


def test_release_cancels_a_pending_invite(session):
    leader_app = make_application(session, make_attendee(session, 'Lee', 'Leader'))
    invitee_app = _invitee(session, leader_app, c.INVITE_PENDING, token='tok-123')

    leader_app.release_invites(session)
    session.flush()

    assert invitee_app.invited_by_id is None
    assert invitee_app.invite_status == c.INVITE_CANCELLED
    assert invitee_app.invite_token == ''


def test_release_leaves_other_leaders_invites_alone(session):
    leader_app = make_application(session, make_attendee(session, 'Lee', 'Leader'))
    other_app = make_application(session, make_attendee(session, 'Otto', 'Other'))
    other_invitee = _invitee(session, other_app, c.INVITE_PENDING, token='tok-456')

    leader_app.release_invites(session)
    session.flush()

    assert other_invitee.invited_by_id == other_app.id
    assert other_invitee.invite_status == c.INVITE_PENDING


def test_withdrawing_cancels_the_leaders_pending_invites(session, post_request):
    leader_app = make_application(session, make_attendee(session, 'Lee', 'Leader'),
                                  status=c.PARTIAL, room_group_name='Lee Group')
    invitee_app = _invitee(session, leader_app, c.INVITE_PENDING, token='tok-789')

    handler = post_request.Root.withdraw_entry
    while hasattr(handler, '__wrapped__'):
        handler = handler.__wrapped__
    with pytest.raises(HTTPRedirect):
        handler(post_request.Root(), session, id=leader_app.id)
    session.flush()

    assert invitee_app.invited_by_id is None
    assert invitee_app.invite_status == c.INVITE_CANCELLED
    assert session.query(LotteryApplication).filter_by(invite_token='tok-789').count() == 0


def test_deleting_the_group_cancels_the_leaders_pending_invites(session, post_request):
    leader_app = make_application(session, make_attendee(session, 'Lee', 'Leader'),
                                  status=c.PARTIAL, room_group_name='Lee Group')
    invitee_app = _invitee(session, leader_app, c.INVITE_PENDING, token='tok-321')

    handler = post_request.Root.delete_group
    while hasattr(handler, '__wrapped__'):
        handler = handler.__wrapped__
    with pytest.raises(HTTPRedirect):
        handler(post_request.Root(), session, id=leader_app.id)
    session.flush()

    assert invitee_app.invited_by_id is None
    assert invitee_app.invite_status == c.INVITE_CANCELLED
    assert invitee_app.invite_token == ''
