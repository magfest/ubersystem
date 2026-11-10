"""Shift requirements only bind staff crash space imported from tuber; the
Staffer Rooms source column says where each room came from."""

import inspect

import cherrypy
import pytest

from uber.config import c
from uber.models.hotel import NightShiftRequirement, RoomAssignment, room_assignment_occupant
from uber.shift_compliance import compliance_violations, non_compliant_staffers

from tests.hotel.factories import (N, make_assignment, make_attendee,
                                   make_hotel, make_inventory, make_run)
from tests.hotel.test_eligibility import _SessionCM


@pytest.fixture
def inv(session):
    return make_inventory(session, make_hotel(session))


@pytest.fixture
def core_nights(session):
    """Every test night demands hours no fresh staffer has."""
    for night in N[:4]:
        session.add(NightShiftRequirement(night_date=night, kind=c.CORE, required_weighted_hours=6))
    session.flush()


def _staffer(session):
    return make_attendee(session, badge_type=c.STAFF_BADGE)


def _report_ids(session):
    return {attendee.id for attendee, _ in non_compliant_staffers(session)}


def test_crash_space_is_subject(session, inv, core_nights):
    staffer = _staffer(session)
    make_assignment(session, staffer, inv, check_in=N[0], check_out=N[2], assignment_reason=c.STAFF_CRASH_SPACE)
    session.refresh(staffer)

    assert [req.night_date for req in compliance_violations(staffer)] == N[:2]
    assert staffer.id in _report_ids(session)


@pytest.mark.parametrize('reason', [c.LOTTERY_AWARD, c.MANUAL, c.PARTITION_GRANT, c.API_CREATED])
def test_other_sources_are_exempt(session, inv, core_nights, reason):
    staffer = _staffer(session)
    make_assignment(session, staffer, inv, check_in=N[0], check_out=N[2], assignment_reason=reason)
    session.refresh(staffer)

    assert compliance_violations(staffer) == []
    assert staffer.id not in _report_ids(session)


def test_only_crash_space_nights_count_when_mixed(session, inv, core_nights):
    staffer = _staffer(session)
    make_assignment(session, staffer, inv, check_in=N[0], check_out=N[2], assignment_reason=c.LOTTERY_AWARD)
    make_assignment(session, staffer, inv, check_in=N[2], check_out=N[3], assignment_reason=c.STAFF_CRASH_SPACE)
    session.refresh(staffer)

    assert [req.night_date for req in compliance_violations(staffer)] == [N[2]]
    report = dict((attendee.id, violations) for attendee, violations in non_compliant_staffers(session))
    assert [req.night_date for req in report[staffer.id]] == [N[2]]


def test_cancelled_crash_space_is_exempt(session, inv, core_nights):
    staffer = _staffer(session)
    make_assignment(session, staffer, inv, check_in=N[0], check_out=N[2],
                    assignment_reason=c.STAFF_CRASH_SPACE, status=c.CANCELLED)
    session.refresh(staffer)

    assert compliance_violations(staffer) == []
    assert staffer.id not in _report_ids(session)


def _update_assignment(session, monkeypatch, **kwargs):
    import uber.api

    monkeypatch.setattr(uber.api, 'Session', lambda: _SessionCM(session))
    monkeypatch.setattr(session, 'commit', session.flush)
    fn = inspect.unwrap(uber.api.HotelLookup.update_assignment)
    return fn(uber.api.HotelLookup(), **kwargs)


def _api_create(session, monkeypatch, inv, **kwargs):
    result = _update_assignment(session, monkeypatch, attendee_id=_staffer(session).id, inventory_id=inv.id,
                                assigned_check_in_date=N[0], assigned_check_out_date=N[2], **kwargs)
    return session.query(RoomAssignment).get(result['id'])


def test_api_create_defaults_to_api_created(session, monkeypatch, inv):
    ra = _api_create(session, monkeypatch, inv)
    assert ra.assignment_reason == c.API_CREATED
    assert not ra.shift_requirements_apply


def test_api_create_accepts_crash_space_label(session, monkeypatch, inv):
    ra = _api_create(session, monkeypatch, inv, assignment_reason='Staff Crash Space')
    session.refresh(ra)
    assert ra.assignment_reason == c.STAFF_CRASH_SPACE
    assert ra.shift_requirements_apply


def test_api_update_keeps_existing_reason(session, monkeypatch, inv):
    ra = make_assignment(session, _staffer(session), inv, check_in=N[0], check_out=N[2])
    _update_assignment(session, monkeypatch, id=ra.id, hotel_confirmation_number='ABC123')
    assert ra.assignment_reason == c.MANUAL


