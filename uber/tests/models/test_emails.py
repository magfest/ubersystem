from uber.tests import *
from unittest.mock import patch


@pytest.fixture
def remove_all_email_categories(monkeypatch):
    # save original email categories list
    original_email_category_instances = AutomatedEmail.instances

    # replace all email categories in the system with an empty list so we can add to it later
    monkeypatch.setattr(AutomatedEmail, 'instances', OrderedDict())


@pytest.fixture
def add_test_email_categories(remove_all_email_categories):
    AutomatedEmail(Attendee, '{EVENT_NAME} test email', 'crap.html',
                   lambda a: a.paid == c.HAS_PAID)


@pytest.fixture
def setup_fake_test_attendees(monkeypatch):
    # save original list of queries to use for model instances
    original_query_list = AutomatedEmail.queries

    # replace all email categories in the system with an empty list so we can add to it later
    monkeypatch.setattr(AutomatedEmail, 'queries', {
        Attendee: lambda session: [
            Attendee(
                placeholder=True,
                first_name="Test1",
                last_name="Test2",
                paid=c.NEED_NOT_PAY,
                badge_type=c.SUPPORTER_BADGE),
        ],
        # Group: lambda session: session.query(Group).options(subqueryload(Group.attendees))
    })


@pytest.fixture
def set_now_to_sept_15th(monkeypatch):
    with patch('uber.utils.localized_now', return_value=datetime(year=2016, month=9, day=15, hour=12, minute=30)):
        yield


@pytest.fixture
def email_subsystem_sane_config(monkeypatch):
    monkeypatch.setattr(c, 'DEV_BOX', False)
    monkeypatch.setattr(c, 'SEND_EMAILS', True)
    monkeypatch.setattr(c, 'AWS_ACCESS_KEY', '')
    monkeypatch.setattr(c, 'AWS_SECRET_KEY', '')
    monkeypatch.setattr(c, 'EVENT_NAME', 'CoolCon9000')


@pytest.fixture
def remove_test_approved_subjects(monkeypatch):
    monkeypatch.setattr(AutomatedEmail, 'get_approved_subjects', Mock(return_value=[]))


@pytest.fixture
def set_test_approved_subjects(monkeypatch, remove_test_approved_subjects):
    monkeypatch.setattr(AutomatedEmail, 'get_approved_subjects', Mock(return_value=[
        'CoolCon9000 test email'
        ])
    )


@pytest.fixture
def email_subsystem_sane_setup(email_subsystem_sane_config, set_now_to_sept_15th, add_test_email_categories, setup_fake_test_attendees):
    pass

_SUBJECT_TO_FIND = 'CoolCon9000 test email'


@pytest.fixture
def get_test_email_category():
    return AutomatedEmail.instances.get(_SUBJECT_TO_FIND)


@pytest.mark.usefixtures("email_subsystem_sane_setup")
class TestAutomatedEmailCategory:
    def test_testing_environment(self):
        assert len(AutomatedEmail.instances) == 1
        assert len(AutomatedEmail.queries[Attendee](None)) == 1

    def test_event_name(self, get_test_email_category):
        assert get_test_email_category.subject == _SUBJECT_TO_FIND

    def test_approval_needed_and_we_have_it(self, set_test_approved_subjects, get_test_email_category):
        assert get_test_email_category.is_approved_to_send(None)


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
