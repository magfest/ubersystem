"""Builders for the hotel lottery admin's export/import surfaces.

The CSV/XLSX/ZIP handlers in uber.site_sections.hotel_lottery_admin stay
as thin decorated routes; this module owns the row/workbook construction
underneath them:

  * booking_dict - the canonical per-RoomAssignment booking shape,
    shared by the JSON `HotelLookup.export_room_bookings` API and the
    spreadsheet export below.
  * booking_columns / booking_row / booking_export_data - the per-hotel
    booking spreadsheet layout (also the layout the back-import accepts),
    derived from booking_dict.
  * resolve_lottery_hotel - the hotel-identifier resolution chain the
    portal-facing API endpoints share (vault reference, name, slug, UUID).
  * derive_sync_status / compute_export_tracking - the per-booking and
    per-hotel export/import bookkeeping shown on the tracking page.
  * write_interchange_export - the legacy survey-interchange CSV.
  * write_hotel_inventory_xlsx - per-hotel occupancy-by-night grid.
  * build_waitlist_xlsx - the one-sheet-per-hotel waitlist demand
    workbook.
"""
import csv
import os
import re
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from io import BytesIO, StringIO

import pycountry
import xlsxwriter
from pytz import UTC
from sqlalchemy import and_, func, or_

from uber.config import c
from uber.custom_tags import datetime_local_filter
from uber.models import Attendee, LotteryApplication
from uber.models.hotel import (HotelExportLog, HotelRoomInventory,
                               LotteryHotel, LotteryRoomType, RoomAssignment)


# CSV/XLSX export + CSV import used by the export-tracking modal. The
# column layout is the canonical booking_dict shape (minus the fields
# noted below), so the JSON `HotelLookup.export_room_bookings` API and
# a hotel that prefers spreadsheets to API calls see the same field
# names for the same data.
#
# Credit-card vault tokens are deliberately omitted on export and
# actively refused on import - the rest of the system treats them as
# PCI-sensitive, so they never leave the database in a spreadsheet
# and we won't accept new ones from one either.

BOOKING_BASE_COLS = [
    'assignment_id', 'lottery_application_id', 'parent_assignment_id',
    'confirmation_num', 'assignment_reason', 'status',
    'hotel', 'room_type', 'suite_type',
    'check_in_date', 'check_out_date',
    'hotel_confirmation_number', 'cancellation_confirmation_number',
    'room_number',
    'legal_first_name', 'legal_last_name', 'cellphone', 'email',
    'address1', 'address2', 'city', 'region', 'zip_code', 'country',
    'wants_ada', 'ada_requests', 'special_requests',
    'last_modified_at', 'cc_captured_at', 'cc_last_four',
]
BOOKING_GUEST_FIELDS = [
    'legal_first_name', 'legal_last_name', 'cellphone', 'email',
]
BOOKING_MAX_GUESTS = 4


def booking_columns():
    cols = list(BOOKING_BASE_COLS)
    for i in range(1, BOOKING_MAX_GUESTS + 1):
        for f in BOOKING_GUEST_FIELDS:
            cols.append(f'guest{i}_{f}')
    return cols


