"""Attendees can cancel any live room, and the booking exports report
cancelled rooms the hotel was already sent with status "Cancelled".
"""

import re
import uuid
from datetime import datetime, timedelta, timezone

import cherrypy
import pytest

import uber.site_sections.hotel_lottery as hl
from uber.config import c
from uber.errors import HTTPRedirect
from uber.hotel.exports import (BOOKING_BASE_COLS, booking_export_data,
                                compute_export_tracking)
from uber.hotel.queries import exportable_assignments
from uber.jinja import JinjaEnv
from uber.models import AttendeeAccount, initialize_db
from uber.models.hotel import HotelExportLog, RoomAssignment

from tests.hotel.factories import (N, make_application, make_assignment,
                                   make_attendee, make_hotel, make_inventory)

NOW = datetime.now(timezone.utc)


def _export(session, hotel):
    """A real booking export for `hotel`: builds the spreadsheet rows,
    which stamps exported_at on every row it includes."""
    booking_export_data(session, hotel.id)
    session.flush()


def _backdate(session, ra, **cols):
    """Set timestamp columns directly (bypassing the presaves, which
    would restamp last_modified_at on flush)."""
    session.query(RoomAssignment).filter_by(id=ra.id).update(
        cols, synchronize_session=False)
    session.flush()
    session.expire(ra)


def _cancel(session, ra):
    ra.status = c.CANCELLED
    session.add(ra)
    session.flush()


def _setup(session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel, quantity=10)
    return hotel, inv


def _room(session, inv, **kw):
    return make_assignment(session, make_attendee(session), inv,
                           check_in=N[1], check_out=N[3], **kw)


# ---------------------------------------------------------------------------
# Which rows the export carries
# ---------------------------------------------------------------------------

def test_export_includes_rooms_cancelled_after_the_hotel_saw_them(session):
    hotel, inv = _setup(session)
    live = _room(session, inv, status=c.SECURED)
    sent_then_cancelled = _room(session, inv, status=c.SECURED)
    _export(session, hotel)
    assert sent_then_cancelled.exported_at is not None
    _cancel(session, sent_then_cancelled)

    ids = {ra.id for ra in exportable_assignments(session, hotel_id=hotel.id)}

    assert live.id in ids
    assert sent_then_cancelled.id in ids


def test_export_omits_cancellations_the_hotel_never_saw(session):
    hotel, inv = _setup(session)
    _export(session, hotel)

    # Created after the last export, then cancelled - never sent.
    new_then_cancelled = _room(session, inv)
    _cancel(session, new_then_cancelled)
    # A later export leaves it out and doesn't stamp it.
    _export(session, hotel)

    ids = {ra.id for ra in exportable_assignments(session, hotel_id=hotel.id)}

    assert new_then_cancelled.exported_at is None
    assert new_then_cancelled.id not in ids


def test_first_export_time_is_kept(session):
    hotel, inv = _setup(session)
    ra = _room(session, inv)
    _export(session, hotel)
    first = ra.exported_at
    _export(session, hotel)

    assert ra.exported_at == first
    assert ra.is_exported


def test_another_hotels_export_does_not_count(session):
    hotel, inv = _setup(session)
    other_hotel = make_hotel(session)
    ra = _room(session, inv)
    _export(session, other_hotel)
    _cancel(session, ra)

    assert ra.exported_at is None
    assert ra.id not in {r.id for r in exportable_assignments(session, hotel_id=hotel.id)}


def test_inventory_scope_includes_sent_cancellations(session):
    """The portal scopes itself by vault reference -> inventory ids."""
    hotel, inv = _setup(session)
    other_inv = make_inventory(session, hotel, quantity=10)
    ra = _room(session, inv)
    elsewhere = _room(session, other_inv)
    _export(session, hotel)
    _cancel(session, ra)

    ids = {r.id for r in exportable_assignments(session, inventory_ids=[inv.id])}

    assert ra.id in ids
    assert elsewhere.id not in ids


def test_spreadsheet_row_says_cancelled(session):
    hotel, inv = _setup(session)
    ra = _room(session, inv, status=c.SECURED)
    _export(session, hotel)
    _cancel(session, ra)

    _, rows = booking_export_data(session, hotel.id)

    by_id = {row[0]: row for row in rows}
    assert by_id[ra.id][BOOKING_BASE_COLS.index('status')] == 'Cancelled'


def test_tracking_counts_new_cancellation_as_pending_export(session):
    hotel, inv = _setup(session)
    ra = _room(session, inv, status=c.SECURED)
    _export(session, hotel)
    _backdate(session, ra, last_modified_at=NOW - timedelta(days=3))
    session.add(HotelExportLog(hotel_id=hotel.id, export_type='room_export',
                               exported_at=NOW - timedelta(days=2), source='admin'))
    session.flush()

    def dirty():
        row = next(h for h in compute_export_tracking(session) if h['hotel'].id == hotel.id)
        return row['dirty_count'], row['total_bookings']

    assert dirty() == (0, 1)
    _cancel(session, ra)
    assert dirty() == (1, 0), \
        'the cancellation needs exporting; it is no longer a live booking'


# ---------------------------------------------------------------------------
# The attendee cancel handler
# ---------------------------------------------------------------------------

@pytest.fixture
def owner_login(session, monkeypatch):
    """POST as the account that owns `attendee`, CSRF stubbed, commits
    turned into flushes."""
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


