"""RoomAssignment / LotteryApplication model-layer properties: waitlist
window math, orphan connectors, the needs_card hybrid (python vs SQL),
card copy/clear helpers, and guarantee_deadline."""

from datetime import date, datetime, time

import pytest

from uber.config import c

from tests.hotel.factories import (N, make_application, make_assignment,
                                   make_attendee, make_hotel, make_inventory)


def _inv(session, quantity=5):
    return make_inventory(session, make_hotel(session), quantity=quantity)


# ---------------------------------------------------------------------------
# Waitlist window math (pure column math - unsaved instances are fine).
# ---------------------------------------------------------------------------

def test_waitlisted_gap_nights_front_and_back_sorted():
    from uber.models.hotel import RoomAssignment

    ra = RoomAssignment(assigned_check_in_date=N[3],
                        assigned_check_out_date=N[5],
                        waitlisted_check_in_date=N[1],
                        waitlisted_check_out_date=N[7])
    assert ra.waitlisted_gap_nights == [N[1], N[2], N[5], N[6]]
    assert ra.is_waitlisted

    # Incomplete assigned range -> no computable gaps.
    ra2 = RoomAssignment(waitlisted_check_in_date=N[1],
                         waitlisted_check_out_date=N[7])
    assert ra2.waitlisted_gap_nights == []
    assert not ra2.is_waitlisted


def test_effective_waitlist_window_coalescing():
    from uber.models.hotel import RoomAssignment

    base = dict(assigned_check_in_date=N[3], assigned_check_out_date=N[5])

    ra = RoomAssignment(**base, waitlisted_check_in_date=N[1])
    assert ra.effective_waitlist_window == (N[1], N[5]), \
        'a missing end coalesces to the assigned date'

    ra = RoomAssignment(**base, waitlisted_check_out_date=N[7])
    assert ra.effective_waitlist_window == (N[3], N[7])

    ra = RoomAssignment(**base)
    assert ra.effective_waitlist_window == (None, None)


# ---------------------------------------------------------------------------
# Orphan connectors
# ---------------------------------------------------------------------------

def test_is_orphan_connector(session):
    inv = _inv(session)
    attendee = make_attendee(session)
    other = make_attendee(session)

    parent = make_assignment(session, attendee, inv,
                             check_in=N[1], check_out=N[3])
    child = make_assignment(session, attendee, inv,
                            check_in=N[1], check_out=N[3],
                            parent_assignment_id=parent.id,
                            assignment_reason=c.SUITE_CONNECTOR)

    assert parent.is_orphan_connector is False, 'no parent -> not a connector'
    assert child.is_orphan_connector is False, \
        'live parent held by the same attendee -> intact pairing'

    parent.status = c.CANCELLED
    session.flush()
    assert child.is_orphan_connector is True, 'cancelled parent orphans it'

    parent.status = c.ASSIGNED
    parent.attendee_id = other.id
    session.flush()
    session.expire(child)
    assert child.is_orphan_connector is True, \
        'parent transferred to another attendee orphans it'


# ---------------------------------------------------------------------------
# needs_card hybrid: python property and SQL expression must agree.
# ---------------------------------------------------------------------------

def test_needs_card_python_matches_sql(session):
    from uber.models.hotel import RoomAssignment

    inv = _inv(session)
    matrix = [
        dict(payment_type='credit_card', status=c.ASSIGNED, cc_token=None),   # needs
        dict(payment_type='credit_card', status=c.ASSIGNED, cc_token=''),     # needs
        dict(payment_type='credit_card', status=c.ASSIGNED, cc_token='tok'),  # token on file
        dict(payment_type='credit_card', status=c.SECURED, cc_token='tok'),
        dict(payment_type='credit_card', status=c.CANCELLED, cc_token=None),
        dict(payment_type='masterbill', status=c.ASSIGNED, cc_token=None),  # master bill
        dict(payment_type='masterbill', status=c.SECURED, cc_token='tok'),
    ]
    rows = [make_assignment(session, make_attendee(session), inv,
                            check_in=N[1], check_out=N[3], **params)
            for params in matrix]

    ids_here = {ra.id for ra in rows}
    sql_ids = {ra.id for ra in session.query(RoomAssignment)
               .filter(RoomAssignment.needs_card).all()} & ids_here
    py_ids = {ra.id for ra in rows if ra.needs_card}

    assert py_ids == sql_ids, \
        'the cron (SQL) and the UI (python) must flag the same rows'
    # And the flagged set is exactly the unsecured self-pay ASSIGNED rows.
    # (secure_if_carded is an explicit helper, not a presave, so row 2 -
    # ASSIGNED with a token - stays ASSIGNED but no longer needs a card.)
    assert py_ids == {rows[0].id, rows[1].id}
    assert rows[2].status == c.ASSIGNED
    assert rows[2].needs_card is False


# ---------------------------------------------------------------------------
# Card copy / clear / secure
# ---------------------------------------------------------------------------

def test_clear_card_strips_and_demotes(session):
    from uber.models.hotel import RoomAssignment

    inv = _inv(session)
    ra = make_assignment(session, make_attendee(session), inv,
                         check_in=N[1], check_out=N[3], status=c.SECURED,
                         cc_token='tok', cc_last_four='4242',
                         cc_card_holder='Test Person',
                         address1='123 Test St', city='Rockville',
                         region='MD', zip_code='20850',
                         country='United States')

    assert ra.clear_card() is True
    for field in RoomAssignment.CC_FIELDS:
        assert getattr(ra, field) is None
    for field in RoomAssignment.ADDRESS_FIELDS:
        assert getattr(ra, field) == ''
    assert ra.status == c.ASSIGNED, 'a SECURED room drops back to ASSIGNED'

    assert ra.clear_card() is False, 'no token on file -> returns False'


