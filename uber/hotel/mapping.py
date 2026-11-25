"""Reading a hotel's room-list format into our bookings.

Hotels send spreadsheets in whatever shape their system produces, usually
without any ubersystem identifier. An ImportMappingTemplate says which source
column feeds which booking field, how that hotel spells our enum values, and
what date formats it uses. A template is matched to an upload by its header
signature when the admin does not pick one explicitly.

Nothing here writes on its own except `sync_value`, which is the single point
where an imported value becomes a booking value.

Transaction convention matches the rest of the package: flush, never commit.
"""

import logging
import os
import re
from datetime import datetime

from sqlalchemy import and_, or_

from uber.config import c
from uber.hotel.service import hotel_sourced_changes, queue_confirmation_updated_email

log = logging.getLogger(__name__)

# Match-only targets carry no value onto the booking; they narrow which
# booking a row refers to.
TARGET_FIELDS = [
    {'key': 'match.ignore', 'label': 'Ignore this column', 'kind': 'text'},
    {'key': 'match.email', 'label': 'Match on: email', 'kind': 'text'},
    {'key': 'match.first_name', 'label': 'Match on: first name', 'kind': 'text'},
    {'key': 'match.last_name', 'label': 'Match on: last name', 'kind': 'text'},
    {'key': 'match.pattern', 'label': 'Match on: combined name (pattern)', 'kind': 'pattern'},
    {'key': 'match.room_type', 'label': 'Match on: room type', 'kind': 'enum:room_type'},
    {'key': 'assignment.hotel_confirmation_number',
     'label': 'Acknowledgement / confirmation number', 'kind': 'text'},
    {'key': 'assignment.cancellation_confirmation_number',
     'label': 'Cancellation number', 'kind': 'text'},
    {'key': 'assignment.assigned_check_in_date', 'label': 'Check-in date', 'kind': 'date'},
    {'key': 'assignment.assigned_check_out_date', 'label': 'Check-out date', 'kind': 'date'},
    {'key': 'assignment.room_number', 'label': 'Room number', 'kind': 'text'},
    {'key': 'assignment.special_requests', 'label': 'Special requests', 'kind': 'text'},
    {'key': 'assignment.hotel_rewards_number', 'label': 'Rewards number', 'kind': 'text'},
    {'key': 'attendee.email', 'label': 'Guest email', 'kind': 'text'},
    {'key': 'attendee.hotel_first_name', 'label': 'Guest first name', 'kind': 'text'},
    {'key': 'attendee.hotel_last_name', 'label': 'Guest last name', 'kind': 'text'},
    {'key': 'assignment.payment_type', 'label': 'Payment type', 'kind': 'enum:payment_type'},
]

TARGETS_BY_KEY = {field['key']: field for field in TARGET_FIELDS}

# Fields a sync button may write. Match-only keys are excluded by construction.
WRITABLE_KEYS = [f['key'] for f in TARGET_FIELDS
                 if f['key'].startswith(('assignment.', 'attendee.'))]

# The format in the sample room list MAGFest receives. Keys are what
# parse_spreadsheet's _normalize produces, which keeps the punctuation:
# "Check-In" becomes "check-in", not "check_in".
BUILTIN_ROOM_LIST = {
    'name': 'Standard room list',
    'description': 'Last/First name, email, dates, room type, acknowledgement '
                   'and external confirmation numbers.',
    'sheet_name': 'Room List',
    'header_row': 1,
    'column_map': {
        'last_name': 'attendee.hotel_last_name',
        'first_name': 'attendee.hotel_first_name',
        'email': 'attendee.email',
        'check-in': 'assignment.assigned_check_in_date',
        'checkout': 'assignment.assigned_check_out_date',
        'room_type': 'match.room_type',
        'attendee_type': 'match.ignore',
        'acknowledgement_number': 'assignment.hotel_confirmation_number',
        # Hotel-internal; we do not track it.
        'ext._confirmation_number': 'match.ignore',
        # Payment types are config keys, so the enum map is a source-string
        # to config-key lookup each event fills in for its hotels.
        'other_pay_description': 'assignment.payment_type',
    },
}

# How many parsed rows are frozen onto a HotelImportFile as JSONB. Larger
# files re-read the retained file from disk (see full_parsed_rows).
STORED_ROW_CAP = 500


def signature_for(fieldnames):
    """A stable fingerprint of a file's headers, for matching a template."""
    return ','.join(sorted(name for name in fieldnames if name))


