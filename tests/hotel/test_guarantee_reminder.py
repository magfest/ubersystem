"""The card reminder email (hotel_lottery_guarantee_reminder) fires for an
awarded entry with an unlocked room still waiting on a card, within a
week of the deadline; not for secured, master-bill, or locked rooms, or
for group members.
"""

from datetime import date, timedelta

from uber.config import c
from uber.models import AutomatedEmail

from tests.hotel.factories import (make_application, make_assignment,
                                   make_attendee, make_hotel, make_inventory)

IDENT = 'hotel_lottery_guarantee_reminder'


def _fires(app):
    fixture = AutomatedEmail._fixtures.get(IDENT)
    assert fixture is not None, 'the reminder fixture is registered'
    return bool(fixture.filter(app))


def _entry(session, **room):
    me = make_attendee(session)
    app = make_application(session, me, status=c.AWARDED)
    inv = make_inventory(session, make_hotel(session), quantity=5)
    params = dict(status=c.ASSIGNED, payment_type='credit_card',
                  lottery_application_id=app.id, booking_url='',
                  deposit_cutoff_date=date.today() + timedelta(days=3))
    params.update(room)
    ra = make_assignment(session, me, inv, **params)
    session.flush()
    return app, ra


def test_fires_without_a_booking_link(session):
    app, _ = _entry(session)
    assert not app.booking_url_ready
    assert _fires(app)


def test_quiet_once_every_room_is_secured(session):
    app, _ = _entry(session, status=c.SECURED, cc_token='tok')
    assert not _fires(app)


def test_quiet_for_master_bill_rooms(session):
    app, _ = _entry(session, payment_type='masterbill')
    assert not _fires(app)


def test_quiet_for_locked_rooms(session):
    app, _ = _entry(session, locked=True)
    assert not _fires(app)


def test_quiet_until_a_week_before_the_deadline(session):
    app, _ = _entry(session, deposit_cutoff_date=date.today() + timedelta(days=30))
    assert not _fires(app)