def booking_dict(ra, app):
    """Canonical serialization of one RoomAssignment (plus its source
    LotteryApplication) - the single booking shape behind both the JSON
    `HotelLookup.export_room_bookings` API and the per-hotel booking
    spreadsheet (booking_row derives its cells from this dict).

    Key naming follows BOOKING_BASE_COLS. The alias keys the API used
    to double-emit are gone: `room_id` (use `assignment_id`),
    `hotel_cancellation_number` (use `cancellation_confirmation_number`),
    `last_modified` (use `last_modified_at`), and `assigned_hotel` /
    `assigned_hotel_id` / `assigned_room_type` / `assigned_suite_type` /
    `assigned_check_in_date` / `assigned_check_out_date` are now
    `hotel` / `hotel_id` / `room_type` / `suite_type` / `check_in_date`
    / `check_out_date`.

    `last_modified_at` is the hotel-facing modification timestamp with a
    fallback to the row's generic `last_updated` audit column when it's
    unset - of the two computations that previously coexisted (the API's
    `last_modified` alias had the fallback; the spreadsheet's
    `last_modified_at` didn't), the fallback version wins so
    changed-since filtering still works on rows that predate the
    hotel-facing column.

    `guests` is everyone sleeping in the room except the booker (who has
    their own top-level fields), built from `effective_occupants` - the
    managed occupants list when set, else booker + group members. The
    API previously read the raw `occupants` relationship and
    under-reported untouched group bookings. `num_occupants` is the
    booker plus those guests.

    Dates and datetimes are serialized to ISO 8601 strings (or None) -
    JSON needs strings anyway, and without this xlsxwriter treats date
    objects as numeric serial values, which Excel displays as bare
    integers that look like opaque IDs.
    """
    def iso(v):
        return v.isoformat() if v else None

    inv = ra.inventory
    hotel = inv.hotel if inv else None
    # Room/suite type labels via the model's display_name (the linked
    # type's name, falling back to the inventory block's own name).
    type_label = inv.display_name if inv else None
    room_type = None if not inv or inv.is_suite else type_label
    suite_type = type_label if inv and inv.is_suite else None

    # The booker: prefer the application's attendee, but fall back to the
    # assignment's own attendee - manually-granted and partition rooms have
    # no lottery application, and their guest names must still export.
    attendee = (app.attendee if app else None) or ra.attendee

    guests = []
    for a in ra.effective_occupants:
        if a.id == ra.attendee_id:
            continue
        # Keep legacy field names but read from the attendee-level
        # hotel-name override (legal/first/last fallback chain).
        guests.append({
            'legal_first_name': a.effective_hotel_first_name,
            'legal_last_name': a.effective_hotel_last_name,
            'cellphone': a.cellphone,
            'email': a.email,
        })

    return {
        # Stable per-room id (distinct from the application's
        # response_id) so the receiver can reconcile rows across exports.
        'assignment_id': ra.id,
        'lottery_application_id': ra.lottery_application_id,
        'parent_assignment_id': ra.parent_assignment_id,
        'confirmation_num': app.confirmation_num if app else None,
        'response_id': app.response_id if app else None,
        'assignment_reason': (ra.assignment_reason_label
                              if hasattr(ra, 'assignment_reason_label')
                              else ra.assignment_reason),
        'status': ra.status_label if hasattr(ra, 'status_label') else ra.status,
        'hotel': hotel.name if hotel else '',
        'hotel_id': str(inv.hotel_id) if inv and inv.hotel_id else None,
        'room_type': room_type,
        'suite_type': suite_type,
        'check_in_date': iso(ra.assigned_check_in_date),
        'check_out_date': iso(ra.assigned_check_out_date),
        'num_nights': (
            (ra.assigned_check_out_date - ra.assigned_check_in_date).days
            if ra.assigned_check_in_date and ra.assigned_check_out_date else None),
        'hotel_confirmation_number': ra.hotel_confirmation_number,
        'cancellation_confirmation_number': ra.cancellation_confirmation_number,
        'room_number': ra.room_number,
        # Legal-name fields live on the attendee (hotel_first_name /
        # hotel_last_name with the legal/first/last fallback chain).
        'legal_first_name': (attendee.effective_hotel_first_name if attendee else ''),
        'legal_last_name': (attendee.effective_hotel_last_name if attendee else ''),
        'cellphone': ((app.cellphone if app else '')
                      or (attendee.cellphone if attendee else '')),
        'email': ((app.email if app else '')
                  or (attendee.email if attendee else '')),
        'address1': ra.address1,
        'address2': ra.address2,
        'city': ra.city,
        'region': ra.region,
        'zip_code': ra.zip_code,
        'country': ra.country,
        'wants_ada': app.wants_ada if app else False,
        'ada_requests': app.ada_requests if app else '',
        'special_requests': ra.special_requests,
        # Loyalty / rewards program number (e.g. Hilton Honors).
        'hotel_rewards_number':
            ra.hotel_rewards_number or (app.hotel_rewards_number if app else ''),
        # Billing: True = self-pay (guest's card guarantees the room,
        # "individual pays own"); False = on the master bill ("room & tax").
        'require_cc': ra.require_cc,
        # Occupancy: booker plus the additional guests below.
        'num_occupants': 1 + len(guests),
        'guests': guests,
        # Vault card token plus stored card metadata (NOT the full PAN,
        # which stays in the vault behind cc_token). Lets a rooming list
        # fill CC Type / Exp Date / cardholder without a vault
        # round-trip. JSON-only: booking_row drops everything here
        # except cc_last_four / cc_captured_at.
        'cc_token': ra.cc_token,
        'cc_last_four': ra.cc_last_four,
        'cc_card_type': ra.cc_card_type,
        'cc_card_expiry': ra.cc_card_expiry,
        'cc_card_holder': ra.cc_card_holder,
        'last_modified_at': iso(ra.last_modified_at or ra.last_updated),
        'cc_captured_at': iso(ra.cc_captured_at),
    }


def booking_row(ra, app, d=None):
    """Base (no-guest) spreadsheet column values for one RoomAssignment,
    in BOOKING_BASE_COLS order, derived from booking_dict (pass `d` to
    reuse an already-built dict).

    The card fields the JSON payload carries (cc_token, cc_card_type,
    cc_card_expiry, cc_card_holder) are deliberately dropped here - the
    rest of the system treats the vault token as PCI-sensitive, so it
    never leaves the database in a spreadsheet - as are the JSON-only
    identifiers the spreadsheet has no column for (response_id,
    hotel_id, num_nights, num_occupants, hotel_rewards_number,
    require_cc, guests - guest columns are appended separately by
    booking_export_data).
    """
    d = d if d is not None else booking_dict(ra, app)
    return [
        d['assignment_id'], d['lottery_application_id'] or '',
        d['parent_assignment_id'] or '',
        d['confirmation_num'] or '',
        d['assignment_reason'],
        d['status'],
        d['hotel'] or '', d['room_type'] or '', d['suite_type'] or '',
        d['check_in_date'] or '',
        d['check_out_date'] or '',
        d['hotel_confirmation_number'] or '',
        d['cancellation_confirmation_number'] or '',
        d['room_number'] or '',
        d['legal_first_name'] or '',
        d['legal_last_name'] or '',
        d['cellphone'] or '',
        d['email'] or '',
        d['address1'] or '', d['address2'] or '', d['city'] or '',
        d['region'] or '', d['zip_code'] or '', d['country'] or '',
        ('yes' if d['wants_ada'] else ''),
        d['ada_requests'] or '',
        d['special_requests'] or '',
        d['last_modified_at'] or '',
        d['cc_captured_at'] or '',
        d['cc_last_four'] or '',
    ]


