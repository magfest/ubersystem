"""Rooms that no longer hold inventory (EXPIRED, CANCELLED) are read-only on
the attendee hotel pages. Every write handler refuses them except leave_room,
so an occupant can still take themselves off a released room."""

from datetime import date

import cherrypy
import pytest

from uber.config import c
from uber.errors import HTTPRedirect

from tests.hotel.factories import (make_application, make_assignment,
                                   make_attendee, make_hotel, make_inventory)

INACTIVE = [c.EXPIRED, c.CANCELLED]


@pytest.fixture
def post_request(monkeypatch, session, no_cherrypy_session):
    """Drive handlers as a POST with CSRF and ownership checks stubbed out;
    those gates have their own coverage and are not what these tests probe.
    Commits become flushes so the per-test rollback still undoes them."""
    import uber.site_sections.hotel_lottery as hotel_lottery
    from uber.models import initialize_db

    # Registers session.attendee() and the other model getters, which the
    # app only does when the CherryPy engine starts.
    initialize_db()
    monkeypatch.setattr(cherrypy.request, 'method', 'POST')
    monkeypatch.setattr(hotel_lottery, 'check_csrf', lambda *a, **k: None)
    monkeypatch.setattr(hotel_lottery, '_require_room_access', lambda *a, **k: None)
    monkeypatch.setattr(hotel_lottery, '_require_view_as_attendee', lambda *a, **k: None)
    monkeypatch.setattr(session, 'commit', session.flush)
    return hotel_lottery


def _handler(name):
    """Return Root.<name> unwrapped down to its room_action layer, or fully
    unwrapped when the handler does not use room_action. Stopping at
    room_action keeps the guard under test in the call path."""
    from uber.site_sections.hotel_lottery import Root, room_action

    room_action_code = room_action(lambda *a, **k: None).__code__
    func = getattr(Root, name)
    while hasattr(func, '__wrapped__') and func.__code__ is not room_action_code:
        func = func.__wrapped__
    return lambda session, **kwargs: func(Root(), session, **kwargs)


def _redirect_url(excinfo):
    return excinfo.value.urls[0]


def _room(session, status, **overrides):
    inventory = make_inventory(session, make_hotel(session))
    return make_assignment(session, make_attendee(session), inventory=inventory,
                           status=status, check_in=date(2027, 1, 6),
                           check_out=date(2027, 1, 10), **overrides)


@pytest.mark.parametrize('status', INACTIVE)
def test_section_save_refuses_an_inactive_room(session, post_request, status):
    ra = _room(session, status, special_requests='')

    with pytest.raises(HTTPRedirect):
        _handler('save_special_requests')(
            session, assignment_id=ra.id, special_requests='Late checkout')

    assert ra.special_requests == ''


def test_section_save_still_works_on_a_live_room(session, post_request):
    ra = _room(session, c.ASSIGNED, special_requests='')

    with pytest.raises(HTTPRedirect):
        _handler('save_special_requests')(
            session, assignment_id=ra.id, special_requests='Late checkout')

    assert ra.special_requests == 'Late checkout'


def test_occupant_can_leave_an_inactive_room(session, post_request, monkeypatch):
    ra = _room(session, c.EXPIRED)
    guest = make_attendee(session)
    ra.occupants.append(guest)
    session.flush()
    monkeypatch.setattr(post_request, '_viewer_attendee', lambda s: guest)

    with pytest.raises(HTTPRedirect):
        _handler('leave_room')(session, assignment_id=ra.id)

    assert guest not in ra.occupants


@pytest.mark.parametrize('status', INACTIVE)
def test_edit_room_refuses_an_inactive_room(session, post_request, status):
    ra = _room(session, status)
    app = make_application(session, ra.attendee)
    ra.lottery_application_id = app.id
    session.flush()

    with pytest.raises(HTTPRedirect):
        _handler('edit_room')(
            session, id=app.id, assignment_id=ra.id,
            assigned_check_in_date='2027-01-05',
            assigned_check_out_date='2027-01-10')

    assert ra.assigned_check_in_date == date(2027, 1, 6)


def test_copy_occupants_refuses_an_inactive_room(session, post_request):
    target = _room(session, c.EXPIRED)
    sibling = make_assignment(session, target.attendee,
                              inventory=target.inventory, status=c.SECURED)
    guest = make_attendee(session)
    sibling.occupants.append(guest)
    session.flush()

    with pytest.raises(HTTPRedirect):
        _handler('copy_occupants')(
            session, target_assignment_id=target.id,
            source_attendee_ids=str(guest.id))

    assert guest not in target.occupants


def _invite(session, ra):
    from uber.models.hotel import RoomAssignmentInvite

    invite = RoomAssignmentInvite(room_assignment_id=ra.id,
                                  invite_token='inactive-room-test-code')
    session.add(invite)
    session.flush()
    return invite