def _signature_overlap(left, right):
    a = set(filter(None, (left or '').split(',')))
    b = set(filter(None, (right or '').split(',')))
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def detect_template(session, fieldnames, hotel=None, template_id=None):
    """Which template to read this upload with.

    Explicit choice, then the hotel's default, then the best signature match
    above a threshold, then the built-in format. None means fall back to the
    older confirmation-number-keyed import, so an unrecognized file behaves
    exactly as it did before templates existed.
    """
    from uber.models.hotel import ImportMappingTemplate

    if template_id:
        chosen = session.query(ImportMappingTemplate).filter_by(id=template_id).first()
        if chosen:
            return chosen
    if hotel is not None and hotel.default_import_template_id:
        default = session.query(ImportMappingTemplate).filter_by(
            id=hotel.default_import_template_id).first()
        if default:
            return default

    signature = signature_for(fieldnames)
    best, best_score = None, 0.0
    for template in session.query(ImportMappingTemplate).filter_by(active=True).all():
        score = _signature_overlap(signature, template.source_signature)
        if score > best_score:
            best, best_score = template, score
    if best is not None and best_score >= 0.6:
        return best

    if _signature_overlap(signature, signature_for(BUILTIN_ROOM_LIST['column_map'])) >= 0.6:
        return builtin_template()
    return None


def detect_upload_template(session, raw, filename, hotel=None, template_id=None):
    """The template to read an upload with, chosen before its rows are read.

    An explicit choice or the hotel's default is honored without sniffing
    headers, so its own sheet_name and header_row govern the parse from the
    start. Signature detection reads the active sheet first, then retries
    every other sheet of an XLSX workbook, since the recognizable sheet is
    not always the first one; a retry match is only accepted when the
    template names the sheet it matched on, so the eventual parse reads the
    same headers that were detected.
    """
    from uber.hotel.imports import parse_spreadsheet, workbook_sheet_names

    # With no fieldnames the signature paths score zero, so this returns
    # only an explicit choice or the hotel's default.
    template = detect_template(session, [], hotel=hotel, template_id=template_id)
    if template is not None:
        return template

    fieldnames, _rows, error = parse_spreadsheet(raw, filename)
    if not error:
        template = detect_template(session, fieldnames)
        if template is not None:
            return template

    for sheet in workbook_sheet_names(raw, filename):
        fieldnames, _rows, error = parse_spreadsheet(raw, filename, sheet_name=sheet)
        if error or not fieldnames:
            continue
        template = detect_template(session, fieldnames)
        if template is not None and (template.sheet_name or '') == sheet:
            return template
    return None


class _PlainTemplate:
    """A format shaped like an ImportMappingTemplate row without being one.

    Used for the built-in layout and for previewing unsaved edits, so neither
    can end up in a session and be mistaken for a saved format.
    """
    id = None

    def __init__(self, spec):
        self.name = spec.get('name', '')
        self.description = spec.get('description', '')
        self.sheet_name = spec.get('sheet_name', '')
        self.header_row = spec.get('header_row', 1) or 1
        self.column_map = dict(spec.get('column_map') or {})
        self.enum_map = dict(spec.get('enum_map') or {})
        self.format_map = dict(spec.get('format_map') or {})
        self.source_signature = signature_for(self.column_map)
        self.active = True


def builtin_template():
    return _PlainTemplate(BUILTIN_ROOM_LIST)


def draft_template(spec):
    """An unsaved format, for previewing what the editor currently shows."""
    return _PlainTemplate(dict(spec, name=spec.get('name') or '(preview)'))


def parse_with_template(raw, filename, template):
    """(fieldnames, rows, error) honoring the template's sheet and header."""
    from uber.hotel.imports import parse_spreadsheet

    if template is None:
        return parse_spreadsheet(raw, filename)
    return parse_spreadsheet(raw, filename,
                             sheet_name=template.sheet_name or None,
                             header_row=template.header_row or 1)


def _parse_date(value, fmt=''):
    """A source date as a date, or None. Tries the template's format first;
    XLSX datetime cells already arrive ISO, so the format only matters for
    CSV exports."""
    value = (value or '').strip()
    if not value:
        return None
    if fmt:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    from uber.hotel.imports import parse_iso_date
    return parse_iso_date(value)


# What a combined-column pattern such as "%last_name, %first_name" may name.
PATTERN_FIELDS = {
    'first_name': 'match.first_name',
    'last_name': 'match.last_name',
    'email': 'match.email',
    'ignore': None,
}
_PATTERN_TOKEN = re.compile(r'%([a-z_]+)')


