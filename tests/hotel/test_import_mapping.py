"""Reading a hotel's room-list format: detection, mapping, matching, and the
one place an imported value becomes a booking value."""

import os
from datetime import date

import pytest

from uber.config import c
from uber.hotel import mapping
from uber.hotel.imports import parse_spreadsheet

from tests.hotel.factories import (make_assignment, make_attendee, make_hotel,
                                   make_inventory, make_room_type)


# A synthetic file in the shape of the room lists hotels actually send:
# real names and emails would be needless PII in the repo.
SAMPLE = os.path.join(os.path.dirname(__file__), 'fixtures', 'sample-room-list.xlsx')


def _sample_bytes():
    with open(SAMPLE, 'rb') as f:
        return f.read()


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------

def test_named_sheet_is_read(session):
    template = mapping.builtin_template()
    fields, rows, error = mapping.parse_with_template(
        _sample_bytes(), 'sample.xlsx', template)
    assert error is None
    assert rows, 'expected data rows'
    assert 'acknowledgement_number' in fields


def test_default_sheet_behavior_is_unchanged():
    """Existing callers pass no sheet name and must keep reading the active
    sheet."""
    raw = b'a,b\n1,2\n'
    fields, rows, error = parse_spreadsheet(raw, 'x.csv')
    assert error is None
    assert fields == ['a', 'b']
    assert rows == [{'a': '1', 'b': '2'}]


def test_header_row_is_xlsx_only():
    """CSV always treats its first line as the header, and header names are
    normalized (lowercased, spaces to underscores)."""
    raw = b'junk line\na,b\n1,2\n'
    fields, _rows, error = parse_spreadsheet(raw, 'x.csv', header_row=2)
    assert error is None
    assert fields == ['junk_line']


# ---------------------------------------------------------------------------
# detection
# ---------------------------------------------------------------------------

def test_the_sample_format_is_detected(session):
    fields, _rows, _error = mapping.parse_with_template(
        _sample_bytes(), 'sample.xlsx', None)
    template = mapping.detect_template(session, fields)
    assert template is not None
    assert template.name == 'Standard room list'


def test_an_unknown_layout_detects_nothing(session):
    """Falling through to None keeps the older confirmation-number import
    working for files nothing recognizes."""
    assert mapping.detect_template(session, ['wibble', 'wobble']) is None


# ---------------------------------------------------------------------------
# mapping
# ---------------------------------------------------------------------------

def test_sample_row_maps_to_our_fields(session):
    template = mapping.builtin_template()
    _fields, rows, _error = mapping.parse_with_template(
        _sample_bytes(), 'sample.xlsx', template)
    mapped = mapping.apply_maps(rows[0], template)

    assert mapped['assignment.hotel_confirmation_number'] == '3G07HMBV'
    assert mapped['attendee.email'] == 'ada.example@example.org'
    assert mapped['assignment.assigned_check_in_date'] == '2027-01-07'
    assert mapped['assignment.assigned_check_out_date'] == '2027-01-10'
    # The external confirmation number is the hotel's own, so we ignore it.
    assert 'ext._confirmation_number' not in mapped
    assert '95555414' not in str(mapped)


def test_enum_values_are_translated():
    template = mapping.builtin_template()
    template.column_map = {'pay': 'assignment.payment_type'}
    template.enum_map = {'assignment.payment_type': {'Room & Tax': 'masterbill'}}

    mapped = mapping.apply_maps({'pay': 'room & tax'}, template)
    assert mapped['assignment.payment_type'] == 'masterbill'


def test_a_date_format_is_honored():
    template = mapping.builtin_template()
    template.column_map = {'arrive': 'assignment.assigned_check_in_date'}
    template.format_map = {'assignment.assigned_check_in_date': '%m/%d/%Y'}

    mapped = mapping.apply_maps({'arrive': '01/07/2027'}, template)
    assert mapped['assignment.assigned_check_in_date'] == '2027-01-07'


# ---------------------------------------------------------------------------
# matching
# ---------------------------------------------------------------------------

def _booking(session, email='guest@example.com', **kwargs):
    hotel = kwargs.pop('hotel', None) or make_hotel(session)
    room_type = make_room_type(session, name=kwargs.pop('type_name', 'Deluxe'))
    inv = make_inventory(session, hotel, room_type=room_type)
    attendee = make_attendee(session)
    attendee.email = email
    ra = make_assignment(session, attendee=attendee, inventory=inv,
                         check_in=date(2027, 1, 7), check_out=date(2027, 1, 10))
    session.flush()
    return ra