def booking_export_data(session, hotel_id):
    """Common query + per-row construction for both CSV and XLSX export.

    Source is now RoomAssignment - one row per assigned room.
    Connectors get their own line; their `parent_assignment_id`
    column points at the parent (suite) assignment's id so the hotel
    can group them.
    """
    hotel = session.query(LotteryHotel).filter_by(id=hotel_id).first()
    if not hotel:
        return None, []

    from uber.hotel.queries import live_assignments_for_hotel
    assignments = (live_assignments_for_hotel(session, hotel.id)
                   .order_by(RoomAssignment.parent_assignment_id.asc().nullsfirst(),
                             RoomAssignment.created.asc())
                   .all())

    # Bulk-fetch each assignment's source LotteryApplication.
    app_ids = {ra.lottery_application_id for ra in assignments
               if ra.lottery_application_id}
    apps_by_id = {}
    if app_ids:
        for app in session.query(LotteryApplication).filter(
                LotteryApplication.id.in_(app_ids)).all():
            apps_by_id[app.id] = app

    rows = []
    for ra in assignments:
        app = apps_by_id.get(ra.lottery_application_id)
        d = booking_dict(ra, app)
        row = booking_row(ra, app, d)

        # Guest columns: everyone sleeping in the room except the
        # booker, who already has their own columns - booking_dict's
        # `guests` list (built from effective_occupants, which handles
        # the occupants-vs-group-members fallback).
        guests = d['guests']
        for i in range(BOOKING_MAX_GUESTS):
            if i < len(guests):
                g = guests[i]
                row += [g['legal_first_name'] or '',
                        g['legal_last_name'] or '',
                        g['cellphone'] or '',
                        g['email'] or '']
            else:
                row += ['', '', '', '']
        rows.append(row)

    return hotel, rows


def resolve_lottery_hotel(session, ident):
    """Resolve the hotel identifier a portal/API caller sent.

    Returns a (hotel, inventory_ids) tuple expressing both cases:

      * A PCI Vault reference (stored per inventory block as
        `vault_reference`) maps to specific blocks: inventory_ids is
        their id list, and hotel is the owning LotteryHotel when every
        matched block belongs to the same one (else None). This is how
        the hotel portal scopes itself.
      * Otherwise a LotteryHotel resolved by export_name/display-name
        exact match, then by slugified name (tolerating casing, spacing
        and punctuation), then by UUID: (hotel, None) - the caller
        decides which of the hotel's inventory to include.
      * (None, None) when nothing matches.

    Slug matching uses uber.utils.slugify, equivalent to the previous
    inline `[^a-z0-9]+ -> '-'` regex for ASCII input; for non-ASCII it
    transliterates accented characters instead of dashing them, which
    only ever widens what matches.
    """
    if not ident:
        return None, None

    inv_rows = session.query(HotelRoomInventory).filter_by(vault_reference=ident).all()
    if inv_rows:
        hotel = None
        hotel_ids = {str(inv.hotel_id) for inv in inv_rows if inv.hotel_id}
        if len(hotel_ids) == 1:
            hotel = session.query(LotteryHotel).get(hotel_ids.pop())
        return hotel, [str(inv.id) for inv in inv_rows]

    hotel = session.query(LotteryHotel).filter(
        or_(LotteryHotel.export_name == ident,
            LotteryHotel.name == ident)).first()
    if not hotel:
        from uber.utils import slugify
        target = slugify(str(ident))
        if target:
            for h in session.query(LotteryHotel).all():
                if target in (slugify(h.export_name), slugify(h.name)):
                    hotel = h
                    break
    if not hotel:
        try:
            uuid.UUID(str(ident))
        except ValueError:
            pass
        else:
            hotel = session.query(LotteryHotel).get(ident)
    return hotel, None


def derive_sync_status(ra, last_export):
    """Sync status for one booking relative to the hotel's last export:

      - in_sync:               exported, has confirmation #, not modified since
      - pending_export:        exported but modified after the export ran
      - awaiting_confirmation: exported, no hotel confirmation # yet
      - never_exported:        no export log for this hotel yet
    """
    has_conf = bool(ra.hotel_confirmation_number and ra.hotel_confirmation_number.strip())
    modified = ra.last_modified_at
    if not last_export:
        return 'never_exported'
    elif modified and modified > last_export.exported_at:
        return 'pending_export'
    elif not has_conf:
        return 'awaiting_confirmation'
    return 'in_sync'


def render_booking_export(session, hotel_id, fmt='csv'):
    """The per-hotel booking file as bytes.

    Returns (hotel, filename, content_type, data). The routes serve
    these bytes AND retain them (store_export_file), so the file a
    hotel received can be reproduced later.
    """
    hotel, rows = booking_export_data(session, hotel_id)
    if hotel is None:
        return None, '', '', b''

    stamp = datetime.now(UTC).strftime('%Y%m%d_%H%M')
    base = f"{(hotel.export_name or hotel.name or 'hotel')}_bookings_{stamp}"
    columns = booking_columns()

    if fmt == 'xlsx':
        buffer = BytesIO()
        with xlsxwriter.Workbook(buffer, {'in_memory': True}) as workbook:
            sheet = workbook.add_worksheet()
            for col, header in enumerate(columns):
                sheet.write(0, col, header)
            for r, row in enumerate(rows, start=1):
                for col, value in enumerate(row):
                    sheet.write(r, col, value)
        return (hotel, f'{base}.xlsx',
                'application/vnd.openxmlformats-officedocument.'
                'spreadsheetml.sheet', buffer.getvalue())

    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    for row in rows:
        writer.writerow(row)
    return hotel, f'{base}.csv', 'text/csv', buffer.getvalue().encode('utf-8')


def store_export_file(session, hotel, raw, filename, content_type, *,
                      source, exported_by='', record_count=0, notes=''):
    """Persist an export's bytes and log it. Returns the HotelExportLog."""
    stored_name = f"hotel_export_{uuid.uuid4().hex}_{filename}"[:200]
    os.makedirs(c.UPLOADED_FILES_DIR, exist_ok=True)
    filepath = os.path.join(c.UPLOADED_FILES_DIR, stored_name)
    with open(filepath, 'wb') as f:
        f.write(raw)

    entry = HotelExportLog(
        hotel_id=hotel.id if hotel else None,
        export_type='room_export',
        record_count=record_count,
        exported_by=exported_by or '',
        notes=notes,
        source=source,
        filename=filename,
        content_type=content_type,
        filepath=filepath,
        size=len(raw),
    )
    session.add(entry)
    session.flush()
    return entry