def split_pattern(value, pattern):
    """{match key: text} for one cell read with a pattern like
    "%last_name, %first_name"; empty when the cell does not fit it.
    Whitespace around the literal separators is not significant."""
    value = str(value or '').strip()
    pattern = (pattern or '').strip()
    if not value or not pattern:
        return {}

    regex, names, pos = '', [], 0
    for token in _PATTERN_TOKEN.finditer(pattern):
        literal = pattern[pos:token.start()].strip()
        if literal:
            regex += r'\s*' + re.escape(literal) + r'\s*'
        elif names:
            regex += r'\s+'
        regex += '(.+?)'
        names.append(token.group(1))
        pos = token.end()
    if not names:
        return {}
    trailing = pattern[pos:].strip()
    if trailing:
        regex += r'\s*' + re.escape(trailing)

    found = re.fullmatch(regex, value, re.DOTALL)
    if not found:
        return {}
    out = {}
    for name, text in zip(names, found.groups()):
        key = PATTERN_FIELDS.get(name)
        if key and text.strip():
            out[key] = text.strip()
    return out


def single_value(value):
    """A repeated form field arrives as a list; keep its first real choice."""
    if isinstance(value, (list, tuple)):
        return next((v for v in value if v and v != 'match.ignore'), '')
    return value


def clean_column_map(column_map):
    # Formats saved from a file with repeated headings stored list targets.
    return {source: single_value(target)
            for source, target in (column_map or {}).items()}


def apply_maps(row, template):
    """One source row as {target_key: value}, with enum names and date
    formats resolved."""
    if template is None:
        return dict(row)

    enum_map = template.enum_map or {}
    format_map = template.format_map or {}
    mapped = {}

    for source_key, target_key in clean_column_map(template.column_map).items():
        if not target_key or target_key == 'match.ignore':
            continue
        raw_value = row.get(source_key, '')
        target = TARGETS_BY_KEY.get(target_key, {})
        kind = target.get('kind', 'text')

        if kind == 'pattern':
            mapped.update(split_pattern(
                raw_value, single_value(format_map.get(target_key, ''))))
        elif kind == 'date':
            parsed = _parse_date(raw_value, single_value(format_map.get(target_key, '')))
            mapped[target_key] = parsed.isoformat() if parsed else ''
        elif kind.startswith('enum:'):
            lookup = {str(k).strip().lower(): v
                      for k, v in (enum_map.get(target_key) or {}).items()}
            mapped[target_key] = lookup.get(str(raw_value).strip().lower(),
                                            str(raw_value).strip())
        else:
            mapped[target_key] = str(raw_value or '').strip()

    return mapped


def match_row(session, mapped, hotel_id=None):
    """(assignments, status) for one mapped row; see match_row_detail."""
    return match_row_detail(session, mapped, hotel_id=hotel_id)[:2]