def _decline(session, **kwargs):
    func = hl.Root.decline
    while hasattr(func, '__wrapped__'):
        func = func.__wrapped__
    return func(hl.Root(), session, **kwargs)


def test_booker_cancels_secured_exported_suite_and_connectors(session, owner_login):
    hotel, inv = _setup(session)
    me = make_attendee(session)
    app = make_application(session, me, status=c.AWARDED, export_locked=True)
    suite = make_assignment(session, me, inv, check_in=N[1], check_out=N[3],
                            status=c.SECURED, lottery_application_id=app.id,
                            cc_token='tok', cc_last_four='4242')
    child = make_assignment(session, me, inv, check_in=N[1], check_out=N[3],
                            status=c.ASSIGNED, lottery_application_id=app.id,
                            parent_assignment_id=suite.id,
                            assignment_reason=c.SUITE_CONNECTOR)
    assert suite.is_exported and not suite.is_locked
    owner_login(me)

    with pytest.raises(HTTPRedirect):
        _decline(session, id=app.id, assignment_id=suite.id, confirm='1')

    assert suite.status == c.CANCELLED
    assert child.status == c.CANCELLED
    assert suite.cc_token == 'tok', 'the hotel may still need the card on file'


def test_award_email_link_with_only_the_application_id(session, owner_login):
    hotel, inv = _setup(session)
    me = make_attendee(session)
    app = make_application(session, me, status=c.AWARDED)
    ra = make_assignment(session, me, inv, check_in=N[1], check_out=N[3],
                         status=c.SECURED, lottery_application_id=app.id)
    owner_login(me)

    with pytest.raises(HTTPRedirect):
        _decline(session, id=app.id, confirm='1')

    assert ra.status == c.CANCELLED


def test_non_lottery_room_can_be_cancelled(session, owner_login):
    hotel, inv = _setup(session)
    me = make_attendee(session)
    ra = make_assignment(session, me, inv, check_in=N[1], check_out=N[3],
                         status=c.ASSIGNED, assignment_reason=c.MANUAL)
    owner_login(me)

    with pytest.raises(HTTPRedirect):
        _decline(session, id='', assignment_id=ra.id, attendee_id=me.id, confirm='1')

    assert ra.status == c.CANCELLED


def test_unconfirmed_post_shows_the_page_again(session, owner_login):
    hotel, inv = _setup(session)
    me = make_attendee(session)
    ra = make_assignment(session, me, inv, check_in=N[1], check_out=N[3], status=c.SECURED)
    owner_login(me)

    ctx = _decline(session, assignment_id=ra.id, attendee_id=me.id)

    assert 'check the box' in ctx['message']
    assert ctx['assignment'] == ra
    assert ra.status == c.SECURED


def test_someone_else_cannot_cancel_my_room(session, owner_login):
    hotel, inv = _setup(session)
    me, stranger = make_attendee(session), make_attendee(session)
    ra = make_assignment(session, me, inv, check_in=N[1], check_out=N[3], status=c.SECURED)
    owner_login(stranger)

    with pytest.raises(HTTPRedirect) as exc:
        _decline(session, assignment_id=ra.id, confirm='1')

    assert 'permission' in str(exc.value.urls)
    assert ra.status == c.SECURED


def test_group_member_cannot_cancel(session, owner_login):
    hotel, inv = _setup(session)
    leader, member = make_attendee(session), make_attendee(session)
    leader_app = make_application(session, leader, status=c.AWARDED)
    member_app = make_application(session, member, status=c.AWARDED,
                                  parent_application_id=leader_app.id)
    ra = make_assignment(session, member, inv, check_in=N[1], check_out=N[3],
                         status=c.SECURED, lottery_application_id=member_app.id)
    owner_login(member)

    with pytest.raises(HTTPRedirect):
        _decline(session, id=member_app.id, assignment_id=ra.id, confirm='1')

    assert ra.status == c.SECURED


def test_already_cancelled_room(session, owner_login):
    hotel, inv = _setup(session)
    me = make_attendee(session)
    ra = make_assignment(session, me, inv, check_in=N[1], check_out=N[3], status=c.CANCELLED)
    owner_login(me)

    with pytest.raises(HTTPRedirect) as exc:
        _decline(session, assignment_id=ra.id, confirm='1')

    assert 'already' in str(exc.value.urls)


def _render_decline(ctx):
    html = JinjaEnv.env().get_template('hotel_lottery/decline.html').render(
        c=c, csrf_token=lambda: '', **ctx)
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html))


def test_cancel_page_renders_for_non_lottery_room(session, owner_login):
    hotel, inv = _setup(session)
    me = make_attendee(session)
    ra = make_assignment(session, me, inv, check_in=N[1], check_out=N[3], status=c.ASSIGNED)
    owner_login(me)
    ctx = _decline(session, assignment_id=ra.id, attendee_id=me.id)

    text = _render_decline(ctx)

    assert 'Cancel Room?' in text
    assert 'already been sent to the hotel' not in text
    assert 'lottery' not in text.split('Cancel Room?')[1].lower()


def test_cancel_page_warns_when_booking_was_sent(session, owner_login):
    hotel, inv = _setup(session)
    me = make_attendee(session)
    app = make_application(session, me, status=c.AWARDED, export_locked=True)
    ra = make_assignment(session, me, inv, check_in=N[1], check_out=N[3],
                         status=c.SECURED, lottery_application_id=app.id)
    owner_login(me)
    ctx = _decline(session, id=app.id, assignment_id=ra.id)

    assert 'already been sent to the hotel' in _render_decline(ctx)
