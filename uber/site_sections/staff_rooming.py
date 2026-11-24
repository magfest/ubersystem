"""Staff Rooming admin - configures the per-date shift-compliance
requirements that gate staff hotel rooms.

Setup/teardown dates require staff with a RoomAssignment to have at least
one shift overlapping a configured time window. Core dates require a total
weighted-hour minimum across the whole con.

The page auto-populates with sensible defaults on first visit
"""

from datetime import date, datetime, time, timedelta

import json
import uuid

import cherrypy

from sqlalchemy import or_
from sqlalchemy.orm import lazyload, selectinload

from uber.config import c
from uber.decorators import ajax, ajax_gettable, all_renderable
from uber.errors import HTTPRedirect
from uber.hotel.audit import collect_issues, issue_identity
from uber.hotel.queries import (attendee_search_results, build_room_assignment_query,
                                clamp_page_size, occupant_stay_dates, paginate,
                                shared_room_eligible_query, staff_rooming_query)
from uber.hotel.service import (RoomAssignmentError, _held_nights, add_room_occupant,
                                apply_room_assignment_edits, cancel_room_occupant_invite,
                                partition_overages, remove_room_occupant,
                                set_occupant_stay_dates, set_room_leader)
from uber.models import (Attendee, Department, NightShiftRequirement,
                         RoomAssignment, Shift)
from uber.models.hotel import (HotelRoomInventory, InventoryPartition, InventoryPartitionBlock,
                               LotteryHotel, RoomAssignmentInvite)
from uber.shift_compliance import non_compliant_staffers
from uber.utils import check_csrf, redirect_with_params


def _redirect_back(return_url, fallback_url, message):
    """Send the user back to `return_url` with `?message=...` appended.

    redirect_with_params builds the final quoted URL (see its docstring
    for the HTTPRedirect footgun); this wrapper adds the safety gate:
    only same-section relative paths are allowed, because a
    client-supplied absolute URL (or protocol-relative //host) would be
    an open redirect.
    """
    target = return_url or fallback_url
    if target.startswith(('http://', 'https://', '//')) or target.startswith('/'):
        target = fallback_url
    raise HTTPRedirect(redirect_with_params(target, message=message))


# Fields the staffer_rooms modals may post.
INLINE_ROOM_FIELDS = ('partition_id', 'inventory_id',
                      'assigned_check_in_date', 'assigned_check_out_date')


# Fields the room_grid may also edit.
GRID_FIELDS = INLINE_ROOM_FIELDS + (
    'payment_type', 'assignment_reason', 'deposit_cutoff_date', 'hotel_confirmation_number',
    'cancellation_confirmation_number', 'room_number', 'special_requests', 'admin_notes',
    'occupant_message')

# How a hand-set source reads; matches RoomAssignment.source_label.
SOURCE_LABELS = {c.PARTITION_GRANT: 'Partition owner', c.MANUAL: 'Hotel admin'}


def _source_locked(ra):
    """A lottery room's source is its lottery run, and a connector's is its parent."""
    return bool(ra.lottery_run_id) or ra.assignment_reason == c.SUITE_CONNECTOR


def _find_staffer_room(session, id):
    """The room for an inline edit, or None; only rooms the staff rooming pages list qualify."""
    ra = session.query(RoomAssignment).get(id) if id else None
    if ra and ra.attendee and ra.attendee.badge_type in (c.STAFF_BADGE, c.CONTRACTOR_BADGE):
        return ra


def _staffer_room(session, id, return_url):
    ra = _find_staffer_room(session, id)
    if not ra:
        _redirect_back(return_url, 'staffer_rooms', 'Room not found.')
    return ra


def _staffer_rooms_query(session, billing='all', hotel_id='', search='', source='all'):
    """Live rooms whose booker is staff, filtered and ordered for the staff rooming lists."""
    # badge_types inner-joins Attendee, so the ordering below can sort on Attendee.last_name.
    q = build_room_assignment_query(
        session, status='live', hotel_id=hotel_id, search=search,
        badge_types=[c.STAFF_BADGE, c.CONTRACTOR_BADGE], search_roommates=True)

    if billing == 'self_pay':
        q = q.filter(RoomAssignment.require_cc)
    elif billing == 'master_bill':
        q = q.filter(~RoomAssignment.require_cc)
    elif billing == 'parking':
        q = q.filter(RoomAssignment.payment_type.in_(c.HOTEL_PAYMENT_TYPES_WITH_PARKING))

    # Same split as RoomAssignment.source_label.
    from_lottery = or_(RoomAssignment.lottery_run_id.isnot(None),
                       RoomAssignment.assignment_reason.in_([c.LOTTERY_AWARD, c.SUITE_CONNECTOR]))
    if source == 'crash_space':
        q = q.filter(RoomAssignment.shift_requirements_apply, ~from_lottery)
    elif source == 'lottery':
        q = q.filter(from_lottery)
    elif source == 'other':
        q = q.filter(~RoomAssignment.shift_requirements_apply, ~from_lottery)

    return q.order_by(RoomAssignment.assigned_check_in_date.asc().nullsfirst(),
                      Attendee.last_name.asc())


