from datetime import datetime, timedelta

import pytest
import pytz

from uber.config import c
from uber.email import EmailService
from uber.models import AdminAccount, Email, Session
from uber.site_sections.email_admin import Root

from tests.emails.conftest import unwrap


@pytest.fixture
def queued_email(monkeypatch):
    """Commit a queued classless email; the send handler commits, so a rollback cannot undo it."""
    monkeypatch.setattr(AdminAccount, 'admin_name', staticmethod(lambda: 'Test Admin'))
    with Session() as session:
        EmailService.queue_email(session, 'pending_emails_admin', to='reports@example.com',
                                 subject='Pending Emails Report',
                                 data={'pending_emails_by_sender': {}, 'primary_sender': 'x@example.com',
                                       'subjects_by_id': {}})
        session.flush()
        email = session.query(Email).filter(Email.subject == 'Pending Emails Report',
                                            Email.status != c.SENT).order_by(Email.generated.desc()).first()
        email.status = c.QUEUED
        email.send_after = datetime.now(pytz.UTC) + timedelta(minutes=10)
        session.commit()
        email_id = email.id

    yield email_id

    with Session() as session:
        session.query(Email).filter(Email.id == email_id).delete()
        session.commit()


def test_admin_send_reports_success_and_stays_sent(session, queued_email):
    result = unwrap(Root.send_email)(Root(), session, id=queued_email)

    assert result['success'], result['message']
    with Session() as fresh:
        email = fresh.get(Email, queued_email)
        assert email.status == c.SENT
        assert email.sent is not None
