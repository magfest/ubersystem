"""Rooms materialized by a lottery run stay admin-only until the run is
awarded. Before Award Winners they hold inventory (they are live), but no
attendee page, email, or hotel export may show them."""

from datetime import date

import cherrypy
import pytest

from uber.config import c
from uber.errors import HTTPRedirect

from tests.hotel.factories import (make_application, make_assignment,
                                   make_attendee, make_hotel, make_inventory,
                                   make_run)


def _rooms(session):
    """One attendee holding a manual room, a room from an awarded run, and
    a room from a still-pending run, all at the same hotel."""
    hotel = make_hotel(session)
    inventory = make_inventory(session, hotel)
    attendee = make_attendee(session)
    app = make_application(session, attendee, status=c.PROCESSED)
    pending_run = make_run(session, status=c.LOTTERY_PENDING)
    awarded_run = make_run(session, status=c.LOTTERY_AWARDED)
    dates = dict(check_in=date(2027, 1, 6), check_out=date(2027, 1, 10))
    manual = make_assignment(session, attendee, inventory, **dates)
    awarded = make_assignment(session, attendee, inventory,
                              lottery_run_id=awarded_run.id,
                              lottery_application_id=app.id, **dates)
    pending = make_assignment(session, attendee, inventory,
                              lottery_run_id=pending_run.id,
                              lottery_application_id=app.id, **dates)
    session.expire_all()
    return hotel, attendee, app, pending_run, manual, awarded, pending


def test_is_released_python_and_sql_agree(session):
    from uber.models.hotel import RoomAssignment

    _hotel, _attendee, _app, _run, manual, awarded, pending = _rooms(session)

    assert manual.is_released and awarded.is_released
    assert not pending.is_released
    assert pending.is_live, 'a pending row still holds inventory'

    ids = {ra.id for ra in session.query(RoomAssignment).filter(
        RoomAssignment.id.in_([manual.id, awarded.id, pending.id]),
        RoomAssignment.is_released)}
    assert ids == {manual.id, awarded.id}


def test_awarding_the_run_releases_its_rows(session):
    _hotel, attendee, _app, run, _manual, _awarded, pending = _rooms(session)

    run.status = c.LOTTERY_AWARDED
    session.flush()
    session.expire_all()

    assert pending.is_released
    assert pending.id in {ra.id for ra in attendee.released_room_assignments}


def test_attendee_and_application_lists_hide_pending_rows(session):
    _hotel, attendee, app, _run, manual, awarded, pending = _rooms(session)

    released = {ra.id for ra in attendee.released_room_assignments}
    assert released == {manual.id, awarded.id}
    assert pending.id in {ra.id for ra in attendee.active_room_assignments}, \
        'active_room_assignments is the admin/inventory view and keeps them'

    assert {ra.id for ra in app.lottery_room_assignments} == {awarded.id}
    assert {ra.id for ra in app.other_live_room_assignments} == {manual.id}


def test_booking_export_omits_pending_rows(session):
    from uber.hotel.exports import booking_export_data

    hotel, _attendee, _app, _run, manual, awarded, pending = _rooms(session)

    _hotel, rows = booking_export_data(session, hotel.id)
    exported = ' '.join(str(cell) for row in rows for cell in row)
    assert str(manual.id) in exported and str(awarded.id) in exported
    assert str(pending.id) not in exported


def test_resolve_assignment_skips_pending_rows(session):
    from uber.site_sections.hotel_lottery import _resolve_assignment

    _hotel, _attendee, app, _run, _manual, awarded, pending = _rooms(session)

    assert _resolve_assignment(session, pending.id) is None
    assert _resolve_assignment(session, pending.id, app,
                               match_application=True).id == awarded.id


def test_room_actions_refuse_pending_rows(session, monkeypatch,
                                          no_cherrypy_session):
    import uber.site_sections.hotel_lottery as hotel_lottery
    from uber.models import initialize_db

    initialize_db()
    monkeypatch.setattr(cherrypy.request, 'method', 'POST')
    monkeypatch.setattr(hotel_lottery, 'check_csrf', lambda *a, **k: None)
    monkeypatch.setattr(hotel_lottery, '_require_room_access', lambda *a, **k: None)
    monkeypatch.setattr(session, 'commit', session.flush)

    _hotel, _attendee, _app, _run, _manual, _awarded, pending = _rooms(session)
    pending.special_requests = ''
    session.flush()

    handler = hotel_lottery.Root.save_special_requests
    room_action_code = hotel_lottery.room_action(lambda *a, **k: None).__code__
    while hasattr(handler, '__wrapped__') and handler.__code__ is not room_action_code:
        handler = handler.__wrapped__

    with pytest.raises(HTTPRedirect) as excinfo:
        handler(hotel_lottery.Root(), session, assignment_id=pending.id,
                special_requests='Late checkout')
    assert 'Room not found' in excinfo.value.urls[0] or 'Room%20not%20found' in excinfo.value.urls[0]
    assert pending.special_requests == ''


def _admin_handler(name):
    from uber.site_sections.hotel_lottery_admin import Root

    func = getattr(Root, name)
    while hasattr(func, '__wrapped__'):
        func = func.__wrapped__
    return lambda session, **kwargs: func(Root(), session, **kwargs)


