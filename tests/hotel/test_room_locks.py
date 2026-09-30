"""Room locks (RoomAssignment.locked), separate from export status: locked
rooms are read-only for attendees, exported rooms are not, and connectors
follow their suite's lock.
"""

import contextlib
import re
import uuid
from datetime import date, datetime, timezone
from urllib.parse import unquote

import cherrypy
import pytest

import uber.site_sections.hotel_lottery as hl
import uber.site_sections.hotel_lottery_admin as hla
from uber.config import c
from uber.errors import HTTPRedirect
from uber.forms.hotel_lottery import HotelInventoryConfig
from uber.hotel.service import apply_room_assignment_edits
from uber.jinja import JinjaEnv
from uber.models import AttendeeAccount, initialize_db
import uber.tasks.hotel as hotel_tasks

from tests.hotel.factories import (N, make_application, make_assignment,
                                   make_attendee, make_hotel, make_inventory,
                                   make_run)


def _inv(session, **kw):
    return make_inventory(session, make_hotel(session), quantity=10, **kw)


# ---------------------------------------------------------------------------
# Where a lock comes from
# ---------------------------------------------------------------------------

def test_unlocked_by_default_even_when_exported(session):
    inv = _inv(session)
    me = make_attendee(session)
    app = make_application(session, me, export_locked=True)
    ra = make_assignment(session, me, inv, check_in=N[1], check_out=N[3],
                         lottery_application_id=app.id)

    assert ra.is_exported
    assert not ra.is_locked
    assert ra.lock_source is None


@pytest.mark.parametrize('signal', ['exported_at', 'confirmation'])
def test_exported_signals(session, signal):
    inv = _inv(session)
    kw = ({'exported_at': datetime.now(timezone.utc)} if signal == 'exported_at'
          else {'hotel_confirmation_number': 'H-1'})
    ra = make_assignment(session, make_attendee(session), inv, **kw)
    assert ra.is_exported
    assert not make_assignment(session, make_attendee(session), inv).is_exported


def test_room_lock(session):
    ra = make_assignment(session, make_attendee(session), _inv(session), locked=True)
    assert ra.is_locked and ra.lock_source == 'room'


def test_connector_follows_locked_suite(session):
    me = make_attendee(session)
    suite = make_assignment(session, me, _inv(session, is_suite=True), locked=True)
    child = make_assignment(session, me, _inv(session), parent_assignment_id=suite.id,
                            assignment_reason=c.SUITE_CONNECTOR)
    session.flush()
    session.refresh(child)

    assert child.lock_source == 'suite'


# ---------------------------------------------------------------------------
# Attendee write paths
# ---------------------------------------------------------------------------

@pytest.fixture
def owner_login(session, monkeypatch):
    initialize_db()
    monkeypatch.setattr(cherrypy, 'session', {}, raising=False)
    monkeypatch.setattr(c, 'HAS_HOTEL_LOTTERY_ADMIN_ACCESS', False, raising=False)
    monkeypatch.setattr(cherrypy.request, 'admin_account', None, raising=False)
    monkeypatch.setattr(cherrypy.request, 'method', 'POST', raising=False)
    monkeypatch.setattr(hl, 'check_csrf', lambda *a, **k: None)
    monkeypatch.setattr(session, 'commit', session.flush)

    def login(attendee):
        aa = AttendeeAccount(email=f'acct-{uuid.uuid4().hex[:8]}@example.com')
        session.add(aa)
        session.flush()
        aa.attendees.append(attendee)
        session.flush()
        monkeypatch.setattr(cherrypy.request, 'attendee_account', aa.id, raising=False)
    return login


def _handler(name):
    """Root.<name> unwrapped down to its room_action layer (so the lock and
    live guards stay in the call path), or fully unwrapped when the handler
    doesn't use room_action."""
    guard_code = hl.room_action(lambda *a, **k: None).__code__
    func = getattr(hl.Root, name)
    while hasattr(func, '__wrapped__') and func.__code__ is not guard_code:
        func = func.__wrapped__
    return lambda session, **kw: func(hl.Root(), session, **kw)


def _awarded_room(session, me, **kw):
    app = make_application(session, me, status=c.AWARDED, **kw.pop('app', {}))
    ra = make_assignment(session, me, _inv(session, **kw.pop('inv', {})),
                         check_in=N[2], check_out=N[4], status=c.SECURED,
                         lottery_application_id=app.id, **kw)
    return app, ra


def _redirect_text(exc):
    return unquote(str(exc.value.urls))


def test_exported_room_is_still_editable(session, owner_login):
    me = make_attendee(session)
    app, ra = _awarded_room(session, me, app={'export_locked': True})
    owner_login(me)

    with pytest.raises(HTTPRedirect) as exc:
        _handler('edit_room')(session, id=app.id, assignment_id=ra.id,
                              attendee_id=me.id, special_requests='Late arrival')

    assert ra.special_requests == 'Late arrival'
    assert 'locked' not in _redirect_text(exc)


