from uber.tests import *
from unittest.mock import patch

@pytest.fixture
def email_subsystem_sane_setup(monkeypatch):
    monkeypatch.setattr(c, 'DEV_BOX', False)
    monkeypatch.setattr(c, 'SEND_EMAILS', True)
    monkeypatch.setattr(c, 'AWS_ACCESS_KEY', "")
    monkeypatch.setattr(c, 'AWS_SECRET_KEY', "")

@pytest.mark.usefixtures("email_subsystem_sane_setup")
class TestAutomatedEmailCategory:
    def test_stuff(self):
        pass

@pytest.mark.usefixtures("email_subsystem_sane_setup")
class TestSendAllAutomatedEmailsJob:
    def test_enabled(self):
        with patch.object(SendAllAutomatedEmailsJob, '_send_all_emails', return_value=None) as mock_method:
            SendAllAutomatedEmailsJob().run()

        assert mock_method.call_count == 1

    def test_disabled(self, monkeypatch):
        monkeypatch.setattr(c, 'SEND_EMAILS', False)
        with patch.object(SendAllAutomatedEmailsJob, '_send_all_emails', return_value=None) as mock_method:
            SendAllAutomatedEmailsJob().run()

        assert mock_method.call_count == 0