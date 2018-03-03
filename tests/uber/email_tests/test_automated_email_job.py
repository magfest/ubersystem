from unittest.mock import patch

import pytest

from tests.uber.email_tests.email_fixtures import *  # noqa: F401,F403
from uber.config import c
from uber.tasks.email import SendAutomatedEmailsJob


@pytest.fixture
def send_all_emails_mock():
    with patch.object(SendAutomatedEmailsJob, '_send_all_emails', return_value=None) as mock:
        yield mock


@pytest.mark.usefixtures("email_subsystem_sane_setup")
class TestSendAutomatedEmailsJob:
    @pytest.mark.parametrize("c_send_emails, c_dev_box, expected_result", [
        (True, True, 1),
        (False, True, 1),
        (True, False, 1),
        (False, False, 0),
    ])
    def test_run_when_config_changed(
            self, monkeypatch, send_all_emails_mock, c_send_emails, c_dev_box, expected_result):
        monkeypatch.setattr(c, 'SEND_EMAILS', c_send_emails)
        monkeypatch.setattr(c, 'DEV_BOX', c_dev_box)

        SendAutomatedEmailsJob().run()
        assert send_all_emails_mock.call_count == expected_result

    @pytest.mark.usefixtures('render_fake_email')
    def test_run_succeeds(self, amazon_send_email_mock, set_test_approved_idents, get_test_email_category):
        assert get_test_email_category.approved

        SendAutomatedEmailsJob().run()

        assert not SendAutomatedEmailsJob.run_lock.locked()
        assert amazon_send_email_mock.call_count == 2
        assert SendAutomatedEmailsJob \
            .last_result['categories'][get_test_email_category.ident]['unsent_because_unapproved'] == 0

        assert not SendAutomatedEmailsJob.last_result['running']
        assert SendAutomatedEmailsJob.last_result['completed']

    def test_run_no_email_approval(self, amazon_send_email_mock, get_test_email_category):
        assert not get_test_email_category.approved

        SendAutomatedEmailsJob().run()

        assert not SendAutomatedEmailsJob.run_lock.locked()
        assert amazon_send_email_mock.call_count == 0
        assert SendAutomatedEmailsJob \
            .last_result['categories'][get_test_email_category.ident]['unsent_because_unapproved'] == 2

        assert not SendAutomatedEmailsJob.last_result['running']
        assert SendAutomatedEmailsJob.last_result['completed']