def test_locked_room_refuses_edits(session, owner_login):
    me = make_attendee(session)
    app, ra = _awarded_room(session, me, locked=True)
    owner_login(me)

    with pytest.raises(HTTPRedirect) as exc:
        _handler('edit_room')(session, id=app.id, assignment_id=ra.id,
                              attendee_id=me.id, special_requests='Late arrival')

    assert ra.special_requests == ''
    assert 'This room is locked' in _redirect_text(exc)


def test_card_change_refused_only_when_locked(session):
    _, exported = _awarded_room(session, make_attendee(session),
                                app={'export_locked': True})
    _, locked = _awarded_room(session, make_attendee(session), locked=True)

    ok, err = hl._secure_flow_assignment(session, exported.id)
    assert ok == exported and err is None
    ok, err = hl._secure_flow_assignment(session, locked.id)
    assert ok is None and err == {'error': hl.LOCKED_MESSAGE}


def test_locked_room_can_still_be_cancelled(session, owner_login):
    me = make_attendee(session)
    app, ra = _awarded_room(session, me, locked=True)
    owner_login(me)

    with pytest.raises(HTTPRedirect):
        _handler('decline')(session, id=app.id, assignment_id=ra.id, confirm='1')

    assert ra.status == c.CANCELLED


# ---------------------------------------------------------------------------
# Admin controls
# ---------------------------------------------------------------------------

def _admin_edit(session, ra, params):
    def fail(msg):
        raise AssertionError(msg)
    return apply_room_assignment_edits(session, ra, params,
                                       audit_prefix='Test', fail=fail)


def test_admin_checkbox_locks_and_unlocks(session):
    ra = make_assignment(session, make_attendee(session), _inv(session))

    assert 'locked' in _admin_edit(session, ra, {'locked_present': '1', 'locked': '1'})
    assert ra.locked
    assert 'unlocked' in _admin_edit(session, ra, {'locked_present': '1'})
    assert not ra.locked


def test_surfaces_without_the_checkbox_leave_the_lock_alone(session):
    ra = make_assignment(session, make_attendee(session), _inv(session), locked=True)

    _admin_edit(session, ra, {'special_requests': 'x'})

    assert ra.locked


def test_inventory_form_has_no_block_lock():
    assert not hasattr(HotelInventoryConfig, 'locked')


def _lock_run(session, run, lock):
    func = hla.Root.lock_run_rooms
    while hasattr(func, '__wrapped__'):
        func = func.__wrapped__
    with pytest.raises(HTTPRedirect) as exc:
        func(hla.Root(), session, id=run.id, lock=lock, csrf_token='x')
    return _redirect_text(exc)


@pytest.fixture
def admin_post(session, monkeypatch):
    monkeypatch.setattr(cherrypy.request, 'method', 'POST', raising=False)
    monkeypatch.setattr(hla, 'check_csrf', lambda *a, **k: None)
    monkeypatch.setattr(session, 'commit', session.flush)


def test_run_button_locks_and_unlocks_its_live_awarded_rooms(session, admin_post):
    run = make_run(session, status=c.LOTTERY_AWARDED)
    other_run = make_run(session, status=c.LOTTERY_AWARDED)
    inv = _inv(session)
    mine = [make_assignment(session, make_attendee(session), inv, status=s,
                            lottery_run_id=run.id) for s in (c.ASSIGNED, c.SECURED)]
    cancelled = make_assignment(session, make_attendee(session), inv,
                                status=c.CANCELLED, lottery_run_id=run.id)
    elsewhere = make_assignment(session, make_attendee(session), inv,
                                lottery_run_id=other_run.id)

    assert 'Locked 2 awarded rooms' in _lock_run(session, run, '1')
    assert all(ra.locked for ra in mine)
    assert not cancelled.locked and not elsewhere.locked

    assert 'Unlocked 2 awarded rooms' in _lock_run(session, run, '0')
    assert not any(ra.locked for ra in mine)


def test_run_button_only_on_awarded_runs(session, admin_post):
    run = make_run(session, status=c.LOTTERY_PENDING)
    ra = make_assignment(session, make_attendee(session), _inv(session), lottery_run_id=run.id)

    assert 'Only an awarded run' in _lock_run(session, run, '1')
    assert not ra.locked


# ---------------------------------------------------------------------------
# Card deadline
# ---------------------------------------------------------------------------

