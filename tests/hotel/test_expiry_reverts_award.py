"""A lottery entry is AWARDED only while it holds a live room. When its
unsecured room expires - by the hourly card-deadline task or by an admin
marking it expired - the entry goes back to COMPLETE (and off its run) so
it can be drawn again; reinstating the room awards it again."""
from contextlib import contextmanager
from datetime import date, timedelta

import pytest

from uber.config import c

from tests.hotel.factories import (make_application, make_assignment,
                                   make_attendee, make_hotel, make_inventory,
                                   make_run)

DATES = dict(check_in=date(2027, 1, 6), check_out=date(2027, 1, 10))
PAST = date.today() - timedelta(days=2)


@pytest.fixture
def awarded(session):
    """An entry awarded one unsecured, card-required room by a lottery run
    whose card deadline has passed."""
    attendee = make_attendee(session)
    app = make_application(session, attendee)
    run = make_run(session, status=c.LOTTERY_AWARDED)
    app.lottery_run_id = run.id
    ra = make_assignment(session, attendee, make_inventory(session, make_hotel(session)),
                         lottery_run_id=run.id, lottery_application_id=app.id,
                         assignment_reason=c.LOTTERY_AWARD, deposit_cutoff_date=PAST,
                         **DATES)
    session.expire(app)
    assert app.status == c.AWARDED and ra.needs_card, 'fixture precondition'
    return app, ra


@pytest.fixture
def run_expiry_task(session, monkeypatch):
    import uber.tasks.hotel as hotel_tasks

    @contextmanager
    def same_session():
        yield session
    monkeypatch.setattr(hotel_tasks, 'Session', same_session)
    monkeypatch.setattr(session, 'commit', session.flush)
    return hotel_tasks.expire_unsecured_assignments


def test_expiry_task_reverts_entry_to_complete(session, awarded, run_expiry_task):
    app, ra = awarded

    assert run_expiry_task() == 1
    session.expire_all()
    assert ra.status == c.EXPIRED
    assert app.status == c.COMPLETE
    assert app.lottery_run_id is None


def test_expiry_task_keeps_entry_awarded_while_another_room_is_live(
        session, awarded, run_expiry_task):
    app, ra = awarded
    secured = make_assignment(session, app.attendee, ra.inventory,
                              lottery_run_id=ra.lottery_run_id,
                              lottery_application_id=app.id, status=c.SECURED,
                              cc_token='tok', **DATES)

    run_expiry_task()
    session.expire_all()
    assert ra.status == c.EXPIRED and secured.status == c.SECURED
    assert app.status == c.AWARDED, 'the entry still holds a room'


def test_admin_expiring_last_room_reverts_entry(session, awarded, no_cherrypy_session):
    from uber.hotel.service import apply_room_assignment_edits

    app, ra = awarded

    def fail(message):
        raise AssertionError(message)
    apply_room_assignment_edits(session, ra, {'status': str(c.EXPIRED)},
                                audit_prefix='test', fail=fail)
    session.flush()
    session.expire_all()
    assert app.status == c.COMPLETE
    assert app.lottery_run_id is None


def test_declining_last_room_does_not_reenter_the_lottery(session, awarded):
    """Only expiry sends an entry back into the draw; an attendee or hotel
    cancelling the room leaves the entry as it was."""
    app, ra = awarded
    ra.status = c.CANCELLED
    session.flush()
    session.expire_all()
    assert app.status == c.AWARDED


def test_reinstating_an_expired_room_awards_the_entry_again(session, awarded):
    app, ra = awarded
    ra.status = c.EXPIRED
    session.flush()
    session.expire_all()
    assert app.status == c.COMPLETE

    ra.status = c.ASSIGNED
    session.flush()
    session.expire_all()
    assert app.status == c.AWARDED


