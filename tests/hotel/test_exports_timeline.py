"""uber.hotel.exports: the per-hotel activity timeline and the change
window behind its "N rooms changed" rows."""

import os
from datetime import timedelta

from pytz import UTC

from uber.hotel.exports import (changed_rooms_between, hotel_activity_timeline,
                                render_booking_export, store_export_file)
from uber.models.hotel import HotelImportFile
from uber.models.tracking import Tracking

from tests.hotel.factories import (N, make_assignment, make_attendee,
                                   make_hotel, make_inventory)


def _track(session, ra, when, data="room_number=''301' -> '302''"):
    from uber.config import c
    session.add(Tracking(model='RoomAssignment', fk_id=ra.id, when=when,
                         who='Tester', which=repr(ra), data=data,
                         action=c.UPDATED))
    session.flush()


def test_timeline_interleaves_changes_between_events(session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel, name='Kings')
    ra = make_assignment(session, make_attendee(session), inventory=inv,
                         check_in=N[1], check_out=N[3], room_number='301')
    session.flush()

    export = store_export_file(session, hotel, b'a,b\n1,2\n', 'first.csv',
                               'text/csv', source='admin', record_count=1)
    base = export.exported_at
    session.add(HotelImportFile(hotel_id=hotel.id, filename='back.csv',
                                filepath='/tmp/back.csv', source='portal',
                                uploaded_at=base + timedelta(hours=2),
                                updated_count=1))
    # One change while the hotel held the export, one after the import.
    _track(session, ra, base + timedelta(hours=1))
    _track(session, ra, base + timedelta(hours=3))
    session.flush()

    timeline = hotel_activity_timeline(session, hotel.id)
    kinds = [row['kind'] for row in timeline]

    # Newest first: changes since the import, the import, the change
    # while the hotel held the export, then the export itself.
    assert kinds == ['changes', 'import', 'changes', 'export']
    assert timeline[0]['count'] == 1 and timeline[0]['end'] is None
    assert timeline[2]['count'] == 1
    assert timeline[1]['source'] == 'portal'
    assert timeline[3]['source'] == 'admin'
    assert timeline[3]['file_id'] == export.id


def test_changed_rooms_parses_fields_and_drops_noise(session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel, name='Kings')
    ra = make_assignment(session, make_attendee(session), inventory=inv,
                         check_in=N[1], check_out=N[3], room_number='301')
    session.flush()

    export = store_export_file(session, hotel, b'x', 'f.csv', 'text/csv',
                               source='admin')
    _track(session, ra, export.exported_at + timedelta(minutes=5),
           data=("hotel_confirmation_number='None -> 'ABC123'', "
                 "last_modified_at='None -> datetime.datetime(2026, 1, 2, "
                 "3, 4, 5, tzinfo=<UTC>)'"))
    session.flush()

    rows = changed_rooms_between(session, hotel.id, export.exported_at, None)

    assert len(rows) == 1
    assert rows[0]['number'] == '301'
    assert rows[0]['guest']
    # Repr quoting stripped, and the bookkeeping column left out.
    assert rows[0]['changes'] == [
        ('hotel_confirmation_number', '(empty)', 'ABC123')]


def test_export_file_is_retained_and_reproducible(session):
    hotel = make_hotel(session)
    make_inventory(session, hotel, name='Kings')

    _hotel, filename, content_type, data = render_booking_export(
        session, hotel.id, 'csv')
    entry = store_export_file(session, hotel, data, filename, content_type,
                              source='admin', record_count=0)
    session.flush()

    assert entry.filepath and entry.size == len(data)
    with open(entry.filepath, 'rb') as f:
        assert f.read() == data
    assert filename.endswith('.csv')


def test_import_changes_scoped_to_its_applied_window(session):
    """The change feed has no link back to the file, so an import's
    changes are the ones recorded inside the window it bracketed."""
    from uber.hotel.exports import import_changes

    hotel = make_hotel(session)
    inv = make_inventory(session, hotel, name='Kings')
    ra = make_assignment(session, make_attendee(session), inventory=inv,
                         check_in=N[1], check_out=N[3], room_number='301')
    session.flush()

    imported = HotelImportFile(hotel_id=hotel.id, filename='conf.csv',
                               filepath='/tmp/conf.csv', source='admin')
    session.add(imported)
    session.flush()
    imported.applied_from = imported.uploaded_at + timedelta(seconds=1)
    imported.applied_to = imported.uploaded_at + timedelta(seconds=2)
    session.flush()

    # One change inside the window, one well after it (an admin edit).
    _track(session, ra, imported.applied_from + timedelta(milliseconds=500),
           data="hotel_confirmation_number='None -> 'ABC123''")
    _track(session, ra, imported.applied_to + timedelta(hours=1),
           data="room_number=''301' -> '302''")
    session.flush()

    rows = import_changes(session, imported)

    assert len(rows) == 1
    assert rows[0]['changes'] == [
        ('hotel_confirmation_number', '(empty)', 'ABC123')]


