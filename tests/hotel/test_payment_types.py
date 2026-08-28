"""Payment types: the config-driven enum, the derived require_cc, and the
export codes."""

import pytest

from uber.config import c
from uber.hotel.service import RoomAssignmentError, parse_payment_type
from uber.models.hotel import RoomAssignment

from tests.hotel.factories import (make_assignment, make_attendee, make_hotel,
                                   make_inventory)


ALL_TYPES = ['masterbill', 'credit_card', 'masterbill_parking', 'credit_card_parking']


def test_default_payment_types_are_configured():
    assert set(ALL_TYPES) <= set(c.HOTEL_PAYMENT_TYPES)


@pytest.mark.parametrize('payment_type, code', [
    ('masterbill', 'RT'),
    ('credit_card', 'IPO'),
    ('masterbill_parking', 'RTP'),
    ('credit_card_parking', 'IPOP'),
])
def test_payment_code_matches_config(payment_type, code):
    assert RoomAssignment(payment_type=payment_type).payment_code == code


@pytest.mark.parametrize('payment_type, require_cc, parking', [
    ('masterbill', False, False),
    ('credit_card', True, False),
    ('masterbill_parking', False, True),
    ('credit_card_parking', True, True),
])
def test_derived_flags(payment_type, require_cc, parking):
    ra = RoomAssignment(payment_type=payment_type)
    assert ra.require_cc is require_cc
    assert ra.event_pays_parking is parking


def test_unknown_payment_type_shows_raw_key_rather_than_blanking():
    ra = RoomAssignment(payment_type='renamed_away')
    assert ra.payment_type_label == 'renamed_away'
    assert ra.payment_code == ''


@pytest.mark.parametrize('payment_type', ALL_TYPES)
def test_require_cc_property_and_sql_expression_agree(session, payment_type):
    attendee = make_attendee(session)
    inventory = make_inventory(session, make_hotel(session))
    ra = make_assignment(session, attendee=attendee, inventory=inventory,
                         payment_type=payment_type)
    session.flush()

    matched = session.query(RoomAssignment).filter(
        RoomAssignment.id == ra.id, RoomAssignment.require_cc).count()
    assert bool(matched) is ra.require_cc


def test_parse_payment_type_defaults_and_rejects():
    assert parse_payment_type('') == 'masterbill'
    assert parse_payment_type('', default='credit_card') == 'credit_card'
    assert parse_payment_type('masterbill_parking') == 'masterbill_parking'
    with pytest.raises(RoomAssignmentError):
        parse_payment_type('not_a_type')
