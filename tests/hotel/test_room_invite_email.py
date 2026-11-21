"""The room occupant invite email ("You have a room at ...") renders from
the invite itself. It used to get the room and its leader through queued
`data`, which is JSON-serialized: models became plain dicts with string
dates, so the room summary failed and the body came out empty."""
from datetime import date, datetime, timedelta

import cherrypy
import pytest
from pytz import UTC

from uber.errors import HTTPRedirect

from tests.hotel.factories import (make_assignment, make_attendee, make_hotel,
                                   make_inventory)


@pytest.fixture
def queued_invite_email(session, monkeypatch, no_cherrypy_session):
    import uber.site_sections.hotel_lottery as module
    from uber.models import AutomatedEmail, Email, initialize_db

    initialize_db()
    if not AutomatedEmail.initialized:
        AutomatedEmail.reconcile_fixtures()
        AutomatedEmail.initialized = True
    monkeypatch.setattr(session, 'commit', session.flush)
    monkeypatch.setattr(module, 'check_csrf', lambda *a, **k: None)
    monkeypatch.setattr(module, '_require_room_access', lambda *a, **k: None)
    monkeypatch.setattr(cherrypy.request, 'method', 'POST')

    leader = make_attendee(session, 'Lee', 'Leader')
    hotel = make_hotel(session, name='Gaylord National')
    ra = make_assignment(session, leader, make_inventory(session, hotel),
                         check_in=date(2027, 1, 6), check_out=date(2027, 1, 10))

    handler = module.Root.invite_email
    room_action_code = module.room_action(lambda *a, **k: None).__code__
    while hasattr(handler, '__wrapped__') and handler.__code__ is not room_action_code:
        handler = handler.__wrapped__
    with pytest.raises(HTTPRedirect):
        handler(module.Root(), session, assignment_id=ra.id, email='friend@example.com')
    session.flush()

    email = session.query(Email).filter_by(ident='room_occupant_invite').one()
    return email, ra


def test_invite_email_names_the_inviter_and_the_room(queued_invite_email):
    email, ra = queued_invite_email
    invite_token = email.fk.invite_token

    assert email.to == 'friend@example.com'
    assert email.subject.startswith('Lee Leader invited you to share a room')
    for expected in ('Lee Leader', 'has invited you', 'Gaylord National',
                     'January 6', 'January 10',
                     f'/hotel_lottery/invite?token={invite_token}'):
        assert expected in email.body, expected


def test_invite_email_renders_the_same_at_send_time(queued_invite_email):
    """Sending re-renders the body from the model plus stored data."""
    email, _ra = queued_invite_email
    assert email.automated_email.render_body(email.fk, email.render_data) == email.body


def test_send_pass_picks_up_the_invite_email(queued_invite_email, session, monkeypatch):
    """send_automated_emails only selects emails whose model is some fixture's model."""
    from uber.config import c
    from uber.email import EmailService
    from uber.models import AutomatedEmail

    email, _ra = queued_invite_email
    # The test database has no send policy, so the email starts Pending Approval; production autosends.
    email.status = c.QUEUED
    email.send_after = datetime.now(UTC) - timedelta(minutes=1)
    session.flush()
    attempted = []
    monkeypatch.setattr(EmailService, 'send_email', lambda session, email, *args: attempted.append(email.id))

    for model_class in set(fixture.model for fixture in AutomatedEmail._fixtures.values()):
        EmailService.process_emails_by_class(session, model_class)

    assert email.id in attempted


def test_invite_email_sends(queued_invite_email, session, monkeypatch):
    from uber.config import c
    from uber.email import EmailService

    email, _ra = queued_invite_email
    # DEV_BOX runs the whole send path but skips the SES call.
    monkeypatch.setattr(c, 'DEV_BOX', True)

    assert EmailService.send_email(session, email, email.automated_email) is email
    assert email.status == c.SENT
    assert email.to == 'friend@example.com'
    assert not email.error
