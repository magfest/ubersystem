"""Staffers can see their staff crash space room but not change it."""

from datetime import date

import pytest

from uber.config import c
from uber.errors import HTTPRedirect
from uber.jinja import JinjaEnv
from uber.models.hotel import room_assignment_occupant

from tests.hotel.factories import make_assignment, make_attendee, make_hotel, make_inventory
from tests.hotel.test_inactive_rooms import _handler, _redirect_url, _render_rooms_list

CHECK_IN, CHECK_OUT = date(2027, 1, 6), date(2027, 1, 10)


@pytest.fixture
def crash(session):
    """A crash space room: one booker, one roommate arriving a day late."""
    booker, mate = (make_attendee(session, badge_type=c.STAFF_BADGE) for _ in range(2))
    ra = make_assignment(session, booker, make_inventory(session, make_hotel(session)), check_in=CHECK_IN,
                         check_out=CHECK_OUT, assignment_reason=c.STAFF_CRASH_SPACE, payment_type='masterbill',
                         special_requests='')
    # The booker's own occupant row is added with the room.
    session.execute(room_assignment_occupant.insert().values(
        room_assignment_id=ra.id, attendee_id=mate.id, check_in_date=date(2027, 1, 7)))
    session.expire_all()
    return ra, booker, mate


def _room_page(session, ra, viewer):
    from uber.site_sections.hotel_lottery import _render_room_detail

    ctx = _render_room_detail(session, ra.id, viewer.id, '')
    ctx['c'] = c
    return JinjaEnv.env().get_template('hotel_lottery/room.html').render(ctx)


def test_booker_and_roommate_see_the_room_read_only(session, post_request, crash):
    ra, booker, mate = crash
    ra.special_requests = 'Near the elevator'
    ra.hotel_rewards_number = 'REWARDS-123'
    session.flush()
    for viewer in (booker, mate):
        html = _room_page(session, ra, viewer)
        # No one is the leader: the same sections show for everyone.
        assert 'Near the elevator' in html
        assert 'Booker' not in html and 'REWARDS-123' not in html and 'Card on file' not in html
        assert 'staff crash space room' in html
        assert '<form' not in html
        assert booker.email in html and mate.email in html
        assert 'Thu Jan 7' in html, "the roommate's own check-in shows"
        assert 'transferred to the hotel' not in html


@pytest.mark.parametrize('action, params', [
    ('save_special_requests', {'special_requests': 'Late checkout'}),
    ('leave_room', {}),
    ('remove_occupant', {}),
    ('invite_code', {}),
])
def test_staffers_cannot_change_the_room(session, post_request, monkeypatch, crash, action, params):
    ra, booker, mate = crash
    viewer = mate if action == 'leave_room' else booker
    monkeypatch.setattr(post_request, '_viewer_attendee', lambda s: viewer)
    if action == 'remove_occupant':
        params = {'occupant_attendee_id': mate.id}

    with pytest.raises(HTTPRedirect) as excinfo:
        _handler(action)(session, assignment_id=ra.id, **params)

    assert 'assigned%20by%20staffing' in _redirect_url(excinfo)
    session.expire_all()
    assert not ra.special_requests
    assert {occ.id for occ in ra.occupants} == {booker.id, mate.id}


def test_staffers_cannot_edit_dates_or_cancel(session, post_request, monkeypatch, crash):
    ra, booker, _ = crash
    monkeypatch.setattr(post_request, '_viewer_attendee', lambda s: booker)

    for action, params in [('edit_room', {'assigned_check_in_date': '2027-01-07',
                                          'assigned_check_out_date': '2027-01-09'}),
                           ('decline', {})]:
        with pytest.raises(HTTPRedirect):
            _handler(action)(session, assignment_id=ra.id, attendee_id=booker.id, **params)
    session.expire_all()
    assert ra.status == c.ASSIGNED
    assert (ra.assigned_check_in_date, ra.assigned_check_out_date) == (CHECK_IN, CHECK_OUT)


def test_rooms_list_offers_view_only(session, post_request, crash):
    ra, booker, mate = crash

    for viewer in (booker, mate):
        html = _render_rooms_list(session, viewer)
        assert f'room?id={ra.id}&attendee_id={viewer.id}' in html
        assert 'Staff crash space' in html
        for leader_only in ('Edit', 'decline?', 'action="leave_room"', 'Rooms you booked', 'guest in', 'Booked by'):
            assert leader_only not in html


def test_roommates_count_as_having_a_room(session, crash):
    ra, booker, mate = crash
    assert [room.id for room in booker.live_released_rooms] == [ra.id]
    assert [room.id for room in mate.live_released_rooms] == [ra.id]
