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


ROOM_LIST_HEADERS = ['Last Name', 'First Name', 'Email', 'Check-In', 'Checkout',
                     'Room Type', 'Attendee Type', 'Acknowledgement Number',
                     'Ext. Confirmation Number', 'Other Pay Description']


def _two_sheet_workbook():
    """An xlsx whose Room List sheet is deliberately not the active one."""
    import io

    from openpyxl import Workbook

    wb = Workbook()
    summary = wb.active
    summary.title = 'Summary'
    summary.append(['Totals', 'Nights'])
    summary.append([2, 6])
    rooms = wb.create_sheet('Room List')
    rooms.append(ROOM_LIST_HEADERS)
    rooms.append(['Example', 'Ada', 'ada.example@example.org', '2027-01-07',
                  '2027-01-10', 'Deluxe Guest Room', 'Attendee', 'ACK1',
                  '95555414', ''])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_detection_retries_the_other_sheets(session, no_cherrypy_session):
    """A workbook whose Room List sheet is not first must still detect and
    read the right sheet."""
    raw = _two_sheet_workbook()
    template = mapping.detect_upload_template(session, raw, 'rooms.xlsx')
    assert template is not None
    assert template.name == 'Standard room list'

    rows, error = mapping.build_rows(session, raw, 'rooms.xlsx', template)
    assert error is None
    assert len(rows) == 1
    assert rows[0]['mapped']['assignment.hotel_confirmation_number'] == 'ACK1'


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


def test_other_pay_description_maps_to_payment_type():
    """The sample's Other Pay Description column feeds payment_type through
    the enum map, and values with no entry pass through unchanged rather
    than crashing."""
    assert mapping.TARGETS_BY_KEY['assignment.payment_type']['kind'] == 'enum:payment_type'

    template = mapping.builtin_template()
    assert template.column_map['other_pay_description'] == 'assignment.payment_type'
    template.enum_map = {'assignment.payment_type': {'Room & Tax': 'masterbill'}}

    mapped = mapping.apply_maps({'other_pay_description': 'room & tax'}, template)
    assert mapped['assignment.payment_type'] == 'masterbill'

    unmapped = mapping.apply_maps({'other_pay_description': 'Comp'}, template)
    assert unmapped['assignment.payment_type'] == 'Comp'


def test_an_unmapped_payment_value_diffs_without_crashing(session, no_cherrypy_session):
    ra = _booking(session)
    diff = mapping.diff_row(ra, {'assignment.payment_type': 'Comp'})
    by_key = {d['key']: d for d in diff}
    assert by_key['assignment.payment_type']['imported'] == 'Comp'
    assert by_key['assignment.payment_type']['changed'] is True


def test_disambiguation_makes_the_rematch_unambiguous(session, no_cherrypy_session):
    """Stamping the row's acknowledgement number onto the chosen booking (as
    resolve_import_row does) makes every later match deterministic."""
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel)
    attendee = make_attendee(session)
    attendee.email = 'dup@example.com'
    chosen = make_assignment(session, attendee=attendee, inventory=inv,
                             check_in=date(2027, 1, 7), check_out=date(2027, 1, 10))
    make_assignment(session, attendee=attendee, inventory=inv,
                    check_in=date(2027, 1, 7), check_out=date(2027, 1, 10))
    session.flush()

    mapped = {'attendee.email': 'dup@example.com',
              'assignment.hotel_confirmation_number': 'ACK42'}
    found, status = mapping.match_row(session, mapped)
    assert status == 'ambiguous'
    assert len(found) == 2

    chosen.hotel_confirmation_number = 'ACK42'
    session.flush()

    found, status = mapping.match_row(session, mapped)
    assert status == 'matched'
    assert found[0].id == chosen.id


# ---------------------------------------------------------------------------
# the import pipeline around the mapping layer
# ---------------------------------------------------------------------------

def _room_list_csv(rows):
    """CSV bytes with the standard room-list headers, so the built-in format
    is detected. Each row is a dict keyed by normalized column name."""
    import csv
    import io

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(ROOM_LIST_HEADERS)
    for row in rows:
        writer.writerow([row.get('last_name', ''), row.get('first_name', ''),
                         row.get('email', ''), row.get('check-in', ''),
                         row.get('checkout', ''), row.get('room_type', ''),
                         row.get('attendee_type', ''),
                         row.get('acknowledgement_number', ''),
                         row.get('ext._confirmation_number', ''),
                         row.get('other_pay_description', '')])
    return buf.getvalue().encode('utf-8')


def test_template_import_auto_applies_confirmation_numbers(session, no_cherrypy_session):
    """An unambiguous match gets its acknowledgement number applied at
    upload; everything else is left for review."""
    from uber.hotel.imports import import_confirmation_file

    ra = _booking(session, email='auto@example.com')
    raw = _room_list_csv([
        {'email': 'auto@example.com', 'acknowledgement_number': 'NEWACK',
         'checkout': '2027-01-11'},
        {'email': 'nobody@example.com', 'acknowledgement_number': 'MISSED'},
    ])

    result = import_confirmation_file(session, raw, 'list.csv',
                                      template=mapping.builtin_template())
    assert result['error'] is None
    assert ra.hotel_confirmation_number == 'NEWACK'
    # The differing checkout date is not auto-applied.
    assert ra.assigned_check_out_date == date(2027, 1, 10)

    record = result['record']
    assert record.matched_count == 1
    assert record.unmatched_count == 1
    assert record.updated_count == 1
    assert record.applied_from is not None and record.applied_to is not None


def test_stored_rows_are_capped_and_reread_from_disk(session, no_cherrypy_session,
                                                     monkeypatch):
    from uber.hotel.imports import _store_file

    monkeypatch.setattr(mapping, 'STORED_ROW_CAP', 2)
    raw = _room_list_csv([
        {'email': f'row{i}@example.com', 'acknowledgement_number': f'ACK{i}'}
        for i in range(4)])

    record = _store_file(session, raw, 'big.csv', 'text/csv', None, 'admin', 'T')
    summary = mapping.prepare_import_review(session, record, raw, 'big.csv')
    assert summary is not None
    assert summary['total'] == 4
    assert len(record.parsed_rows) == 2

    full = mapping.full_parsed_rows(session, record)
    assert len(full) == 4
    assert [row['index'] for row in full] == [0, 1, 2, 3]


def test_header_map_round_trips(session):
    from uber.models.hotel import ImportMappingTemplate

    template = ImportMappingTemplate(
        name='Header map format',
        column_map={'acknowledgement_number': 'assignment.hotel_confirmation_number'},
        header_map={'acknowledgement_number': 'Acknowledgement Number'})
    session.add(template)
    session.flush()
    session.expire(template)

    stored = session.query(ImportMappingTemplate).get(template.id)
    assert stored.header_map == {'acknowledgement_number': 'Acknowledgement Number'}