def _inventory_partitions_map(session):
    """{inventory_id: [partition_id, ...]} for the room pickers."""
    blocks = {}
    for pb in session.query(InventoryPartitionBlock).all():
        blocks.setdefault(str(pb.inventory_id), []).append(str(pb.partition_id))
    return blocks


def _iso(day):
    return day.isoformat() if day else ''


def _room_type_label(inv):
    return f"{inv.hotel.name if inv.hotel else '?'} - {inv.display_name}"


def _block_label(inv):
    return inv.name or _room_type_label(inv)


def _grid_row(ra):
    """One room as the room_grid page's JSON row."""
    inv, app = ra.inventory, ra.lottery_application
    return {
        'id': ra.id,
        'leader_id': ra.attendee_id,
        'leader_badge': ra.attendee.badge_type_label if ra.attendee else '',
        # Leader first, then by name.
        'occupants': [{'id': o.id, 'name': o.full_name, 'badge': o.badge_type_label} for o in sorted(
            ra.effective_occupants, key=lambda o: (o.id != ra.attendee_id, o.full_name.lower()))],
        'capacity': inv.capacity if inv else 0,
        'inventory_id': ra.inventory_id or '',
        'inventory_label': _block_label(inv) if inv else '',
        'room_type': _room_type_label(inv) if inv else '',
        'hotel_id': inv.hotel_id if inv else '',
        'partition_id': ra.partition_id or '',
        'check_in': _iso(ra.assigned_check_in_date),
        'check_out': _iso(ra.assigned_check_out_date),
        'status': ra.status_label,
        'live': ra.is_live,
        # The requested stay: what is still waitlisted, else what the lottery entry asked for.
        'requested_in': _iso(ra.waitlisted_check_in_date or (app.earliest_checkin_date if app else None)),
        'requested_out': _iso(ra.waitlisted_check_out_date or (app.latest_checkout_date if app else None)),
        'card': (' '.join(filter(None, [ra.cc_card_type, f'ending {ra.cc_last_four}' if ra.cc_last_four else '']))
                 or 'On file') if ra.cc_token else ('No card' if ra.require_cc else ''),
        'card_expiry': ra.cc_card_expiry or '',
        'has_card': bool(ra.cc_token),
        'deposit_cutoff_date': _iso(ra.deposit_cutoff_date),
        'hotel_confirmation_number': ra.hotel_confirmation_number or '',
        'cancellation_confirmation_number': ra.cancellation_confirmation_number or '',
        'physical_room': ra.physical_room.room_number if ra.physical_room_id and ra.physical_room else '',
        'room_number': ra.room_number or '',
        'special_requests': ra.special_requests or '',
        'admin_notes': ra.admin_notes or '',
        'occupant_message': ra.occupant_message or '',
        'app_id': app.id if app else '',
        'app_label': (app.confirmation_num or 'Open') if app else '',
        'app_notes': app.admin_notes if app else '',
        'payment_type': ra.payment_type,
        'assignment_reason': str(ra.assignment_reason),
        'source': ra.source_label,
        'source_locked': _source_locked(ra),
        'has_run': bool(ra.lottery_run_id),
        # What the search box matches besides the roommates' names.
        'haystack': ' '.join(filter(None, [
            ra.hotel_confirmation_number, ra.room_number,
            app.confirmation_num if app else '',
            *[o.email for o in ra.effective_occupants]])).lower(),
    }


def _unsavable_grid_fields(session, fields):
    """{field: problem} for staged values that cannot be saved."""
    bad = {}

    def check_date(field, label, required):
        value = fields.get(field)
        if value is None:
            return
        if not value:
            if required:
                bad[field] = f'{label} is empty.'
            return
        try:
            date.fromisoformat(value)
        except (TypeError, ValueError):
            bad[field] = f'{label} "{value}" is not a date.'

    def exists(model, id):
        # Pasted text reaches here, and a non-UUID would make the query itself fail.
        try:
            uuid.UUID(str(id))
        except ValueError:
            return False
        return session.query(model).get(id)

    check_date('assigned_check_in_date', 'Check-in', True)
    check_date('assigned_check_out_date', 'Check-out', True)
    check_date('deposit_cutoff_date', 'Deposit cutoff', False)

    choices = {
        'inventory_id': ('Inventory block', lambda v: exists(HotelRoomInventory, v)),
        'partition_id': ('Partition', lambda v: not v or exists(InventoryPartition, v)),
        'payment_type': ('Billing', lambda v: v in c.HOTEL_PAYMENT_TYPES),
        'assignment_reason': ('Source', lambda v: v in [str(r) for r, _ in c.HOTEL_ASSIGNMENT_REASON_OPTS]),
    }
    for field, (label, valid) in choices.items():
        if field in fields:
            value = fields[field]
            if not valid(value):
                bad[field] = f'{label} "{value}" is not one of the choices.' if value else f'{label} is empty.'
    return bad


