"""Which rooms put a staffer under the night shift requirements behind the
hotel banner and the Staff Rooming compliance report."""

from datetime import datetime, time

import pytest

from uber.config import c
from uber.models.hotel import NightShiftRequirement
from uber.shift_compliance import (compliance_violations, non_compliant_staffers, room_reason_opts,
                                   staff_rooming_config)

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


def _room_rules(session, **changes):
    data = staff_rooming_config.load_data(session)
    data.update(changes)
    staff_rooming_config.save(data, session)


@pytest.mark.parametrize('payment_type, checked', [
    ('masterbill', True), ('masterbill_parking', True),
    ('credit_card', False), ('credit_card_parking', False),
])
def test_default_billing_checks_both_master_bill_types(session, setup_night, payment_type, checked):
    staffer = _staffer(session)
    _room(session, staffer, payment_type=payment_type)
    assert bool(compliance_violations(staffer, {N[0]: setup_night})) is checked


def test_self_paid_room_is_not_checked(session, setup_night):
    staffer = _staffer(session)
    _room(session, staffer, payment_type='credit_card')
    assert compliance_violations(staffer, {N[0]: setup_night}) == []


@pytest.mark.parametrize('reason', ['LOTTERY_AWARD', 'SUITE_CONNECTOR'])
def test_lottery_room_is_not_checked_even_on_master_bill(session, setup_night, reason):
    staffer = _staffer(session)
    _lottery_room(session, staffer, getattr(c, reason))
    assert compliance_violations(staffer, {N[0]: setup_night}) == []


@pytest.mark.parametrize('payment_type, checked', [('masterbill', True), ('credit_card', False)])
def test_manual_room_added_from_a_lottery_entry_counts_only_on_master_bill(
        session, setup_night, payment_type, checked):
    staffer = _staffer(session)
    app = make_application(session, staffer)
    _room(session, staffer, lottery_application_id=app.id, payment_type=payment_type)
    assert bool(compliance_violations(staffer, {N[0]: setup_night})) is checked


def test_non_staff_badge_is_not_checked(session, setup_night):
    volunteer = make_attendee(session)
    _room(session, volunteer)
    assert compliance_violations(volunteer, {N[0]: setup_night}) == []


def test_checked_room_still_counts_beside_an_exempt_room(session, setup_night):
    staffer = _staffer(session)
    _lottery_room(session, staffer, c.LOTTERY_AWARD)
    _room(session, staffer)
    assert compliance_violations(staffer, {N[0]: setup_night}) == [setup_night]


def test_room_rules_can_count_self_paid_rooms(session, setup_night):
    _room_rules(session, payment_types=list(c.HOTEL_PAYMENT_TYPES))
    staffer = _staffer(session)
    _room(session, staffer, payment_type='credit_card')
    assert compliance_violations(staffer, {N[0]: setup_night}) == [setup_night]


def test_room_rules_can_skip_master_bill_rooms(session, setup_night):
    _room_rules(session, payment_types=['credit_card'])
    staffer = _staffer(session)
    _room(session, staffer)
    assert compliance_violations(staffer, {N[0]: setup_night}) == []


def test_room_rules_can_count_lottery_awards(session, setup_night):
    _room_rules(session, room_reasons=staff_rooming_config.defaults['room_reasons'] + [c.LOTTERY_AWARD])
    staffer = _staffer(session)
    _lottery_room(session, staffer, c.LOTTERY_AWARD)
    assert compliance_violations(staffer, {N[0]: setup_night}) == [setup_night]


def test_room_rules_can_check_other_badge_types(session, setup_night):
    _room_rules(session, badge_types=[c.STAFF_BADGE, c.ATTENDEE_BADGE])
    volunteer = make_attendee(session)
    _room(session, volunteer)
    assert compliance_violations(volunteer, {N[0]: setup_night}) == [setup_night]


def test_report_follows_room_rules(session, setup_night):
    session.query(NightShiftRequirement).delete()
    session.add(setup_night)
    session.flush()
    _room_rules(session, payment_types=list(c.HOTEL_PAYMENT_TYPES), badge_types=[c.STAFF_BADGE, c.ATTENDEE_BADGE])

    self_paid = _staffer(session)
    _room(session, self_paid, payment_type='credit_card')
    volunteer = make_attendee(session)
    _room(session, volunteer)

    flagged = {attendee.id for attendee, _ in non_compliant_staffers(session)}
    assert {self_paid.id, volunteer.id} <= flagged


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


def _share(session, room, *roommates):
    room.occupants.extend(roommates)
    session.flush()
    for roommate in roommates:
        session.expire(roommate, ['occupied_rooms'])


def test_staff_roommate_in_a_checked_room_is_checked(session, setup_night):
    room = _room(session, _staffer(session))
    roommate = _staffer(session)
    _share(session, room, roommate)
    assert compliance_violations(roommate, {N[0]: setup_night}) == [setup_night]


