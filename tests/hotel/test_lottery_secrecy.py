"""A lottery's results stay secret until Award Winners is clicked.

Walks one lottery through every admin stage - running it, viewing and
editing the pending run, setting booking links, importing hotel
confirmations, exporting bookings, letting days pass with the automated
email sweep and the card-deadline cron running - and after each stage
checks that:

  * no email was queued, either directly or by an automated fixture, and
  * every attendee-visible page renders exactly as it did before the run.

Then it awards the run and checks that the winners' pages do change and
their award email is generated, so the comparison isn't vacuous.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace

import cherrypy
import pytest

from uber.config import c
from uber.errors import HTTPRedirect

from tests.hotel.factories import (make_application, make_assignment,
                                   make_attendee, make_hotel, make_inventory,
                                   make_room_type)

CHECK_IN = c.HOTEL_LOTTERY_CHECKIN_START.date()
CHECK_OUT = c.HOTEL_LOTTERY_CHECKOUT_END.date()


def _unwrap(func, stop_at=None):
    while hasattr(func, '__wrapped__') and func.__code__ is not stop_at:
        func = func.__wrapped__
    return func


def _call(root_cls, handler, session, **kwargs):
    """Call a site-section handler below its decorators. Returns the
    template context, or the redirect URL when the handler redirects."""
    try:
        return _unwrap(getattr(root_cls, handler))(root_cls(), session, **kwargs)
    except HTTPRedirect as e:
        return {'redirect': e.urls[0]}


@pytest.fixture
def world(session, monkeypatch, no_cherrypy_session):
    import uber.site_sections.hotel_lottery as attendee_site
    import uber.site_sections.hotel_lottery_admin as admin_site
    import uber.tasks.hotel as hotel_tasks
    from uber.models import AutomatedEmail, initialize_db

    initialize_db()
    if not AutomatedEmail.initialized:
        AutomatedEmail.reconcile_fixtures()
        AutomatedEmail.initialized = True

    # Handlers run as POSTs with CSRF and ownership checks stubbed: those
    # gates have their own tests and aren't what this one probes.
    monkeypatch.setattr(cherrypy.request, 'method', 'POST')
    for module in (attendee_site, admin_site):
        monkeypatch.setattr(module, 'check_csrf', lambda *a, **k: None, raising=False)
        monkeypatch.setattr(module, '_require_post_csrf', lambda *a, **k: None, raising=False)
    monkeypatch.setattr(attendee_site, '_require_view_as_attendee', lambda *a, **k: None)
    monkeypatch.setattr(session, 'commit', session.flush)

    # The card-deadline cron opens its own Session; hand it ours.
    @contextmanager
    def same_session():
        yield session
    monkeypatch.setattr(hotel_tasks, 'Session', same_session)

    class World:
        now = datetime.now(c.EVENT_TIMEZONE)

    w = World()
    monkeypatch.setattr('uber.utils.localized_now', lambda: w.now)
    monkeypatch.setattr(hotel_tasks, 'localized_now', lambda: w.now)
    return w


def _hotel_fixture_rows(session):
    from uber.models import AutomatedEmail

    idents = {ident for ident, fixture in AutomatedEmail._fixtures.items()
              if fixture.template.startswith('hotel/')}
    rows = session.query(AutomatedEmail).filter(AutomatedEmail.ident.in_(idents)).all()
    for row in rows:
        row.policy = c.AUTOSEND
    session.flush()
    return rows


def _sweep(session, rows):
    """Run the automated email generator for every hotel fixture."""
    from uber.email import EmailService

    for row in rows:
        if row.fixture and row.fixture.filter and row.can_generate:
            EmailService.check_emails_for_fixture(session, row)
    session.flush()


def _emails(session):
    from uber.models import Email
    return {(e.ident, e.fk_id) for e in session.query(Email)}


def _render(template, ctx):
    from uber.decorators import render
    if 'redirect' in ctx:
        return 'REDIRECT ' + ctx['redirect']
    return render(template, ctx, encoding=None)


def _diff(before, after):
    import difflib
    return '\n'.join(line for line in difflib.unified_diff(
        before.splitlines(), after.splitlines(), 'before', 'after', lineterm='', n=1)
        if line.strip())


def _attendee_view(session, attendee):
    """Everything this attendee can see about their hotel situation, as
    rendered text: the lottery status page, the rooms list, every room
    page they can open (probing every assignment in the database by id),
    their badge card, their lottery entry and room group pages, and the
    card-capture status endpoint."""
    from uber.models.hotel import RoomAssignment
    from uber.site_sections.hotel_lottery import (Root, _render_room_detail,
                                                  _secure_flow_assignment)

    session.expire_all()
    # Viewing is a GET: under the fixture's POST the entry-form handlers
    # would save (and so change) the entry they're displaying.
    cherrypy.request.method = 'GET'
    try:
        return _attendee_view_get(session, attendee, Root, _render_room_detail,
                                  _secure_flow_assignment, RoomAssignment)
    finally:
        cherrypy.request.method = 'POST'


def _attendee_view_get(session, attendee, Root, _render_room_detail,
                       _secure_flow_assignment, RoomAssignment):
    view = {
        'index': _render('hotel_lottery/index.html',
                         _call(Root, 'index', session, attendee_id=attendee.id)),
        'rooms': _render('hotel_lottery/rooms.html',
                         _call(Root, 'rooms', session, attendee_id=attendee.id)),
        'card': _render('preregistration/attendee_card.html',
                        {'attendee': attendee,
                         'account': SimpleNamespace(owner=attendee)}),
    }
    app = attendee.lottery_application
    if app:
        for page in ('room_lottery', 'suite_lottery', 'room_group'):
            view[page] = _render(f'hotel_lottery/{page}.html',
                                 _call(Root, page, session, id=app.id))
    for ra in session.query(RoomAssignment).order_by(RoomAssignment.created):
        try:
            ctx = _render_room_detail(session, ra.id, attendee.id, '')
            view[f'room {ra.id}'] = _render('hotel_lottery/room.html', ctx)
        except HTTPRedirect:
            pass  # Same "not found / no access" as a room that never existed.
        found, _error = _secure_flow_assignment(session, ra.id)
        if found and found.attendee_id == attendee.id:
            view[f'card_status {ra.id}'] = 'available'
    return view


def test_nothing_is_revealed_until_award_winners(session, world):
    from uber.hotel.exports import booking_export_data
    from uber.hotel.imports import apply_confirmation_rows
    from uber.hotel.solver import build_eligible_applications
    from uber.models.hotel import LotteryRun, RoomAssignment
    from uber.site_sections.hotel_lottery_admin import (
        Root as Admin, _send_confirmation_updated_email)
    from uber.tasks.hotel import expire_unsecured_assignments

    hotel = make_hotel(session)
    room_type = make_room_type(session)
    unwanted_type = make_room_type(session)
    make_inventory(session, hotel, room_type, quantity=5)

    def entry(attendee, **overrides):
        params = dict(entry_type=c.ROOM_ENTRY, status=c.COMPLETE,
                      hotel_preference=hotel.id,
                      room_type_preference=room_type.id,
                      earliest_checkin_date=CHECK_IN,
                      latest_checkout_date=CHECK_OUT,
                      last_submitted=world.now - timedelta(days=1),
                      confirmation_num=f'CONF-{attendee.id[:8]}',
                      guarantee_policy_accepted=True)
        params.update(overrides)
        return make_application(session, attendee, **params)

    solo = make_attendee(session)
    leader = make_attendee(session)
    member = make_attendee(session)
    loser = make_attendee(session)
    bystander = make_attendee(session)  # holds a manual room all along

    entry(solo)
    leader_app = entry(leader, room_group_name='The Group')
    entry(member, entry_type=c.GROUP_ENTRY, parent_application_id=leader_app.id,
          hotel_preference='', room_type_preference='')
    entry(loser, room_type_preference=unwanted_type.id)  # no such inventory
    make_assignment(session, bystander, make_inventory(session, hotel),
                    check_in=CHECK_IN, check_out=CHECK_OUT,
                    booking_url='https://example.com/bystander')
    attendees = {'solo': solo, 'leader': leader, 'member': member,
                 'loser': loser, 'bystander': bystander}

    fixture_rows = _hotel_fixture_rows(session)
    _sweep(session, fixture_rows)  # whatever was already due goes out now
    baseline_emails = _emails(session)
    baseline = {name: _attendee_view(session, a) for name, a in attendees.items()}

    leaks = []
    seen_emails = set(baseline_emails)

    def assert_nothing_revealed(stage):
        """Record (rather than raise on) every leak, so one run of the test
        reports all of them across all stages."""
        _sweep(session, fixture_rows)
        new_emails = _emails(session) - seen_emails
        if new_emails:
            leaks.append(f'{stage}: emails queued before award: {sorted(new_emails)}')
            seen_emails.update(new_emails)
        for name, attendee in attendees.items():
            view = _attendee_view(session, attendee)
            if view.keys() != baseline[name].keys():
                leaks.append(f'{stage}: pages {name} can open changed: '
                             f'{sorted(set(view) ^ set(baseline[name]))}')
            for page in sorted(view.keys() & baseline[name].keys()):
                if view[page] != baseline[name][page]:
                    leaks.append(f'{stage}: {name}\'s {page} page changed before award:\n'
                                 + _diff(baseline[name][page], view[page]))

    # 1. Run the lottery.
    result = _call(Admin, 'run_lottery', session, lottery_group='attendee',
                   lottery_type='room', run_name='Secrecy Run')
    run = session.query(LotteryRun).one()
    pending_rooms = session.query(RoomAssignment).filter_by(lottery_run_id=run.id).all()
    assert run.status == c.LOTTERY_PENDING, result
    assert {ra.attendee_id for ra in pending_rooms} == {solo.id, leader.id}, \
        'precondition: the run should award the solo entry and the group leader'
    assert_nothing_revealed('run lottery')
    if {app.attendee_id for app in build_eligible_applications(
            session, c.ROOM_ENTRY, 'attendee')} & {solo.id, leader.id}:
        leaks.append('run lottery: a second run would consider entries that '
                     'already won this one')

    # 2. Admin looks the run over and edits it.
    _call(Admin, 'lottery_runs', session)
    _call(Admin, 'lottery_run_detail', session, id=run.id)
    _call(Admin, 'update_lottery_run', session, id=run.id, name='Renamed Run')
    _call(Admin, 'update_run_card_deadline', session, id=run.id,
          card_deadline=(world.now + timedelta(days=3)).strftime('%Y-%m-%d'),
          propagate='true')
    assert_nothing_revealed('edit pending run')

    # 3. Booking links arrive and the hotel sends confirmation numbers back.
    for ra in pending_rooms:
        ra.booking_url = f'https://example.com/book/{ra.id}'
    session.flush()
    apply_confirmation_rows(
        session,
        [{'lottery_application_id': ra.lottery_application_id,
          'hotel_confirmation_number': f'HOTEL-{ra.id[:6]}'} for ra in pending_rooms],
        apply_changes=True,
        on_update=lambda ra: _send_confirmation_updated_email(session, ra))
    session.flush()
    assert_nothing_revealed('booking links and confirmation import')

    # 4. Booking exports go to the hotel.
    _hotel, rows = booking_export_data(session, hotel.id)
    exported = ' '.join(str(cell) for row in rows for cell in row)
    if any(ra.id in exported for ra in pending_rooms):
        leaks.append('booking export: pending rooms were exported to the hotel')
    assert_nothing_revealed('booking export')

    # 5. Days pass: the reminder sweep and the card-deadline cron keep running.
    for _day in range(10):
        world.now += timedelta(days=1)
        expire_unsecured_assignments()
        assert_nothing_revealed(f'day {_day + 1}')
    if any(ra.status != c.ASSIGNED for ra in pending_rooms):
        leaks.append('days pass: the card-deadline cron expired rooms nobody could see')

    assert not leaks, '\n\n'.join(leaks)

    # 6. Award Winners. Now the winners' pages change and mail goes out.
    world.now = datetime.now(c.EVENT_TIMEZONE)
    _call(Admin, 'award_run', session, id=run.id)
    session.expire_all()
    assert run.status == c.LOTTERY_AWARDED
    _sweep(session, fixture_rows)

    new_emails = _emails(session) - baseline_emails
    awarded_ids = {app.id for app in (solo.lottery_application, leader_app)}
    assert {fk for ident, fk in new_emails if ident == 'hotel_lottery_awarded'} \
        == awarded_ids
    for name in ('solo', 'leader', 'member'):
        assert _attendee_view(session, attendees[name]) != baseline[name], \
            f'{name}\'s pages should show the award once it is made'
    for name in ('loser', 'bystander'):
        assert _attendee_view(session, attendees[name]) == baseline[name]