def _hotel_assignment_ids(session, hotel_id):
    """Every RoomAssignment id ever tied to this hotel's blocks - the
    keys the Tracking feed records changes against."""
    from uber.models.hotel import HotelRoomInventory

    inv_ids = [str(i) for i, in session.query(HotelRoomInventory.id)
               .filter_by(hotel_id=hotel_id)]
    if not inv_ids:
        return []
    return [str(i) for i, in session.query(RoomAssignment.id)
            .filter(RoomAssignment.inventory_id.in_(inv_ids))]


# Tracking.data is "attr='old -> new', attr2='old -> new'"; pull the
# field names and their before/after out of it.
_CHANGE_RE = re.compile(r"(\w+)='(.*?) -> (.*?)'(?:, |$)")
# Bookkeeping columns every edit touches - noise in a change report.
_CHANGE_NOISE = {'last_modified_at', 'last_updated', 'last_synced'}
_DATETIME_REPR_RE = re.compile(
    r"datetime\.datetime\((\d+), (\d+), (\d+), (\d+), (\d+)[^)]*\)")
_DATE_REPR_RE = re.compile(r"datetime\.date\((\d+), (\d+), (\d+)\)")


def _clean_change_value(value):
    """Tracking stores Python reprs; show the value itself."""
    value = (value or '').strip()
    value = _DATETIME_REPR_RE.sub(
        lambda m: '{}-{:0>2}-{:0>2} {:0>2}:{:0>2}'.format(*m.groups()), value)
    value = _DATE_REPR_RE.sub(
        lambda m: '{}-{:0>2}-{:0>2}'.format(*m.groups()), value)
    if len(value) > 1 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1]
    return '(empty)' if value in ('None', '') else value


def import_windows(session, hotel_id):
    """(from, to) for every import's applied writes at this hotel.

    Timeline gap rows subtract these so a hotel's own confirmation
    numbers aren't also counted as changes we made - those belong to
    the import row that caused them.
    """
    from uber.models.hotel import HotelImportFile

    windows = []
    for entry in session.query(HotelImportFile).filter_by(hotel_id=hotel_id):
        start, end = entry.applied_from, entry.applied_to
        if not start and entry.uploaded_at:
            # Imported before the window was recorded: bound a guess.
            start = entry.uploaded_at
            end = entry.uploaded_at + timedelta(minutes=1)
        if start and end:
            windows.append((start, end))
    return windows


def _outside_import_windows(query, column, windows):
    for start, end in windows:
        query = query.filter(~and_(column > start, column <= end))
    return query


def changed_rooms_between(session, hotel_id, start, end,
                          exclude_imports=False):
    """Room-level changes recorded for this hotel between two moments.

    Reads the admin change feed (Tracking) rather than the assignments
    themselves, so it reports what changed while a hotel was holding a
    given export - including for rooms that have since changed again.
    `exclude_imports` drops the changes an import file applied, which is
    what the timeline's gap rows want: those are reported on the import
    row itself.

    Returns [{'assignment', 'number', 'guest', 'when', 'who', 'action',
    'changes': [(field, old, new)]}], newest first.
    """
    from uber.models.tracking import Tracking

    ids = _hotel_assignment_ids(session, hotel_id)
    if not ids:
        return []

    q = session.query(Tracking).filter(
        Tracking.model == 'RoomAssignment', Tracking.fk_id.in_(ids))
    if start:
        q = q.filter(Tracking.when > start)
    if end:
        q = q.filter(Tracking.when <= end)
    if exclude_imports:
        q = _outside_import_windows(q, Tracking.when,
                                    import_windows(session, hotel_id))

    entries = q.order_by(Tracking.when.desc()).all()
    if not entries:
        return []

    rooms = {str(ra.id): ra for ra in session.query(RoomAssignment)
             .filter(RoomAssignment.id.in_({e.fk_id for e in entries}))}

    out = []
    for entry in entries:
        ra = rooms.get(str(entry.fk_id))
        out.append({
            'assignment': ra,
            'assignment_id': str(entry.fk_id),
            'number': (ra.room_number if ra else '') or '',
            'guest': (ra.attendee.full_name if ra and ra.attendee else ''),
            'when': entry.when,
            'who': entry.who,
            'action': entry.action_label,
            'changes': [
                (field, _clean_change_value(old), _clean_change_value(new))
                for field, old, new in _CHANGE_RE.findall(entry.data or '')
                if field not in _CHANGE_NOISE],
        })
    return out


def import_changes(session, import_file):
    """The room changes one uploaded file caused.

    Scoped by the window the import recorded around its own writes
    (HotelImportFile.applied_from/applied_to) - the change feed has no
    link back to the file. Files imported before that window was
    recorded fall back to the upload timestamp onward, which can also
    catch an unrelated edit made in the same moment.
    """
    start = import_file.applied_from or import_file.uploaded_at
    end = import_file.applied_to
    if not end and import_file.applied_from is None:
        # Legacy row: bound the guess to a minute after the upload.
        end = (import_file.uploaded_at + timedelta(minutes=1)
               if import_file.uploaded_at else None)
    return changed_rooms_between(session, import_file.hotel_id, start, end,
                                 exclude_imports=False)