def match_row_detail(session, mapped, hotel_id=None):
    """(assignments, status, via) for one mapped row.

    status is 'matched' for exactly one candidate, 'ambiguous' for several,
    and 'unmatched' for none. Precedence runs from the most reliable key
    down: an acknowledgement number we already recorded identifies a booking
    outright, then email, then name, each narrowed by room type and check-in
    date when the row carries them. The room's leader is tried before its
    roommates; via is 'roommate' when only a roommate fit, so callers know
    the row's guest details are not the leader's.
    """
    from uber.models import Attendee
    from uber.models.hotel import HotelRoomInventory, RoomAssignment, room_assignment_occupant

    def _scoped(query):
        if hotel_id:
            query = query.join(
                HotelRoomInventory,
                HotelRoomInventory.id == RoomAssignment.inventory_id).filter(
                HotelRoomInventory.hotel_id == hotel_id)
        return query

    def _people(roommates):
        query = session.query(RoomAssignment)
        if roommates:
            return query.join(
                room_assignment_occupant,
                room_assignment_occupant.c.room_assignment_id == RoomAssignment.id).join(
                Attendee, Attendee.id == room_assignment_occupant.c.attendee_id).filter(
                Attendee.id != RoomAssignment.attendee_id)
        return query.join(Attendee, Attendee.id == RoomAssignment.attendee_id)

    def _by_name(first, last, roommates):
        return _scoped(_people(roommates).filter(RoomAssignment.is_live, or_(
            and_(Attendee.first_name.ilike(first),
                 Attendee.last_name.ilike(last)),
            and_(Attendee.hotel_first_name.ilike(first),
                 Attendee.hotel_last_name.ilike(last))))).all()

    confirmation = mapped.get('assignment.hotel_confirmation_number', '').strip()
    if confirmation:
        exact = _scoped(session.query(RoomAssignment).filter(
            RoomAssignment.hotel_confirmation_number == confirmation)).all()
        if len(exact) == 1:
            return exact, 'matched', ''
        if len(exact) > 1:
            return exact, 'ambiguous', ''

    email = (mapped.get('attendee.email') or mapped.get('match.email') or '').strip()
    first = (mapped.get('attendee.hotel_first_name')
             or mapped.get('match.first_name') or '').strip()
    last = (mapped.get('attendee.hotel_last_name')
            or mapped.get('match.last_name') or '').strip()

    candidates, via = [], ''
    for roommates in (False, True):
        if email:
            candidates = _scoped(_people(roommates).filter(
                RoomAssignment.is_live, Attendee.email.ilike(email))).all()
        if not candidates and first and last:
            candidates = _by_name(first, last, roommates)
            # Hotels often append a middle name or initial to the first name.
            if not candidates and ' ' in first:
                candidates = _by_name(first.split()[0], last, roommates)
        if candidates:
            via = 'roommate' if roommates else ''
            break

    if not candidates:
        return [], 'unmatched', ''

    candidates = _narrow(candidates, mapped)
    if len(candidates) == 1:
        return candidates, 'matched', via
    return candidates, 'ambiguous', via


def search_bookings(session, text, hotel_id=None, limit=20):
    """Live bookings whose guest name, email, or confirmation number contains
    the text, for pointing an import row at a booking by hand."""
    from uber.models import Attendee
    from uber.models.hotel import HotelRoomInventory, RoomAssignment

    words = (text or '').split()
    if not words:
        return []
    query = (session.query(RoomAssignment)
             .join(Attendee, Attendee.id == RoomAssignment.attendee_id)
             .filter(RoomAssignment.is_live))
    if hotel_id:
        query = query.join(
            HotelRoomInventory,
            HotelRoomInventory.id == RoomAssignment.inventory_id).filter(
            HotelRoomInventory.hotel_id == hotel_id)
    for word in words:
        like = '%' + word.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        query = query.filter(or_(
            Attendee.first_name.ilike(like), Attendee.last_name.ilike(like),
            Attendee.hotel_first_name.ilike(like), Attendee.hotel_last_name.ilike(like),
            Attendee.email.ilike(like),
            RoomAssignment.hotel_confirmation_number.ilike(like)))
    return query.order_by(Attendee.last_name, Attendee.first_name).limit(limit).all()


def assign_row(session, record, row_index, ra):
    """Point one row of an upload at a booking, whatever it matched before.

    Stamps the row's acknowledgement number onto the chosen booking so later
    uploads match it outright, and takes that number back off a booking the
    row was wrongly matched to. Returns False when the row is gone.
    """
    from uber.models.hotel import RoomAssignment

    rows = list(record.parsed_rows or [])
    row = next((r for r in rows if str(r.get('index')) == str(row_index)), None)
    stored = row is not None
    if row is None:
        # Rows past the storage cap live only in the retained file.
        row = next((r for r in full_parsed_rows(session, record)
                    if str(r.get('index')) == str(row_index)), None)
    if row is None:
        return False

    confirmation = (row.get('mapped') or {}).get(
        'assignment.hotel_confirmation_number', '').strip()
    previous_ids = [i for i in row.get('assignment_ids', []) if i != str(ra.id)]
    if confirmation:
        with hotel_sourced_changes(session):
            if row.get('status') == 'matched' and previous_ids:
                for old in session.query(RoomAssignment).filter(
                        RoomAssignment.id.in_(previous_ids),
                        RoomAssignment.hotel_confirmation_number == confirmation):
                    old.hotel_confirmation_number = ''
                    session.add(old)
            previous = ra.hotel_confirmation_number or ''
            ra.hotel_confirmation_number = confirmation
            session.add(ra)
        queue_confirmation_updated_email(session, ra, previous)

    previous_status = row.get('status')
    row['assignment_ids'] = [str(ra.id)]
    row['status'] = 'matched'
    # Keep guest fields off the leader when the row names one of the roommates.
    row['via'] = 'roommate' if _names_a_roommate(ra, row.get('mapped') or {}) else ''
    if stored:
        record.parsed_rows = rows
    # Adjusted incrementally rather than recounted, because the stored
    # rows may be only a slice of the file.
    if previous_status != 'matched':
        record.matched_count += 1
        if previous_status == 'ambiguous':
            record.ambiguous_count = max(0, record.ambiguous_count - 1)
        elif previous_status == 'unmatched':
            record.unmatched_count = max(0, record.unmatched_count - 1)
    session.add(record)
    return True


