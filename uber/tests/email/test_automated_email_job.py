from uber.tests.email.email_fixtures import *


@pytest.fixture
def send_all_emails_mock():
    with patch.object(SendAllAutomatedEmailsJob, '_send_all_emails', return_value=None) as mock:
        yield mock


@pytest.fixture
def send_all_emails_mock():
    with patch.object(SendAllAutomatedEmailsJob, '_send_all_emails', return_value=None) as mock:
        yield mock


@pytest.mark.usefixtures("email_subsystem_sane_setup")
class TestSendAllAutomatedEmailsJob:
    @pytest.mark.parametrize("c_at_the_con, c_send_emails, c_dev_box, expected_result", [
        (True, True, True, 0),
        (True, False, True, 0),
        (True, True, False, 0),
        (True, False, False, 0),
        (False, True, True, 1),
        (False, False, True, 1),
        (False, True, False, 1),
        (False, False, False, 0),
    ])
    def test_run_when_config_changed(self, monkeypatch, send_all_emails_mock, c_at_the_con, c_send_emails, c_dev_box, expected_result):
        monkeypatch.setattr(c, 'AT_THE_CON', c_at_the_con)
        monkeypatch.setattr(c, 'SEND_EMAILS', c_send_emails)
        monkeypatch.setattr(c, 'DEV_BOX', c_dev_box)

        SendAllAutomatedEmailsJob().run()
        assert send_all_emails_mock.call_count == expected_result

    # TODO: test job results to make sure unapproved email stuff comes through OK.

    # , record_email_was_sent
    def test_run_succeeds(self, amazon_send_email_mock, set_test_approved_idents, get_test_email_category, render_fake_email):
        assert get_test_email_category.approved

        SendAllAutomatedEmailsJob().run()
        assert amazon_send_email_mock.call_count == 2

    def test_run_no_email_approval(self, amazon_send_email_mock, get_test_email_category):
        assert not get_test_email_category.approved

        SendAllAutomatedEmailsJob().run()
        assert amazon_send_email_mock.call_count == 0
