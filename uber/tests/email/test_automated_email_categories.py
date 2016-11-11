from uber.tests.email.email_fixtures import *


@pytest.mark.usefixtures("email_subsystem_sane_setup")
class TestAutomatedEmailCategory:
    def test_testing_environment(self, get_test_email_category):
        assert len(AutomatedEmail.instances) == 1
        assert len(AutomatedEmail.queries[Attendee](None)) == 2
        assert not get_test_email_category.unapproved_emails_not_sent

    def test_event_name(self, get_test_email_category):
        assert get_test_email_category.subject == E.SUBJECT_TO_FIND
        assert get_test_email_category.ident == E.IDENT_TO_FIND

    def test_approval_needed_and_we_have_it(self, monkeypatch, set_test_approved_idents, get_test_email_category):
        assert get_test_email_category.is_approved_to_send()
        assert get_test_email_category.unapproved_emails_not_sent is None

        monkeypatch.setattr(get_test_email_category, 'unapproved_emails_not_sent', 0)
        assert get_test_email_category.is_approved_to_send()
        assert get_test_email_category.unapproved_emails_not_sent == 0

    def test_approval_needed_and_we_dont_have_it(self, monkeypatch, get_test_email_category):
        assert not get_test_email_category.is_approved_to_send()
        assert get_test_email_category.unapproved_emails_not_sent is None

        monkeypatch.setattr(get_test_email_category, 'unapproved_emails_not_sent', 0)
        assert not get_test_email_category.is_approved_to_send()
        assert get_test_email_category.unapproved_emails_not_sent == 1

    def test_approval_not_needed(self, monkeypatch, get_test_email_category):
        assert not get_test_email_category.is_approved_to_send()
        monkeypatch.setattr(get_test_email_category, 'needs_approval', False)
        assert get_test_email_category.is_approved_to_send()