def _names_a_roommate(ra, mapped):
    first = (mapped.get('attendee.hotel_first_name')
             or mapped.get('match.first_name') or '').strip().casefold()
    last = (mapped.get('attendee.hotel_last_name')
            or mapped.get('match.last_name') or '').strip().casefold()
    email = (mapped.get('attendee.email') or mapped.get('match.email') or '').strip().casefold()

    def fits(attendee):
        if email and (attendee.email or '').casefold() == email:
            return True
        return bool(first and last) and (first, last) in (
            ((attendee.first_name or '').casefold(), (attendee.last_name or '').casefold()),
            ((attendee.hotel_first_name or '').casefold(), (attendee.hotel_last_name or '').casefold()))

    if ra.attendee and fits(ra.attendee):
        return False
    return any(fits(a) for a in ra.occupants if a.id != ra.attendee_id)


def _narrow(candidates, mapped):
    """Apply the weaker signals only while they leave something behind."""
    room_type = (mapped.get('match.room_type') or '').strip().lower()
    if room_type and len(candidates) > 1:
        narrowed = [ra for ra in candidates
                    if ra.inventory and room_type in (
                        (ra.inventory.display_name or '').lower())]
        if narrowed:
            candidates = narrowed

    check_in = (mapped.get('assignment.assigned_check_in_date') or '').strip()
    if check_in and len(candidates) > 1:
        narrowed = [ra for ra in candidates
                    if ra.assigned_check_in_date
                    and ra.assigned_check_in_date.isoformat() == check_in]
        if narrowed:
            candidates = narrowed

    return candidates


def _current_value(ra, key):
    scope, _, attr = key.partition('.')
    target = ra if scope == 'assignment' else (ra.attendee if ra else None)
    if target is None:
        return ''
    value = getattr(target, attr, '')
    if value is None:
        return ''
    return value.isoformat() if hasattr(value, 'isoformat') else str(value)


def diff_row(ra, mapped, via=''):
    """[{key, label, imported, current, changed}] for the writable fields this
    row carries. Compared case-insensitively on trimmed text so cosmetic
    differences do not read as changes. A row matched through a roommate
    describes that roommate, so its guest fields never apply to the leader."""
    out = []
    for key in WRITABLE_KEYS:
        if key not in mapped:
            continue
        if via == 'roommate' and key.startswith('attendee.'):
            continue
        imported = (mapped.get(key) or '').strip()
        if not imported:
            continue
        current = _current_value(ra, key) if ra is not None else ''
        out.append({
            'key': key,
            'label': TARGETS_BY_KEY[key]['label'],
            'imported': imported,
            'current': current,
            'changed': imported.casefold() != (current or '').strip().casefold(),
        })
    return out


def sync_value(session, ra, key, value):
    """Write one imported value onto a booking. The only writer here, so
    every sync button and the auto-apply path share its coercion."""
    if key not in WRITABLE_KEYS:
        return False, 'That field cannot be synced.'

    scope, _, attr = key.partition('.')
    target = ra if scope == 'assignment' else ra.attendee
    if target is None:
        return False, 'That booking has no attendee to update.'

    kind = TARGETS_BY_KEY[key]['kind']
    value = (value or '').strip()

    if kind == 'date':
        parsed = _parse_date(value)
        if value and not parsed:
            return False, f'Could not read {value} as a date.'
        value = parsed
    elif kind == 'enum:payment_type':
        if value and value not in c.HOTEL_PAYMENT_TYPES:
            return False, f'Unknown payment type: {value}'
        value = value or c.DEFAULT_HOTEL_PAYMENT_TYPE

    with hotel_sourced_changes(session):
        setattr(target, attr, value)
        session.add(target)
    return True, f'{TARGETS_BY_KEY[key]["label"]} updated.'


