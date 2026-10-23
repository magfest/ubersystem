"""The "room dates were updated" email sent when waitlisted nights are fulfilled.

Rooms with no lottery application, such as partition grants, email the
attendee.
"""

import pytest

from uber.config import c
from uber.models import AutomatedEmail, Email

from tests.hotel.factories import (N, make_application, make_assignment,
                                   make_attendee, make_hotel, make_inventory)


@pytest.fixture
def waitlist_fixture(session, no_cherrypy_session):
    if not AutomatedEmail.initialized:
        AutomatedEmail.reconcile_fixtures()
        AutomatedEmail.initialized = True
    row = session.query(AutomatedEmail).filter_by(
        ident='hotel_lottery_waitlist_fulfilled').one()
    row.policy = c.AUTOSEND
    session.flush()
    return row


def _room(session, attendee, app=None, still_waitlisted=False):
    inv = make_inventory(session, make_hotel(session, name='Waitlist Hotel'))
    extra = dict(waitlisted_check_in_date=N[0], waitlisted_check_out_date=N[3]) \
        if still_waitlisted else {}
    return make_assignment(session, attendee, inv, check_in=N[1], check_out=N[3],
                           lottery_application_id=app.id if app else None, **extra)


def _queue(session, ra):
    from uber.site_sections.hotel_lottery_admin import _queue_waitlist_fulfilled_email

    _queue_waitlist_fulfilled_email(session, ra)
    session.flush()
    return session.query(Email).filter_by(
        ident='hotel_lottery_waitlist_fulfilled').filter(
        Email.fk_id.in_([ra.attendee_id, ra.lottery_application_id])).all()


def test_room_without_lottery_application_emails_the_attendee(
        session, waitlist_fixture):
    attendee = make_attendee(session, first='Partition')
    ra = _room(session, attendee)

    emails = _queue(session, ra)
    assert len(emails) == 1
    assert emails[0].to == attendee.email
    assert 'Hello Partition' in emails[0].body
    assert 'Waitlist Hotel' in emails[0].body
    assert 'All of your requested nights' in emails[0].body
    assert emails[0].subject == f'Your {c.EVENT_NAME_AND_YEAR} hotel room dates were updated'


def test_still_waitlisted_room_says_so(session, waitlist_fixture):
    attendee = make_attendee(session, first='Lottery')
    app = make_application(session, attendee, status=c.AWARDED)
    ra = _room(session, attendee, app=app, still_waitlisted=True)
    assert ra.is_waitlisted

    emails = _queue(session, ra)
    assert len(emails) == 1
    assert emails[0].fk_id == app.id
    assert 'still on the waitlist' in emails[0].body
    assert 'All of your requested nights' not in emails[0].body
