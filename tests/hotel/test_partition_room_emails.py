"""Emails for rooms assigned from a department's partition.

The assignment email goes to partition rooms an hour after they are created,
whether a department head or an admin assigned them. Card-required rooms are
asked to secure the room; master-billed rooms are told no card is needed. Once
it has been sent, a change to dates, room block, or billing queues the
room-updated email, which waits until the room has gone ten minutes without a
change.
"""

from datetime import datetime, timedelta

import pytest
from pytz import UTC

from uber.config import c
from uber.hotel.service import apply_room_assignment_edits
from uber.models import AutomatedEmail, Email

from tests.hotel.factories import (N, make_assignment, make_attendee, make_hotel,
                                   make_inventory, make_partition,
                                   make_partition_block)


@pytest.fixture
def partition_fixtures(session, no_cherrypy_session):
    if not AutomatedEmail.initialized:
        AutomatedEmail.reconcile_fixtures()
        AutomatedEmail.initialized = True
    rows = session.query(AutomatedEmail).filter(AutomatedEmail.ident.in_(
        ['hotel_partition_room_assigned', 'hotel_partition_room_updated'])).all()
    for row in rows:
        row.policy = c.AUTOSEND
    session.flush()
    return {row.ident: row for row in rows}


def _assigned_filter(ra):
    return AutomatedEmail._fixtures['hotel_partition_room_assigned'].filter(ra)


def _grant(session, age=timedelta(hours=2), **overrides):
    inv = make_inventory(session, make_hotel(session, name='Partition Hotel'))
    partition = make_partition(session)
    make_partition_block(session, partition, inv, quantity=2)
    params = dict(partition_id=partition.id, assignment_reason=c.PARTITION_GRANT,
                  payment_type='credit_card', check_in=N[1], check_out=N[3])
    params.update(overrides)
    ra = make_assignment(session, make_attendee(session, first='Granted'), inv, **params)
    ra.created = datetime.now(UTC) - age
    session.flush()
    return ra


def test_assigned_email_waits_an_hour(session, partition_fixtures):
    assert _assigned_filter(_grant(session))
    assert not _assigned_filter(_grant(session, age=timedelta(minutes=30)))


def test_assigned_email_covers_admin_made_partition_rooms(session, partition_fixtures):
    assert _assigned_filter(_grant(session, assignment_reason=c.MANUAL))


@pytest.mark.parametrize('overrides', [
    {'status': c.SECURED},
    {'status': c.CANCELLED},
    {'assignment_reason': c.LOTTERY_AWARD},
    {'assignment_reason': c.MANUAL, 'partition_id': None},
])
def test_assigned_email_skips_rooms_that_need_nothing(session, partition_fixtures,
                                                      overrides):
    assert not _assigned_filter(_grant(session, **overrides))


def test_assigned_email_covers_master_billed_rooms(session, partition_fixtures):
    assert _assigned_filter(_grant(session, payment_type='masterbill'))
    assert _assigned_filter(_grant(session, payment_type='masterbill_parking'))


def test_master_billed_email_says_no_card_is_needed(session, partition_fixtures,
                                                    monkeypatch):
    from uber.email import EmailService

    monkeypatch.setattr(session, 'commit', session.flush)
    ra = _grant(session, payment_type='masterbill')
    EmailService.check_emails_for_fixture(
        session, partition_fixtures['hotel_partition_room_assigned'])
    email = session.query(Email).filter_by(
        ident='hotel_partition_room_assigned', fk_id=ra.id).one()

    assert 'do not need to provide a credit card' in email.body
    assert 'secure_room' not in email.body
    assert f'room?id={ra.id}' in email.body


def test_assigned_email_skips_guests_without_a_valid_badge(session, partition_fixtures):
    ra = _grant(session)
    ra.attendee.badge_status = c.REFUNDED_STATUS
    session.flush()
    assert not _assigned_filter(ra)


def test_assigned_email_renders_deadline_and_links(session, partition_fixtures,
                                                   monkeypatch):
    from uber.email import EmailService

    from tests.hotel.test_partition_guarantee_due import set_partition_guarantee_due

    # check_emails_for_fixture commits; keep the per-test rollback intact.
    monkeypatch.setattr(session, 'commit', session.flush)
    set_partition_guarantee_due(session, '2026-11-22')
    ra = _grant(session)
    EmailService.check_emails_for_fixture(
        session, partition_fixtures['hotel_partition_room_assigned'])
    email = session.query(Email).filter_by(
        ident='hotel_partition_room_assigned', fk_id=ra.id).one()

    assert email.to == ra.attendee.email
    assert 'Partition Hotel' in email.body
    assert 'Please secure it by' in email.body
    assert f'secure_room?assignment_id={ra.id}' in email.body


def _sent_assigned_email(session, ra):
    session.add(Email(ident='hotel_partition_room_assigned', fk_id=ra.id,
                      model='RoomAssignment', status=c.SENT,
                      sent=datetime.now(UTC)))
    session.flush()


def _updated_emails(session, ra):
    return session.query(Email).filter_by(
        ident='hotel_partition_room_updated', fk_id=ra.id).all()


def _edit(session, ra, **params):
    def fail(msg):
        raise AssertionError(msg)
    return apply_room_assignment_edits(session, ra, params, audit_prefix='Test',
                                       fail=fail)


def test_edit_after_assigned_email_queues_update(session, partition_fixtures):
    ra = _grant(session)
    _sent_assigned_email(session, ra)

    _edit(session, ra, assigned_check_out_date=N[4].isoformat())
    emails = _updated_emails(session, ra)
    assert len(emails) == 1
    assert 'has been updated' in emails[0].body

    # A second change replaces the unsent update rather than stacking another.
    _edit(session, ra, payment_type='masterbill')
    emails = _updated_emails(session, ra)
    assert len(emails) == 1
    assert 'do not need to provide a credit card' in emails[0].body


def test_no_update_before_assigned_email_or_for_other_fields(session,
                                                            partition_fixtures):
    ra = _grant(session)
    _edit(session, ra, assigned_check_out_date=N[4].isoformat())
    assert _updated_emails(session, ra) == []

    _sent_assigned_email(session, ra)
    assert _edit(session, ra, assigned_check_out_date=N[4].isoformat()) == 'No changes.'
    _edit(session, ra, admin_notes='Called the guest.')
    assert _updated_emails(session, ra) == []


def test_update_email_waits_for_ten_quiet_minutes(session, partition_fixtures):
    send_filter = AutomatedEmail._fixtures['hotel_partition_room_updated'].send_filter
    ra = _grant(session)

    ra.last_updated = datetime.now(UTC) - timedelta(minutes=2)
    assert not send_filter(ra)
    ra.last_updated = datetime.now(UTC) - timedelta(minutes=11)
    assert send_filter(ra)