def build_rows(session, raw, filename, template, hotel_id=None):
    """Parse, map, and match a whole file.

    Returns (rows, error) where each row carries its source values, the
    mapped values, and how it matched. This is what gets frozen onto the
    HotelImportFile: templates stay editable, so a half-reviewed file must
    keep saying what it said when it was uploaded.
    """
    fieldnames, source_rows, error = parse_with_template(raw, filename, template)
    if error:
        return [], error

    rows = []
    for index, source in enumerate(source_rows):
        mapped = apply_maps(source, template)
        assignments, status, via = match_row_detail(session, mapped, hotel_id=hotel_id)
        rows.append({
            'index': index,
            'source': source,
            'mapped': mapped,
            'status': status,
            'via': via,
            'assignment_ids': [str(ra.id) for ra in assignments],
        })
    return rows, None


def enum_source_values(rows, template, limit=50):
    """{target key: distinct source spellings} for the list-backed columns, so
    the editor can ask what each one means."""
    out = {}
    for source_key, target_key in clean_column_map(template.column_map).items():
        kind = TARGETS_BY_KEY.get(target_key, {}).get('kind', '')
        if not kind.startswith('enum:'):
            continue
        seen = out.setdefault(target_key, [])
        for row in rows:
            value = str(row.get('source', {}).get(source_key, '') or '').strip()
            if value and value not in seen and len(seen) < limit:
                seen.append(value)
    return {key: sorted(values) for key, values in out.items() if values}


def enum_choices(session):
    """{target key: [{value, label}]} of what each list-backed field accepts."""
    from uber.models.hotel import HotelRoomInventory

    room_names = sorted({inv.display_name for inv in session.query(HotelRoomInventory)
                         if inv.display_name}, key=str.casefold)
    return {
        'match.room_type': [{'value': name, 'label': name} for name in room_names],
        'assignment.payment_type': [{'value': key, 'label': f'{label} ({key})'}
                                    for key, label in c.HOTEL_PAYMENT_TYPE_OPTS],
    }


def counts_for(rows):
    counts = {'matched': 0, 'ambiguous': 0, 'unmatched': 0}
    for row in rows:
        counts[row['status']] = counts.get(row['status'], 0) + 1
    return counts


def prepare_import_review(session, record, raw, filename, template_id='',
                          template=None):
    """Freeze a template-mapped read of an upload onto its HotelImportFile.

    Frozen rather than re-parsed on view because templates stay editable: an
    admin fixing a template mid-review must not silently change what a
    half-reviewed file is recorded as having said. The comparison against
    live bookings is still recomputed on every view, so a synced value stops
    showing as changed immediately. Storage is capped at STORED_ROW_CAP rows;
    the retained file on disk covers the rest (see full_parsed_rows).

    Returns a summary, or None when no template applies and the older
    confirmation-number import already handled the file.
    """
    if template is None:
        template = detect_upload_template(session, raw, filename,
                                          hotel=record.hotel,
                                          template_id=template_id or None)
    if template is None:
        _fieldnames, _rows, error = parse_with_template(raw, filename, None)
        if error:
            record.parse_error = error
            record.status = 'pending'
            session.add(record)
        return None

    rows, error = build_rows(
        session, raw, filename, template,
        hotel_id=record.hotel_id if record.hotel_id else None)
    if error:
        record.parse_error = error
        record.status = 'pending'
        session.add(record)
        return None

    counts = counts_for(rows)
    record.parsed_rows = rows[:STORED_ROW_CAP]
    record.parse_error = ''
    record.status = 'pending'
    record.template_id = getattr(template, 'id', None)
    record.matched_count = counts['matched']
    record.ambiguous_count = counts['ambiguous']
    record.unmatched_count = counts['unmatched']
    session.add(record)

    return {'total': len(rows), 'template_name': template.name, 'counts': counts}


def full_parsed_rows(session, record):
    """Every parsed row of an upload, re-read from the retained file on disk
    when the frozen JSONB was capped at STORED_ROW_CAP. Falls back to the
    stored slice when the file is gone or no longer readable."""
    stored = list(record.parsed_rows or [])
    total = ((record.matched_count or 0) + (record.ambiguous_count or 0)
             + (record.unmatched_count or 0))
    if len(stored) >= total:
        return stored
    if not record.filepath or not os.path.exists(record.filepath):
        return stored

    with open(record.filepath, 'rb') as f:
        raw = f.read()
    template = record.template if record.template_id else None
    if template is None:
        template = detect_upload_template(session, raw, record.filename,
                                          hotel=record.hotel)
    rows, error = build_rows(
        session, raw, record.filename, template,
        hotel_id=record.hotel_id if record.hotel_id else None)
    if error:
        return stored
    return rows