def test_stored_files_render_as_tables_in_every_format(session, tmp_path):
    """CSV, XLSX, and the API export's JSON all feed one viewer."""
    import json

    from uber.hotel.exports import read_stored_file

    hotel = make_hotel(session)
    make_inventory(session, hotel, name='Kings')

    _h, csv_name, csv_type, csv_data = render_booking_export(
        session, hotel.id, 'csv')
    csv_entry = store_export_file(session, hotel, csv_data, csv_name,
                                  csv_type, source='admin')
    _h, xlsx_name, xlsx_type, xlsx_data = render_booking_export(
        session, hotel.id, 'xlsx')
    xlsx_entry = store_export_file(session, hotel, xlsx_data, xlsx_name,
                                   xlsx_type, source='admin')
    json_entry = store_export_file(
        session, hotel,
        json.dumps({'bookings': [{'confirmation_num': '1',
                                  'room_number': None}]}).encode('utf-8'),
        'api.json', 'application/json', source='api')
    session.flush()

    for entry in (csv_entry, xlsx_entry):
        columns, rows, error = read_stored_file(entry)
        assert error is None
        assert 'confirmation_num' in columns

    columns, rows, error = read_stored_file(json_entry)
    assert error is None
    assert columns == ['confirmation_num', 'room_number']
    # JSON nulls render as empty cells rather than the string "None".
    assert rows == [{'confirmation_num': '1', 'room_number': ''}]


def test_missing_file_reports_instead_of_raising(session):
    from uber.hotel.exports import read_stored_file

    hotel = make_hotel(session)
    entry = store_export_file(session, hotel, b'x', 'gone.csv', 'text/csv',
                              source='admin')
    session.flush()
    os.remove(entry.filepath)

    columns, rows, error = read_stored_file(entry)
    assert (columns, rows) == ([], [])
    assert 'no longer retained' in error


def test_import_changes_are_not_double_counted_in_gap_rows(session):
    """An import's own writes belong to its row, not to the gap above
    it - otherwise the same change is reported twice."""
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel, name='Kings')
    ra = make_assignment(session, make_attendee(session), inventory=inv,
                         check_in=N[1], check_out=N[3], room_number='301')
    session.flush()

    export = store_export_file(session, hotel, b'x', 'sent.csv', 'text/csv',
                               source='admin', record_count=1)
    base = export.exported_at

    imported = HotelImportFile(hotel_id=hotel.id, filename='back.csv',
                               filepath='/tmp/back.csv', source='portal',
                               uploaded_at=base + timedelta(hours=1))
    session.add(imported)
    session.flush()
    imported.applied_from = base + timedelta(hours=1)
    imported.applied_to = base + timedelta(hours=1, seconds=1)
    session.flush()

    # The hotel's confirmation number (inside the import's window) and
    # an admin edit afterward.
    _track(session, ra, base + timedelta(hours=1, milliseconds=200),
           data="hotel_confirmation_number='None -> 'FROM-HOTEL''")
    _track(session, ra, base + timedelta(hours=2),
           data="room_number=''301' -> '302''")
    session.flush()

    timeline = hotel_activity_timeline(session, hotel.id)
    changes = [row for row in timeline if row['kind'] == 'changes']

    # Only the admin edit shows as a gap row; the import's write does not.
    assert len(changes) == 1
    assert changes[0]['count'] == 1
    gap = changed_rooms_between(session, hotel.id, changes[0]['start'],
                                changes[0]['end'], exclude_imports=True)
    assert [f for row in gap for f, _o, _n in row['changes']] == ['room_number']

    # And the import row still reports its own change.
    from uber.hotel.exports import import_changes
    caused = import_changes(session, imported)
    assert [f for row in caused for f, _o, _n in row['changes']] == [
        'hotel_confirmation_number']
