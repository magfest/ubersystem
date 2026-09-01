"""Staff hotel eligibility: the two independent flags (staff lottery vs
shared room), the hotel_room_kind summary, the solver pool respecting a
revoked staffer, the eligible_attendees API shapes, and the eligibility
page hiding every shared-room control when no checklist system is
configured."""

import inspect

import cherrypy

from uber.config import c

from tests.hotel.factories import (N, make_application, make_assignment,
                                   make_attendee, make_hotel, make_inventory,
                                   make_run)


class _SessionCM:
    """Stand-in for uber.api.Session() that yields the test session and
    never commits, so the per-test rollback still isolates everything."""
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, *args):
        return False


# ---------------------------------------------------------------------------
# The two flags
# ---------------------------------------------------------------------------

def test_staff_lottery_eligible_defaults_true(session):
    attendee = make_attendee(session)
    assert attendee.staff_lottery_eligible is True
    assert attendee.hotel_eligible is False


def test_staff_hotel_lottery_eligible_requires_staff_badge_and_flag(session):
    staffer = make_attendee(session, badge_type=c.STAFF_BADGE)
    assert staffer.staff_hotel_lottery_eligible is True

    staffer.staff_lottery_eligible = False
    assert staffer.staff_hotel_lottery_eligible is False

    attendee = make_attendee(session, badge_type=c.ATTENDEE_BADGE)
    assert attendee.staff_lottery_eligible is True
    assert attendee.staff_hotel_lottery_eligible is False, \
        'a non-staff badge never qualifies, whatever the flag says'


def test_the_two_flags_gate_independently(session):
    staffer = make_attendee(session, badge_type=c.STAFF_BADGE,
                            hotel_eligible=True, staff_lottery_eligible=False)
    assert staffer.hotel_eligible is True
    assert staffer.staff_hotel_lottery_eligible is False

    staffer.hotel_eligible = False
    staffer.staff_lottery_eligible = True
    assert staffer.hotel_eligible is False
    assert staffer.staff_hotel_lottery_eligible is True


# ---------------------------------------------------------------------------
# hotel_room_kind
# ---------------------------------------------------------------------------

def _staffer_with_room(session, **assignment_overrides):
    inv = make_inventory(session, make_hotel(session))
    staffer = make_attendee(session, badge_type=c.STAFF_BADGE)
    make_assignment(session, staffer, inv, check_in=N[1], check_out=N[3],
                    **assignment_overrides)
    return staffer


def test_hotel_room_kind_no_room(session):
    assert make_attendee(session).hotel_room_kind == ''


def test_hotel_room_kind_lottery_by_reason(session):
    staffer = _staffer_with_room(session, assignment_reason=c.LOTTERY_AWARD)
    assert staffer.hotel_room_kind == 'lottery'


def test_hotel_room_kind_lottery_by_run(session):
    run = make_run(session)
    staffer = _staffer_with_room(session, assignment_reason=c.MANUAL,
                                 lottery_run_id=run.id)
    assert staffer.hotel_room_kind == 'lottery'


def test_hotel_room_kind_shared(session):
    staffer = _staffer_with_room(session, assignment_reason=c.STAFF_AUTO)
    assert staffer.hotel_room_kind == 'shared'


def test_hotel_room_kind_other(session):
    staffer = _staffer_with_room(session, assignment_reason=c.MANUAL)
    assert staffer.hotel_room_kind == 'other'


def test_hotel_room_kind_mixed(session):
    inv = make_inventory(session, make_hotel(session))
    staffer = make_attendee(session, badge_type=c.STAFF_BADGE)
    make_assignment(session, staffer, inv, check_in=N[1], check_out=N[3],
                    assignment_reason=c.LOTTERY_AWARD)
    make_assignment(session, staffer, inv, check_in=N[1], check_out=N[3],
                    assignment_reason=c.STAFF_AUTO)
    assert staffer.hotel_room_kind == 'mixed'


def test_hotel_room_kind_ignores_dead_rooms(session):
    staffer = _staffer_with_room(session, assignment_reason=c.LOTTERY_AWARD,
                                 status=c.CANCELLED)
    assert staffer.hotel_room_kind == ''


# ---------------------------------------------------------------------------
# Solver pool
# ---------------------------------------------------------------------------

