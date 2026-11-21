"""uber.hotel.exports: the per-hotel activity timeline and the change
window behind its "N rooms changed" rows."""

import inspect
import os
import uuid
from datetime import timedelta

import cherrypy
import pytest
from pytz import UTC

from uber.hotel.exports import (changed_rooms_between, hotel_activity_timeline,
                                render_booking_export, store_export_file,
                                unprocessed_imports)
from uber.models.hotel import HotelImportFile
from uber.models.tracking import Tracking

from tests.hotel.factories import (N, make_application, make_assignment,
                                   make_attendee, make_hotel, make_inventory)


STAMPED = ", last_modified_at='None -> datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=<UTC>)'"


def _track(session, ra, when, data="special_requests='None -> 'Low floor''" + STAMPED):
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
    _track(session, ra, base + timedelta(hours=2))
    session.flush()

    timeline = hotel_activity_timeline(session, hotel.id)
    changes = [row for row in timeline if row['kind'] == 'changes']

    # Only the admin edit shows as a gap row; the import's write does not.
    assert len(changes) == 1
    assert changes[0]['count'] == 1
    gap = changed_rooms_between(session, hotel.id, changes[0]['start'],
                                changes[0]['end'], exclude_imports=True)
    assert [f for row in gap for f, _o, _n in row['changes']] == ['special_requests']

    # And the import row still reports its own change.
    from uber.hotel.exports import import_changes
    caused = import_changes(session, imported)
    assert [f for row in caused for f, _o, _n in row['changes']] == [
        'hotel_confirmation_number']


# ---------------------------------------------------------------------------
# Who column: exported_by and the update_assignment acting user
# ---------------------------------------------------------------------------

class _SessionCM:
    """Stand-in for uber.api.Session() that yields the test session and
    never commits, so the per-test rollback still isolates everything."""
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, *args):
        return False


def _api_call(session, monkeypatch, method, **kwargs):
    import uber.api

    monkeypatch.setattr(uber.api, 'Session', lambda: _SessionCM(session))
    monkeypatch.setattr(session, 'commit', session.flush)
    fn = inspect.unwrap(getattr(uber.api.HotelLookup, method))
    return fn(uber.api.HotelLookup(), **kwargs)


def _clear_acting_user():
    if hasattr(cherrypy.request, 'api_acting_user'):
        del cherrypy.request.api_acting_user


def test_export_who_column_carries_exported_by(session):
    hotel = make_hotel(session)
    entry = store_export_file(session, hotel, b'x', 'f.csv', 'text/csv',
                              source='api', record_count=0,
                              exported_by='portal-admin')
    session.flush()

    timeline = hotel_activity_timeline(session, hotel.id)
    exports = [row for row in timeline if row['kind'] == 'export']
    assert exports[0]['file_id'] == entry.id
    assert exports[0]['who'] == 'portal-admin'


def test_api_export_attribution_defaults_to_api(session, monkeypatch):
    from uber.models.hotel import HotelExportLog

    hotel = make_hotel(session)
    inv = make_inventory(session, hotel, name='Kings')
    attendee = make_attendee(session)
    app = make_application(session, attendee)
    make_assignment(session, attendee, inventory=inv,
                    check_in=N[1], check_out=N[3],
                    lottery_application_id=app.id)
    session.flush()

    result = _api_call(session, monkeypatch, 'export_room_bookings',
                       hotel=hotel.id)
    assert len(result['bookings']) == 1

    logs = session.query(HotelExportLog).filter_by(
        hotel_id=hotel.id, export_type='room_export').all()
    assert [log.exported_by for log in logs] == ['api']

    _api_call(session, monkeypatch, 'export_room_bookings',
              hotel=hotel.id, exported_by='  portal-admin ')
    logs = session.query(HotelExportLog).filter_by(
        hotel_id=hotel.id, export_type='room_export').order_by(
        HotelExportLog.exported_at).all()
    assert logs[-1].exported_by == 'portal-admin'


