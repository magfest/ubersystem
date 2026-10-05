"""Every hotel export and import that includes a room leaves a Tracking
row on it (c.HOTEL_EXPORT / c.HOTEL_IMPORT), so the application history
shows them in order with the room's own edits. Those rows are markers,
not changes, so the hotel timeline's change counts leave them out.
"""

from datetime import datetime, timedelta, timezone

import uber.site_sections.hotel_lottery_admin as hla
from uber.config import c
from uber.hotel.exports import (booking_export_data, changed_rooms_between,
                                hotel_activity_timeline, record_hotel_transfer,
                                store_export_file)
from uber.hotel.imports import (apply_cancellation_rows, apply_confirmation_rows,
                                import_confirmation_file)
from uber.models import initialize_db
from uber.models.tracking import Tracking

from tests.hotel.factories import (N, make_application, make_assignment,
                                   make_attendee, make_hotel, make_inventory)


def _setup(session, **room):
    hotel = make_hotel(session, name='Gaylord National')
    inv = make_inventory(session, hotel, quantity=5)
    me = make_attendee(session)
    app = make_application(session, me, status=c.AWARDED)
    ra = make_assignment(session, me, inv, check_in=N[1], check_out=N[3],
                         status=c.SECURED, lottery_application_id=app.id, **room)
    return hotel, app, ra


def _clear_tracking(session, *ids):
    """Drop the automatic 'created' rows the factories leave behind (the
    tracking listener queues them for the next flush, so flush first)."""
    session.flush()
    session.query(Tracking).filter(Tracking.fk_id.in_(ids)).delete(synchronize_session=False)
    session.flush()


def _rows(session, ra, action):
    return session.query(Tracking).filter_by(
        model='RoomAssignment', fk_id=ra.id, action=action).all()


def test_spreadsheet_export_marks_each_room(session, no_cherrypy_session):
    hotel, app, ra = _setup(session)
    other = make_assignment(session, make_attendee(session), make_inventory(
        session, make_hotel(session), quantity=5), check_in=N[1], check_out=N[3])
    _, rows = booking_export_data(session, hotel.id)

    store_export_file(session, hotel, b'x', 'gaylord_bookings.csv', 'text/csv',
                      source='admin', record_count=len(rows), exported_by='Hotel Admin',
                      assignment_ids=[row[0] for row in rows])

    (mark,) = _rows(session, ra, c.HOTEL_EXPORT)
    assert mark.data == 'Sent to Gaylord National: gaylord_bookings.csv'
    assert mark.who == 'Hotel Admin'
    assert not _rows(session, other, c.HOTEL_EXPORT), 'not in this file'


def test_import_marks_matched_rooms_even_when_nothing_changes(session, no_cherrypy_session, tmp_path, monkeypatch):
    monkeypatch.setattr(c, 'UPLOADED_FILES_DIR', str(tmp_path), raising=False)
    hotel, app, ra = _setup(session, hotel_confirmation_number='GN-1')
    raw = f'confirmation_num,hotel_confirmation_number\n{app.confirmation_num},GN-1\n'.encode()

    result = import_confirmation_file(session, raw, 'gaylord_confs.csv', hotel=hotel,
                                      source='admin', uploaded_by='Hotel Admin')

    assert result['updated'] == 0 and result['unchanged'] == 1
    (mark,) = _rows(session, ra, c.HOTEL_IMPORT)
    assert mark.data == 'Hotel import gaylord_confs.csv: confirmation # GN-1'
    assert mark.who == 'Hotel Admin'
    assert mark.links == f'hotel_import_file({result["record"].id})'


def test_shared_row_appliers_mark_rooms_only_when_applying(session, no_cherrypy_session):
    hotel, app, ra = _setup(session)
    row = {'confirmation_num': app.confirmation_num, 'hotel_confirmation_number': 'GN-2'}

    apply_confirmation_rows(session, [row], apply_changes=False, filename='preview.csv')
    assert not _rows(session, ra, c.HOTEL_IMPORT), 'a preview leaves no history'

    apply_confirmation_rows(session, [row], apply_changes=True, filename='confs.csv')
    apply_cancellation_rows(session, [{'confirmation_num': app.confirmation_num,
                                       'cancellation_confirmation_number': 'CX-9'}],
                            apply_changes=True, filename='cancels.csv')

    notes = sorted(m.data for m in _rows(session, ra, c.HOTEL_IMPORT))
    assert notes == ['Hotel import cancels.csv: cancellation # CX-9',
                     'Hotel import confs.csv: confirmation # GN-2']
    assert ra.status == c.CANCELLED


def test_history_page_merges_room_rows_in_time_order(session, no_cherrypy_session):
    initialize_db()
    hotel, app, ra = _setup(session)
    _clear_tracking(session, app.id, ra.id)
    t0 = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
    session.add(Tracking(model='LotteryApplication', fk_id=app.id, action=c.UPDATED,
                         data="status='x -> y'", when=t0))
    session.add(Tracking(model='RoomAssignment', fk_id=ra.id, action=c.UPDATED,
                         data="assigned_check_out_date='a -> b'", when=t0 + timedelta(days=2)))
    session.flush()
    record_hotel_transfer(session, c.HOTEL_EXPORT, [ra.id], 'Sent to Gaylord National: f.csv')
    session.query(Tracking).filter_by(action=c.HOTEL_EXPORT, fk_id=ra.id).update(
        {'when': t0 + timedelta(days=1)}, synchronize_session=False)

    func = hla.Root.history
    while hasattr(func, '__wrapped__'):
        func = func.__wrapped__
    ctx = func(hla.Root(), session, id=app.id)

    assert [(t.model, t.action) for t in ctx['changes']] == [
        ('LotteryApplication', c.UPDATED),
        ('RoomAssignment', c.HOTEL_EXPORT),
        ('RoomAssignment', c.UPDATED)]
    assert ctx['rooms'][ra.id] == ra


def test_marker_rows_are_not_counted_as_changes(session, no_cherrypy_session):
    hotel, app, ra = _setup(session)
    _clear_tracking(session, ra.id)
    export = store_export_file(session, hotel, b'x', 'f.csv', 'text/csv',
                               source='admin', record_count=1, assignment_ids=[ra.id])
    record_hotel_transfer(session, c.HOTEL_IMPORT, [ra.id], 'Hotel import g.csv: no numbers')

    assert changed_rooms_between(session, hotel.id, None, None) == []
    gaps = [row for row in hotel_activity_timeline(session, hotel.id) if row['kind'] == 'changes']
    assert gaps == [], 'export/import markers are not room changes'
    assert export.record_count == 1
