from uber.tests.email.email_fixtures import *


@pytest.mark.usefixtures("email_subsystem_sane_setup")
class TestAutomatedEmailCategory:
    def test_testing_environment(self):
        assert len(AutomatedEmail.instances) == 1
        assert len(AutomatedEmail.queries[Attendee](None)) == 1

    def test_event_name(self, get_test_email_category):
        assert get_test_email_category.subject == E.SUBJECT_TO_FIND

    def test_approval_needed_and_we_have_it(self, set_test_approved_subjects, get_test_email_category):
        assert get_test_email_category.is_approved_to_send(None)