def read_stored_file(entry, max_rows=None):
    """A retained export/import file as (columns, rows, error).

    Handles the spreadsheet formats through the shared parser and the
    JSON payload the API export retains. Rows come back as dicts keyed
    by column name so one viewer renders any of them.
    """
    from uber.hotel.imports import parse_spreadsheet

    path = getattr(entry, 'filepath', '')
    if not path or not os.path.exists(path):
        return [], [], 'That file is no longer retained.'
    with open(path, 'rb') as f:
        raw = f.read()

    name = (entry.filename or '').lower()
    if name.endswith('.json') or 'json' in (entry.content_type or ''):
        import json
        try:
            payload = json.loads(raw.decode('utf-8'))
        except Exception as e:
            return [], [], f'Could not parse file: {e}'
        rows = payload.get('bookings', payload) if isinstance(payload, dict) \
            else payload
        if not isinstance(rows, list):
            return [], [], 'That file has no tabular rows.'
        columns = list(rows[0].keys()) if rows else []
        rows = [{k: ('' if v is None else str(v)) for k, v in row.items()}
                for row in rows]
        return columns, rows[:max_rows] if max_rows else rows, None

    columns, rows, error = parse_spreadsheet(raw, entry.filename)
    return columns, (rows[:max_rows] if max_rows else rows), error


def hotel_activity_timeline(session, hotel_id, limit=100):
    """Everything that touched this hotel, newest first.

    Merges exports we sent (dashboard downloads and API pulls, each
    with the retained file) and imports we received, then injects a
    'changes' row for each gap between consecutive events - how many
    distinct rooms changed while the hotel was working from the file it
    had at the time. The newest gap runs from the last event to now.
    """
    from uber.models.hotel import HotelImportFile
    from uber.models.tracking import Tracking

    events = []
    for log in (session.query(HotelExportLog)
                .filter(HotelExportLog.hotel_id == hotel_id,
                        HotelExportLog.export_type == 'room_export')
                .order_by(HotelExportLog.exported_at.desc()).limit(limit)):
        events.append({
            'kind': 'export', 'at': log.exported_at, 'entry': log,
            'source': log.source or 'admin',
            'count': log.record_count,
            'file_id': log.id if log.filepath else None,
            'filename': log.filename,
            'who': log.exported_by,
            'notes': log.notes,
        })

    for imp in (session.query(HotelImportFile)
                .filter(HotelImportFile.hotel_id == hotel_id)
                .order_by(HotelImportFile.uploaded_at.desc()).limit(limit)):
        events.append({
            'kind': 'import', 'at': imp.uploaded_at, 'entry': imp,
            'source': imp.source or 'admin',
            'count': imp.updated_count,
            'file_id': imp.id if imp.filepath else None,
            'filename': imp.filename,
            'who': imp.uploaded_by,
            'notes': imp.note,
        })

    events = sorted([e for e in events if e['at']],
                    key=lambda e: e['at'], reverse=True)

    ids = _hotel_assignment_ids(session, hotel_id)

    windows = import_windows(session, hotel_id)

    def rooms_changed(start, end):
        """Rooms WE changed in this gap - an import's own writes are
        reported on that import's row instead."""
        if not ids:
            return 0
        q = session.query(func.count(func.distinct(Tracking.fk_id))).filter(
            Tracking.model == 'RoomAssignment', Tracking.fk_id.in_(ids))
        if start:
            q = q.filter(Tracking.when > start)
        if end:
            q = q.filter(Tracking.when <= end)
        return _outside_import_windows(q, Tracking.when, windows).scalar() or 0

    # Walk newest-first, inserting the gap above each event.
    timeline = []
    newer_edge = None  # None = "now"
    for event in events:
        count = rooms_changed(event['at'], newer_edge)
        if count:
            timeline.append({
                'kind': 'changes', 'at': newer_edge, 'count': count,
                'start': event['at'], 'end': newer_edge,
            })
        timeline.append(event)
        newer_edge = event['at']
    return timeline


def compute_export_tracking(session):
    """Per-hotel export/import summary for the export-tracking page:
    last export/import log entries plus booking counts (total, missing a
    hotel confirmation number, and modified since the last export)."""
    hotels = []
    for hotel in session.query(LotteryHotel).filter_by(active=True).all():
        last_export = session.query(HotelExportLog).filter(
            HotelExportLog.hotel_id == hotel.id, HotelExportLog.export_type == 'room_export'
        ).order_by(HotelExportLog.exported_at.desc()).first()

        last_import = session.query(HotelExportLog).filter(
            HotelExportLog.hotel_id == hotel.id, HotelExportLog.export_type == 'confirmation_import'
        ).order_by(HotelExportLog.exported_at.desc()).first()

        from uber.hotel.queries import live_assignments_for_hotel
        bookings = live_assignments_for_hotel(session, hotel.id)

        total_bookings = bookings.count()
        missing_confirmation = bookings.filter(
            or_(RoomAssignment.hotel_confirmation_number == None,  # noqa: E711
                RoomAssignment.hotel_confirmation_number == '')
        ).count()

        dirty_count = 0
        if last_export:
            dirty_count = bookings.filter(
                RoomAssignment.last_modified_at > last_export.exported_at
            ).count()

        hotels.append({
            'hotel': hotel,
            'last_export': last_export,
            'last_import': last_import,
            'total_bookings': total_bookings,
            'missing_confirmation': missing_confirmation,
            'dirty_count': dirty_count,
        })
    return hotels