def test_roommate_in_a_lottery_room_is_not_checked(session, setup_night):
    room = _lottery_room(session, _staffer(session), c.LOTTERY_AWARD)
    roommate = _staffer(session)
    _share(session, room, roommate)
    assert compliance_violations(roommate, {N[0]: setup_night}) == []


def test_roommate_badge_is_checked_on_its_own(session, setup_night):
    room = _room(session, _staffer(session))
    volunteer = make_attendee(session)
    _share(session, room, volunteer)
    assert compliance_violations(volunteer, {N[0]: setup_night}) == []


def test_holder_stays_checked_when_left_off_the_occupant_list(session, setup_night):
    holder = _staffer(session)
    room = _room(session, holder)
    _share(session, room, _staffer(session))
    assert compliance_violations(holder, {N[0]: setup_night}) == [setup_night]


def test_report_lists_every_staffer_sharing_a_checked_room(session, setup_night):
    session.query(NightShiftRequirement).delete()
    session.add(setup_night)
    session.flush()

    holder = _staffer(session)
    room = _room(session, holder)
    roommates = [_staffer(session) for _ in range(3)]
    _share(session, room, *roommates)
    lottery_roommate = _staffer(session)
    _share(session, _lottery_room(session, _staffer(session), c.LOTTERY_AWARD), lottery_roommate)

    flagged = {attendee.id for attendee, _ in non_compliant_staffers(session)}
    assert {holder.id, *(r.id for r in roommates)} <= flagged
    assert lottery_roommate.id not in flagged


@pytest.fixture
def post(session, monkeypatch):
    """Call a Staff Rooming handler unwrapped, as a POST with CSRF stubbed and
    commits turned into flushes. Returns the redirect's message text."""
    from urllib.parse import unquote

    import cherrypy

    import uber.site_sections.staff_rooming as staff_rooming
    from uber.errors import HTTPRedirect

    monkeypatch.setattr(cherrypy.request, 'method', 'POST')
    monkeypatch.setattr(staff_rooming, 'check_csrf', lambda *a, **k: None)
    monkeypatch.setattr(session, 'commit', session.flush)

    def call(name, **kwargs):
        func = getattr(staff_rooming.Root, name)
        while hasattr(func, '__wrapped__'):
            func = func.__wrapped__
        with pytest.raises(HTTPRedirect) as excinfo:
            func(staff_rooming.Root(), session, **kwargs)
        return unquote(excinfo.value.urls[0])
    return call


def test_add_night_creates_an_unchecked_row(session, post):
    session.query(NightShiftRequirement).delete()
    post('add_night', night_date='2026-01-02')

    req = session.query(NightShiftRequirement).one()
    assert (req.night_date.isoformat(), req.kind) == ('2026-01-02', c.NONE)


def test_add_night_refuses_a_date_that_already_has_a_row(session, post, setup_night):
    session.query(NightShiftRequirement).delete()
    session.add(setup_night)
    session.flush()

    assert 'already' in post('add_night', night_date=N[0].isoformat())
    assert session.query(NightShiftRequirement).one().kind == c.SETUP


def test_add_night_requires_a_date(session, post):
    before = session.query(NightShiftRequirement).count()
    assert 'date' in post('add_night', night_date='').lower()
    assert session.query(NightShiftRequirement).count() == before


def test_save_room_rules_stores_the_checked_boxes(session, post):
    post('save_room_rules', badge_types=[str(c.STAFF_BADGE), str(c.ATTENDEE_BADGE)],
         room_reasons=str(c.MANUAL), payment_types='credit_card')

    rules = staff_rooming_config.load_data(session)
    assert rules == {'badge_types': [c.STAFF_BADGE, c.ATTENDEE_BADGE], 'room_reasons': [c.MANUAL],
                     'payment_types': ['credit_card']}


def test_save_room_rules_with_no_boxes_checks_nothing(session, post, setup_night):
    post('save_room_rules')
    staffer = _staffer(session)
    _room(session, staffer)
    assert compliance_violations(staffer, {N[0]: setup_night}) == []


def test_page_shows_plain_names_for_room_reasons(session, no_cherrypy_session):
    from uber.decorators import render

    html = render('staff_rooming/index.html', {
        'message': '', 'requirements': [], 'night_kind_opts': c.NIGHT_KIND_OPTS,
        'room_rules': staff_rooming_config.load(session), 'badge_opts': c.BADGE_OPTS,
        'room_reason_opts': room_reason_opts()})
    html = html.decode() if isinstance(html, bytes) else html

    assert 'Won in the lottery' in html
    assert 'Migrated From Legacy' not in html
    assert 'Billing' in html
    assert 'id="payment-type-masterbill_parking" checked' in html
    assert 'id="payment-type-credit_card" />' in html
