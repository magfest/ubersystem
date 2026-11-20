import uuid

import pytest

from uber.config import c
from uber.decorators import render
from uber.models import Attendee, Email, Session, _attendee_validity_check
from uber.site_sections.registration import Root

from tests.emails.conftest import unwrap

POPUP_SCOPE = 'Emails sent about this badge.'
NO_BADGE_EMAILS = 'No emails have been sent about this badge.'
NO_ADDRESS = 'This badge has no email address.'
UNASSIGNED = 'This badge has not been assigned to anyone yet, so it has no email address.'


@pytest.fixture(scope='module', autouse=True)
def badge_lookup():
    """Install session.attendee's allow_invalid wrapper, which the server adds at startup."""
    original = Session.SessionMixin.attendee
    _attendee_validity_check()
    yield
    Session.SessionMixin.attendee = original


def _attendee(session, email):
    attendee = Attendee(first_name='Mail', last_name='Badge', email=email,
                        badge_status=c.COMPLETED_STATUS, paid=c.NEED_NOT_PAY)
    session.add(attendee)
    session.flush()
    return attendee


def _email(session, to, model='', fk_id=None):
    email = Email(model=model, fk_id=fk_id, to=to, subject=f'Subject {uuid.uuid4().hex[:8]}', body='Body',
                  sender='reg@example.com', ident='badge_emails_test')
    session.add(email)
    session.flush()
    return email


def _render(template, data):
    return render(template, data, encoding=None)


def test_popup_holds_only_this_badges_emails(session):
    address = f'{uuid.uuid4().hex}@example.com'
    attendee = _attendee(session, address)
    badge_email = _email(session, address, model='Attendee', fk_id=attendee.id)
    other_email = _email(session, address, model='AttendeeAccount', fk_id=str(uuid.uuid4()))

    html = _render('registration/attendee_emails.html',
                   unwrap(Root.attendee_emails)(Root(), session, id=attendee.id))

    assert badge_email.subject in html
    assert other_email.subject not in html


def test_popup_says_what_it_covers_and_when_it_is_empty(session):
    attendee = _attendee(session, f'{uuid.uuid4().hex}@example.com')

    html = _render('registration/attendee_emails.html',
                   unwrap(Root.attendee_emails)(Root(), session, id=attendee.id))

    assert POPUP_SCOPE in html
    assert NO_BADGE_EMAILS in html
    assert NO_ADDRESS not in html


def test_popup_says_when_the_badge_has_no_address(session):
    attendee = _attendee(session, '')

    html = _render('registration/attendee_emails.html',
                   unwrap(Root.attendee_emails)(Root(), session, id=attendee.id))

    assert 'This badge has no email address. Most badges have one, so check how it was created.' in html
    assert UNASSIGNED not in html


def test_popup_says_an_unassigned_badge_has_no_address_yet(session):
    attendee = _attendee(session, '')
    attendee.first_name = ''
    attendee.last_name = ''
    session.flush()

    html = _render('registration/attendee_emails.html',
                   unwrap(Root.attendee_emails)(Root(), session, id=attendee.id))

    assert UNASSIGNED in html
    assert 'Most badges have one' not in html


def test_full_page_does_not_search_a_blank_address(session):
    attendee = _attendee(session, '')
    _email(session, f'{uuid.uuid4().hex}@example.com', model='AttendeeAccount', fk_id=str(uuid.uuid4()))

    result = unwrap(Root.emails)(Root(), session, id=attendee.id)

    assert result['other_emails'] == []
    assert 'This badge has no email address, so there is no address to search.' in _render(
        'registration/emails.html', result)


def test_full_page_says_when_no_other_emails_were_sent(session):
    address = f'{uuid.uuid4().hex}@example.com'
    attendee = _attendee(session, address)

    html = _render('registration/emails.html', unwrap(Root.emails)(Root(), session, id=attendee.id))

    assert f'No other emails were sent to {address}.' in html


def test_full_page_lists_other_emails_to_the_address(session):
    address = f'{uuid.uuid4().hex}@example.com'
    attendee = _attendee(session, address)
    other_email = _email(session, address, model='AttendeeAccount', fk_id=str(uuid.uuid4()))

    result = unwrap(Root.emails)(Root(), session, id=attendee.id)

    assert [email.id for email in result['other_emails']] == [other_email.id]


def test_full_page_lists_other_emails_that_are_not_filed_under_anything(session):
    address = f'{uuid.uuid4().hex}@example.com'
    attendee = _attendee(session, address)
    manual_email = _email(session, address)

    result = unwrap(Root.emails)(Root(), session, id=attendee.id)

    assert [email.id for email in result['other_emails']] == [manual_email.id]