def write_interchange_export(out, session, staff_lottery=False):
    """Write the legacy survey-interchange CSV to `out` (the csv writer
    provided by the @csv_file handler)."""
    def print_dt(dt):
        if not dt:
            return ""

        if isinstance(dt, datetime):
            return dt.astimezone(c.EVENT_TIMEZONE).strftime('%m/%d/%Y %H:%M:%S')
        else:
            return dt.strftime('%m/%d/%Y')

    def print_bool(bool):
        return "TRUE" if bool else "FALSE"

    country_codes = {}
    for country in list(pycountry.countries):
        value = country.name if "Taiwan" not in country.name else "Taiwan"
        country_codes[value] = f"{country.alpha_2};{country.name}"

    header_row = []
    # Config data and IDs
    header_row.extend(["Lottery Close", "suite_cutoff", "year", "Response ID", "Confirmation Code",
                       "SessionID", "Survey ID", "entry_id", "dealer_group_id"])

    # Contact data
    header_row.extend(["is_staff", "email", "first_name:contact", "last_name:contact", "Title:contact",
                       "Company Name:contact", "street_address:contact", "apt_suite_office:contact",
                       "city:contact", "state:contact", "zip:contact", "country:contact", "phone:contact",
                       "Mobile Phone:contact"])

    # Entry metadata
    header_row.extend(["Time Started", "Date Submitted", "entry_confirmed", "Status", "edit_link", "I agree:agree",
                       "Comments", "payment_valid", "reg_conf_code", "entry_type", "Referer",
                       "User Agent", "IP Address", "Longitude", "Latitude", "Country", "City", "State/Region",
                       "Postal"])

    # Entry data
    header_row.extend(["group_conf", "group_email", "Yes:age_ack", "special_room", "ada_req_text",
                       "I agree, understand and will comply:suite_agree",
                       "desired_arrival", "latest_arrival", "desired_departure", "earliest_departure"])

    all_hotels = session.query(LotteryHotel).filter_by(active=True).order_by(LotteryHotel.name).all()
    all_room_types = session.query(LotteryRoomType).filter_by(is_suite=False, active=True).order_by(LotteryRoomType.name).all()
    all_suite_types = session.query(LotteryRoomType).filter_by(is_suite=True, active=True).order_by(LotteryRoomType.name).all()

    for hotel in all_hotels:
        header_row.append(f"{hotel.export_name or hotel.name}:hotel_pref")

    for rt in all_room_types:
        header_row.append(f"{rt.export_name or rt.name}:room_pref")

    for st in all_suite_types:
        header_row.append(f"{st.export_name or st.name}:suite_type")

    out.writerow(header_row)

    applications = session.query(LotteryApplication).join(LotteryApplication.attendee
                                                          ).filter(LotteryApplication.status != c.PROCESSED,
                                                                   Attendee.hotel_lottery_eligible == True)
    if staff_lottery:
        applications = applications.filter(LotteryApplication.is_staff_entry == True)
    else:
        applications = applications.filter(LotteryApplication.is_staff_entry == False)

    for app in applications:
        attendee = app.attendee
        row = []

        # Config data and IDs
        dealer_id = ''
        if app.attendee.is_dealer and app.attendee.group and app.attendee.group.status in c.DEALER_ACCEPTED_STATUSES:
            dealer_id = app.attendee.group.id
        # The model property additionally gates on the relevant lottery
        # window actually being open (None when closed).
        row.extend([datetime_local_filter(app.current_lottery_deadline), datetime_local_filter(c.HOTEL_LOTTERY_SUITE_CUTOFF),
                    c.EVENT_YEAR, app.response_id, app.confirmation_num, app.id, "RAMS_1", app.id, dealer_id])

        # Contact data
        base_cellphone = app.cellphone or app.attendee.cellphone
        # `staff_ribbon` is optional config - not every event defines one,
        # and c.<NAME> raises AttributeError rather than returning None for
        # an unconfigured ribbon, which used to 500 the whole export.
        staff_ribbon = getattr(c, 'STAFF_RIBBON', None)
        is_staff = (attendee.badge_type == c.STAFF_BADGE
                    or (staff_ribbon is not None
                        and staff_ribbon in attendee.ribbon_ints))
        row.extend([print_bool(is_staff),
                    attendee.email,
                    attendee.effective_hotel_first_name,
                    attendee.effective_hotel_last_name,
                    "", "", attendee.address1,
                    attendee.address2, attendee.city, attendee.region, attendee.zip_code,
                    country_codes.get(attendee.country, attendee.country),
                    ''.join(filter(str.isdigit, base_cellphone)) if base_cellphone else "", ""])

        # Entry metadata
        if app.entry_type:
            type_str = "I am entering as a roommate" if app.entry_type == c.GROUP_ENTRY else "I am requesting a room"
        else:
            type_str = "I am withdrawing from the lottery"
        row.extend([print_dt(app.entry_started), print_dt(app.last_submitted), print_bool(app.status == c.COMPLETE),
                    app.status_label, f"{c.URL_BASE}/hotel_lottery/index?attendee_id={app.attendee.id}",
                    print_bool(app.terms_accepted), app.admin_notes, "FALSE", attendee.id, type_str])
        if app.entry_metadata:
            row.extend([app.entry_metadata.get('referer'), app.entry_metadata.get('user_agent'), app.entry_metadata.get('ip_address')])
        else:
            row.extend(['', '', ''])
        row.extend(['', '', '', '', '', ''])

        # Entry data
        if app.parent_application:
            row.extend([app.parent_application.confirmation_num, app.parent_application.email,
                        '', '', '', '', '', '', '', ''])
        else:
            row.extend(['', '', print_bool(app.entry_form_completed)])

            entry_type_base = app.entry_type or c.ROOM_ENTRY
            if entry_type_base == c.ROOM_ENTRY:
                if app.wants_ada:
                    row.extend(['ADA Room', app.ada_requests, ''])
                else:
                    row.extend(['Standard Rooms with no Special Requests', '', ''])
            elif entry_type_base == c.SUITE_ENTRY:
                row.extend(['Hyatt Regency O\'Hare Suites', '', print_bool(app.suite_terms_accepted)])

            row.extend([print_dt(app.earliest_checkin_date), print_dt(app.latest_checkin_date),
                        print_dt(app.latest_checkout_date), print_dt(app.earliest_checkout_date)])

        if app.parent_application or not app.hotel_preference or (
                app.entry_type and app.entry_type == c.SUITE_ENTRY and app.room_opt_out):
            row.extend(['' for _ in range(len(all_hotels))])
        else:
            hotels_ranking = {}
            for index, item in enumerate(app.hotel_preference.split(','), start=1):
                hotels_ranking[item] = index

            for hotel in all_hotels:
                row.append(hotels_ranking.get(str(hotel.id), ''))

        if app.parent_application or not app.room_type_preference or (
                app.entry_type and app.entry_type == c.SUITE_ENTRY and app.room_opt_out):
            row.extend(['' for _ in range(len(all_room_types))])
        else:
            room_types_ranking = {}
            for index, item in enumerate(app.room_type_preference.split(','), start=1):
                room_types_ranking[item] = index

            for rt in all_room_types:
                row.append(room_types_ranking.get(str(rt.id), ''))

        if app.parent_application or not app.suite_type_preference or (
                app.entry_type and app.entry_type == c.ROOM_ENTRY):
            row.extend(['' for _ in range(len(all_suite_types))])
        else:
            suite_types_ranking = {}
            for index, item in enumerate(app.suite_type_preference.split(','), start=1):
                suite_types_ranking[item] = index

            for st in all_suite_types:
                row.append(suite_types_ranking.get(str(st.id), ''))

        out.writerow(row)


