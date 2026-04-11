"""
Email idempotency tests for send_automated_emails().

Tests that:
1. Running send_automated_emails() twice never sends a duplicate email to
   the same recipient (application-level deduplication via fk_id_list).
2. The PostgreSQL advisory lock prevents a second concurrent worker from
   processing the same AutomatedEmail simultaneously.
3. A partial run (crash after N sends) does not re-send to already-emailed
   recipients on the next run.
"""

import uuid

import pytest
from sqlalchemy import text, select, func

from uber.models import Session, AutomatedEmail, Attendee
from uber.models.email import Email
from uber.tasks.email import send_automated_emails

from tests.uber.email_tests.email_fixtures import *  # noqa: F401,F403


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def approve_all_emails():
    """Set all AutomatedEmail records to approved=True so they will send."""
    with Session() as session:
        for ae in session.query(AutomatedEmail):
            ae.approved = True
        session.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _email_count(session):
    """Count Email records created by automated email sending."""
    return session.query(Email).count()


def _emails_for_ident(session, ident):
    """Return all Email records for a given ident."""
    return session.query(Email).filter(Email.ident == ident).all()


# ---------------------------------------------------------------------------
# Sequential idempotency: second run sends no duplicates
# ---------------------------------------------------------------------------

class TestSequentialIdempotency:

    @pytest.mark.usefixtures('create_test_attendees', 'automated_email_fixture', 'fixed_localized_now', 'approve_all_emails')
    def test_second_run_sends_no_new_emails(self, mock_send_email):
        """
        Running send_automated_emails() twice with the same attendees and the
        same active email should result in exactly 5 emails (one per attendee),
        not 10.
        """
        result1 = send_automated_emails()
        first_run_count = mock_send_email.call_count
        assert first_run_count == 5, f"Expected 5 emails on first run, got {first_run_count}"

        result2 = send_automated_emails()
        second_run_count = mock_send_email.call_count
        assert second_run_count == 5, (
            f"Expected no new emails on second run, but mock was called "
            f"{second_run_count - first_run_count} additional times"
        )

    @pytest.mark.usefixtures('create_test_attendees', 'automated_email_fixture', 'fixed_localized_now', 'approve_all_emails')
    def test_second_run_email_records_count_unchanged(self, mock_send_email):
        """
        The number of Email records in the DB should not increase on a second run.
        """
        send_automated_emails()
        with Session() as session:
            count_after_first = _email_count(session)

        send_automated_emails()
        with Session() as session:
            count_after_second = _email_count(session)

        assert count_after_first == 5
        assert count_after_second == 5, (
            f"Email DB records increased from {count_after_first} to {count_after_second} on second run"
        )

    @pytest.mark.usefixtures('create_test_attendees', 'automated_email_fixture', 'fixed_localized_now', 'approve_all_emails')
    def test_each_attendee_receives_exactly_one_email(self, mock_send_email):
        """
        Each of the 5 test attendees receives exactly one email, even across
        multiple send runs.
        """
        send_automated_emails()
        send_automated_emails()
        send_automated_emails()

        with Session() as session:
            emails = _emails_for_ident(session, 'attendee_txt')
            fk_ids = [e.fk_id for e in emails]

        assert len(fk_ids) == 5, f"Expected 5 Email records, got {len(fk_ids)}"
        assert len(set(fk_ids)) == 5, "Duplicate fk_ids found — same attendee emailed twice"


# ---------------------------------------------------------------------------
# Advisory lock: lock held elsewhere prevents sending
# ---------------------------------------------------------------------------