def _apply_grid_edits(session, ra, edit):
    """Apply one room's staged room_grid edits, flushed but uncommitted.
    Returns (problems that stop them being saved, things worth a warning)."""
    problems, warnings = [], []

    def attempt(action, *args, **kwargs):
        try:
            return action(session, ra, *args, audit_prefix='Staff rooming admin', **kwargs)
        except RoomAssignmentError as e:
            problems.append(e.message)

    def fail(msg):
        raise RoomAssignmentError(msg)

    fields = {k: v for k, v in (edit.get('fields') or {}).items() if k in GRID_FIELDS}
    if 'assignment_reason' in fields and (
            _source_locked(ra) or fields['assignment_reason'] == str(c.SUITE_CONNECTOR)):
        problems.append('This room\'s source cannot be changed here.')
        del fields['assignment_reason']
    for field, problem in _unsavable_grid_fields(session, fields).items():
        problems.append(problem)
        del fields[field]
    if fields:
        try:
            apply_room_assignment_edits(session, ra, fields, audit_prefix='Staff rooming admin updated',
                                        fail=fail, check_capacity=False)
        except RoomAssignmentError as e:
            problems.append(e.message)
        session.flush()
        session.expire(ra, ['inventory'])

    # The outgoing leader can only leave once the new one is in and leading.
    leader = edit.get('leader')
    removals = list(edit.get('remove') or [])
    outgoing = [r for r in removals if r == ra.attendee_id]
    for attendee_id in [r for r in removals if r not in outgoing]:
        attempt(remove_room_occupant, attendee_id)
    for attendee_id in edit.get('add') or []:
        attempt(add_room_occupant, attendee_id)
    if leader and leader != ra.attendee_id:
        target = session.query(Attendee).get(leader)
        # A non-staff leader would drop the room off the staff rooming pages.
        if target and target.badge_type not in (c.STAFF_BADGE, c.CONTRACTOR_BADGE):
            problems.append(f'{target.full_name} is not staff, so cannot lead a staff room.')
        else:
            deadline_passed = ra.leader_change_blocked
            changed = attempt(set_room_leader, leader, extend_deadline=True)
            if changed and deadline_passed:
                warnings.append('The card deadline had passed, so it was extended to '
                                f'{ra.deposit_cutoff_date.strftime("%A, %B %-d")}.')
            if changed and changed[1]:
                warnings.append('Changing the leader resets the payment information on this room; '
                                'the new leader will need to secure it with their own card.')
    for attendee_id in outgoing:
        attempt(remove_room_occupant, attendee_id)
    return problems, warnings


# Room Issues findings that stop a grid save when an edit introduces them;
# the rest of that report's findings come through as warnings.
BLOCKING_AUDIT_KINDS = {'missing_dates', 'inverted_dates', 'too_short', 'out_of_range', 'empty_room',
                        'over_capacity', 'secured_without_payment', 'physical_double_booked'}
# Covered by the grid's own batch-wide capacity checks, or allowed: people can hold several rooms.
SKIPPED_AUDIT_KINDS = {'oversubscribed_partition', 'oversubscribed_inventory', 'partition_unconfigured',
                       'double_booked'}


def _audit_findings(session):
    """The Room Issues report as {(kind, target, wording): finding}."""
    room_issues, inventory_issues = collect_issues(session)
    return {(iss['kind'],) + issue_identity(iss) + (iss['label'],): iss
            for iss in room_issues + inventory_issues if iss['kind'] not in SKIPPED_AUDIT_KINDS}


def _grid_issue(severity, text, ra=None):
    return {'severity': severity, 'text': text, 'row_id': ra.id if ra else '',
            'room': ra.attendee.full_name if ra and ra.attendee else ''}