def test_source_label(session, inv):
    staffer = _staffer(session)
    staff_run = make_run(session, lottery_group='staff')
    attendee_run = make_run(session, lottery_group='attendee')

    def label(**overrides):
        return make_assignment(session, staffer, inv, check_in=N[0], check_out=N[2], **overrides).source_label

    assert label(assignment_reason=c.LOTTERY_AWARD, lottery_run_id=staff_run.id) == 'Staff lottery'
    assert label(assignment_reason=c.LOTTERY_AWARD, lottery_run_id=attendee_run.id) == 'Attendee lottery'
    assert label(assignment_reason=c.SUITE_CONNECTOR, lottery_run_id=staff_run.id) == 'Staff lottery'
    assert label(assignment_reason=c.STAFF_CRASH_SPACE) == 'Staff Crash Space'
    assert label(assignment_reason=c.API_CREATED) == 'API Created'
    assert label(assignment_reason=c.MANUAL) == 'Hotel admin'
    assert label(assignment_reason=c.PARTITION_GRANT) == 'Partition owner'


def test_staffer_rooms_lists_every_source(session, inv, no_cherrypy_session):
    from uber.decorators import render
    from uber.site_sections.staff_rooming import Root

    staffer = _staffer(session)
    run = make_run(session, lottery_group='staff')
    make_assignment(session, staffer, inv, check_in=N[0], check_out=N[2],
                    assignment_reason=c.LOTTERY_AWARD, lottery_run_id=run.id)
    make_assignment(session, staffer, inv, check_in=N[0], check_out=N[2], assignment_reason=c.STAFF_CRASH_SPACE)
    make_assignment(session, staffer, inv, check_in=N[0], check_out=N[2], assignment_reason=c.MANUAL)

    data = inspect.unwrap(Root.staffer_rooms)(Root(), session, search=staffer.email)
    assert data['total'] == 3
    for source, label in [('crash_space', 'Staff Crash Space'), ('lottery', 'Staff lottery'), ('other', 'Hotel admin')]:
        rooms = inspect.unwrap(Root.staffer_rooms)(Root(), session, search=staffer.email, source=source)
        assert [ra.source_label for ra in rooms['assignments']] == [label]

    html = render('staff_rooming/staffer_rooms.html', data)
    text = html.decode('utf-8') if isinstance(html, bytes) else html
    for source in ('Staff lottery', 'Staff Crash Space', 'Hotel admin'):
        assert source in text
    assert text.count('shift requirements apply') == 1


def test_api_create_rejects_unknown_reason(session, monkeypatch, inv):
    with pytest.raises(cherrypy.HTTPError) as err:
        _update_assignment(session, monkeypatch, attendee_id=_staffer(session).id, inventory_id=inv.id,
                           assignment_reason='Staff Automatic')
    assert err.value.code == 400


# ---------------------------------------------------------------------------
# Occupants of crash space
# ---------------------------------------------------------------------------

def _crash_room(session, monkeypatch, inv, booker, occupants, **kwargs):
    kwargs.setdefault('assignment_reason', 'Staff Crash Space')
    result = _update_assignment(
        session, monkeypatch, attendee_id=booker.id, inventory_id=inv.id,
        assigned_check_in_date=N[0].isoformat(), assigned_check_out_date=N[3].isoformat(),
        occupants=occupants, **kwargs)
    session.expire_all()
    return session.query(RoomAssignment).get(result['id'])


def test_api_sets_occupants_with_their_own_dates(session, monkeypatch, inv):
    booker, late = _staffer(session), _staffer(session)
    ra = _crash_room(session, monkeypatch, inv, booker, [
        booker.id, {'attendee_id': late.id, 'check_in_date': N[2].isoformat(), 'check_out_date': N[3].isoformat()}])

    assert ra.assigned_check_in_date == N[0] and ra.assigned_check_out_date == N[3]
    assert {occ.id for occ in ra.occupants} == {booker.id, late.id}
    rows = {row.attendee_id: (row.check_in_date, row.check_out_date) for row in session.execute(
        room_assignment_occupant.select().where(room_assignment_occupant.c.room_assignment_id == ra.id))}
    assert rows == {booker.id: (None, None), late.id: (N[2], N[3])}


def test_api_occupants_replace_the_list(session, monkeypatch, inv):
    booker, first, second = _staffer(session), _staffer(session), _staffer(session)
    ra = _crash_room(session, monkeypatch, inv, booker, [booker.id, first.id])
    result = _update_assignment(session, monkeypatch, id=ra.id, occupants=[booker.id, second.id])
    assert set(result['occupant_ids']) == {booker.id, second.id}

    # Leaving occupants out keeps the list.
    result = _update_assignment(session, monkeypatch, id=ra.id, room_number='12')
    assert set(result['occupant_ids']) == {booker.id, second.id}