def test_a_known_confirmation_number_matches_outright(session, no_cherrypy_session):
    ra = _booking(session)
    ra.hotel_confirmation_number = 'ABC123'
    session.flush()

    found, status = mapping.match_row(
        session, {'assignment.hotel_confirmation_number': 'ABC123'})
    assert status == 'matched'
    assert found[0].id == ra.id


def test_email_matches_when_there_is_no_number(session, no_cherrypy_session):
    ra = _booking(session, email='someone@example.com')
    found, status = mapping.match_row(session, {'attendee.email': 'someone@example.com'})
    assert status == 'matched'
    assert found[0].id == ra.id


def test_two_bookings_for_one_email_are_ambiguous(session, no_cherrypy_session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel)
    attendee = make_attendee(session)
    attendee.email = 'twice@example.com'
    make_assignment(session, attendee=attendee, inventory=inv,
                    check_in=date(2027, 1, 7), check_out=date(2027, 1, 10))
    make_assignment(session, attendee=attendee, inventory=inv,
                    check_in=date(2027, 1, 8), check_out=date(2027, 1, 11))
    session.flush()

    found, status = mapping.match_row(session, {'attendee.email': 'twice@example.com'})
    assert status == 'ambiguous'
    assert len(found) == 2


def test_check_in_date_narrows_an_ambiguous_match(session, no_cherrypy_session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel)
    attendee = make_attendee(session)
    attendee.email = 'narrow@example.com'
    first = make_assignment(session, attendee=attendee, inventory=inv,
                            check_in=date(2027, 1, 7), check_out=date(2027, 1, 10))
    make_assignment(session, attendee=attendee, inventory=inv,
                    check_in=date(2027, 1, 8), check_out=date(2027, 1, 11))
    session.flush()

    found, status = mapping.match_row(session, {
        'attendee.email': 'narrow@example.com',
        'assignment.assigned_check_in_date': '2027-01-07',
    })
    assert status == 'matched'
    assert found[0].id == first.id


def test_an_unknown_guest_is_unmatched(session, no_cherrypy_session):
    _booking(session)
    found, status = mapping.match_row(session, {'attendee.email': 'nobody@example.com'})
    assert status == 'unmatched'
    assert found == []


# ---------------------------------------------------------------------------
# diffing and writing
# ---------------------------------------------------------------------------

def test_diff_reports_only_real_differences(session, no_cherrypy_session):
    ra = _booking(session, email='diff@example.com')
    diff = mapping.diff_row(ra, {
        'attendee.email': 'diff@example.com',
        'assignment.assigned_check_out_date': '2027-01-11',
    })
    by_key = {d['key']: d for d in diff}
    assert by_key['attendee.email']['changed'] is False
    assert by_key['assignment.assigned_check_out_date']['changed'] is True


def test_sync_writes_the_imported_value(session, no_cherrypy_session):
    ra = _booking(session)
    ok, _message = mapping.sync_value(
        session, ra, 'assignment.assigned_check_out_date', '2027-01-12')
    assert ok
    assert ra.assigned_check_out_date == date(2027, 1, 12)


def test_sync_refuses_a_match_only_field(session, no_cherrypy_session):
    ra = _booking(session)
    ok, message = mapping.sync_value(session, ra, 'match.room_type', 'Deluxe')
    assert not ok
    assert 'cannot be synced' in message


def test_sync_rejects_an_unreadable_date(session, no_cherrypy_session):
    ra = _booking(session)
    ok, message = mapping.sync_value(
        session, ra, 'assignment.assigned_check_in_date', 'not a date')
    assert not ok
    assert 'date' in message


def test_sync_rejects_an_unknown_payment_type(session, no_cherrypy_session):
    ra = _booking(session)
    ok, message = mapping.sync_value(
        session, ra, 'assignment.payment_type', 'wibble')
    assert not ok
    assert 'payment type' in message


def test_payment_types_are_offered_as_a_target():
    """The sample's Other Pay Description column maps here once an event
    configures how that hotel spells each type."""
    assert 'assignment.payment_type' in mapping.TARGETS_BY_KEY
    assert mapping.TARGETS_BY_KEY['assignment.payment_type']['kind'] == 'enum:payment_type'