def test_acting_name_prefixes_stashed_api_user(monkeypatch):
    from uber.models.admin import AdminAccount

    _clear_acting_user()
    assert AdminAccount.acting_name() == AdminAccount.admin_or_volunteer_name()

    monkeypatch.setattr(cherrypy.request, 'api_acting_user', 'portal-admin',
                        raising=False)
    assert AdminAccount.acting_name() == 'api:portal-admin'


def test_update_assignment_attributes_changes_to_acting_user(
        session, monkeypatch):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel, name='Kings')
    ra = make_assignment(session, make_attendee(session), inventory=inv,
                         check_in=N[1], check_out=N[3], room_number='301')
    session.flush()

    try:
        result = _api_call(session, monkeypatch, 'update_assignment',
                           id=str(ra.id), acting_user='  Portal Admin ',
                           room_number='302')
        assert result['room_number'] == '302'

        # The tracking row is added during after_flush; flush again so it
        # is queryable.
        session.flush()
        rows = session.query(Tracking).filter_by(
            model='RoomAssignment', fk_id=ra.id).all()
        assert [row.who for row in rows if "302" in row.data] == [
            'api:Portal Admin'], \
            'the RPC write must carry the stripped, prefixed acting name'
    finally:
        _clear_acting_user()

    # Without an acting_user the stash stays unset and attribution falls
    # back to the normal path ('non-admin' outside a web request).
    result = _api_call(session, monkeypatch, 'update_assignment',
                       id=str(ra.id), room_number='303')
    assert result['room_number'] == '303'
    assert not hasattr(cherrypy.request, 'api_acting_user')
    session.flush()
    rows = session.query(Tracking).filter_by(
        model='RoomAssignment', fk_id=ra.id).all()
    assert [row.who for row in rows if "303" in row.data] == ['non-admin']


def test_update_assignment_caps_acting_user_length(session, monkeypatch):
    from cherrypy import HTTPError

    try:
        with pytest.raises(HTTPError):
            _api_call(session, monkeypatch, 'update_assignment',
                      id=str(uuid.uuid4()), acting_user='x' * 300)
        assert cherrypy.request.api_acting_user == 'x' * 255
    finally:
        _clear_acting_user()


# ---------------------------------------------------------------------------
# Import status: pending uploads and legacy rows
# ---------------------------------------------------------------------------

def test_uploaded_import_lands_pending(session):
    from uber.hotel.imports import _store_file

    hotel = make_hotel(session)
    record = _store_file(session, b'a,b\n1,2\n', 'roomlist.csv', 'text/csv',
                         hotel, 'portal', 'portal-admin')

    assert record.effective_status == 'pending'
    assert record.id in {f.id for f in unprocessed_imports(session, hotel.id)}


def test_legacy_applied_import_reads_processed(session):
    hotel = make_hotel(session)
    imported = HotelImportFile(hotel_id=hotel.id, filename='old.csv',
                               filepath='/tmp/old.csv', source='admin')
    session.add(imported)
    session.flush()
    imported.applied_from = imported.uploaded_at
    imported.applied_to = imported.uploaded_at + timedelta(seconds=1)
    session.flush()

    # Rows predating the status column have no status value; the applied
    # window stands in for it.
    assert imported.status == ''
    assert imported.effective_status == 'processed'
    assert imported.id not in {
        f.id for f in unprocessed_imports(session, hotel.id)}

    # An explicit status always wins over the applied window.
    imported.status = 'pending'
    assert imported.effective_status == 'pending'


def test_details_pending_only_hides_in_sync_rooms(session, no_cherrypy_session):
    from uber.site_sections import hotel_lottery_admin

    hotel = make_hotel(session)
    inv = make_inventory(session, hotel)
    synced, changed, unconfirmed = [
        make_assignment(session, make_attendee(session), inventory=inv, check_in=N[1], check_out=N[3],
                        hotel_confirmation_number=number) for number in ('H1', 'H2', '')]
    details = lambda **params: inspect.unwrap(hotel_lottery_admin.Root.hotel_export_details)(  # noqa: E731
        hotel_lottery_admin.Root(), session, hotel_id=hotel.id, **params)

    # Before any export everything is pending.
    assert details(pending_only='1')['total'] == 3

    export = store_export_file(session, hotel, b'a\n1\n', 'first.csv', 'text/csv', source='admin', record_count=3)
    for ra in (synced, changed, unconfirmed):
        ra.last_modified_at = export.exported_at - timedelta(hours=1)
    changed.last_modified_at = export.exported_at + timedelta(hours=1)
    session.flush()

    assert details()['total'] == 3
    pending = details(pending_only='1')
    assert pending['total'] == 2
    assert {row['assignment'].id for row in pending['bookings']} == {changed.id, unconfirmed.id}
    assert {row['sync_status'] for row in pending['bookings']} == {'pending_export', 'awaiting_confirmation'}