def test_revoked_staffer_drops_out_of_staff_pool(session):
    from uber.hotel.solver import build_eligible_applications

    kept = make_attendee(session, badge_type=c.STAFF_BADGE)
    revoked = make_attendee(session, badge_type=c.STAFF_BADGE)
    kept_app = make_application(session, kept, entry_type=c.ROOM_ENTRY,
                                is_staff_entry=True)
    revoked_app = make_application(session, revoked, entry_type=c.ROOM_ENTRY,
                                   is_staff_entry=True)

    ids = {app.id for app in
           build_eligible_applications(session, c.ROOM_ENTRY, 'staff')}
    assert kept_app.id in ids and revoked_app.id in ids

    revoked.staff_lottery_eligible = False
    session.flush()

    ids = {app.id for app in
           build_eligible_applications(session, c.ROOM_ENTRY, 'staff')}
    assert kept_app.id in ids
    assert revoked_app.id not in ids, \
        'revoking eligibility after entry must remove the app from the pool'


# ---------------------------------------------------------------------------
# eligible_attendees API shapes
# ---------------------------------------------------------------------------

def _eligible_attendees(session, monkeypatch, **kwargs):
    import uber.api

    monkeypatch.setattr(uber.api, 'Session', lambda: _SessionCM(session))
    fn = inspect.unwrap(uber.api.HotelLookup.eligible_attendees)
    return fn(uber.api.HotelLookup(), **kwargs)


def test_eligible_attendees_full_false_string_returns_bare_ids(
        session, monkeypatch):
    eligible = make_attendee(session, hotel_eligible=True)

    result = _eligible_attendees(session, monkeypatch, full='false')
    assert eligible.id in result
    assert all(isinstance(entry, str) for entry in result), \
        'a JSON-RPC "false" string must keep the bare id-list shape'

    result = _eligible_attendees(session, monkeypatch)
    assert eligible.id in result
    assert all(isinstance(entry, str) for entry in result)


def test_eligible_attendees_full_dict_shape(session, monkeypatch):
    eligible = make_attendee(session, hotel_eligible=True)

    for full in (True, 'true'):
        result = _eligible_attendees(session, monkeypatch, full=full)
        entry = next(e for e in result if e['id'] == eligible.id)
        assert entry['first_name'] == eligible.first_name
        assert entry['hotel_eligible'] is True
        assert entry['staff_lottery_eligible'] is True
        assert 'has_live_room' not in entry, \
            'the query already excludes live rooms, so the key is meaningless'


# ---------------------------------------------------------------------------
# The eligibility page with and without a checklist system
# ---------------------------------------------------------------------------

def _render_eligibility_page(session, shared_enabled):
    from uber.decorators import render

    staffer = make_attendee(session, badge_type=c.STAFF_BADGE)
    html = render('staff_rooming/hotel_eligibility.html', {
        'message': '',
        'staffers': [staffer],
        'page': 1,
        'page_size': 50,
        'total': 1,
        'page_count': 1,
        'show': 'all',
        'search': '',
        'shared_enabled': shared_enabled,
        'total_staff': 1,
        'total_eligible': 0,
        'total_ineligible': 1,
        'total_staff_lottery': 1,
        'total_not_staff_lottery': 0,
    })
    return html.decode('utf-8') if isinstance(html, bytes) else html


def test_eligibility_page_hides_shared_controls_without_checklist(
        session, no_cherrypy_session):
    text = _render_eligibility_page(session, shared_enabled=False)

    assert 'tuber-status' not in text
    assert 'Shared room request' not in text
    assert 'data-field="shared_room"' not in text
    assert 'value="shared_room"' not in text
    assert 'value="not_shared"' not in text

    assert 'data-field="staff_lottery"' in text
    assert 'value="staff_lottery"' in text
    assert 'Staff lottery eligible: 1' in text
    assert 'Shared room eligible' not in text


def test_eligibility_page_shows_shared_controls_with_checklist(
        session, no_cherrypy_session):
    text = _render_eligibility_page(session, shared_enabled=True)

    assert 'Shared room request' in text
    assert 'data-field="shared_room"' in text
    assert 'class="tuber-status"' in text
    assert 'Shared room eligible: 0' in text

    # The status script must land in the body, not inside <title> where an
    # include in the title block would render it as inert text.
    head, _sep, body = text.partition('</title>')
    assert 'tuber-status.js' not in head
    assert 'tuber-status.js' in body