def _grid_issues(session, edits):
    """Apply every staged edit and list what is wrong with the result.
    Partition limits are judged across the whole batch, so rooms can trade
    places. Errors block saving; warnings do not. Returns (issues, rooms)."""
    issues, edited = [], []
    known = _audit_findings(session)
    for room_id, edit in edits.items():
        ra = _find_staffer_room(session, room_id)
        if not ra:
            issues.append(_grid_issue('error', 'A room in your edits no longer exists. Reload the page.'))
            continue
        held = _held_nights(ra)
        problems, warnings = _apply_grid_edits(session, ra, edit)
        issues.extend(_grid_issue('error', problem, ra) for problem in problems)
        issues.extend(_grid_issue('warning', warning, ra) for warning in warnings)
        edited.append((ra, held))
    session.flush()

    blocks = _inventory_partitions_map(session)
    # A block outside the partition is reported below, not also as an overage.
    issues.extend(_grid_issue('error', problem) for problem in partition_overages(session, [
        (ra, held) for ra, held in edited
        if not ra.partition_id or ra.partition_id in blocks.get(str(ra.inventory_id), [])]))
    stays = occupant_stay_dates(session, [ra.id for ra, _ in edited])
    for ra, _ in edited:
        session.refresh(ra)
        inv = ra.inventory
        if ra.partition_id and inv and ra.partition_id not in blocks.get(str(inv.id), []):
            issues.append(_grid_issue(
                'error', f'{inv.display_name} is not allocated to {ra.partition.name}.', ra))
        if not ra.is_live:
            issues.append(_grid_issue(
                'warning', 'A cancellation number cancels the room; it will leave this grid when saved.', ra))
            continue
        check_in, check_out = ra.assigned_check_in_date, ra.assigned_check_out_date
        if ra.deposit_cutoff_date and check_in and ra.deposit_cutoff_date > check_in:
            issues.append(_grid_issue('warning', 'The deposit cutoff is after check-in.', ra))
        # Crash space roommates can have their own dates, which must stay inside the room's.
        for occupant in ra.occupants:
            own_in, own_out = stays.get(ra.id, {}).get(occupant.id, (None, None))
            if (own_in and check_in and own_in < check_in) or (own_out and check_out and own_out > check_out) \
                    or (own_in and check_out and own_in >= check_out) or (own_out and check_in and own_out <= check_in):
                issues.append(_grid_issue(
                    'error', f"{occupant.full_name}'s own stay dates fall outside the room's dates.", ra))

    # Anything else the Room Issues report would now say that it did not say before.
    edited_ids = {ra.id for ra, _ in edited}
    session.expire_all()
    for key, finding in _audit_findings(session).items():
        if key in known:
            continue
        ra = finding.get('assignment')
        other = finding['extra'].get('other_assignment')
        if ra is not None and ra.id not in edited_ids:
            if other is None or other.id not in edited_ids:
                continue
            ra = other
        issues.append(_grid_issue(
            'error' if finding['kind'] in BLOCKING_AUDIT_KINDS else 'warning', finding['label'], ra))
    return issues, [ra for ra, _ in edited]


def _roommate_action(session, assignment_id, csrf_token, return_url, action, target_id):
    """Run a uber.hotel.service roommate helper for the staffer_rooms roommates modal."""
    if cherrypy.request.method != 'POST':
        raise HTTPRedirect('staffer_rooms')
    check_csrf(csrf_token)
    ra = _staffer_room(session, assignment_id, return_url)
    try:
        result = action(session, ra, target_id, audit_prefix='Staff rooming admin')
    except RoomAssignmentError as e:
        session.rollback()
        _redirect_back(return_url, 'staffer_rooms', e.message)
    session.commit()
    return result


def _default_settings():
    """Generate default per-date requirements spanning the convention.

    The user's spec: pre-fill based on epoch/eschaton, assuming Thu->Sun
    are core. We extend two days before EPOCH (setup) and one day after
    ESCHATON (teardown).

    Setup/teardown windows default to a 6-hour mid-day block; admins
    edit before relying on the data. Core nights default to 6 weighted
    hours each.
    """
    settings = []
    epoch = c.EPOCH.date()
    eschaton = c.ESCHATON.date()
    cur = epoch - timedelta(days=2)
    end = eschaton + timedelta(days=1)
    tz = c.EVENT_TIMEZONE

    while cur <= end:
        if cur < epoch:
            start_dt = tz.localize(datetime.combine(cur, time(12, 0)))
            settings.append({
                'night_date': cur,
                'kind': c.SETUP,
                'shift_window_start': start_dt,
                'shift_window_end': start_dt + timedelta(hours=6),
                'required_weighted_hours': 0,
            })
        elif cur > eschaton:
            start_dt = tz.localize(datetime.combine(cur, time(10, 0)))
            settings.append({
                'night_date': cur,
                'kind': c.TEARDOWN,
                'shift_window_start': start_dt,
                'shift_window_end': start_dt + timedelta(hours=6),
                'required_weighted_hours': 0,
            })
        else:
            settings.append({
                'night_date': cur,
                'kind': c.CORE,
                'shift_window_start': None,
                'shift_window_end': None,
                'required_weighted_hours': 6,
            })
        cur += timedelta(days=1)
    return settings