def test_roommate_changes_count_as_changed_since_export(session, no_cherrypy_session):
    from uber.hotel.exports import derive_sync_status
    from uber.hotel.service import add_room_occupant, remove_room_occupant

    hotel = make_hotel(session)
    ra = make_assignment(session, make_attendee(session), inventory=make_inventory(session, hotel),
                         check_in=N[1], check_out=N[3], hotel_confirmation_number='H1')
    mate = make_attendee(session)
    export = store_export_file(session, hotel, b'a\n1\n', 'first.csv', 'text/csv', source='admin', record_count=1)

    def settle():
        ra.last_modified_at = export.exported_at - timedelta(hours=1)
        session.flush()
        assert derive_sync_status(ra, export) == 'in_sync'

    settle()
    # An edit that leaves the roommates alone is not a change for the hotel.
    ra.admin_notes = 'note'
    session.flush()
    assert derive_sync_status(ra, export) == 'in_sync'

    add_room_occupant(session, ra, mate.id)
    assert derive_sync_status(ra, export) == 'pending_export'
    settle()
    remove_room_occupant(session, ra, mate.id)
    assert derive_sync_status(ra, export) == 'pending_export'


@pytest.mark.parametrize('fmt', ['csv', 'xlsx', 'json'])
def test_catch_up_flags_rooms_that_differ_from_the_last_file(session, no_cherrypy_session, fmt):
    import json

    from uber.hotel.exports import booking_dict, flag_rooms_changed_since_export
    from uber.models.hotel import room_assignment_occupant

    hotel = make_hotel(session)
    inv = make_inventory(session, hotel)
    same, new_mate, new_email, already = rooms = [
        make_assignment(session, make_attendee(session), inventory=inv, check_in=N[1], check_out=N[3],
                        hotel_confirmation_number=f'H{i}') for i in range(4)]
    session.execute(room_assignment_occupant.insert().values(
        room_assignment_id=same.id, attendee_id=make_attendee(session).id))
    session.flush()
    session.expire_all()

    if fmt == 'json':
        name, kind = 'pull.json', 'application/json'
        raw = json.dumps({'bookings': [booking_dict(ra, None) for ra in rooms]}, default=str).encode()
    else:
        _, name, kind, raw = render_booking_export(session, hotel.id, fmt)
    export = store_export_file(session, hotel, raw, name, kind, source='admin', record_count=4)

    # Changes of the kind that never moved last_modified_at.
    session.execute(room_assignment_occupant.insert().values(
        room_assignment_id=new_mate.id, attendee_id=make_attendee(session).id))
    session.execute(room_assignment_occupant.insert().values(
        room_assignment_id=already.id, attendee_id=make_attendee(session).id))
    new_email.attendee.email = 'changed@example.com'
    for ra in rooms:
        ra.last_modified_at = export.exported_at - timedelta(hours=1)
    already.last_modified_at = export.exported_at + timedelta(hours=1)
    session.flush()
    session.expire_all()

    found = {ra.id: changed for ra, changed in flag_rooms_changed_since_export(session)}
    assert found == {new_mate.id: ['guests'], new_email.id: ['email']}
    assert new_mate.last_modified_at < export.exported_at   # a dry run

    flag_rooms_changed_since_export(session, commit=True)
    assert new_mate.last_modified_at > export.exported_at and new_email.last_modified_at > export.exported_at
    assert same.last_modified_at < export.exported_at
    assert flag_rooms_changed_since_export(session) == []


