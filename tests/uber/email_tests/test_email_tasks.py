"""
Tests for uber.tasks.email scheduled tasks.
"""

import pytest

from uber.config import c, Config
from uber.models import AutomatedEmail, Session
from uber.tasks.email import notify_admins_of_pending_emails, send_automated_emails

from tests.uber.email_tests.email_fixtures import *  # noqa: F401,F403


@pytest.fixture
def enable_report(monkeypatch):
    monkeypatch.setattr(c, 'ENABLE_PENDING_EMAILS_REPORT', True)
    monkeypatch.setattr(Config, 'PRE_CON', property(lambda s: True))


class TestNotifyAdminsOfPendingEmails(object):
    @pytest.mark.parametrize('send_emails,dev_box,expected', [
        (True, True, dict),
        (False, True, dict),
        (True, False, dict),
        (False, False, type(None)),
    ])
    def test_config_send_email_dev_box(self, monkeypatch, send_emails, dev_box, expected):
        monkeypatch.setattr(c, 'SEND_EMAILS', send_emails)
        monkeypatch.setattr(c, 'DEV_BOX', dev_box)
        monkeypatch.setattr(c, 'ENABLE_PENDING_EMAILS_REPORT', True)
        monkeypatch.setattr(Config, 'PRE_CON', lambda: True)
        assert isinstance(notify_admins_of_pending_emails(), expected)

    @pytest.mark.parametrize('enable_pending_emails_report,pre_con,expected', [
        (True, True, dict),
        (False, True, type(None)),
        (True, False, type(None)),
        (False, False, type(None)),
    ])
    def test_config(self, monkeypatch, enable_pending_emails_report, pre_con, expected):
        monkeypatch.setattr(c, 'SEND_EMAILS', True)
        monkeypatch.setattr(c, 'DEV_BOX', False)
        monkeypatch.setattr(c, 'ENABLE_PENDING_EMAILS_REPORT', enable_pending_emails_report)
        monkeypatch.setattr(Config, 'PRE_CON', property(lambda s: pre_con))
        assert isinstance(notify_admins_of_pending_emails(), expected)

    @pytest.mark.parametrize('approved,needs_approval,unapproved_count,expected,send_email_counts', [
        (False, False, 0, {}, [0, 0]),
        (False, True, 0, {}, [0, 0]),
        (
            False, True, 1, {
                'test_even@example.com': ['attendee_html', 'attendee_html_after_08/09'],
                'test_odd@example.com': ['attendee_txt_before_08/11', 'attendee_txt_after_08/09_before_08/11'],
            }, [2, 4]
        ),
        (True, True, 0, {}, [0, 0]),
    ])
    @pytest.mark.usefixtures(
        'create_test_attendees',
        'automated_email_fixtures',
        'enable_report',
        'fixed_localized_now',
    )
    def test_notify_admins_of_pending_emails(
            self, mock_send_email, approved, needs_approval, unapproved_count, expected, send_email_counts):

        with Session() as session:
            for email in session.query(AutomatedEmail):
                email.approved = approved
                email.needs_approval = needs_approval
                email.unapproved_count = unapproved_count

        for send_email_count in send_email_counts:
            result = notify_admins_of_pending_emails()
            assert isinstance(result, type(expected))
            assert result == expected
            assert mock_send_email.call_count == send_email_count


class TestSendAutomatedEmails(object):
    @pytest.mark.parametrize('send_emails,dev_box,expected', [
        (True, True, dict),
        (False, True, dict),
        (True, False, dict),
        (False, False, type(None)),
    ])
    def test_config_send_email_dev_box(self, monkeypatch, send_emails, dev_box, expected):
        monkeypatch.setattr(c, 'SEND_EMAILS', send_emails)
        monkeypatch.setattr(c, 'DEV_BOX', dev_box)
        assert isinstance(send_automated_emails(), expected)

    @pytest.mark.parametrize('approved,needs_approval,expected,send_email_counts', [
        (True, True, {}, [20, 20]),
        (
            False, True, {
                'attendee_html': 5,
                'attendee_html_after_08/09': 5,
                'attendee_txt_after_08/09_before_08/11': 5,
                'attendee_txt_before_08/11': 5,
            }, [0, 0]
        ),
    ])
    @pytest.mark.usefixtures('create_test_attendees', 'automated_email_fixtures', 'fixed_localized_now')
    def test_send_automated_emails(self, mock_send_email, approved, needs_approval, expected, send_email_counts):

        inactive = {
            'attendee_html_after_08/11': 42,
            'attendee_txt_after_08/11_before_08/12': 42,
            'attendee_html_before_08/09': 42,
            'attendee_txt_after_08/08_before_08/09': 42,
        }

        with Session() as session:
            for automated_email in session.query(AutomatedEmail):
                automated_email.approved = approved
                automated_email.needs_approval = needs_approval
                automated_email.unapproved_count = 42

        for send_email_count in send_email_counts:
            results = send_automated_emails()
            assert results == expected
            assert mock_send_email.call_count == send_email_count

            with Session() as session:
                automated_emails = session.query(AutomatedEmail).all()
                assert len(automated_emails) == 8
                for automated_email in automated_emails:
                    ident = automated_email.ident
                    assert automated_email.unapproved_count == expected.get(ident, inactive.get(ident, 0))
                    if automated_email.unapproved_count == 0:
                        assert len(automated_email.emails) == 5
                        assert sorted(map(lambda e: (e.model, e.fk_id), automated_email.emails)) == [
                            ('Attendee', '00000000-0000-0000-0000-000000000000'),
                            ('Attendee', '00000000-0000-0000-0000-000000000001'),
                            ('Attendee', '00000000-0000-0000-0000-000000000002'),
                            ('Attendee', '00000000-0000-0000-0000-000000000003'),
                            ('Attendee', '00000000-0000-0000-0000-000000000004')]
                    else:
                        assert len(automated_email.emails) == 0