def test_redeem_code_refuses_an_inactive_room(session, post_request):
    invite = _invite(session, _room(session, c.EXPIRED))

    with pytest.raises(HTTPRedirect) as excinfo:
        _handler('redeem_code')(session, code=invite.invite_token)

    assert 'invite?token' not in _redirect_url(excinfo)


def test_accepting_an_invite_to_an_inactive_room_does_not_join(session, post_request):
    ra = _room(session, c.EXPIRED)
    invite = _invite(session, ra)
    guest = make_attendee(session)

    try:
        _handler('invite')(session, token=invite.invite_token, action='accept',
                           attendee_id=guest.id)
    except HTTPRedirect:
        pass

    assert guest not in ra.occupants


def test_rooms_list_separates_inactive_rooms(session, post_request):
    attendee = make_attendee(session)
    inventory = make_inventory(session, make_hotel(session))
    live = make_assignment(session, attendee, inventory=inventory, status=c.SECURED)
    expired = make_assignment(session, attendee, inventory=inventory, status=c.EXPIRED)

    ctx = _handler('rooms')(session, attendee_id=attendee.id)

    assert ctx['primaries'] == [live]
    assert ctx['inactive_rooms'] == [expired]


def test_live_connector_of_an_expired_suite_stays_in_the_live_list(session, post_request):
    attendee = make_attendee(session)
    inventory = make_inventory(session, make_hotel(session))
    suite = make_assignment(session, attendee, inventory=inventory, status=c.EXPIRED)
    connector = make_assignment(session, attendee, inventory=inventory,
                                status=c.SECURED, parent_assignment_id=suite.id)

    ctx = _handler('rooms')(session, attendee_id=attendee.id)

    assert ctx['primaries'] == [connector]
    assert ctx['inactive_rooms'] == [suite]


def test_guest_rooms_separate_inactive_rooms(session, post_request):
    guest = make_attendee(session)
    live = _room(session, c.SECURED)
    expired = _room(session, c.EXPIRED)
    for ra in (live, expired):
        ra.occupants.append(guest)
    session.flush()

    ctx = _handler('rooms')(session, attendee_id=guest.id)

    assert ctx['guest_in'] == [live]
    assert ctx['inactive_rooms'] == [expired]


def _render_rooms_list(session, attendee):
    from uber.jinja import JinjaEnv

    ctx = _handler('rooms')(session, attendee_id=attendee.id)
    ctx['c'] = c
    return JinjaEnv.env().get_template('hotel_lottery/rooms.html').render(ctx)


def test_rooms_list_shows_inactive_rooms_read_only(session, post_request):
    ra = _room(session, c.CANCELLED)

    html = _render_rooms_list(session, ra.attendee)

    assert 'Inactive rooms' in html
    assert 'This reservation was cancelled.' in html
    assert f'room?id={ra.id}&attendee_id={ra.attendee_id}" class="btn btn-sm btn-outline-secondary">View' in html
    assert 'Edit' not in html
    assert 'Rooms you booked' not in html


def test_rooms_list_with_only_inactive_rooms_says_none_are_active(session, post_request):
    ra = _room(session, c.EXPIRED)

    html = _render_rooms_list(session, ra.attendee)

    assert "You don't have any active room assignments." in html


def test_inactive_connector_under_a_live_suite_offers_view_only(session, post_request):
    suite = _room(session, c.SECURED)
    connector = make_assignment(session, suite.attendee, inventory=suite.inventory,
                                status=c.CANCELLED, parent_assignment_id=suite.id)

    html = _render_rooms_list(session, suite.attendee)

    child_link = f'room?id={connector.id}&attendee_id={suite.attendee_id}'
    assert html.split(child_link, 1)[1].split('</a>', 1)[0].strip().endswith('View')


def _render_room_page(session, ra):
    from uber.jinja import JinjaEnv
    from uber.site_sections.hotel_lottery import _render_room_detail

    ctx = _render_room_detail(session, ra.id, ra.attendee_id, '')
    ctx['c'] = c
    return JinjaEnv.env().get_template('hotel_lottery/room.html').render(ctx)


def test_room_page_for_an_inactive_room_has_no_forms_but_explains(session, post_request):
    ra = _room(session, c.EXPIRED, deposit_cutoff_date=date(2026, 9, 23))

    html = _render_room_page(session, ra)

    assert '<form' not in html
    assert 'Card due by' not in html
    assert 'no card was on file by Wednesday, September 23' in html


def test_room_page_for_a_live_room_still_has_forms(session, post_request):
    ra = _room(session, c.ASSIGNED)

    html = _render_room_page(session, ra)

    assert 'action="edit_room"' in html
