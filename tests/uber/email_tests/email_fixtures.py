from collections import OrderedDict
from datetime import datetime
from unittest.mock import patch, Mock

import pytest
from pockets import listify

from uber import decorators, utils
from uber.amazon_ses import AmazonSES
from uber.config import c, Config
from uber.models import Attendee, AutomatedEmail
from uber.tasks.email import send_automated_emails
from uber.utils import DateBase, localize_datetime


@pytest.fixture(autouse=True)
def mock_send_email(monkeypatch):
    monkeypatch.setattr(c, 'DEV_BOX', False)
    monkeypatch.setattr(c, 'SEND_EMAILS', True)
    monkeypatch.setattr(AmazonSES, 'sendEmail', Mock(return_value=None))
    return AmazonSES.sendEmail


@pytest.fixture
def clear_automated_email_fixtures(monkeypatch):
    monkeypatch.setattr(AutomatedEmail, '_fixtures', OrderedDict())


@pytest.fixture
def render_empty_attendee_template(monkeypatch):
    def _render_empty(template_name_list):
        if listify(template_name_list)[0].endswith('.txt'):
            return '{{ attendee.full_name }}\n{{ c.EVENT_NAME }}\n{{ extra_data }}'
        return '<html><body>{{ attendee.full_name }}<br>{{ c.EVENT_NAME }}<br>{{ extra_data }}</body></html>'
    monkeypatch.setattr(decorators, 'render_empty', _render_empty)


# @pytest.fixture
# def setup_fake_test_attendees(monkeypatch):
#     # replace all email categories in the system with an empty list so we can add to it later
#     monkeypatch.setattr(AutomatedEmailFixture, 'queries', {
#         Attendee: lambda ignored_param: [
#             Attendee(
#                 placeholder=True,
#                 first_name="Gambler",
#                 last_name="Kirkdouglas",
#                 email="thegambler@protos.com",
#                 paid=c.NEED_NOT_PAY,
#                 badge_type=c.GUEST_BADGE,
#                 id='b699bfd3-1ada-4f47-b07f-cb7939783afa',
#             ),
#             Attendee(
#                 placeholder=True,
#                 first_name="Kilroy",
#                 last_name="Kilroy",
#                 email="that_one_robot@ihaveasecret.com",
#                 paid=c.NEED_NOT_PAY,
#                 badge_type=c.GUEST_BADGE,
#                 id='e91e6c7e-699e-4784-b43f-303acc419dd5',
#             ),
#             Attendee(
#                 placeholder=False,
#                 first_name="Reanimator",
#                 last_name="Lovejoy",
#                 email="yeswecan@jumpfromanywhere.com",
#                 paid=c.HAS_PAID,
#                 badge_type=c.ATTENDEE_BADGE,
#                 id='c8b35ec5-4385-4ad7-b7db-b6f082f74aeb',
#             ),
#         ],
#         # Group: lambda ignored_param: would need to replace with:
#         # session.query(Group).options(subqueryload(Group.attendees))
#     })


# @pytest.fixture
# def remove_approved_idents(monkeypatch):
#     monkeypatch.setattr(Config, 'EMAIL_APPROVED_IDENTS', {})


# @pytest.fixture
# def set_test_approved_idents(monkeypatch, remove_approved_idents):
#     # list of idents of emails which are approved for sending.  this matches AutomatedEmailFixture.ident
#     approved_idents = [
#         E.IDENT_TO_FIND,
#     ]

#     monkeypatch.setattr(Config, 'EMAIL_APPROVED_IDENTS', approved_idents)


# @pytest.fixture
# def set_previously_sent_emails_empty(monkeypatch):
#     # include this fixture if we want to act like no emails have ever been previously sent
#     monkeypatch.setattr(Config, 'PREVIOUSLY_SENT_EMAILS', set())


# @pytest.fixture
# def set_previously_sent_emails_to_attendee1(monkeypatch):
#     # include this fixture if we want to act like the email category with ident 'you_are_not_him'
#     # was previously sent to attendee with ID #78

#     # format of this set: (Email.model, Email.fk_id, Email.ident)
#     list_of_emails_previously_sent = {
#         (Attendee.__name__, 'b699bfd3-1ada-4f47-b07f-cb7939783afa', 'you_are_not_him'),
#     }

#     monkeypatch.setattr(Config, 'PREVIOUSLY_SENT_EMAILS', list_of_emails_previously_sent)
#     return list_of_emails_previously_sent


# @pytest.fixture
# def reset_unapproved_emails_count(monkeypatch):
#     for email_category in AutomatedEmailFixture.fixtures_by_ident.values():
#         email_category.unapproved_emails_not_sent = None


# @pytest.fixture
# def email_subsystem_sane_setup(
#         email_subsystem_sane_config,
#         add_test_email_categories,
#         setup_fake_test_attendees,
#         set_previously_sent_emails_empty,
#         reset_unapproved_emails_count,
#         remove_approved_idents,
#         amazon_send_email_mock):
#     """
#     Catch-all test for setting up all email subsystem tests.  This fixture is a catch-all container of all relevant
#     email testing fixtures.

#     We will reset a bunch of global state and fake database data in each test run
#     """
#     pass

