"""Day-by-day email lifecycles for the hotel lottery.

Each test walks attendees through a full lifecycle on a simulated clock,
running the real automated-email sweep (generation) each day and then a
delivery pass that mirrors the send path: the send window must be open and
the fixture filter must still match, otherwise the queued row is deleted
(uber/email.py send_email does exactly this).

Assertions cover which email idents each persona receives and when, never
the bodies. All fixtures are treated as approved (policy AUTOSEND).
"""
from datetime import timedelta

import pytest

from uber.config import c
from uber.email import EmailService
from uber.models import AutomatedEmail, Email

from tests.hotel.factories import (N, make_application, make_assignment,
                                   make_attendee, make_hotel, make_inventory)

DEADLINE = c.HOTEL_LOTTERY_FORM_DEADLINE

HOTEL_IDENTS = [
    'enter_hotel_lottery',
    'hotel_lottery_reminder',
    'staff_hotel_lottery_reminder',
    'hotel_lottery_awarded',
    'hotel_lottery_guarantee_reminder',
    'hotel_lottery_rejected',
    'hotel_lottery_award_cancelled',
    'hotel_lottery_secured',
]


def _sim_now(offset):
    """Noon, `offset` days relative to the lottery form deadline."""
    return (DEADLINE + timedelta(days=offset)).replace(
        hour=12, minute=0, second=0)


@pytest.fixture
def email_world(session, monkeypatch):
    """Simulated clock plus sweep/deliver drivers against the real fixtures."""
    # Reconcile (own session, committed) BEFORE this session takes row locks,
    # and mark initialized so EmailHandler's @reconcile_fixtures decorator
    # does not reconcile again mid-test and deadlock against our updates.
    if not AutomatedEmail.initialized:
        AutomatedEmail.reconcile_fixtures()
        AutomatedEmail.initialized = True

    hotel_idents = {ident for ident, fixture in AutomatedEmail._fixtures.items()
                    if fixture.template.startswith('hotel/')}
    rows = {}
    for row in session.query(AutomatedEmail).filter(
            AutomatedEmail.ident.in_(hotel_idents)):
        row.policy = c.AUTOSEND
        rows[row.ident] = row
    session.flush()

    monkeypatch.setattr(session, 'commit', session.flush)

    class World:
        def __init__(self):
            self.now = _sim_now(-30)
            self.delivered = []  # (offset, ident, fk_id)
            self._offset = None

        def set_day(self, offset):
            self._offset = offset
            self.now = _sim_now(offset)

        def sweep(self):
            for ident in HOTEL_IDENTS:
                row = rows.get(ident)
                if row and row.fixture and row.fixture.filter \
                        and row.can_generate:
                    EmailService.check_emails_for_fixture(session, row)

        def deliver(self):
            for email in session.query(Email).filter(
                    Email.status == c.QUEUED):
                auto = email.automated_email
                if auto and auto.active_after and auto.active_after > self.now:
                    continue
                fixture = auto.fixture if auto else None
                if fixture and fixture.filter:
                    model = session.query(email.model_class).get(email.fk_id)
                    if not model or not fixture.filter(model):
                        session.delete(email)
                        continue
                email.status = c.SENT
                self.delivered.append((self._offset, email.ident, email.fk_id))
            session.flush()

        def run_day(self, offset, events=lambda: None):
            self.set_day(offset)
            events()
            self.sweep()
            self.deliver()

        def received(self, *fk_ids):
            """{day_offset: set of idents} delivered to any of the ids."""
            out = {}
            for offset, ident, fk_id in self.delivered:
                if fk_id in fk_ids:
                    out.setdefault(offset, set()).add(ident)
            return out

    world = World()
    monkeypatch.setattr('uber.utils.localized_now', lambda: world.now)
    return world


