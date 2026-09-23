"""Attendee-facing hotel pages under Keycloak (OIDC) login.

Keycloak logins put the account ids on `cherrypy.request`
(`attendee_account` / `admin_account`) and never write the
`attendee_account_id` / `account_id` session keys. The hotel pages used
to read only the session, so an OIDC attendee looked anonymous, and a
staffer logged in with just their admin identity was refused their own
badge's rooms ("You do not have permission to view that attendee")
even though requires_account had already let them through.
"""

import uuid

import cherrypy
import pytest

from uber.config import c

from tests.hotel.factories import (N, make_assignment, make_attendee,
                                   make_hotel, make_inventory)


@pytest.fixture
def oidc_request(monkeypatch):
    """An OIDC-style request: empty cherrypy session, identity on the
    request object. Returns a setter for the two account ids."""
    # The per-model session getters (session.admin_account(id), ...) are
    # registered on cherrypy engine start, which tests never run.
    from uber.models import initialize_db
    initialize_db()
    monkeypatch.setattr(cherrypy, 'session', {}, raising=False)
    monkeypatch.setattr(c, 'HAS_HOTEL_LOTTERY_ADMIN_ACCESS', False, raising=False)

    def login(attendee_account=None, admin_account=None):
        monkeypatch.setattr(cherrypy.request, 'attendee_account',
                            attendee_account.id if attendee_account else None,
                            raising=False)
        monkeypatch.setattr(cherrypy.request, 'admin_account',
                            admin_account.id if admin_account else None,
                            raising=False)
    return login


def _attendee_account(session, *attendees):
    from uber.models import AttendeeAccount
    aa = AttendeeAccount(email=f'acct-{uuid.uuid4().hex[:8]}@example.com')
    session.add(aa)
    session.flush()
    for a in attendees:
        aa.attendees.append(a)
    session.flush()
    return aa


def _admin_account(session, attendee):
    from uber.models import AdminAccount
    admin = AdminAccount(attendee=attendee, hashed='x')
    session.add(admin)
    session.flush()
    return admin


def _room(session, attendee):
    inv = make_inventory(session, make_hotel(session), quantity=2)
    return make_assignment(session, attendee, inv, check_in=N[1], check_out=N[3])


def test_oidc_attendee_is_the_viewer(session, oidc_request):
    from uber.site_sections.hotel_lottery import _can_view_as_attendee, _viewer_attendee
    me, stranger = make_attendee(session), make_attendee(session)
    oidc_request(attendee_account=_attendee_account(session, me))

    assert _viewer_attendee(session) == me
    assert _can_view_as_attendee(session, me.id)
    assert not _can_view_as_attendee(session, stranger.id)


def test_oidc_attendee_sees_own_room_without_attendee_id(session, oidc_request):
    from uber.site_sections.hotel_lottery import _render_room_detail
    me = make_attendee(session)
    ra = _room(session, me)
    oidc_request(attendee_account=_attendee_account(session, me))

    ctx = _render_room_detail(session, ra.id, None, '')

    assert ctx['viewer'] == me
    assert ctx['is_leader']


def test_staff_admin_login_can_view_own_badge_rooms(session, oidc_request):
    """Admin identity only (no attendee account on the request)."""
    from uber.site_sections.hotel_lottery import (_can_view_as_attendee,
                                                  _render_room_detail,
                                                  _viewer_attendee)
    me, stranger = make_attendee(session), make_attendee(session)
    ra = _room(session, me)
    oidc_request(admin_account=_admin_account(session, me))

    assert _viewer_attendee(session) == me
    assert _can_view_as_attendee(session, me.id)
    assert not _can_view_as_attendee(session, stranger.id), \
        'an admin without lottery access still cannot view other attendees'

    ctx = _render_room_detail(session, ra.id, me.id, '')
    assert ctx['is_leader']


def test_staff_admin_login_refused_someone_elses_room(session, oidc_request):
    from uber.errors import HTTPRedirect
    from uber.site_sections.hotel_lottery import _render_room_detail
    me, stranger = make_attendee(session), make_attendee(session)
    ra = _room(session, stranger)
    oidc_request(admin_account=_admin_account(session, me))

    with pytest.raises(HTTPRedirect):
        _render_room_detail(session, ra.id, stranger.id, '')


def test_perms_resolves_admin_from_oidc_request(session, oidc_request):
    from uber.hotel.perms import _current_admin_account
    admin = _admin_account(session, make_attendee(session))
    oidc_request(admin_account=admin)

    assert _current_admin_account(session) == admin