def test_pending_run_room_status_change_does_not_award(session):
    """Status changes on a pending run's rooms leave the entry COMPLETE:
    only Award Winners awards it."""
    attendee = make_attendee(session)
    app = make_application(session, attendee)
    run = make_run(session, status=c.LOTTERY_PENDING)
    app.lottery_run_id = run.id
    ra = make_assignment(session, attendee, make_inventory(session, make_hotel(session)),
                         lottery_run_id=run.id, lottery_application_id=app.id,
                         status=c.EXPIRED, **DATES)
    ra.status = c.ASSIGNED
    session.flush()
    session.expire_all()
    assert app.status == c.COMPLETE


# ---------------------------------------------------------------------------
# Hotel cancellations (imports and the hotel portal API)
# ---------------------------------------------------------------------------

def test_cancellation_import_cancels_the_entry(session, awarded):
    from uber.hotel.imports import apply_cancellation_rows

    app, ra = awarded
    result = apply_cancellation_rows(session, [{
        'lottery_application_id': app.id,
        'cancellation_confirmation_number': 'HOTEL-CXL-1'}])
    session.flush()
    session.expire_all()

    assert result['applied'] == 1
    assert ra.status == c.CANCELLED
    assert app.status == c.CANCELLED
    assert app.lottery_run_id == ra.lottery_run_id, 'the run stays on record'


def test_cancellation_import_sends_the_award_cancelled_email(session, awarded, monkeypatch):
    from uber.hotel.imports import apply_cancellation_rows
    from uber.models import AutomatedEmail, Email
    from tests.hotel.test_lottery_secrecy import _hotel_fixture_rows, _sweep

    # The email sweep commits; keep everything inside the test's rollback.
    monkeypatch.setattr(session, 'commit', session.flush)
    if not AutomatedEmail.initialized:
        AutomatedEmail.reconcile_fixtures()
        AutomatedEmail.initialized = True
    app, _ra = awarded
    rows = _hotel_fixture_rows(session)
    _sweep(session, rows)

    apply_cancellation_rows(session, [{'lottery_application_id': app.id}])
    session.flush()
    session.expire_all()
    _sweep(session, rows)

    assert session.query(Email).filter_by(
        ident='hotel_lottery_award_cancelled', fk_id=app.id).count() == 1


def test_hotel_cancelling_one_room_keeps_entry_awarded_while_another_is_live(
        session, awarded):
    """The hotel portal's API can cancel a single room; the entry stays
    AWARDED while it still holds another."""
    app, ra = awarded
    make_assignment(session, app.attendee, ra.inventory,
                    lottery_run_id=ra.lottery_run_id, lottery_application_id=app.id,
                    status=c.SECURED, cc_token='tok', **DATES)

    ra.cancellation_confirmation_number = 'HOTEL-CXL-2'
    session.add(ra)
    session.flush()
    session.expire_all()
    assert ra.status == c.CANCELLED
    assert app.status == c.AWARDED


def _cancel_email_text(app):
    import re
    from uber.decorators import render
    html = render('emails/hotel/cancel_notification.html', {'app': app}, encoding=None)
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html))


REASONS = ['credit card', 'deadline', 'declined', 'group leader', 'secure']


def test_cancel_email_says_the_hotel_cancelled_and_nothing_more(session, awarded):
    from uber.hotel.imports import apply_cancellation_rows

    app, _ra = awarded
    apply_cancellation_rows(session, [{'lottery_application_id': app.id,
                                       'cancellation_confirmation_number': 'HOTEL-CXL-3'}])
    session.flush()
    session.expire_all()

    text = _cancel_email_text(app)
    assert 'has been cancelled by the hotel.' in text
    assert not [r for r in REASONS if r in text.lower()], text


def test_cancel_email_without_hotel_number_gives_no_reason(session, awarded):
    """An admin can also cancel an entry; then the email just says so."""
    app, ra = awarded
    ra.status = c.CANCELLED
    app.status = c.CANCELLED
    session.flush()
    session.expire_all()

    text = _cancel_email_text(app)
    assert 'hotel lottery has been cancelled.' in text
    assert 'by the hotel' not in text
    assert not [r for r in REASONS if r in text.lower()], text