def write_hotel_inventory_xlsx(out, session, hotel_id):
    """Write the per-hotel occupancy-by-night grid (one row per active
    room/suite type, one column per occupied night) to `out` (the writer
    provided by the @xlsx_file handler). Writes nothing when the hotel
    has no live assignments.

    Occupancy is checkout-day EXCLUSIVE, matching every other occupancy
    computation in the system (a room checking out on the 15th is not
    occupied the night of the 15th), so these numbers reconcile with the
    admin inventory page and the audit."""
    from uber.hotel.queries import (live_assignments_for_hotel,
                                    occupancy_by_block_night)

    assignments = live_assignments_for_hotel(session, hotel_id).all()
    dated = [ra for ra in assignments
             if ra.assigned_check_in_date and ra.assigned_check_out_date]
    if not dated:
        return  # No dated assignments for this hotel
    earliest_check_in = min(ra.assigned_check_in_date for ra in dated)
    latest_check_out = max(ra.assigned_check_out_date for ra in dated)
    # Nights run [check_in, check_out): the checkout day itself is not an
    # occupied night, so it gets no column.
    date_range = [earliest_check_in + timedelta(days=x)
                  for x in range((latest_check_out - earliest_check_in).days)]

    hist = occupancy_by_block_night(dated)

    inv_by_room_type = defaultdict(list)
    inv_by_suite_type = defaultdict(list)
    for inv in session.query(HotelRoomInventory).filter_by(hotel_id=hotel_id).all():
        if inv.is_suite:
            inv_by_suite_type[str(inv.suite_type_id)].append(str(inv.id))
        else:
            inv_by_room_type[str(inv.room_type_id)].append(str(inv.id))

    def type_rows(type_query, inv_map):
        for rt in type_query.order_by(LotteryRoomType.name).all():
            inv_ids = inv_map.get(str(rt.id), [])
            yield [rt.name] + [
                sum(hist.get(iid, {}).get(d, 0) for iid in inv_ids)
                for d in date_range]

    rows = list(type_rows(
        session.query(LotteryRoomType).filter_by(is_suite=False, active=True),
        inv_by_room_type))
    if any(inv_by_suite_type.values()):
        rows.extend(type_rows(
            session.query(LotteryRoomType).filter_by(is_suite=True, active=True),
            inv_by_suite_type))

    header_row = [''] + [d.strftime("%A %-m/%-d") for d in date_range]
    out.writerows(header_row, rows)