def test_copy_card_from_and_secure_if_carded(session):
    inv = _inv(session)
    source = make_assignment(session, make_attendee(session), inv,
                             check_in=N[1], check_out=N[3], status=c.SECURED,
                             cc_token='tok-src', cc_last_four='1111',
                             address1='9 Copy Ave', city='Austin',
                             region='TX', zip_code='78701',
                             country='United States',
                             hotel_rewards_number='HR-42')
    target = make_assignment(session, make_attendee(session), inv,
                             check_in=N[1], check_out=N[3],
                             status=c.ASSIGNED, payment_type='credit_card')

    target.copy_card_from(source)
    assert target.cc_token == 'tok-src'
    assert target.address1 == '9 Copy Ave'
    assert target.hotel_rewards_number == 'HR-42'
    assert target.status == c.SECURED, \
        'copying a card onto an awaiting-card room secures it'

    # Master-bill rooms never flip to SECURED.
    master = make_assignment(session, make_attendee(session), inv,
                             check_in=N[1], check_out=N[3],
                             status=c.ASSIGNED, payment_type='masterbill')
    master.cc_token = 'tok-master'
    master.secure_if_carded()
    assert master.status == c.ASSIGNED


# ---------------------------------------------------------------------------
# guarantee_deadline
# ---------------------------------------------------------------------------

def test_guarantee_deadline_from_room_cutoff_is_tz_aware(session):
    inv = _inv(session)
    attendee = make_attendee(session)
    app = make_application(session, attendee)
    cutoff = date(2026, 10, 1)
    make_assignment(session, attendee, inv, status=c.ASSIGNED,
                    payment_type='credit_card', deposit_cutoff_date=cutoff,
                    check_in=N[1], check_out=N[3],
                    lottery_application_id=app.id)
    # A later cutoff on a second unsecured room: the EARLIEST one wins.
    make_assignment(session, attendee, inv, status=c.ASSIGNED,
                    payment_type='credit_card', deposit_cutoff_date=date(2026, 10, 15),
                    check_in=N[1], check_out=N[3],
                    lottery_application_id=app.id)

    deadline = app.guarantee_deadline
    assert isinstance(deadline, datetime)
    assert deadline.tzinfo is not None, 'must be tz-aware for email filters'
    expected = c.EVENT_TIMEZONE.localize(
        datetime.combine(cutoff, time(23, 59)))
    assert deadline == expected


def test_guarantee_deadline_global_fallback(session):
    attendee = make_attendee(session)
    app = make_application(session, attendee)

    if not c.HOTEL_LOTTERY_GUARANTEE_DUE:
        pytest.skip('HOTEL_LOTTERY_GUARANTEE_DUE is not configured in this '
                    'environment; fallback assertion not checkable')
    deadline = app.guarantee_deadline
    assert deadline == c.HOTEL_LOTTERY_GUARANTEE_DUE
    assert deadline.tzinfo is not None


# ---------------------------------------------------------------------------
# lottery_room_assignments scoping: rooms from other sources must not leak
# into award text, booking readiness, or deadlines.
# ---------------------------------------------------------------------------

def test_rejected_entry_ignores_unrelated_live_room(session):
    inv = _inv(session)
    attendee = make_attendee(session)
    app = make_application(session, attendee, status=c.REJECTED)
    make_assignment(session, attendee, inv, status=c.ASSIGNED,
                    assignment_reason=c.MANUAL, booking_url='https://example.com/book',
                    check_in=N[1], check_out=N[3])

    assert 'not chosen' in app.award_status_str
    assert not app.booking_url_ready
    assert app.lottery_room_assignments == []


def test_awarded_entry_reads_its_own_rooms(session):
    inv = _inv(session)
    attendee = make_attendee(session)
    app = make_application(session, attendee, status=c.AWARDED)
    ra = make_assignment(session, attendee, inv, status=c.ASSIGNED,
                         assignment_reason=c.LOTTERY_AWARD,
                         booking_url='https://example.com/book',
                         check_in=N[1], check_out=N[3],
                         lottery_application_id=app.id)

    assert 'was chosen' in app.award_status_str
    assert app.booking_url_ready
    assert app.lottery_room_assignments == [ra]


def test_guarantee_deadline_ignores_unrelated_room_cutoff(session):
    inv = _inv(session)
    attendee = make_attendee(session)
    app = make_application(session, attendee, status=c.AWARDED)
    make_assignment(session, attendee, inv, status=c.ASSIGNED,
                    payment_type='credit_card',
                    deposit_cutoff_date=date(2026, 9, 1),
                    check_in=N[1], check_out=N[3])
    make_assignment(session, attendee, inv, status=c.ASSIGNED,
                    payment_type='credit_card',
                    deposit_cutoff_date=date(2026, 10, 1),
                    check_in=N[1], check_out=N[3],
                    lottery_application_id=app.id)

    expected = c.EVENT_TIMEZONE.localize(
        datetime.combine(date(2026, 10, 1), time(23, 59)))
    assert app.guarantee_deadline == expected