def test_api_rejects_unknown_occupant(session, monkeypatch, inv):
    booker = _staffer(session)
    with pytest.raises(cherrypy.HTTPError) as err:
        _update_assignment(session, monkeypatch, attendee_id=booker.id, inventory_id=inv.id,
                           occupants=[booker.id, '00000000-0000-0000-0000-000000000000'])
    assert err.value.code == 404
    assert not session.query(RoomAssignment).filter_by(attendee_id=booker.id).count()


def test_api_status_accepts_label(session, monkeypatch, inv):
    ra = make_assignment(session, _staffer(session), inv, check_in=N[0], check_out=N[2])
    _update_assignment(session, monkeypatch, id=ra.id, status='Cancelled')
    assert ra.status == c.CANCELLED


def test_occupants_are_subject_for_their_own_nights(session, monkeypatch, inv, core_nights):
    booker, late = _staffer(session), _staffer(session)
    _crash_room(session, monkeypatch, inv, booker, [
        booker.id, {'attendee_id': late.id, 'check_in_date': N[2].isoformat(), 'check_out_date': N[3].isoformat()}])

    assert [req.night_date for req in compliance_violations(booker)] == N[:3]
    assert [req.night_date for req in compliance_violations(late)] == [N[2]]
    report = {attendee.id: [req.night_date for req in broken] for attendee, broken in non_compliant_staffers(session)}
    assert report[booker.id] == N[:3]
    assert report[late.id] == [N[2]]
    assert late.hotel_room_kind == 'shared'


def test_occupants_of_other_rooms_are_exempt(session, inv, core_nights):
    booker, guest = _staffer(session), _staffer(session)
    ra = make_assignment(session, booker, inv, check_in=N[0], check_out=N[2], assignment_reason=c.LOTTERY_AWARD)
    ra.occupants = [booker, guest]
    session.flush()

    assert compliance_violations(guest) == []
    assert not {booker.id, guest.id} & _report_ids(session)
    assert guest.hotel_room_kind == ''


# ---------------------------------------------------------------------------
# Per-occupant dates belong to staff crash space only
# ---------------------------------------------------------------------------

def _occupant_rows(session, ra):
    return {row.attendee_id: (row.check_in_date, row.check_out_date) for row in session.execute(
        room_assignment_occupant.select().where(room_assignment_occupant.c.room_assignment_id == ra.id))}


def _late(late):
    return {'attendee_id': late.id, 'check_in_date': N[2].isoformat(), 'check_out_date': N[3].isoformat()}


def test_api_drops_occupant_dates_on_other_rooms(session, monkeypatch, inv):
    booker, late = _staffer(session), _staffer(session)
    ra = _crash_room(session, monkeypatch, inv, booker, [booker.id, _late(late)], assignment_reason='API Created')
    assert _occupant_rows(session, ra) == {booker.id: (None, None), late.id: (None, None)}


def test_leaving_crash_space_clears_occupant_dates(session, monkeypatch, inv):
    booker, late = _staffer(session), _staffer(session)
    ra = _crash_room(session, monkeypatch, inv, booker, [booker.id, _late(late)])
    assert _occupant_rows(session, ra)[late.id] == (N[2], N[3])

    ra.assignment_reason = c.MANUAL
    session.flush()
    assert _occupant_rows(session, ra) == {booker.id: (None, None), late.id: (None, None)}


def test_api_create_missing_is_idempotent(session, monkeypatch, inv):
    booker = _staffer(session)
    room_id = '6f1d2c3a-0b1e-4c5d-8e9f-a1b2c3d4e5f6'
    with pytest.raises(cherrypy.HTTPError):
        _update_assignment(session, monkeypatch, id=room_id, attendee_id=booker.id, inventory_id=inv.id)

    for special_requests in ('first', 'retried'):
        result = _update_assignment(
            session, monkeypatch, id=room_id, create_missing=True, attendee_id=booker.id, inventory_id=inv.id,
            assignment_reason='Staff Crash Space', special_requests=special_requests)
        assert result['id'] == room_id and result['is_live']
    rooms = session.query(RoomAssignment).filter_by(attendee_id=booker.id).all()
    assert [(ra.id, ra.special_requests) for ra in rooms] == [(room_id, 'retried')]

    with pytest.raises(cherrypy.HTTPError):
        _update_assignment(session, monkeypatch, id='not-a-uuid', create_missing=True, attendee_id=booker.id)