def _ensure_populated(session):
    if session.query(NightShiftRequirement).first():
        return
    for s in _default_settings():
        session.add(NightShiftRequirement(**s))
    session.commit()


def _parse_local_datetime(value):
    """Parse an HTML datetime-local value and attach the event timezone."""
    if not value:
        return None
    dt = datetime.strptime(value, '%Y-%m-%dT%H:%M')
    return c.EVENT_TIMEZONE.localize(dt)


@all_renderable()
class Root:
    def index(self, session, message=''):
        _ensure_populated(session)
        requirements = session.query(NightShiftRequirement).order_by(
            NightShiftRequirement.night_date).all()
        return {
            'message': message,
            'requirements': requirements,
            'night_kind_opts': c.NIGHT_KIND_OPTS,
        }

    def save(self, session, csrf_token=None, **params):
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('index')
        check_csrf(csrf_token)

        requirements = session.query(NightShiftRequirement).all()
        by_id = {str(r.id): r for r in requirements}

        for req_id, req in by_id.items():
            req.kind = int(params.get(f'kind_{req_id}', c.NONE))
            req.shift_window_start = _parse_local_datetime(params.get(f'window_start_{req_id}'))
            req.shift_window_end = _parse_local_datetime(params.get(f'window_end_{req_id}'))
            hours_raw = params.get(f'required_weighted_hours_{req_id}', '0').strip()
            try:
                req.required_weighted_hours = int(hours_raw or 0)
            except ValueError:
                req.required_weighted_hours = 0
            session.add(req)

        session.commit()
        raise HTTPRedirect('index?message={}', 'Staff rooming requirements saved.')

    def reset_to_defaults(self, session, csrf_token=None):
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('index')
        check_csrf(csrf_token)

        session.query(NightShiftRequirement).delete()
        session.commit()
        # Re-populate from defaults on the next index load.
        raise HTTPRedirect('index?message={}', 'Requirements reset to defaults.')

    def compliance_report(self, session, message='', department_id='',
                          page='1', page_size='50', search=''):
        """Non-compliant staffers report - optionally filtered to a
        single department via the department picker.

        Search + pagination live in Python (not SQL) because
        `non_compliant_staffers` materializes a list of
        `(attendee, violations)` tuples after running the per-attendee
        compliance check - we can't push the filter down to the query
        without rewriting that function. The page sizes are small
        enough (one row per non-compliant staffer, typically tens to
        low hundreds even at scale) that the in-Python filter is
        cheap. Page size defaults to 50, matches the convention on
        `staffer_rooms`.
        """
        ps = clamp_page_size(page_size)
        search_text = (search or '').strip()

        department = None
        if department_id:
            department = session.query(Department).get(department_id)
            if not department:
                raise HTTPRedirect('compliance_report?message={}',
                                   'Department not found.')
            all_results = non_compliant_staffers(
                session, department_id=department.id)
        else:
            all_results = non_compliant_staffers(session)

        total_unfiltered = len(all_results)

        if search_text:
            # Case-insensitive substring match against the attendee's
            # full name, email, the joined dept-label string the
            # template displays, and each violation's `kind_label` +
            # date. The dept and violation strings are how an admin
            # would describe what they're looking for ("ADA shift
            # Saturday", "Marketplace department", etc.); matching
            # them keeps the filter expectations consistent with what
            # the table actually shows.
            needle = search_text.lower()

            def _row_matches(attendee, violations):
                hay = [
                    (attendee.full_name or '').lower(),
                    (attendee.email or '').lower(),
                    ' / '.join(attendee.assigned_depts_labels or []).lower(),
                ]
                for req in violations:
                    if getattr(req, 'kind_label', None):
                        hay.append(req.kind_label.lower())
                    if getattr(req, 'night_date', None):
                        # Match both "Sat 1/10" and "2026-01-10" forms.
                        hay.append(req.night_date.strftime('%a %b %-d').lower())
                        hay.append(req.night_date.isoformat())
                return any(needle in h for h in hay)

            filtered = [(a, v) for (a, v) in all_results
                        if _row_matches(a, v)]
        else:
            filtered = all_results

        page_slice, total, page_num, page_count = paginate(filtered, page, ps)
        if page_slice:
            session.query(Attendee).filter(Attendee.id.in_([a.id for a, _ in page_slice])).options(
                selectinload(Attendee.lottery_application),
                selectinload(Attendee.shifts).options(lazyload(Shift.attendee))).all()

        departments = (session.query(Department)
                       .order_by(Department.name).all())
        return {
            'message': message,
            'results': page_slice,
            'total': total,
            'total_unfiltered': total_unfiltered,
            'page': page_num,
            'page_size': ps,
            'page_count': page_count,
            'search': search_text,
            'department': department,
            'departments': departments,
        }

    def staffer_rooms(self, session, message='', page='1', page_size='50',
                      billing='all', hotel_id='', search='', source='all'):
        ps = clamp_page_size(page_size)
        q = _staffer_rooms_query(session, billing, hotel_id, search, source)
        q = q.options(selectinload(RoomAssignment.lottery_run),
                      selectinload(RoomAssignment.occupants))
        assignments, total, page_num, page_count = paginate(q, page, ps)

        # Aggregates ignore page / billing filter so the badges always
        # show the full picture (lets the admin gauge how the filter
        # narrows the view).
        live_q = build_room_assignment_query(
            session, status='live', badge_types=[c.STAFF_BADGE, c.CONTRACTOR_BADGE])
        total_self = live_q.filter(RoomAssignment.require_cc).count()
        total_master = live_q.filter(~RoomAssignment.require_cc).count()

        hotels = (session.query(LotteryHotel)
                  .filter_by(active=True)
                  .order_by(LotteryHotel.name).all())

        ra_ids = [ra.id for ra in assignments]
        invites_by_room = {}
        if ra_ids:
            for invite in (session.query(RoomAssignmentInvite)
                           .filter(RoomAssignmentInvite.room_assignment_id.in_(ra_ids))
                           .order_by(RoomAssignmentInvite.created)):
                invites_by_room.setdefault(invite.room_assignment_id, []).append(invite)
        return {
            'message': message,
            'assignments': assignments,
            'stay_dates': occupant_stay_dates(session, ra_ids),
            'invites_by_room': invites_by_room,
            'partitions': session.query(InventoryPartition).filter_by(
                active=True).order_by(InventoryPartition.name).all(),
            'inventory_blocks': session.query(HotelRoomInventory).filter_by(
                active=True).order_by(HotelRoomInventory.hotel_id, HotelRoomInventory.name).all(),
            'inventory_partitions_map': _inventory_partitions_map(session),
            'page': page_num,
            'page_size': ps,
            'total': total,
            'page_count': page_count,
            'billing': billing,
            'source': source,
            'hotel_id': hotel_id,
            'search': search,
            'hotels': hotels,
            'total_self': total_self,
            'total_master': total_master,
        }

    def update_room(self, session, id, csrf_token=None, return_url='', **params):
        """Save the staffer_rooms room type / dates modals. The dates modal also posts each
        crash space roommate's own stay dates; a blank one means the room's own."""
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('staffer_rooms')
        check_csrf(csrf_token)
        ra = _staffer_room(session, id, return_url)

        def fail(msg):
            session.rollback()
            _redirect_back(return_url, 'staffer_rooms', msg)

        msg = apply_room_assignment_edits(
            session, ra, {k: params[k] for k in INLINE_ROOM_FIELDS if k in params},
            audit_prefix='Staff rooming admin updated', fail=fail)

        occupant_ids = {key.split('_')[-1] for key in params if key.startswith(('check_in_', 'check_out_'))}
        if occupant_ids:
            try:
                changed = set_occupant_stay_dates(session, ra, {
                    attendee_id: tuple(
                        date.fromisoformat(params[key]) if params.get(key) else None
                        for key in (f'check_in_{attendee_id}', f'check_out_{attendee_id}'))
                    for attendee_id in occupant_ids})
            except ValueError:
                fail('Dates must look like 2027-01-07.')
            except RoomAssignmentError as e:
                fail(e.message)
            if changed:
                stay_msg = f'Stay dates updated for {changed} roommate(s).'
                msg = stay_msg if msg == 'No changes.' else f'{msg} {stay_msg}'
        session.commit()
        _redirect_back(return_url, 'staffer_rooms', f'{ra.attendee.full_name}: {msg}')

    def add_occupant(self, session, assignment_id, attendee_id='', csrf_token=None, return_url=''):
        attendee = _roommate_action(session, assignment_id, csrf_token, return_url,
                                    add_room_occupant, attendee_id)
        _redirect_back(return_url, 'staffer_rooms', f'Added {attendee.full_name} as a roommate.')

    def remove_occupant(self, session, assignment_id, attendee_id='', csrf_token=None, return_url=''):
        attendee = _roommate_action(session, assignment_id, csrf_token, return_url,
                                    remove_room_occupant, attendee_id)
        _redirect_back(return_url, 'staffer_rooms', f'Removed {attendee.full_name} from the room.')

    def cancel_occupant_invite(self, session, assignment_id, invite_id='', csrf_token=None, return_url=''):
        label = _roommate_action(session, assignment_id, csrf_token, return_url,
                                 cancel_room_occupant_invite, invite_id)
        _redirect_back(return_url, 'staffer_rooms', f'Cancelled the invite for {label}.')

    @ajax_gettable
    def search_attendees(self, session, q='', **params):
        return attendee_search_results(session, q)

    def room_grid(self, session, message='', search=''):
        """Spreadsheet-style editor over every room staffer_rooms lists.
        The page filters and sorts in the browser, so it gets them all."""
        rooms = _staffer_rooms_query(session).options(
            selectinload(RoomAssignment.lottery_run), selectinload(RoomAssignment.occupants),
            selectinload(RoomAssignment.lottery_application), selectinload(RoomAssignment.physical_room),
            selectinload(RoomAssignment.inventory).selectinload(HotelRoomInventory.hotel)).all()

        partitions_map = _inventory_partitions_map(session)
        blocks = session.query(HotelRoomInventory).filter_by(active=True).order_by(
            HotelRoomInventory.hotel_id, HotelRoomInventory.name).all()
        return {
            'message': message,
            'search': search,
            'hotels': session.query(LotteryHotel).filter_by(active=True).order_by(LotteryHotel.name).all(),
            'grid': {
                'rows': [_grid_row(ra) for ra in rooms],
                'blocks': [{'id': inv.id, 'capacity': inv.capacity, 'hotel_id': inv.hotel_id,
                            'label': _block_label(inv), 'room_type': _room_type_label(inv),
                            'partitions': partitions_map.get(str(inv.id), [])} for inv in blocks],
                'partitions': [{'id': p.id, 'name': p.name} for p in session.query(InventoryPartition).filter_by(
                    active=True).order_by(InventoryPartition.name)],
                'payment_types': c.HOTEL_PAYMENT_TYPE_OPTS,
                'card_types': c.HOTEL_PAYMENT_TYPES_REQUIRING_CC,
                'parking_types': c.HOTEL_PAYMENT_TYPES_WITH_PARKING,
                'reasons': [(str(value), SOURCE_LABELS.get(value, label))
                            for value, label in c.HOTEL_ASSIGNMENT_REASON_OPTS if value != c.SUITE_CONNECTOR],
                'lottery_reasons': [str(c.LOTTERY_AWARD), str(c.SUITE_CONNECTOR)],
                'crash_reason': str(c.STAFF_CRASH_SPACE),
            },
        }

    @ajax
    def grid_save(self, session, edits='{}', commit='', **params):
        """Check the room_grid's staged edits, and save them when `commit`
        is set and nothing blocks. `edits` is JSON: {room id: {fields: {...},
        add: [attendee ids], remove: [attendee ids], leader: attendee id}}.
        Without `commit` this is a dry run that only reports the issues."""
        try:
            edits = json.loads(edits)
            assert isinstance(edits, dict) and all(isinstance(e, dict) for e in edits.values())
        except (ValueError, AssertionError):
            return {'error': 'Could not read the edits. Reload the page.'}

        savepoint = session.begin_nested()
        issues, rooms = _grid_issues(session, edits)
        if commit and not any(issue['severity'] == 'error' for issue in issues):
            savepoint.commit()
            session.commit()
            for ra in rooms:
                session.refresh(ra)
            return {'saved': True, 'issues': issues, 'rows': [_grid_row(ra) for ra in rooms]}
        savepoint.rollback()
        return {'saved': False, 'issues': issues}

    @ajax_gettable
    def grid_rows(self, session, ids='', **params):
        """Fresh room_grid rows, for after a room was edited in the full form.
        Rooms that no longer exist are left out."""
        rooms = [_find_staffer_room(session, id) for id in ids.split(',') if id]
        return [_grid_row(ra) for ra in rooms if ra]

    @ajax_gettable
    def grid_search_roommates(self, session, id='', q='', **params):
        """Attendees who could be added to this room and are not already in it."""
        ra = _find_staffer_room(session, id)
        if not ra:
            return []
        return attendee_search_results(
            session, q, filters=[~Attendee.id.in_([o.id for o in ra.effective_occupants])])

    # List all staff with toggleable `hotel_eligible` flag. Default
    # filter shows currently-eligible staff so the admin can scan who
    # would be invited into the next staff lottery without scrolling
    # through everyone who's been disqualified historically.

    def hotel_eligibility(self, session, message='', page='1', page_size='50',
                          show='all', search=''):
        """Staff hotel eligibility, tracked separately for the two ways a
        staffer can be given a room.

        When hotel_requests_url is unset there is no shared room signup to
        integrate with, so the lottery is the only route and the shared room
        controls are hidden entirely.
        """
        ps = clamp_page_size(page_size)
        shared_enabled = bool(c.HOTEL_REQUESTS_URL)

        q = staff_rooming_query(session)

        # 'eligible' and 'ineligible' are the pre-split values; keep them
        # meaning the shared room flag so existing links still work.
        if show in ('eligible', 'shared'):
            q = shared_room_eligible_query(session)
        elif show in ('ineligible', 'not_shared'):
            q = q.filter(Attendee.hotel_eligible.is_(False))
        elif show == 'staff_lottery':
            q = q.filter(Attendee.staff_lottery_eligible.is_(True))
        elif show == 'not_staff_lottery':
            q = q.filter(Attendee.staff_lottery_eligible.is_(False))
        elif show == 'neither':
            q = q.filter(Attendee.hotel_eligible.is_(False),
                         Attendee.staff_lottery_eligible.is_(False))

        if search:
            like = f'%{search.strip()}%'
            q = q.filter(or_(
                Attendee.first_name.ilike(like),
                Attendee.last_name.ilike(like),
                Attendee.email.ilike(like),
            ))

        q = q.order_by(Attendee.last_name.asc(), Attendee.first_name.asc())
        # The template reads both per row, and without these it is one query
        # per staffer for each.
        q = q.options(selectinload(Attendee.room_assignments),
                      selectinload(Attendee.occupied_rooms),
                      selectinload(Attendee.assigned_depts))
        staffers, total, page_num, page_count = paginate(q, page, ps)

        # Cross-status counts for the header badges.
        all_staff_q = staff_rooming_query(session)
        total_staff = all_staff_q.count()
        total_eligible = shared_room_eligible_query(session).count()
        total_ineligible = all_staff_q.filter(Attendee.hotel_eligible.is_(False)).count()
        total_staff_lottery = all_staff_q.filter(
            Attendee.staff_lottery_eligible.is_(True)).count()
        total_not_staff_lottery = all_staff_q.filter(
            Attendee.staff_lottery_eligible.is_(False)).count()

        return {
            'message': message,
            'staffers': staffers,
            'page': page_num,
            'page_size': ps,
            'total': total,
            'page_count': page_count,
            'show': show,
            'search': search,
            'shared_enabled': shared_enabled,
            'total_staff': total_staff,
            'total_eligible': total_eligible,
            'total_ineligible': total_ineligible,
            'total_staff_lottery': total_staff_lottery,
            'total_not_staff_lottery': total_not_staff_lottery,
        }

    ELIGIBILITY_FIELDS = {
        'shared_room': ('hotel_eligible', 'a shared staff room'),
        'staff_lottery': ('staff_lottery_eligible', 'the staff hotel lottery'),
    }

    def set_hotel_eligibility(self, session, attendee_id, eligible='false',
                              field='shared_room', csrf_token=None,
                              return_url=''):
        """Toggle one of a staffer's two eligibility flags.

        `field` defaults to the shared room flag, which is what this endpoint
        toggled before the two were split apart.
        """
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('hotel_eligibility')
        check_csrf(csrf_token)

        column, label = self.ELIGIBILITY_FIELDS.get(
            field, self.ELIGIBILITY_FIELDS['shared_room'])

        attendee = session.query(Attendee).get(attendee_id)
        if not attendee:
            _redirect_back(return_url, 'hotel_eligibility',
                           'Attendee not found.')
        new_val = (str(eligible).lower() == 'true')
        setattr(attendee, column, new_val)
        session.add(attendee)
        session.commit()

        msg = (f"{attendee.full_name} is now "
               f"{'eligible' if new_val else 'ineligible'} for {label}.")
        _redirect_back(return_url, 'hotel_eligibility', msg)

    def bulk_set_hotel_eligibility(self, session, attendee_ids='',
                                   eligible='false', field='shared_room',
                                   csrf_token=None, return_url=''):
        """Bulk flip of one eligibility flag across the selected rows."""
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('hotel_eligibility')
        check_csrf(csrf_token)

        column, _label = self.ELIGIBILITY_FIELDS.get(
            field, self.ELIGIBILITY_FIELDS['shared_room'])

        ids = [i.strip() for i in (attendee_ids or '').split(',') if i.strip()]
        if not ids:
            _redirect_back(return_url, 'hotel_eligibility',
                           'No attendees selected.')
        new_val = (str(eligible).lower() == 'true')
        rows = session.query(Attendee).filter(Attendee.id.in_(ids)).all()
        for a in rows:
            setattr(a, column, new_val)
            session.add(a)
        session.commit()

        msg = (f"Marked {len(rows)} staffer(s) "
               f"{'eligible' if new_val else 'ineligible'} "
               f"for the staff hotel lottery.")
        _redirect_back(return_url, 'hotel_eligibility', msg)
