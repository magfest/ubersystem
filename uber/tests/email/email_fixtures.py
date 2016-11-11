from uber.tests import *
from unittest.mock import patch


class EmailTestsConstants:
    SUBJECT_TO_FIND = 'CoolCon9000 test email'

E = EmailTestsConstants

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
    return patch('uber.utils.localized_now', return_value=datetime(year=2016, month=9, day=15, hour=12, minute=30))


@pytest.fixture
def email_subsystem_sane_config(monkeypatch):
    monkeypatch.setattr(c, 'DEV_BOX', False)
    monkeypatch.setattr(c, 'SEND_EMAILS', True)


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


@pytest.fixture
def get_test_email_category():
    return AutomatedEmail.instances.get(E.SUBJECT_TO_FIND)