def test_locked_room_does_not_expire_at_the_card_deadline(session, monkeypatch):
    inv = _inv(session)
    kw = dict(check_in=N[2], check_out=N[4], status=c.ASSIGNED,
              payment_type='credit_card', deposit_cutoff_date=date(2026, 1, 1))
    open_room = make_assignment(session, make_attendee(session), inv, **kw)
    locked_room = make_assignment(session, make_attendee(session), inv, locked=True, **kw)
    # Run the task inside the test's transaction.
    monkeypatch.setattr(session, 'commit', session.flush)
    monkeypatch.setattr(hotel_tasks, 'Session', lambda: contextlib.nullcontext(session))

    hotel_tasks.expire_unsecured_assignments()

    assert open_room.status == c.EXPIRED
    assert locked_room.status == c.ASSIGNED


def test_locked_room_card_alert_says_contact_us(session):
    inv = _inv(session)
    kw = dict(status=c.ASSIGNED, payment_type='credit_card', deposit_cutoff_date=date(2026, 12, 1))
    tpl = JinjaEnv.env().from_string(
        "{% import 'hotel_lottery/_macros.html' as m with context %}{{ m.needs_card_alert(ra) }}")

    locked = tpl.render(c=c, ra=make_assignment(session, make_attendee(session), inv, locked=True, **kw))
    unlocked = tpl.render(c=c, ra=make_assignment(session, make_attendee(session), inv, **kw))

    assert 'contact the hotel' in locked and 'released' not in locked
    assert 'released' in unlocked


# ---------------------------------------------------------------------------
# Attendee room page
# ---------------------------------------------------------------------------

def _room_page_text(session, ra):
    ctx = hl._render_room_detail(session, ra.id, ra.attendee_id, '')
    html = JinjaEnv.env().get_template('hotel_lottery/room.html').render(
        c=c, csrf_token=lambda: '', **ctx)
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html))


def test_room_page_shows_hotel_numbers(session, owner_login):
    me = make_attendee(session)
    hotel = make_hotel(session, name='Gaylord National')
    inv = make_inventory(session, hotel, quantity=5)
    # A cancellation number flips the room to CANCELLED on save.
    ra = make_assignment(session, me, inv, check_in=N[2], check_out=N[4], status=c.CANCELLED,
                         hotel_confirmation_number='GN-123',
                         cancellation_confirmation_number='CX-9')
    owner_login(me)

    text = _room_page_text(session, ra)

    assert 'Hotel confirmation #: GN-123' in text
    assert 'Cancellation #: CX-9' in text


def test_room_page_hides_numbers_the_hotel_has_not_sent(session, owner_login):
    me = make_attendee(session)
    ra = make_assignment(session, me, _inv(session), check_in=N[2], check_out=N[4])
    owner_login(me)

    text = _room_page_text(session, ra)

    assert 'confirmation #' not in text
    assert 'Cancellation #' not in text


def test_locked_live_room_banner_points_to_the_hotel(session, owner_login):
    me = make_attendee(session)
    hotel = make_hotel(session, name='Gaylord National')
    ra = make_assignment(session, me, make_inventory(session, hotel, quantity=5),
                         check_in=N[2], check_out=N[4], status=c.SECURED, locked=True)
    owner_login(me)

    text = _room_page_text(session, ra)

    assert 'This room is locked.' in text
    assert 'contact Gaylord National directly' in text


def test_cancelled_exported_room_is_read_only(session, owner_login):
    """An inactive room stays read-only even when exported or locked."""
    me = make_attendee(session)
    app, ra = _awarded_room(session, me, app={'export_locked': True}, locked=True)
    ra.status = c.CANCELLED
    session.flush()
    owner_login(me)

    text = _room_page_text(session, ra)
    assert 'This reservation was cancelled.' in text
    assert 'Please contact' in text and 'directly' in text
    assert 'You can still make changes' not in text
    assert 'This room is locked' not in text
    assert 'Save dates' not in text

    with pytest.raises(HTTPRedirect) as exc:
        _handler('edit_room')(session, id=app.id, assignment_id=ra.id,
                              attendee_id=me.id, special_requests='Late arrival')
    assert ra.special_requests == ''
    assert 'no longer active' in _redirect_text(exc)


def test_occupant_can_leave_a_cancelled_room_but_not_a_locked_one(session, owner_login):
    booker, guest = make_attendee(session), make_attendee(session)
    inv = _inv(session)
    cancelled = make_assignment(session, booker, inv, status=c.CANCELLED)
    locked = make_assignment(session, booker, inv, status=c.SECURED, locked=True)
    for ra in (cancelled, locked):
        ra.occupants.append(guest)
    session.flush()
    owner_login(guest)

    with pytest.raises(HTTPRedirect):
        _handler('leave_room')(session, assignment_id=cancelled.id, attendee_id=guest.id)
    assert guest not in cancelled.occupants

    with pytest.raises(HTTPRedirect) as exc:
        _handler('leave_room')(session, assignment_id=locked.id, attendee_id=guest.id)
    assert guest in locked.occupants
    assert 'This room is locked' in _redirect_text(exc)