def test_set_occupant_stay_dates(session, monkeypatch, inv, core_nights):
    from uber.hotel.service import RoomAssignmentError, set_occupant_stay_dates

    booker, mate = _staffer(session), _staffer(session)
    ra = _crash_room(session, monkeypatch, inv, booker, [booker.id, mate.id])
    assert len(compliance_violations(mate)) == 3

    assert set_occupant_stay_dates(session, ra, {mate.id: (N[2], None)}) == 1
    assert _occupant_rows(session, ra) == {booker.id: (None, None), mate.id: (N[2], None)}
    session.expire_all()
    assert len(compliance_violations(mate)) == 1
    assert set_occupant_stay_dates(session, ra, {mate.id: (N[2], None)}) == 0

    for bad in [(N[3], None), (None, N[0]), (N[0] - (N[1] - N[0]), None)]:
        with pytest.raises(RoomAssignmentError):
            set_occupant_stay_dates(session, ra, {mate.id: bad})

    other = make_assignment(session, booker, inv, check_in=N[0], check_out=N[3], assignment_reason=c.LOTTERY_AWARD)
    other.occupants.append(mate)
    session.flush()
    with pytest.raises(RoomAssignmentError):
        set_occupant_stay_dates(session, other, {mate.id: (N[1], N[2])})
    assert _occupant_rows(session, other)[mate.id] == (None, None)


def test_staffer_rooms_lists_roommates(session, monkeypatch, inv, no_cherrypy_session):
    from uber.decorators import render
    from uber.site_sections.staff_rooming import Root

    booker, late, friend = _staffer(session), _staffer(session), make_attendee(session)
    crash = _crash_room(session, monkeypatch, inv, booker, [booker.id, _late(late)])
    lottery = make_assignment(session, booker, inv, check_in=N[0], check_out=N[3], assignment_reason=c.LOTTERY_AWARD)
    lottery.occupants.extend([booker, friend])
    session.flush()

    data = inspect.unwrap(Root.staffer_rooms)(Root(), session, search=booker.email)
    assert data['stay_dates'][crash.id][late.id] == (N[2], N[3])
    html = render('staff_rooming/staffer_rooms.html', data)
    text = html.decode('utf-8') if isinstance(html, bytes) else html
    assert late.full_name in text and friend.full_name in text
    # Only the crash space room offers the date editor.
    assert text.count('action="set_occupant_dates"') == 1
    assert f'name="check_in_{late.id}"' in text
    assert f'name="check_in_{friend.id}"' not in text


def test_set_occupant_dates_page(session, monkeypatch, inv, no_cherrypy_session):
    from uber.errors import HTTPRedirect
    from uber.site_sections import staff_rooming

    monkeypatch.setattr(cherrypy.request, 'method', 'POST')
    monkeypatch.setattr(staff_rooming, 'check_csrf', lambda *a, **k: None)
    monkeypatch.setattr(session, 'commit', session.flush)
    booker, mate = _staffer(session), _staffer(session)
    ra = _crash_room(session, monkeypatch, inv, booker, [booker.id, mate.id])
    save = inspect.unwrap(staff_rooming.Root.set_occupant_dates)

    with pytest.raises(HTTPRedirect) as redirect:
        save(staff_rooming.Root(), session, id=ra.id, **{
            f'check_in_{mate.id}': N[1].isoformat(), f'check_out_{mate.id}': N[2].isoformat(),
            f'check_in_{booker.id}': '', f'check_out_{booker.id}': ''})
    assert 'updated%20for%201' in redirect.value.urls[0]
    assert _occupant_rows(session, ra) == {booker.id: (None, None), mate.id: (N[1], N[2])}


# ---------------------------------------------------------------------------
# The shift requirement email goes to crash space holders only
# ---------------------------------------------------------------------------

def test_shift_requirement_email_goes_to_crash_space_only(session, monkeypatch, inv, core_nights):
    from datetime import datetime, timedelta

    from pytz import UTC

    from uber.decorators import render
    from uber.models import AutomatedEmail

    fixture = AutomatedEmail._fixtures['staff_crash_space_shift_requirements']
    booker, mate, winner = (make_attendee(session, badge_type=c.STAFF_BADGE, staffing=True) for _ in range(3))
    _crash_room(session, monkeypatch, inv, booker, [booker.id, mate.id])
    make_assignment(session, winner, inv, check_in=N[0], check_out=N[3], assignment_reason=c.LOTTERY_AWARD)
    session.flush()

    # Nothing goes out before shifts exist.
    monkeypatch.setattr(c, 'SHIFTS_CREATED', None)
    assert not fixture.filter(booker)

    monkeypatch.setattr(c, 'SHIFTS_CREATED', datetime.now(UTC) - timedelta(days=1))
    assert fixture.filter(booker) and fixture.filter(mate)
    assert not fixture.filter(winner), 'a lottery room carries no shift requirements'

    body = render('emails/' + fixture.template, {'attendee': mate, 'email_signature': 'Staffing'}, encoding=None)
    assert 'staff crash space' in body
    # Three core nights share one hours target, so one line covers them.
    assert len(compliance_violations(mate)) == 3 and body.count('<li>') == 1