@pytest.mark.parametrize('status', [c.PROCESSED, c.COMPLETE])
def test_award_run_promotes_winners_even_after_attendee_opt_in(
        session, monkeypatch, no_cherrypy_session, status):
    """A staff winner may opt into the attendee lottery while the staff run
    is pending, which resets them to COMPLETE. Awarding the run must still
    make them AWARDED."""
    import uber.site_sections.hotel_lottery_admin as admin

    monkeypatch.setattr(admin, '_require_post_csrf', lambda *a, **k: None)
    monkeypatch.setattr(session, 'commit', session.flush)

    _hotel, _attendee, app, run, _manual, _awarded, pending = _rooms(session)
    app.lottery_run_id = run.id
    app.status = status
    session.flush()

    with pytest.raises(HTTPRedirect):
        _admin_handler('award_run')(session, id=run.id)

    session.expire_all()
    assert run.status == c.LOTTERY_AWARDED
    assert app.status == c.AWARDED
    assert pending.is_released


def test_staff_rooms_awarded_waits_for_every_staff_run(session):
    app = make_application(session, make_attendee(session), is_staff_entry=True)
    assert not app.staff_rooms_awarded, 'no staff run yet'

    def fresh():
        session.expire(app)
        app.__dict__.pop('_staff_rooms_awarded_cache', None)
        return app.staff_rooms_awarded

    make_run(session, lottery_group='attendee', status=c.LOTTERY_AWARDED)
    assert not fresh(), 'attendee runs do not count'

    pending = make_run(session, lottery_group='staff', status=c.LOTTERY_PENDING)
    assert not fresh(), 'a pending staff run keeps everyone on the same text'

    pending.status = c.LOTTERY_AWARDED
    session.flush()
    assert fresh()


def test_enter_attendee_lottery_refused_until_staff_rooms_awarded(
        session, monkeypatch, no_cherrypy_session):
    import uber.site_sections.hotel_lottery as hotel_lottery
    from uber.models import initialize_db

    initialize_db()
    monkeypatch.setattr(hotel_lottery, '_require_post_csrf', lambda *a, **k: None)
    monkeypatch.setattr(session, 'commit', session.flush)

    app = make_application(session, make_attendee(session), status=c.PROCESSED,
                           is_staff_entry=True)
    make_run(session, lottery_group='staff', status=c.LOTTERY_PENDING)

    handler = hotel_lottery.Root.enter_attendee_lottery
    while hasattr(handler, '__wrapped__'):
        handler = handler.__wrapped__

    with pytest.raises(HTTPRedirect):
        handler(hotel_lottery.Root(), session, id=app.id)
    assert app.is_staff_entry and app.status == c.PROCESSED


def test_pending_run_rooms_do_not_promote_their_entry(session):
    """The after_insert listener promotes COMPLETE entries that gain a live
    room - except for a pending run's rooms, which wait for Award Winners."""
    from uber.models.hotel import RoomAssignment

    inventory = make_inventory(session, make_hotel(session))
    attendee = make_attendee(session)
    app = make_application(session, attendee, status=c.COMPLETE)
    run = make_run(session, status=c.LOTTERY_PENDING)
    app.lottery_run_id = run.id
    ra = make_assignment(session, attendee, inventory, lottery_run_id=run.id,
                         lottery_application_id=app.id,
                         check_in=date(2027, 1, 6), check_out=date(2027, 1, 10))
    session.expire(app)
    assert app.status == c.COMPLETE
    assert app.holds_pending_award and app.admin_status_label == 'Pending Award'
    assert app.id in {a.id for a in session.query(type(app)).filter(
        type(app).holds_pending_award)}

    app.sync_award_status(session)
    assert app.status == c.COMPLETE, 'sync must not award a pending run either'

    session.delete(ra)
    session.flush()
    session.expire(app)
    assert app.lottery_run_id is None, 'losing its last pending room detaches the run'
    assert not session.query(RoomAssignment).filter_by(lottery_run_id=run.id).count()


def test_award_run_drops_what_changed_while_pending(session, monkeypatch,
                                                    no_cherrypy_session):
    """A winner who withdrew before the award loses the room instead of it
    appearing; someone who left a winning group comes off its room."""
    import uber.site_sections.hotel_lottery_admin as admin
    from uber.models.hotel import RoomAssignment

    monkeypatch.setattr(admin, '_require_post_csrf', lambda *a, **k: None)
    monkeypatch.setattr(session, 'commit', session.flush)

    inventory = make_inventory(session, make_hotel(session))
    run = make_run(session, status=c.LOTTERY_PENDING)
    dates = dict(check_in=date(2027, 1, 6), check_out=date(2027, 1, 10))

    quitter = make_attendee(session)
    quitter_app = make_application(session, quitter, lottery_run_id=run.id)
    quitter_room = make_assignment(session, quitter, inventory, lottery_run_id=run.id,
                                   lottery_application_id=quitter_app.id, **dates)

    leader, member, leaver = (make_attendee(session) for _ in range(3))
    leader_app = make_application(session, leader, lottery_run_id=run.id,
                                  room_group_name='Group')
    for attendee in (member, leaver):
        make_application(session, attendee, entry_type=c.GROUP_ENTRY,
                         parent_application_id=leader_app.id)
    group_room = make_assignment(session, leader, inventory, lottery_run_id=run.id,
                                 lottery_application_id=leader_app.id, **dates)
    group_room.occupants = [leader, member, leaver]
    session.flush()

    quitter_app.status = c.WITHDRAWN
    leaver.lottery_application.parent_application_id = None
    session.flush()

    with pytest.raises(HTTPRedirect):
        _admin_handler('award_run')(session, id=run.id)

    session.expire_all()
    assert not session.query(RoomAssignment).filter_by(id=quitter_room.id).count()
    assert quitter_app.status == c.WITHDRAWN
    assert leader_app.status == c.AWARDED
    assert {o.id for o in group_room.occupants} == {leader.id, member.id}