class TestAdvisoryLock:

    @pytest.mark.usefixtures('create_test_attendees', 'automated_email_fixture', 'fixed_localized_now', 'approve_all_emails')
    def test_held_advisory_lock_prevents_send(self, mock_send_email):
        """
        If another worker holds the advisory lock for an AutomatedEmail,
        send_automated_emails() must skip it and send no emails for that fixture.

        We simulate "another worker" by acquiring pg_advisory_lock (blocking
        form) on a separate connection before calling send_automated_emails().
        The function uses pg_try_advisory_lock (non-blocking), which will
        return False and cause it to skip.
        """
        from uber.models import Session as UberSession

        with Session() as session:
            ae = session.query(AutomatedEmail).filter_by(ident='attendee_txt').one()
            ae_id = ae.id

        lock_key = uuid.UUID(str(ae_id)).int & ((1 << 63) - 1)

        # Acquire blocking advisory lock on a fresh connection (outside the test transaction)
        lock_conn = UberSession.engine.connect()
        try:
            lock_conn.execute(text(f"SELECT pg_advisory_lock({lock_key})"))

            result = send_automated_emails()

            # No emails should have been sent — lock prevented processing
            assert mock_send_email.call_count == 0, (
                f"Expected 0 emails with lock held, but {mock_send_email.call_count} were sent"
            )
        finally:
            # Release the lock by closing the connection
            lock_conn.close()

    @pytest.mark.usefixtures('create_test_attendees', 'automated_email_fixture', 'fixed_localized_now', 'approve_all_emails')
    def test_after_lock_released_emails_send_normally(self, mock_send_email):
        """
        After the competing lock is released, the next run sends normally.
        """
        from uber.models import Session as UberSession

        with Session() as session:
            ae = session.query(AutomatedEmail).filter_by(ident='attendee_txt').one()
            lock_key = uuid.UUID(str(ae.id)).int & ((1 << 63) - 1)

        # Hold lock for first run, release before second
        lock_conn = UberSession.engine.connect()
        lock_conn.execute(text(f"SELECT pg_advisory_lock({lock_key})"))

        send_automated_emails()
        assert mock_send_email.call_count == 0  # blocked

        lock_conn.close()  # releases the advisory lock

        send_automated_emails()
        assert mock_send_email.call_count == 5  # now succeeds


# ---------------------------------------------------------------------------
# Crash recovery: partial run followed by full run
# ---------------------------------------------------------------------------

class TestCrashRecovery:

    @pytest.mark.usefixtures('create_test_attendees', 'fixed_localized_now')
    def test_partial_send_no_duplicates_on_retry(self, mock_send_email, clear_automated_email_fixtures,
                                                  render_empty_attendee_template):
        """
        Simulate a partial send by manually creating Email records for a subset
        of attendees. The next full send should only email the remaining attendees.
        """
        from uber.automated_emails import AutomatedEmailFixture

        AutomatedEmailFixture(
            Attendee,
            'Test Email {EVENT_NAME}',
            'attendee.txt',
            filter=lambda a: True,
            ident='partial_test_email',
            sender='test@example.com',
        )
        AutomatedEmail.reconcile_fixtures()

        # Approve the email so it will send
        with Session() as session:
            ae = session.query(AutomatedEmail).filter_by(ident='partial_test_email').one()
            ae.approved = True
            ae_id = ae.id
            session.commit()

            # Simulate a partial previous run: manually create Email records for
            # 3 of the 5 attendees (as if a previous worker crashed after sending 3)
            attendees = session.query(Attendee).filter(
                Attendee.first_name.in_(['0', '1', '2'])
            ).all()
            assert len(attendees) == 3

            for attendee in attendees:
                session.add(Email(
                    automated_email_id=ae_id,
                    fk_id=attendee.id,
                    model='Attendee',
                    ident='partial_test_email',
                    subject='Test',
                    body='test body',
                    sender='test@example.com',
                    to=attendee.email,
                ))
            session.commit()

        # Run send_automated_emails — should only email the remaining 2 attendees
        send_automated_emails()

        assert mock_send_email.call_count == 2, (
            f"Expected 2 emails for remaining attendees, got {mock_send_email.call_count}"
        )

        # Verify no duplicates: total Email records should be 5 (3 existing + 2 new)
        with Session() as session:
            emails = _emails_for_ident(session, 'partial_test_email')
            fk_ids = [e.fk_id for e in emails]

        assert len(fk_ids) == 5
        assert len(set(fk_ids)) == 5, "Duplicate fk_ids found after recovery run"

    @pytest.mark.usefixtures('create_test_attendees', 'automated_email_fixture', 'fixed_localized_now', 'approve_all_emails')
    def test_new_attendee_added_after_first_run_receives_email(self, mock_send_email):
        """
        An attendee added after the first send run should receive the email on
        the next run, while previously-emailed attendees should not be re-emailed.
        """
        send_automated_emails()
        assert mock_send_email.call_count == 5

        # Add a new attendee
        new_id = '00000000-0000-0000-0000-000000000099'
        with Session() as session:
            session.add(Attendee(
                id=new_id,
                first_name='new',
                last_name='attendee',
                email='new@example.com',
            ))
            session.commit()

        send_automated_emails()
        assert mock_send_email.call_count == 6, (
            f"Expected exactly 1 new email for the new attendee, "
            f"got {mock_send_email.call_count - 5} new emails"
        )