def test_catch_up_unflags_rooms_only_the_hotel_changed(session, no_cherrypy_session):
    from uber.hotel.exports import flag_rooms_changed_since_export, unflag_rooms_changed_by_hotel
    from uber.models.hotel import room_assignment_occupant

    hotel = make_hotel(session)
    inv = make_inventory(session, hotel)
    confirmed, cancelled, also_ours, ours_later, by_hand = rooms = [
        make_assignment(session, make_attendee(session), inventory=inv, check_in=N[1], check_out=N[3],
                        hotel_confirmation_number='OLD' if i == 1 else '') for i in range(5)]
    _, name, kind, raw = render_booking_export(session, hotel.id, 'csv')
    export = store_export_file(session, hotel, raw, name, kind, source='admin', record_count=5)
    during, after = export.exported_at + timedelta(hours=1), export.exported_at + timedelta(hours=3)
    session.add(HotelImportFile(hotel_id=hotel.id, filename='back.csv', filepath='/tmp/back.csv', source='portal',
                                uploaded_at=during, applied_from=during - timedelta(seconds=5),
                                applied_to=during + timedelta(seconds=5)))

    # What the old code did: the upload's numbers stamped every room they landed on.
    for ra in (confirmed, also_ours, ours_later, by_hand):
        ra.hotel_confirmation_number = 'NEW'
    cancelled.cancellation_confirmation_number = 'X1'
    session.execute(room_assignment_occupant.insert().values(
        room_assignment_id=also_ours.id, attendee_id=make_attendee(session).id))
    ours_later.special_requests = 'Low floor'
    session.flush()
    for ra in rooms:
        ra.last_modified_at = during
    ours_later.last_modified_at = by_hand.last_modified_at = after
    session.flush()
    session.expire_all()

    found = {ra.id: changed for ra, changed in unflag_rooms_changed_by_hotel(session)}
    assert set(found) == {confirmed.id, cancelled.id}
    assert found[confirmed.id] == ['hotel_confirmation_number']
    assert 'cancellation_confirmation_number' in found[cancelled.id]
    assert confirmed.last_modified_at == during   # a dry run

    unflag_rooms_changed_by_hotel(session, commit=True)
    assert confirmed.last_modified_at <= export.exported_at and cancelled.last_modified_at <= export.exported_at
    assert {ra.last_modified_at for ra in (also_ours, ours_later, by_hand)} == {during, after}
    # The other catch-up does not put the flag back.
    assert flag_rooms_changed_since_export(session) == []


def test_timeline_counts_only_changes_the_hotel_has_yet_to_see(session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel)
    notes, unflagged, roommates, edited = [
        make_assignment(session, make_attendee(session), inventory=inv, check_in=N[1], check_out=N[3])
        for _ in range(4)]
    export = store_export_file(session, hotel, b'x', 'f.csv', 'text/csv', source='admin')
    session.query(Tracking).filter(Tracking.fk_id.in_([ra.id for ra in (notes, unflagged, roommates, edited)])).delete(
        synchronize_session=False)
    when = export.exported_at + timedelta(hours=1)
    later, earlier = 'datetime.datetime(2026, 1, 2, 3, 4, 6, tzinfo=<UTC>)', 'datetime.datetime(2026, 1, 2, 3, 4)'

    # Not for the hotel: a field it never gets, its own upload, and the catch-up clearing a flag.
    _track(session, notes, when, data="admin_notes=''' -> 'called''")
    _track(session, notes, when, data="hotel_confirmation_number='None -> 'H1''")
    _track(session, unflagged, when, data=f"last_modified_at='{later} -> {earlier}'")
    # For the hotel: a roommate change is a stamp alone.
    _track(session, roommates, when, data=f"last_modified_at='{earlier} -> {later}'")
    _track(session, edited, when)

    gap = hotel_activity_timeline(session, hotel.id)[0]
    assert gap['kind'] == 'changes' and gap['count'] == 2
    rows = changed_rooms_between(session, hotel.id, export.exported_at, None, exclude_imports=True)
    assert {row['assignment_id']: [f for f, _, _ in row['changes']] for row in rows} == {
        roommates.id: ['roommates or guest details'], edited.id: ['special_requests']}
