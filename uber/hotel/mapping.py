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
from datetime import datetime

from uber.config import c

log = logging.getLogger(__name__)

# Match-only targets carry no value onto the booking; they narrow which
# booking a row refers to.
TARGET_FIELDS = [
    {'key': 'match.ignore', 'label': 'Ignore this column', 'kind': 'text'},
    {'key': 'match.email', 'label': 'Match on: email', 'kind': 'text'},
    {'key': 'match.first_name', 'label': 'Match on: first name', 'kind': 'text'},
    {'key': 'match.last_name', 'label': 'Match on: last name', 'kind': 'text'},
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
        'other_pay_description': 'match.ignore',
    },
}


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


def apply_maps(row, template):
    """One source row as {target_key: value}, with enum names and date
    formats resolved."""
    if template is None:
        return dict(row)

    enum_map = template.enum_map or {}
    format_map = template.format_map or {}
    mapped = {}

    for source_key, target_key in (template.column_map or {}).items():
        if not target_key or target_key == 'match.ignore':
            continue
        raw_value = row.get(source_key, '')
        target = TARGETS_BY_KEY.get(target_key, {})
        kind = target.get('kind', 'text')

        if kind == 'date':
            parsed = _parse_date(raw_value, format_map.get(target_key, ''))
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
    """(assignments, status) for one mapped row.

    status is 'matched' for exactly one candidate, 'ambiguous' for several,
    and 'unmatched' for none. Precedence runs from the most reliable key
    down: an acknowledgement number we already recorded identifies a booking
    outright, then email, then name, each narrowed by room type and check-in
    date when the row carries them.
    """
    from uber.models import Attendee, LotteryApplication
    from uber.models.hotel import HotelRoomInventory, RoomAssignment

    def _scoped(query):
        if hotel_id:
            query = query.join(
                HotelRoomInventory,
                HotelRoomInventory.id == RoomAssignment.inventory_id).filter(
                HotelRoomInventory.hotel_id == hotel_id)
        return query

    confirmation = mapped.get('assignment.hotel_confirmation_number', '').strip()
    if confirmation:
        exact = _scoped(session.query(RoomAssignment).filter(
            RoomAssignment.hotel_confirmation_number == confirmation)).all()
        if len(exact) == 1:
            return exact, 'matched'
        if len(exact) > 1:
            return exact, 'ambiguous'

    email = (mapped.get('attendee.email') or mapped.get('match.email') or '').strip()
    candidates = []
    if email:
        candidates = _scoped(
            session.query(RoomAssignment)
            .join(Attendee, Attendee.id == RoomAssignment.attendee_id)
            .filter(RoomAssignment.is_live, Attendee.email.ilike(email))).all()

    if not candidates:
        first = (mapped.get('attendee.hotel_first_name')
                 or mapped.get('match.first_name') or '').strip()
        last = (mapped.get('attendee.hotel_last_name')
                or mapped.get('match.last_name') or '').strip()
        if first and last:
            candidates = _scoped(
                session.query(RoomAssignment)
                .join(Attendee, Attendee.id == RoomAssignment.attendee_id)
                .filter(RoomAssignment.is_live,
                        Attendee.first_name.ilike(first),
                        Attendee.last_name.ilike(last))).all()

    if not candidates:
        return [], 'unmatched'

    candidates = _narrow(candidates, mapped)
    if len(candidates) == 1:
        return candidates, 'matched'
    return candidates, 'ambiguous'


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


def diff_row(ra, mapped):
    """[{key, label, imported, current, changed}] for the writable fields this
    row carries. Compared case-insensitively on trimmed text so cosmetic
    differences do not read as changes."""
    out = []
    for key in WRITABLE_KEYS:
        if key not in mapped:
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
        setattr(target, attr, parsed)
    elif kind == 'enum:payment_type':
        if value and value not in c.HOTEL_PAYMENT_TYPES:
            return False, f'Unknown payment type: {value}'
        setattr(target, attr, value or c.DEFAULT_HOTEL_PAYMENT_TYPE)
    else:
        setattr(target, attr, value)

    session.add(target)
    session.flush()
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
        assignments, status = match_row(session, mapped, hotel_id=hotel_id)
        rows.append({
            'index': index,
            'source': source,
            'mapped': mapped,
            'status': status,
            'assignment_ids': [str(ra.id) for ra in assignments],
        })
    return rows, None


def counts_for(rows):
    counts = {'matched': 0, 'ambiguous': 0, 'unmatched': 0}
    for row in rows:
        counts[row['status']] = counts.get(row['status'], 0) + 1
    return counts
