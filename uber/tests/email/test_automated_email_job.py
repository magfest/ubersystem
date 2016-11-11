from uber.tests.email.email_fixtures import *


@pytest.mark.usefixtures("email_subsystem_sane_setup")
class TestSendAllAutomatedEmailsJob:
    def test_enabled(self):
        with patch.object(SendAllAutomatedEmailsJob, '_send_all_emails', return_value=None) as _send_all_emails:
            SendAllAutomatedEmailsJob().run()

        assert _send_all_emails.call_count == 1

    def test_disabled(self, monkeypatch):
        monkeypatch.setattr(c, 'SEND_EMAILS', False)
        with patch.object(SendAllAutomatedEmailsJob, '_send_all_emails', return_value=None) as _send_all_emails:
            SendAllAutomatedEmailsJob().run()

        assert _send_all_emails.call_count == 0