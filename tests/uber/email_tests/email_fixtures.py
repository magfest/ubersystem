"""
Test fixtures used by all our email related tests.
"""

from datetime import datetime, timedelta

from collections import OrderedDict
from unittest.mock import Mock

import pytest

from uber import utils
from uber.amazon_ses import AmazonSES
from uber.automated_emails import AutomatedEmailFixture
from uber.config import c
from uber.models import Attendee, AutomatedEmail, Session
from uber.utils import after, before


NOW = c.EVENT_TIMEZONE.localize(datetime(year=2016, month=8, day=10, hour=12, tzinfo=None))
TWO_DAYS_FROM_NOW = NOW + timedelta(days=2)
TOMORROW = NOW + timedelta(days=1)
YESTERDAY = NOW - timedelta(days=1)
TWO_DAYS_AGO = NOW - timedelta(days=2)

ACTIVE_WHEN = [
    # ==== ACTIVE ====
    [],  # Always active
    [before(TOMORROW)],  # Will expire tomorrow
    [after(YESTERDAY)],  # Became active yesterday
    [after(YESTERDAY), before(TOMORROW)],  # Became active yesterday, will expire tomorrow

    # ==== INACTIVE BUT APPROVABLE ====
    [after(TOMORROW)],  # Will become active tomorrow
    [after(TOMORROW), before(TWO_DAYS_FROM_NOW)],  # Will become active tomorrow, will expire in 2 days

    # ==== INACTIVE ====
    [before(YESTERDAY)],  # Expired yesterday
    [after(TWO_DAYS_AGO), before(YESTERDAY)],  # Became active 2 days ago, expired yesterday
]

ACTIVE_WHEN_LABELS = [
    '',
    'before Aug 11',
    'after Aug 9',
    'between Aug 9 and Aug 11',
    'after Aug 11',
    'between Aug 11 and Aug 12',
    'before Aug 9',
    'between Aug 8 and Aug 9',
]


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
def fixed_localized_now(monkeypatch):
    monkeypatch.setattr(utils, 'localized_now', Mock(return_value=NOW))
    return NOW


@pytest.fixture
def create_test_attendees():
    """
    Creates 5 test attendees with ids 000...000 through 000...004.
    """
    with Session() as session:
        for s in map(str, range(5)):
            attendee = Attendee(
                id='00000000-0000-0000-0000-00000000000{}'.format(s),
                first_name=s,
                last_name=s,
                email='{}@example.com'.format(s))
            session.add(attendee)


@pytest.fixture
def automated_email_fixture(clear_automated_email_fixtures, render_empty_attendee_template):
    """
    Generates a single AutomatedEmail that is currently active.
    """
    AutomatedEmailFixture(
        Attendee,
        '{EVENT_NAME} {EVENT_YEAR} {EVENT_DATE} {{ attendee.full_name }}',
        'attendee.txt',
        filter=lambda a: True,
        ident='attendee_txt',
        sender='test@example.com',
        extra_data={'extra_data': 'EXTRA DATA'})
    AutomatedEmail.reconcile_fixtures()


@pytest.fixture
def send_emails_for_automated_email_fixture(create_test_attendees, automated_email_fixture):
    """
    Sends two copies of the same email to five newly created attendees.
    """
    with Session() as session:
        automated_email = session.query(AutomatedEmail).one()
        for s in map(str, range(5)):
            attendee = session.query(Attendee).filter_by(first_name=s, last_name=s).one()
            session.add(attendee)
            assert automated_email.send_to(attendee, delay=False)
            assert automated_email.send_to(attendee, delay=False)


@pytest.fixture
def automated_email_fixtures(clear_automated_email_fixtures, render_empty_attendee_template):
    """
    Generates 8 AutomatedEmails. Of those:
     * 4 are currently active (within the sending window)
     * 6 can be approved (already active, or will become active in the future)
     * 4 are html formatted
    """
    for i, when in enumerate(ACTIVE_WHEN):
        template_ext = ['html', 'txt'][i % 2]
        AutomatedEmailFixture(
            Attendee,
            '{EVENT_NAME} {EVENT_YEAR} {EVENT_DATE} {{ attendee.full_name }}',
            'attendee.{}'.format(template_ext),
            filter=lambda a: True,
            ident='attendee_{}{}'.format(
                template_ext,
                '_{}'.format('_'.join(w.active_when for w in when)).replace(' ', '_') if when else ''),
            when=when,
            sender='test_{}@example.com'.format('odd' if bool(i % 2) else 'even'),
            needs_approval=False,
            allow_at_the_con=False,
            allow_post_con=False,
            extra_data={'extra_data': 'EXTRA DATA'})
    AutomatedEmail.reconcile_fixtures()
