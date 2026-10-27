"""Which rooms put a staffer under the night shift requirements behind the
hotel banner and the Staff Rooming compliance report."""

from datetime import datetime, time

import pytest

from uber.config import c
from uber.models.hotel import NightShiftRequirement
from uber.shift_compliance import compliance_violations, non_compliant_staffers

from tests.hotel.factories import (N, make_application, make_assignment,
                                   make_attendee, make_run)


@pytest.fixture
def setup_night():
    start = c.EVENT_TIMEZONE.localize(datetime.combine(N[0], time(12, 0)))
    return NightShiftRequirement(night_date=N[0], kind=c.SETUP, shift_window_start=start,
                                 shift_window_end=start.replace(hour=18), required_weighted_hours=0)


def _room(session, attendee, **overrides):
    params = dict(check_in=N[0], check_out=N[1], payment_type='masterbill')
    params.update(overrides)
    return make_assignment(session, attendee, **params)


def _staffer(session):
    return make_attendee(session, badge_type=c.STAFF_BADGE)


def _lottery_room(session, attendee, reason):
    app = make_application(session, attendee)
    return _room(session, attendee, lottery_application_id=app.id,
                 lottery_run_id=make_run(session).id, assignment_reason=reason)


def test_staff_master_bill_manual_room_is_checked(session, setup_night):
    staffer = _staffer(session)
    _room(session, staffer)
    assert compliance_violations(staffer, {N[0]: setup_night}) == [setup_night]


def test_self_paid_room_is_not_checked(session, setup_night):
    staffer = _staffer(session)
    _room(session, staffer, payment_type='credit_card')
    assert compliance_violations(staffer, {N[0]: setup_night}) == []


@pytest.mark.parametrize('reason', ['LOTTERY_AWARD', 'SUITE_CONNECTOR'])
def test_lottery_room_is_not_checked_even_on_master_bill(session, setup_night, reason):
    staffer = _staffer(session)
    _lottery_room(session, staffer, getattr(c, reason))
    assert compliance_violations(staffer, {N[0]: setup_night}) == []


def test_non_staff_badge_is_not_checked(session, setup_night):
    volunteer = make_attendee(session)
    _room(session, volunteer)
    assert compliance_violations(volunteer, {N[0]: setup_night}) == []


def test_checked_room_still_counts_beside_an_exempt_room(session, setup_night):
    staffer = _staffer(session)
    _lottery_room(session, staffer, c.LOTTERY_AWARD)
    _room(session, staffer)
    assert compliance_violations(staffer, {N[0]: setup_night}) == [setup_night]


def test_report_lists_only_staff_with_a_checked_room(session, setup_night):
    # Rows committed by other suites would leak into load_requirements;
    # the per-test rollback restores them.
    session.query(NightShiftRequirement).delete()
    session.add(setup_night)
    session.flush()

    crash_space = _staffer(session)
    _room(session, crash_space)
    lottery_winner = _staffer(session)
    _lottery_room(session, lottery_winner, c.LOTTERY_AWARD)
    self_paid = _staffer(session)
    _room(session, self_paid, payment_type='credit_card')

    flagged = {attendee.id for attendee, _ in non_compliant_staffers(session)}
    assert crash_space.id in flagged
    assert lottery_winner.id not in flagged
    assert self_paid.id not in flagged


@pytest.fixture
def add_night(session, monkeypatch):
    """Root.add_night unwrapped, as a POST with CSRF stubbed and commits
    turned into flushes."""
    import cherrypy

    import uber.site_sections.staff_rooming as staff_rooming

    monkeypatch.setattr(cherrypy.request, 'method', 'POST')
    monkeypatch.setattr(staff_rooming, 'check_csrf', lambda *a, **k: None)
    monkeypatch.setattr(session, 'commit', session.flush)
    func = staff_rooming.Root.add_night
    while hasattr(func, '__wrapped__'):
        func = func.__wrapped__
    return lambda **kwargs: func(staff_rooming.Root(), session, **kwargs)


def _add(add_night, **kwargs):
    from urllib.parse import unquote

    from uber.errors import HTTPRedirect

    with pytest.raises(HTTPRedirect) as excinfo:
        add_night(**kwargs)
    return unquote(excinfo.value.urls[0])


def test_add_night_creates_an_unchecked_row(session, add_night):
    session.query(NightShiftRequirement).delete()
    _add(add_night, night_date='2026-01-02')

    req = session.query(NightShiftRequirement).one()
    assert (req.night_date.isoformat(), req.kind) == ('2026-01-02', c.NONE)


def test_add_night_refuses_a_date_that_already_has_a_row(session, add_night, setup_night):
    session.query(NightShiftRequirement).delete()
    session.add(setup_night)
    session.flush()

    assert 'already' in _add(add_night, night_date=N[0].isoformat())
    assert session.query(NightShiftRequirement).one().kind == c.SETUP


def test_add_night_requires_a_date(session, add_night):
    before = session.query(NightShiftRequirement).count()
    assert 'date' in _add(add_night, night_date='').lower()
    assert session.query(NightShiftRequirement).count() == before
