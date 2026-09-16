"""The per-room "Hotel Lottery Award Confirmed!" email.

One email is queued for every room the attendee secures, addressed to
the RoomAssignment itself. A multi-room winner is told which of their
other rooms still need a card; once the last one is secured the email
says every room is confirmed.
"""

import pytest

from uber.config import c
from uber.models import AutomatedEmail, Email

from tests.hotel.factories import (N, make_application, make_assignment,
                                   make_attendee, make_hotel, make_inventory)


@pytest.fixture
def secured_fixture(session):
    if not AutomatedEmail.initialized:
        AutomatedEmail.reconcile_fixtures()
        AutomatedEmail.initialized = True
    row = session.query(AutomatedEmail).filter_by(
        ident='hotel_lottery_secured').one()
    row.policy = c.AUTOSEND
    session.flush()
    return row


def _award(session, attendee, app, hotel_name, deadline=None):
    inv = make_inventory(session, make_hotel(session, name=hotel_name), quantity=2)
    return make_assignment(session, attendee, inv, status=c.ASSIGNED,
                           assignment_reason=c.LOTTERY_AWARD,
                           payment_type='credit_card',
                           lottery_application_id=app.id if app else None,
                           deposit_cutoff_date=deadline,
                           check_in=N[1], check_out=N[3])


def _secure(session, ra):
    from uber.site_sections.hotel_lottery import _queue_room_secured_email

    ra.cc_token = 'tok-' + ra.id
    ra.cc_last_four = '4242'
    ra.status = c.SECURED
    session.add(ra)
    session.flush()
    _queue_room_secured_email(session, ra)
    session.flush()


def _emails_for(session, ra):
    return session.query(Email).filter_by(
        ident='hotel_lottery_secured', fk_id=ra.id).all()


def test_each_confirmed_room_gets_its_own_email(
        session, no_cherrypy_session, secured_fixture):
    attendee = make_attendee(session)
    app = make_application(session, attendee, status=c.AWARDED,
                           entry_type=c.ROOM_ENTRY)
    first = _award(session, attendee, app, 'Alpha Hotel', deadline=N[0])
    second = _award(session, attendee, app, 'Beta Hotel', deadline=N[0])

    _secure(session, first)
    emails = _emails_for(session, first)
    assert len(emails) == 1
    email = emails[0]
    assert email.model == 'RoomAssignment'
    assert email.to == attendee.email
    assert email.status == c.QUEUED
    assert 'Alpha Hotel' in email.body
    assert 'ending in 4242' in email.body
    # The other room is still unsecured: named, with its secure link.
    assert '1 other room that needs a credit card' in email.body
    assert 'Beta Hotel' in email.body
    assert f'secure_room?assignment_id={second.id}' in email.body
    assert 'Put a card down by' in email.body
    assert 'rooms are now confirmed' not in email.body

    _secure(session, second)
    emails = _emails_for(session, second)
    assert len(emails) == 1
    body = emails[0].body
    assert 'Beta Hotel' in body
    assert 'other room' not in body
    assert 'All 2 of your rooms are now confirmed' in body
    assert session.query(Email).filter_by(
        ident='hotel_lottery_secured').count() == 2, 'one per room'


def test_single_room_email_mentions_no_other_rooms(
        session, no_cherrypy_session, secured_fixture):
    attendee = make_attendee(session)
    app = make_application(session, attendee, status=c.AWARDED,
                           entry_type=c.ROOM_ENTRY)
    only = _award(session, attendee, app, 'Solo Hotel')

    _secure(session, only)
    body = _emails_for(session, only)[0].body
    assert 'Solo Hotel' in body
    assert 'other room' not in body
    assert 'rooms are now confirmed' not in body
    assert 'view and update your reservation here' in body


def test_room_without_lottery_application_still_renders(
        session, no_cherrypy_session, secured_fixture):
    attendee = make_attendee(session)
    manual = _award(session, attendee, None, 'Manual Hotel')
    manual.assignment_reason = c.MANUAL

    _secure(session, manual)
    emails = _emails_for(session, manual)
    assert len(emails) == 1
    assert 'Manual Hotel' in emails[0].body
    assert emails[0].to == attendee.email


def test_fixture_is_transactional_not_swept(secured_fixture):
    assert secured_fixture.fixture.filter is None, \
        'the sweep must never send this; only the secure flow queues it'
    assert secured_fixture.fixture.model.__name__ == 'RoomAssignment'
