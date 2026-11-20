"""Leaving a lottery group after joining by an emailed invite."""
import pytest

from uber.config import c
from uber.errors import HTTPRedirect

from tests.hotel.factories import make_application, make_attendee


def _leave(post_request, session, monkeypatch, member_app):
    monkeypatch.setattr(post_request.EmailService, 'queue_email', lambda *a, **k: None)
    handler = post_request.Root.leave_group
    while hasattr(handler, '__wrapped__'):
        handler = handler.__wrapped__
    with pytest.raises(HTTPRedirect):
        handler(post_request.Root(), session, id=member_app.id)
    session.flush()


def _accepted_member(session, leader_app):
    return make_application(session, make_attendee(session, 'Ivy', 'Invitee'),
                            status=c.COMPLETE, entry_type=c.GROUP_ENTRY, can_edit=True,
                            parent_application_id=leader_app.id, invited_by_id=leader_app.id,
                            invite_status=c.INVITE_ACCEPTED)


def test_accepted_member_can_leave_a_locked_leader(session, post_request, monkeypatch):
    leader_app = make_application(session, make_attendee(session, 'Lee', 'Leader'),
                                  status=c.AWARDED, room_group_name='Lee Group')
    member_app = _accepted_member(session, leader_app)
    assert leader_app.locked

    _leave(post_request, session, monkeypatch, member_app)

    assert member_app.parent_application_id is None
    assert member_app.status == c.WITHDRAWN


def test_accepted_member_cannot_leave_an_unlocked_leader(session, post_request, monkeypatch):
    leader_app = make_application(session, make_attendee(session, 'Lee', 'Leader'),
                                  status=c.COMPLETE, room_group_name='Lee Group', can_edit=True)
    member_app = _accepted_member(session, leader_app)
    assert not leader_app.locked

    _leave(post_request, session, monkeypatch, member_app)

    assert member_app.parent_application_id == leader_app.id
    assert member_app.status == c.COMPLETE