def build_waitlist_xlsx(session):
    """Build the waitlist-demand workbook and return its bytes: one
    worksheet per hotel that has any waitlisted rooms.

    Sheet layout (within each hotel):

        row 1:  Hotel name (merged across the night columns)
        row 2:  blank spacer
        row 3:  header - ["Room type", <night 1>, <night 2>, ..., "Total"]
        row 4+: one row per room type at this hotel, with the count of
                distinct waitlisted RoomAssignment rows demanding each
                (type, night) pair.
        last:   "Total" row summing each column.

    Built manually (no `@xlsx_file` decorator) because that helper
    only hands out a single worksheet, and we need one sheet per
    hotel.
    """
    # Gather every waitlisted assignment.
    waitlisted = (session.query(RoomAssignment)
                  .filter(or_(
                      RoomAssignment.waitlisted_check_in_date.isnot(None),
                      RoomAssignment.waitlisted_check_out_date.isnot(None)))
                  .all())

    # Build a {hotel_id: {(type_name, type_is_suite): {night: count}}}
    # nested histogram, plus parallel lookup tables for hotel display
    # names. Multiple inventory blocks of the same room type at the same
    # hotel collapse together so the report shows room type by night
    # within a hotel: two Standard King blocks at the same hotel roll
    # into one "Standard King" row.
    per_hotel = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))  # hotel_id -> type_label -> night -> count
    hotel_name_by_id = {}
    nights_by_hotel = defaultdict(set)
    type_order_by_hotel = defaultdict(list)  # preserve first-seen order per hotel
    type_seen_by_hotel = defaultdict(set)

    for ra in waitlisted:
        # Demand population: rows that are actually waitlisted (the
        # requested window strictly extends the assigned one on at
        # least one end) - a row with waitlist dates that don't widen
        # anything contributes no demand and gets no type row.
        if not ra.is_waitlisted:
            continue
        inv = ra.inventory
        if not inv or not inv.hotel:
            continue
        hotel = inv.hotel
        hotel_id = str(hotel.id)
        hotel_name_by_id[hotel_id] = hotel.name or '(unnamed hotel)'

        # Resolve a stable label for this room type: the model's
        # display_name (the linked LotteryRoomType's name, falling
        # back to the inventory block's own name), suffixed for
        # suites.
        label = inv.display_name
        if inv.is_suite:
            label = (label or '') + ' (suite)'
        label = label or '(unnamed type)'

        if label not in type_seen_by_hotel[hotel_id]:
            type_seen_by_hotel[hotel_id].add(label)
            type_order_by_hotel[hotel_id].append(label)

        # Tick each (type, night) cell for the nights this assignment
        # is waiting on - the model's waitlisted_gap_nights walks the
        # front gap [wl_ci, assigned_check_in) plus the back gap
        # [assigned_check_out, wl_co).
        for night in ra.waitlisted_gap_nights:
            per_hotel[hotel_id][label][night] += 1
            nights_by_hotel[hotel_id].add(night)

    # Build the workbook. Sheet name has a 31-char cap and can't
    # contain :\/?*[]; truncate and substitute.
    def _safe_sheet_name(name, taken):
        cleaned = ''
        for ch in (name or 'Waitlist'):
            cleaned += ' ' if ch in ':\\/?*[]' else ch
        cleaned = cleaned.strip()[:31] or 'Waitlist'
        # Disambiguate collisions (rare - two hotels with names
        # truncating to the same 31 chars).
        base = cleaned
        n = 2
        while cleaned in taken:
            suffix = f' ({n})'
            cleaned = base[:31 - len(suffix)] + suffix
            n += 1
        taken.add(cleaned)
        return cleaned

    rawoutput = BytesIO()
    with xlsxwriter.Workbook(rawoutput, {'in_memory': True}) as workbook:
        title_fmt = workbook.add_format(
            {'bold': True, 'font_size': 14, 'align': 'left'})
        header_fmt = workbook.add_format(
            {'bold': True, 'bg_color': '#EFEFEF', 'border': 1})
        total_fmt = workbook.add_format(
            {'bold': True, 'top': 1})
        date_fmt = workbook.add_format(
            {'bold': True, 'bg_color': '#EFEFEF', 'border': 1,
             'align': 'center', 'num_format': 'ddd m/d'})
        cell_fmt = workbook.add_format({'align': 'center'})

        if not per_hotel:
            # Always produce at least one sheet so the file is
            # openable - an empty workbook would be confusing
            # output for an admin who clicked Export.
            ws = workbook.add_worksheet('Waitlist')
            ws.write(0, 0, 'No rooms are currently on the waitlist.',
                     title_fmt)
        else:
            taken_sheet_names = set()
            # Stable sheet order: alphabetical by hotel name so the
            # tab strip across the bottom of Excel is predictable.
            hotel_ids_sorted = sorted(
                per_hotel.keys(),
                key=lambda hid: hotel_name_by_id.get(hid, ''))

            for hotel_id in hotel_ids_sorted:
                hotel_name = hotel_name_by_id[hotel_id]
                sheet_name = _safe_sheet_name(
                    hotel_name, taken_sheet_names)
                ws = workbook.add_worksheet(sheet_name)

                nights_sorted = sorted(nights_by_hotel[hotel_id])
                types_sorted = type_order_by_hotel[hotel_id]
                n_cols = 1 + len(nights_sorted) + 1  # type + nights + total

                # Row 0: hotel title spanning the night columns.
                ws.merge_range(0, 0, 0, n_cols - 1,
                               f'{hotel_name} - Waitlist demand',
                               title_fmt)
                # Row 1: spacer (left blank).

                # Row 2: header.
                ws.write(2, 0, 'Room type', header_fmt)
                for i, night in enumerate(nights_sorted):
                    # Write as a real date so admins can re-sort
                    # or compute on it; format string handles
                    # display.
                    ws.write_datetime(
                        2, 1 + i, datetime.combine(night, datetime.min.time()),
                        date_fmt)
                ws.write(2, 1 + len(nights_sorted), 'Total', header_fmt)

                # Rows 3..N: one row per room type.
                col_totals = [0] * len(nights_sorted)
                for r_offset, label in enumerate(types_sorted):
                    row_idx = 3 + r_offset
                    ws.write(row_idx, 0, label)
                    row_total = 0
                    for c_offset, night in enumerate(nights_sorted):
                        count = per_hotel[hotel_id][label].get(night, 0)
                        if count:
                            ws.write_number(
                                row_idx, 1 + c_offset, count, cell_fmt)
                            row_total += count
                            col_totals[c_offset] += count
                        else:
                            # Leave blank rather than writing 0
                            # so the sparse cells visually
                            # disappear and the populated ones
                            # pop.
                            ws.write_blank(
                                row_idx, 1 + c_offset, None, cell_fmt)
                    ws.write_number(
                        row_idx, 1 + len(nights_sorted), row_total,
                        total_fmt)

                # Final row: per-night totals.
                total_row = 3 + len(types_sorted)
                ws.write(total_row, 0, 'Total', total_fmt)
                for c_offset, total in enumerate(col_totals):
                    ws.write_number(
                        total_row, 1 + c_offset, total, total_fmt)
                ws.write_number(
                    total_row, 1 + len(nights_sorted), sum(col_totals),
                    total_fmt)

                # Modest column widths so the sheet is readable
                # without manual resizing.
                ws.set_column(0, 0, 28)
                ws.set_column(1, len(nights_sorted), 11)
                ws.set_column(1 + len(nights_sorted),
                              1 + len(nights_sorted), 8)
                ws.freeze_panes(3, 1)

    return rawoutput.getvalue()