def test_lottery_email_lifecycles(session, no_cherrypy_session, email_world):
    """Winner, loser, and manually-roomed staff/guest, day -10 through +3.

    The loser also receives a manually assigned room after rejection: they
    must get the rejection (their entry genuinely lost) and then nothing
    else, so the safe room is never contradicted by lottery mail.
    """
    from uber.site_sections.hotel_lottery import _queue_entry_confirmation

    world = email_world
    world.set_day(-10)
    inv = make_inventory(session, make_hotel(session), quantity=5)

    registered = _sim_now(-11)
    winner = make_attendee(session, registered=registered)
    loser = make_attendee(session, registered=registered)
    staffer = make_attendee(session, badge_type=c.STAFF_BADGE,
                            registered=registered)
    guest = make_attendee(session, registered=registered)

    entry_started = _sim_now(-10) - timedelta(hours=1)
    winner_app = make_application(session, winner, status=c.PARTIAL,
                                  entry_started=entry_started)
    loser_app = make_application(session, loser, status=c.PARTIAL,
                                 entry_started=entry_started)

    # Manual rooms exist before the lottery nag window ever opens.
    make_assignment(session, staffer, inv, status=c.ASSIGNED,
                    assignment_reason=c.STAFF_AUTO, payment_type='masterbill',
                    check_in=N[1], check_out=N[3])
    make_assignment(session, guest, inv, status=c.ASSIGNED,
                    assignment_reason=c.MANUAL, payment_type='masterbill',
                    check_in=N[1], check_out=N[3])
    session.flush()

    def winner_completes():
        winner_app.status = c.COMPLETE
        _queue_entry_confirmation(session, winner_app,
                                  'entering the room lottery')

    def lottery_runs():
        loser_app.status = c.COMPLETE
        _queue_entry_confirmation(session, loser_app,
                                  'entering the room lottery')
        session.flush()
        winner_app.status = c.AWARDED
        make_assignment(session, winner, inv, status=c.ASSIGNED,
                        assignment_reason=c.LOTTERY_AWARD,
                        payment_type='credit_card',
                        booking_url='https://example.com/book',
                        deposit_cutoff_date=(DEADLINE + timedelta(days=6)).date(),
                        check_in=N[1], check_out=N[3],
                        lottery_application_id=winner_app.id)
        loser_app.status = c.REJECTED

    def loser_safe_room():
        make_assignment(session, loser, inv, status=c.ASSIGNED,
                        assignment_reason=c.MANUAL, payment_type='masterbill',
                        check_in=N[1], check_out=N[3])

    def winner_secures():
        winner_app.status = c.SECURED
        for ra in winner_app.lottery_room_assignments:
            ra.status = c.SECURED

    events = {
        -9: winner_completes,
        -1: lottery_runs,
        1: loser_safe_room,
        2: winner_secures,
    }
    for offset in range(-10, 4):
        world.run_day(offset, events.get(offset, lambda: None))

    assert world.received(winner.id, winner_app.id) == {
        -9: {'hotel_lottery_confirmation'},
        -1: {'hotel_lottery_awarded'},
        0: {'hotel_lottery_guarantee_reminder'},
        2: {'hotel_lottery_secured'},
    }
    assert world.received(loser.id, loser_app.id) == {
        -2: {'hotel_lottery_reminder'},
        -1: {'hotel_lottery_confirmation', 'hotel_lottery_rejected'},
    }
    assert world.received(staffer.id) == {}
    assert world.received(guest.id) == {}

    # Nobody is ever told they both won and lost.
    for ids in [(winner.id, winner_app.id), (loser.id, loser_app.id),
                (staffer.id,), (guest.id,)]:
        idents = set().union(*world.received(*ids).values()) \
            if world.received(*ids) else set()
        won = idents & {'hotel_lottery_awarded', 'hotel_lottery_secured',
                        'hotel_lottery_guarantee_reminder'}
        lost = idents & {'hotel_lottery_rejected'}
        assert not (won and lost)


def test_completing_an_entry_cancels_the_pending_reminder(
        session, no_cherrypy_session, email_world):
    """A reminder generated while the entry was PARTIAL must not deliver
    after the entry is completed: the send-time refilter drops it."""
    world = email_world
    world.set_day(-10)

    attendee = make_attendee(session, registered=_sim_now(-11))
    app = make_application(session, attendee, status=c.PARTIAL,
                           entry_started=_sim_now(-10) - timedelta(hours=1))
    session.flush()

    def completes():
        app.status = c.COMPLETE

    events = {-4: completes}
    for offset in range(-10, 0):
        world.run_day(offset, events.get(offset, lambda: None))

    assert world.received(attendee.id, app.id) == {}


def test_manual_room_after_registration_stops_the_lottery_nag(
        session, no_cherrypy_session, email_world):
    """An eligible attendee with no entry is nagged to enter, unless a room
    was assigned to them first: they already have a room."""
    world = email_world
    world.set_day(-10)
    inv = make_inventory(session, make_hotel(session), quantity=5)

    nagged = make_attendee(session, registered=_sim_now(-11))
    roomed = make_attendee(session, registered=_sim_now(-11))
    make_assignment(session, roomed, inv, status=c.ASSIGNED,
                    assignment_reason=c.MANUAL, payment_type='masterbill',
                    check_in=N[1], check_out=N[3])
    session.flush()

    for offset in range(-10, -5):
        world.run_day(offset)

    # The window opens at the deadline's clock time on day -7, which is
    # after that day's noon delivery pass, so the nag lands on day -6.
    assert world.received(nagged.id) == {-6: {'enter_hotel_lottery'}}
    assert world.received(roomed.id) == {}
