import base64
import os
import cherrypy
import logging
from cherrypy.lib.static import serve_file
import random
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from pytz import UTC
from dateutil import parser as dateparser
import sqlalchemy as sa
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import joinedload
from sqlalchemy.types import String

from uber.config import c
from uber.decorators import all_renderable, log_pageview, ajax, ajax_gettable, xlsx_file, csv_file, multifile_zipfile, render
from uber.errors import HTTPRedirect
from uber.forms import load_forms
from uber.models import Attendee, Group, LotteryApplication, Email, Tracking, PageViewTracking
from uber.lottery_perms import record_partition_audit
from uber.models.hotel import (HotelRoomInventory, InventoryNightQuantity, InventoryPartition,
                               InventoryPartitionBlock, LotteryRun, HotelExportLog, LotteryHotel, LotteryRoomType,
                               PartitionAuditLog, PartitionOwner, RoomAssignment,
                               WaitlistReveal, WaitlistRevealLink, HotelRoomIssueNote,
                               HotelImportFile)
from uber.email import EmailService
from uber.hotel_exports import (booking_columns, booking_export_data,
                                build_waitlist_xlsx, compute_export_tracking,
                                derive_sync_status, write_hotel_inventory_xlsx,
                                write_interchange_export)
from uber.hotel_imports import parse_confirmation_rows, parse_iso_date, parse_spreadsheet
from uber.hotel_lottery_solver import (adjust_available_rooms,
                                       build_eligible_applications,
                                       count_assigned_per_block_night,
                                       filter_inventory_table,
                                       materialize_room_assignments,
                                       solve_lottery)
from uber.hotel_room_audit import (annotate_issues, collect_issues,
                                   filter_issues, get_or_make_issue_note,
                                   group_inventory_issues, group_room_issues,
                                   load_issue_notes)
from uber.hotel_room_queries import build_room_assignment_query, clamp_page_size, paginate
from uber.utils import (Order, check_csrf, get_page, localized_now,
                        validate_model, get_age_from_birthday,
                        normalize_email_legacy)

log = logging.getLogger(__name__)

def _picker_context(session):
    """Shared dropdown option lists for the hotel-lottery admin pages.

    Most pages in this section offer some combination of hotel / room type /
    inventory-block / partition pickers; this builds all of them once so the
    handlers don't each hand-roll the same queries.
    """
    return {
        'hotels': session.query(LotteryHotel).filter_by(
            active=True).order_by(LotteryHotel.name).all(),
        'room_types': session.query(LotteryRoomType).filter_by(
            is_suite=False, active=True).order_by(LotteryRoomType.name).all(),
        'suite_types': session.query(LotteryRoomType).filter_by(
            is_suite=True, active=True).order_by(LotteryRoomType.name).all(),
        'inventory_blocks': session.query(HotelRoomInventory).filter_by(
            active=True).order_by(HotelRoomInventory.hotel_id, HotelRoomInventory.name).all(),
        'partitions': session.query(InventoryPartition).filter_by(
            active=True).order_by(InventoryPartition.name).all(),
    }


def _event_nights():
    """Hotel night dates for the lottery window, from the first check-in
    night through the night before the last check-out. Drives the
    per-night quantity grid and the inventory overview columns."""
    nights = []
    day = c.HOTEL_LOTTERY_CHECKIN_START.date()
    end = c.HOTEL_LOTTERY_CHECKOUT_END.date()
    while day < end:
        nights.append(day)
        day += timedelta(days=1)
    return nights


def _search(session, text):
    applications = session.query(LotteryApplication)

    terms = text.split()
    if len(terms) == 1 and terms[0].isdigit():
        if len(terms[0]) == 10:
            return applications.filter(or_(LotteryApplication.confirmation_num == terms[0])), ''

    check_list = []

    # Skip columns that will raise unexpected applications
    skip_columns = {'id', 'parent_application_id',
                    'lottery_run_id', 'former_parent_id'}
    for attr in [col for col in LotteryApplication.__table__.columns if isinstance(col.type, String)]:
        if attr.name not in skip_columns:
            check_list.append(attr.ilike('%' + text + '%'))

    # Search by hotel / room-type name through inventory. Room assignments
    # live on RoomAssignment, so the inventory match goes through the
    # RoomAssignment join (applications that have any awarded
    # RoomAssignment at a matching inventory row).
    from uber.models.hotel import RoomAssignment

    matching_inventory_ids = set()
    hotel_matches = session.query(HotelRoomInventory.id).join(
        LotteryHotel, HotelRoomInventory.hotel_id == LotteryHotel.id
    ).filter(LotteryHotel.name.ilike('%' + text + '%')).all()
    matching_inventory_ids.update(str(row[0]) for row in hotel_matches)

    rt_matches = session.query(HotelRoomInventory.id).join(
        LotteryRoomType, or_(
            HotelRoomInventory.room_type_id == LotteryRoomType.id,
            HotelRoomInventory.suite_type_id == LotteryRoomType.id,
        )
    ).filter(LotteryRoomType.name.ilike('%' + text + '%')).all()
    matching_inventory_ids.update(str(row[0]) for row in rt_matches)

    if matching_inventory_ids:
        app_ids_with_inventory_match = session.query(
            RoomAssignment.lottery_application_id
        ).filter(
            RoomAssignment.inventory_id.in_(matching_inventory_ids),
            RoomAssignment.lottery_application_id.isnot(None),
        ).distinct().all()
        if app_ids_with_inventory_match:
            check_list.append(
                LotteryApplication.id.in_(
                    str(row[0]) for row in app_ids_with_inventory_match))

    for col_name in ['entry_type', 'status']:
        col = getattr(LotteryApplication, col_name).type
        label_list = [choice for choice in col.choices.values()]
        for label in label_list:
            if text.lower() in label.lower():
                check_list.append(getattr(LotteryApplication, col_name) == col.convert_if_label(label))

    if not check_list:
        return applications.filter(sa.false()), 'No matches found.'

    return applications.filter(or_(*check_list)), ''


def _require_post_csrf(params, redirect='lottery_runs'):
    """Guard for destructive endpoints: mutations must never fire on a
    bare GET (a crawler or prefetch would silently run them), and every
    POST must carry a valid CSRF token."""
    if cherrypy.request.method != 'POST':
        raise HTTPRedirect(redirect)
    check_csrf(params.get('csrf_token'))


def _partition_capacity(session, inv, night, partition_id):
    """Compute the effective capacity and assigned count for a block/night respecting partitions.

    If partition_id is set, the capacity is the partition's allocation for
    this block and only same-partition assignments count. If partition_id
    is None, the capacity is the block's total minus all partition
    allocations, and only non-partitioned assignments count.

    Assignment count is sourced from RoomAssignment (per multi-room).

    Returns (capacity, assigned_count, open_slots).
    """
    from uber.models.hotel import RoomAssignment

    nq_map = inv.night_quantity_map
    block_qty = nq_map.get(night, inv.quantity) if nq_map else inv.quantity

    base_filters = [
        RoomAssignment.inventory_id == str(inv.id),
        RoomAssignment.is_live,
        RoomAssignment.assigned_check_in_date <= night,
        RoomAssignment.assigned_check_out_date > night,
    ]

    if partition_id:
        pb = session.query(InventoryPartitionBlock).filter_by(
            partition_id=partition_id, inventory_id=inv.id).first()
        capacity = min(pb.quantity, block_qty) if pb else 0
        assigned_count = session.query(RoomAssignment).filter(
            *base_filters,
            RoomAssignment.partition_id == partition_id,
        ).count()
    else:
        total_partitioned = session.query(
            func.coalesce(func.sum(InventoryPartitionBlock.quantity), 0)
        ).filter(
            InventoryPartitionBlock.inventory_id == str(inv.id),
        ).scalar()
        capacity = max(0, block_qty - total_partitioned)
        assigned_count = session.query(RoomAssignment).filter(
            *base_filters,
            RoomAssignment.partition_id == None,  # noqa: E711
        ).count()

    return capacity, assigned_count, max(0, capacity - assigned_count)


def _wl_ci(ra):
    """Effective waitlisted check-in for an assignment, coalesced to the
    assigned date when only the other end of the range is waitlisted."""
    return ra.waitlisted_check_in_date or ra.assigned_check_in_date


def _wl_co(ra):
    """Effective waitlisted check-out (see _wl_ci)."""
    return ra.waitlisted_check_out_date or ra.assigned_check_out_date


def _waitlist_pairs_to_process(base_q, inventory_id, night_date):
    """Discover the (inventory_id, night) pairs with waitlist demand for
    _fulfill_waitlist, sorted by night. An explicit inventory + night
    short-circuits; otherwise every candidate's front/back gap nights
    are collected."""
    if inventory_id and night_date:
        return [(str(inventory_id), night_date)]

    candidates = base_q.all()
    if inventory_id:
        candidates = [ra for ra in candidates
                      if str(ra.inventory_id) == str(inventory_id)]

    pairs = set()
    for ra in candidates:
        block_id = str(ra.inventory_id)
        wl_ci = _wl_ci(ra)
        wl_co = _wl_co(ra)
        if wl_ci and ra.assigned_check_in_date and wl_ci < ra.assigned_check_in_date:
            d = wl_ci
            while d < ra.assigned_check_in_date:
                pairs.add((block_id, d))
                d += timedelta(days=1)
        if wl_co and ra.assigned_check_out_date and wl_co > ra.assigned_check_out_date:
            d = ra.assigned_check_out_date
            while d < wl_co:
                pairs.add((block_id, d))
                d += timedelta(days=1)
    return sorted(pairs, key=lambda p: p[1])


def _eligible_waitlist_extensions(candidates, night):
    """Of `candidates`, the assignments extendable by this specific
    night, as ('checkin'|'checkout', assignment) pairs. We walk the gap
    one night at a time on either end - we only extend by one contiguous
    night per pass."""
    eligible = []
    for ra in candidates:
        wl_ci = _wl_ci(ra)
        wl_co = _wl_co(ra)
        if (wl_ci and ra.assigned_check_in_date
                and night < ra.assigned_check_in_date
                and night >= wl_ci
                and night == ra.assigned_check_in_date - timedelta(days=1)):
            eligible.append(('checkin', ra))
        elif (wl_co and ra.assigned_check_out_date
                and night >= ra.assigned_check_out_date
                and night < wl_co
                and night == ra.assigned_check_out_date):
            eligible.append(('checkout', ra))
    return eligible


def _fulfill_waitlist(session, inventory_id=None, night_date=None):
    """Process waitlist by extending the assigned dates on SECURED
    RoomAssignment rows that have unfulfilled per-room waitlist demand.

    Waitlist demand is the delta between the assignment's
    `waitlisted_check_in_date` / `waitlisted_check_out_date` and the
    confirmed `assigned_check_in_date` / `assigned_check_out_date`.
    Both waitlist columns NULL -> no demand -> row is skipped.

    The per-room columns are the source of truth: the application's
    `earliest_checkin_date` / `latest_checkout_date` represent the
    original lottery entry, which isn't meaningful once attendees can
    edit per-room dates post-award.

    Args:
        inventory_id: If provided, only process this inventory block.
        night_date: If provided, only process this specific night.
    """
    from uber.models.hotel import RoomAssignment

    total_fulfilled = 0
    total_skipped_locked = 0
    fulfilled_assignments = set()

    # Only SECURED, non-group, inventory-bound rows with at least one
    # waitlist column populated are candidates. (Group-entry sub-apps
    # don't get their own RoomAssignment; the leader's row covers the
    # group's nights.)
    base_q = (session.query(RoomAssignment)
              .outerjoin(LotteryApplication,
                         RoomAssignment.lottery_application_id == LotteryApplication.id)
              .filter(RoomAssignment.status == c.SECURED,
                      RoomAssignment.inventory_id.isnot(None),
                      sa.or_(LotteryApplication.id.is_(None),
                             LotteryApplication.entry_type != c.GROUP_ENTRY),
                      sa.or_(RoomAssignment.waitlisted_check_in_date.isnot(None),
                             RoomAssignment.waitlisted_check_out_date.isnot(None))))

    pairs_to_process = _waitlist_pairs_to_process(base_q, inventory_id, night_date)

    for block_id, night in pairs_to_process:
        inv = session.query(HotelRoomInventory).get(block_id)
        if not inv:
            continue

        # Discover the set of partition_ids covered by candidates for this block.
        # Exclude export-locked applications (those rows can't be edited locally
        # anymore - they live with the hotel).
        block_candidates = base_q.filter(
            RoomAssignment.inventory_id == block_id,
            sa.or_(LotteryApplication.id.is_(None),
                   LotteryApplication.export_locked == False),
        ).all()

        candidate_partitions = set()
        for ra in block_candidates:
            wl_ci = _wl_ci(ra)
            wl_co = _wl_co(ra)
            has_demand = (
                (wl_ci and ra.assigned_check_in_date and wl_ci < ra.assigned_check_in_date)
                or
                (wl_co and ra.assigned_check_out_date and wl_co > ra.assigned_check_out_date))
            if has_demand:
                candidate_partitions.add(ra.partition_id)

        skipped_locked = base_q.filter(
            RoomAssignment.inventory_id == block_id,
            LotteryApplication.export_locked == True,
        ).count()
        total_skipped_locked += skipped_locked

        for part_id in candidate_partitions:
            max_iterations = 500
            for _iteration in range(max_iterations):
                capacity, assigned_count, open_slots = _partition_capacity(
                    session, inv, night, part_id)
                if open_slots <= 0:
                    break

                part_filter = ((RoomAssignment.partition_id == part_id) if part_id
                               else (RoomAssignment.partition_id == None))  # noqa: E711
                candidates = base_q.filter(
                    RoomAssignment.inventory_id == block_id,
                    sa.or_(LotteryApplication.id.is_(None),
                           LotteryApplication.export_locked == False),
                    part_filter,
                ).all()

                eligible = _eligible_waitlist_extensions(candidates, night)

                if not eligible:
                    break

                # FIFO: earliest waitlist_started_at first. Stable on
                # `id` so concurrent same-millisecond entries (rare but
                # possible during a solver re-run) get a deterministic
                # order. NULL `waitlist_started_at` is treated as the
                # epoch - should never happen post-migration, but if a
                # row ever ends up with waitlisted_* set and no start
                # timestamp, we still want it served (FIFO can't
                # reasonably gauge "when did they join" if it's missing,
                # so we default to "as early as possible" rather than
                # silently dropping the row).
                from datetime import datetime as _dt, timezone as _tz
                _epoch = _dt(1970, 1, 1, tzinfo=_tz.utc)
                eligible.sort(key=lambda dr: (
                    dr[1].waitlist_started_at or _epoch,
                    str(dr[1].id)))
                selected = eligible[:open_slots]
                if not selected:
                    break

                for direction, ra in selected:
                    if direction == 'checkin':
                        ra.assigned_check_in_date = night
                    else:
                        ra.assigned_check_out_date = night + timedelta(days=1)
                    # The model's `clear_waitlist_when_satisfied` presave
                    # zeros the waitlist columns when the assigned range
                    # fully covers the request, so the row drops out of
                    # subsequent scans without an extra branch here.
                    session.add(ra)
                    total_fulfilled += 1
                    fulfilled_assignments.add(ra)

                session.flush()

    session.commit()

    for ra in fulfilled_assignments:
        if ra.attendee and ra.lottery_application:
            EmailService.queue_email(
                session, 'hotel_lottery_waitlist_fulfilled', ra.lottery_application,
                subject=f'{c.EVENT_NAME} Hotel Lottery - Room Dates Updated',
                data={'assignment': ra, 'app': ra.lottery_application})

    return {
        "success": True,
        "fulfilled": total_fulfilled,
        "skipped_locked": total_skipped_locked,
        "message": f"Fulfilled {total_fulfilled} waitlist entries." + (
            f" Skipped {total_skipped_locked} locked entries." if total_skipped_locked else "")
    }


def _count_inventory_usage(assigned_ras):
    """Tally the live assignments for the inventory overview.

    Builds per-block per-night assignment counts + per-block status
    counts, plus per-block per-night waitlist demand from each
    assignment's own waitlisted_* range. For the waitlist demand, either
    column NULL means no demand on that end; we coalesce to the assigned
    date so the gap calculation is symmetric.

    Returns (assigned_per_block_night, status_per_block,
    waitlist_per_block_night).
    """
    assigned_per_block_night = defaultdict(lambda: defaultdict(int))
    status_per_block = defaultdict(lambda: defaultdict(int))
    for ra in assigned_ras:
        block_id = str(ra.inventory_id)
        status_per_block[block_id][ra.status] += 1
        if ra.assigned_check_in_date and ra.assigned_check_out_date:
            d = ra.assigned_check_in_date
            while d < ra.assigned_check_out_date:
                assigned_per_block_night[block_id][d] += 1
                d += timedelta(days=1)

    waitlist_per_block_night = defaultdict(lambda: defaultdict(int))
    for ra in assigned_ras:
        if ra.status != c.SECURED:
            continue
        if not (ra.waitlisted_check_in_date or ra.waitlisted_check_out_date):
            continue
        block_id = str(ra.inventory_id)
        wl_ci = ra.waitlisted_check_in_date or ra.assigned_check_in_date
        wl_co = ra.waitlisted_check_out_date or ra.assigned_check_out_date
        if wl_ci and ra.assigned_check_in_date and wl_ci < ra.assigned_check_in_date:
            d = wl_ci
            while d < ra.assigned_check_in_date:
                waitlist_per_block_night[block_id][d] += 1
                d += timedelta(days=1)
        if wl_co and ra.assigned_check_out_date and wl_co > ra.assigned_check_out_date:
            d = ra.assigned_check_out_date
            while d < wl_co:
                waitlist_per_block_night[block_id][d] += 1
                d += timedelta(days=1)

    return assigned_per_block_night, status_per_block, waitlist_per_block_night


def _waitlist_block_rows(session, filtered):
    """Per-block per-night waitlist demand rows for the admin Waitlist
    dashboard, derived from the (possibly search-filtered) set of
    waitlisted assignments. One row per inventory block, with the
    per-night queue depth and total demand, sorted by hotel then block
    name."""
    demand_by_block = defaultdict(lambda: defaultdict(list))
    for ra in filtered:
        block_id = str(ra.inventory_id) if ra.inventory_id else None
        if not block_id:
            continue
        wl_ci = ra.waitlisted_check_in_date or ra.assigned_check_in_date
        wl_co = ra.waitlisted_check_out_date or ra.assigned_check_out_date
        if wl_ci and ra.assigned_check_in_date and wl_ci < ra.assigned_check_in_date:
            d = wl_ci
            while d < ra.assigned_check_in_date:
                demand_by_block[block_id][d].append(ra)
                d += timedelta(days=1)
        if wl_co and ra.assigned_check_out_date and wl_co > ra.assigned_check_out_date:
            d = ra.assigned_check_out_date
            while d < wl_co:
                demand_by_block[block_id][d].append(ra)
                d += timedelta(days=1)

    block_ids = list(demand_by_block.keys())
    inventory_by_id = {}
    if block_ids:
        for inv in session.query(HotelRoomInventory).filter(
                HotelRoomInventory.id.in_(block_ids)).all():
            inventory_by_id[str(inv.id)] = inv

    block_rows = []
    for block_id in block_ids:
        nights = demand_by_block[block_id]
        block_rows.append({
            'inventory': inventory_by_id.get(block_id),
            'inventory_id': block_id,
            'nights': sorted(((n, len(ras)) for n, ras in nights.items()),
                             key=lambda p: p[0]),
            'total_demand': sum(len(ras) for ras in nights.values()),
        })
    block_rows.sort(key=lambda r: (
        r['inventory'].hotel.name if r['inventory'] and r['inventory'].hotel else '',
        r['inventory'].name if r['inventory'] else ''))
    return block_rows


def _notify_applicants_of_inventory_change(session, inventory):
    """When an inventory row is deactivated, email applicants whose
    preferences referenced it. Matches by UUID inside the comma-separated
    preference strings on LotteryApplication.
    """
    if not inventory:
        return
    inv_id = str(inventory.id)
    hotel_id = str(inventory.hotel_id) if inventory.hotel_id else None
    type_id = (str(inventory.suite_type_id) if inventory.is_suite
               else str(inventory.room_type_id))

    candidates = session.query(LotteryApplication).filter(
        LotteryApplication.status.in_([c.COMPLETE, c.PROCESSED]),
    ).all()

    for app in candidates:
        hotels = {x.strip() for x in (app.hotel_preference or '').split(',') if x.strip()}
        rooms = {x.strip() for x in (app.room_type_preference or '').split(',') if x.strip()}
        suites = {x.strip() for x in (app.suite_type_preference or '').split(',') if x.strip()}
        if hotel_id and hotel_id not in hotels:
            continue
        if type_id and type_id not in (suites if inventory.is_suite else rooms):
            continue
        if not app.attendee:
            continue
        EmailService.queue_email(
            session, 'hotel_lottery_inventory_changed_applicant', app,
            subject=f"{c.EVENT_NAME_AND_YEAR}: One of your lottery preferences is no longer available",
            data={
            'attendee': app.attendee, 'application': app, 'inventory': inventory,
        })


def _notify_partition_owners_of_inventory_change(session, partition, change_description):
    """Notify partition owners with can_view_inventory of edits to
    blocks in their partition."""
    if not partition:
        return
    grants = session.query(PartitionOwner).filter_by(
        partition_id=partition.id, can_view_inventory=True).all()
    for grant in grants:
        if not grant.admin_account or not grant.admin_account.attendee:
            continue
        recipient = grant.admin_account.attendee
        EmailService.queue_email(
            session, 'hotel_lottery_inventory_changed_owner', partition,
            subject=f"{c.EVENT_NAME_AND_YEAR}: Inventory change in {partition.name}",
            data={
            'attendee': recipient, 'partition': partition,
            'change_description': change_description,
        })


def _send_confirmation_updated_email(session, assignment):
    """Notify the attendee that hotel_confirmation_number has changed.

    Direct send rather than AutomatedEmailFixture so it fires exactly once
    at the change site (the import endpoint or the API). Called after the
    field is set on `assignment` but before commit.
    """
    if not assignment or not assignment.attendee_id:
        return
    attendee = session.query(Attendee).get(assignment.attendee_id)
    if not attendee:
        return
    EmailService.queue_email(
        session, 'hotel_lottery_confirmation_updated', assignment,
        subject=f"{c.EVENT_NAME_AND_YEAR}: Hotel confirmation number updated",
        data={
        'attendee': attendee, 'assignment': assignment,
    })


def _room_issues_url(message='', severity='all', kind='all', search='',
                     show_hidden=''):
    """Build a room_issues URL preserving the active filters, so the
    hide/unhide/note POST handlers redirect back to the same view. Built
    with urlencode and passed to HTTPRedirect as one pre-formatted
    string (HTTPRedirect quotes each `{}` substitution, which would
    double-encode a hand-built query string)."""
    from urllib.parse import urlencode
    params = {}
    if severity and severity != 'all':
        params['severity'] = severity
    if kind and kind not in ('all', ''):
        params['kind'] = kind
    if search:
        params['search'] = search
    if show_hidden:
        params['show_hidden'] = '1'
    if message:
        params['message'] = message
    qs = urlencode(params)
    return 'room_issues' + ('?' + qs if qs else '')



def _validate_physical_room(session, ra, room):
    """Why a physical room can't take this booking, or None if it can."""
    from uber.hotel_room_queries import physical_room_conflicts

    inv = ra.inventory
    if not inv or not inv.hotel_id:
        return 'This booking has no inventory block, so no hotel to match.'
    if room.hotel_id != inv.hotel_id:
        return (f'Room {room.room_number} is at a different hotel than '
                'this booking.')
    if room.out_of_service:
        return f'Room {room.room_number} is out of service.'
    conflicts = physical_room_conflicts(
        session, room.id, ra.assigned_check_in_date,
        ra.assigned_check_out_date, exclude_assignment_id=ra.id)
    if conflicts:
        other = conflicts[0]
        return (f'Room {room.room_number} is already booked '
                f'{other.assigned_check_in_date} -> '
                f'{other.assigned_check_out_date}.')
    return None


@all_renderable()
class Root:
    def index(self, session, message='', page='0', search_text='', order='status', **params):
        if c.DEV_BOX and not int(page):
            page = 1

        total_count = session.query(LotteryApplication.id).count()
        complete_valid_entries = session.query(LotteryApplication.id).filter(LotteryApplication.status == c.COMPLETE).join(
            LotteryApplication.attendee).filter(Attendee.hotel_lottery_eligible == True)
        room_count_base = complete_valid_entries.filter(LotteryApplication.entry_type != c.GROUP_ENTRY)
        count = 0
        search_text = search_text.strip()
        advanced_filters = {}

        if search_text:
            search_results, message = _search(session, search_text)
            if search_results and search_results.count():
                applications = search_results
                count = applications.count()
                if count == total_count:
                    message = 'Every lottery application matched this search.'
            elif not message:
                message = 'No matches found. Try searching the lottery tracking history instead.'

        filter_status = params.get('filter_status', '')
        filter_entry_type = params.get('filter_entry_type', '')
        filter_hotel = params.get('filter_hotel', '')
        filter_inventory = params.get('filter_inventory', '')
        filter_partition = params.get('filter_partition', '')
        filter_export_locked = params.get('filter_export_locked', '')
        filter_staff = params.get('filter_staff', '')

        has_advanced = any([filter_status, filter_entry_type, filter_hotel,
                           filter_inventory, filter_partition, filter_export_locked, filter_staff])

        if has_advanced:
            if not count:
                applications = session.query(LotteryApplication)
            if filter_status:
                applications = applications.filter(LotteryApplication.status == int(filter_status))
            if filter_entry_type:
                applications = applications.filter(LotteryApplication.entry_type == int(filter_entry_type))
            if filter_hotel:
                inv_ids = [str(inv.id) for inv in
                           session.query(HotelRoomInventory).filter_by(hotel_id=filter_hotel).all()]
                if inv_ids:
                    matched_app_ids = [
                        row[0] for row in session.query(
                            RoomAssignment.lottery_application_id
                        ).filter(
                            RoomAssignment.inventory_id.in_(inv_ids),
                            RoomAssignment.lottery_application_id.isnot(None),
                        ).distinct().all()
                    ]
                    if matched_app_ids:
                        applications = applications.filter(
                            LotteryApplication.id.in_(matched_app_ids))
                    else:
                        applications = applications.filter(sa.false())
                else:
                    applications = applications.filter(sa.false())
            if filter_inventory:
                matched_app_ids = [
                    row[0] for row in session.query(
                        RoomAssignment.lottery_application_id
                    ).filter(
                        RoomAssignment.inventory_id == filter_inventory,
                        RoomAssignment.lottery_application_id.isnot(None),
                    ).distinct().all()
                ]
                if matched_app_ids:
                    applications = applications.filter(
                        LotteryApplication.id.in_(matched_app_ids))
                else:
                    applications = applications.filter(sa.false())
            if filter_partition:
                applications = applications.filter(LotteryApplication.partition_id == filter_partition)
            if filter_export_locked == 'true':
                applications = applications.filter(LotteryApplication.export_locked == True)
            elif filter_export_locked == 'false':
                applications = applications.filter(LotteryApplication.export_locked == False)
            if filter_staff == 'true':
                applications = applications.filter(LotteryApplication.is_staff_entry == True)
            elif filter_staff == 'false':
                applications = applications.filter(LotteryApplication.is_staff_entry == False)
            count = applications.count()
            advanced_filters = {k: v for k, v in params.items() if k.startswith('filter_') and v}

        if not count:
            applications = session.query(LotteryApplication)
            count = applications.count()

        applications = applications.order(order).options(joinedload(LotteryApplication.attendee))

        page = int(page)
        if search_text:
            page = page or 1

        pages = range(1, int(math.ceil(count / 100)) + 1)
        applications = applications[-100 + 100*page: 100*page] if page else []

        return {
            'message':        message if isinstance(message, str) else message[-1],
            'page':           page,
            'pages':          pages,
            'search_text':    search_text,
            'search_results': bool(search_text) or has_advanced,
            'applications':   applications,
            'order':          Order(order),
            'search_count':   count,
            'total_count':    total_count,
            'complete_count': complete_valid_entries.count(),
            'suite_count': room_count_base.filter(LotteryApplication.entry_type == c.SUITE_ENTRY).count(),
            'room_count': room_count_base.filter(or_(LotteryApplication.entry_type == c.ROOM_ENTRY,
                                                     LotteryApplication.room_opt_out == False)).count(),
            'advanced_filters': advanced_filters,
            **_picker_context(session),
        }  # noqa: E711

    def feed(self, session, message='', page='1', who='', what='', action=''):
        feed = session.query(Tracking).filter(Tracking.model == 'LotteryApplication').order_by(Tracking.when.desc())
        what = what.strip()
        if who:
            feed = feed.filter_by(who=who)
        if what:
            like = '%' + what + '%'
            or_filters = [Tracking.page.ilike(like),
                          Tracking.which.ilike(like),
                          Tracking.data.ilike(like)]
            feed = feed.filter(or_(*or_filters))
        if action:
            feed = feed.filter_by(action=action)
        return {
            'message': message,
            'who': who,
            'what': what,
            'page': page,
            'action': action,
            'count': feed.count(),
            'feed': get_page(page, feed),
            'action_opts': c.TRACKING_OPTS,
            'who_opts': [
                who for [who] in session.query(Tracking).filter(
                    Tracking.model == 'LotteryApplication').distinct().order_by(Tracking.who).values(Tracking.who)]
        }
    
    @ajax
    def validate_hotel_lottery(self, session, id=None, form_list=[], **params):
        application = session.lottery_application(id)

        if not form_list:
            form_list = ["LotteryAdminInfo"]
        elif isinstance(form_list, str):
            form_list = [form_list]
        forms = load_forms(params, application, form_list)
        all_errors = validate_model(session, forms, application, is_admin=True)
        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    @log_pageview
    def form(self, session, message='', return_to='', **params):
        id = params.get('id', None)

        if id in [None, '', 'None']:
            application = LotteryApplication()
        else:
            application = session.lottery_application(id)

        forms = load_forms(params, application, ['LotteryAdminInfo'])

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                form.populate_obj(application, is_admin=True)
            # hotel_confirmation_number is per-RoomAssignment and edited in
            # the form's "Rooms" section, not on the application here.

            message = '{}\'s entry (conf # {}) has been saved.'.format(application.attendee_name,
                                                                       application.confirmation_num)
            stay_on_form = params.get('save_return_to_search', False) is False
            session.add(application)
            if application.orig_value_of('status') != application.status and application.status in [
                    c.REJECTED, c.CANCELLED, c.REMOVED, c.WITHDRAWN]:
                application.attendee.hotel_eligible = True
                session.add(application.attendee)
            session.commit()
            if stay_on_form:
                    raise HTTPRedirect('form?id={}&message={}&return_to={}', application.id, message, return_to)
            else:
                if return_to:
                    raise HTTPRedirect(return_to + '&message={}', 'Application updated.')
                else:
                    raise HTTPRedirect('index?message={}', message)

        # Partition + inventory picker data for the Rooms section's
        # add/edit modals. The template renders both selects with the
        # partition on top; JS filters the inventory options to those in
        # the selected partition (or all unpartitioned + every block when
        # "no partition" is chosen).
        picker = _picker_context(session)
        # {inventory_id: [partition_id, ...]} - drives the JS filter.
        # An inventory with no entry in this dict has no partition
        # restriction and is always offered.
        partition_blocks = session.query(InventoryPartitionBlock).all()
        inventory_partitions_map = {}
        for pb in partition_blocks:
            inventory_partitions_map.setdefault(
                str(pb.inventory_id), []).append(str(pb.partition_id))

        return {
            'message':    message,
            'application':   application,
            'forms': forms,
            'return_to':  return_to,
            'partitions': picker['partitions'],
            'inventory_blocks': picker['inventory_blocks'],
            'inventory_partitions_map': inventory_partitions_map,
        }

    def history(self, session, id):
        application = session.lottery_application(id)
        return {
            'application':  application,
            'emails': session.query(Email).filter(Email.model == 'LotteryApplication',
                                                  Email.fk_id == id
                                                  ).order_by(Email.when).all(),
            'changes': session.query(Tracking).filter(Tracking.model == 'LotteryApplication', Tracking.fk_id == id
                                                      ).order_by(Tracking.when).all(),
            'pageviews': session.query(PageViewTracking).filter(PageViewTracking.which == repr(application)
                                                                ).order_by(PageViewTracking.when).all(),
        }
    
    def lottery_runs(self, session, message=''):
        runs = session.query(LotteryRun).order_by(LotteryRun.run_at.desc()).all()
        return {
            'runs': runs,
            'message': message,
            **_picker_context(session),
        }

    def lottery_run_detail(self, session, id, message=''):
        lottery_run = session.query(LotteryRun).get(id)
        applications = session.query(LotteryApplication).filter(
            LotteryApplication.lottery_run_id == id,
            LotteryApplication.entry_type != c.GROUP_ENTRY,
        ).order_by(LotteryApplication.confirmation_num).all()
        picker = _picker_context(session)
        partition_lookup = {str(p.id): p.name for p in picker['partitions']}
        return {
            'lottery_run': lottery_run,
            'applications': applications,
            'partition_lookup': partition_lookup,
            'message': message,
            **picker,
        }

    def update_lottery_run(self, session, id, name, **params):
        _require_post_csrf(params, redirect=f'lottery_run_detail?id={id}')
        lottery_run = session.query(LotteryRun).get(id)
        lottery_run.name = name
        session.commit()
        raise HTTPRedirect('lottery_run_detail?id={}&message={}', id, 'Run name updated.')

    def update_run_card_deadline(self, session, id, card_deadline='',
                                 propagate='', csrf_token=None):
        """Edit LotteryRun.card_deadline. Optionally retroactively apply
        the new deadline to RoomAssignments produced by this run that
        haven't been individually overridden.
        """
        from uber.utils import check_csrf
        from dateutil import parser as dateparser
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('lottery_run_detail?id={}', id)
        check_csrf(csrf_token)

        lottery_run = session.query(LotteryRun).get(id)
        if not lottery_run:
            raise HTTPRedirect('lottery_runs?message={}', 'Run not found.')

        new_deadline = None
        if card_deadline.strip():
            try:
                new_deadline = dateparser.parse(card_deadline).replace(tzinfo=c.EVENT_TIMEZONE)
            except (ValueError, TypeError):
                raise HTTPRedirect(
                    'lottery_run_detail?id={}&message={}',
                    id, 'Could not parse the deadline.')

        original = lottery_run.card_deadline
        lottery_run.card_deadline = new_deadline
        session.add(lottery_run)

        propagated_count = 0
        if propagate == '1' and new_deadline:
            from uber.models import RoomAssignment
            target_date = new_deadline.date()
            assignments = session.query(RoomAssignment).filter_by(
                lottery_run_id=lottery_run.id).all()
            original_date = original.date() if original else None
            for ra in assignments:
                # Only push the new deadline onto rows that match the prior
                # run-level deadline - leaving per-assignment overrides
                # alone, per the plan.
                if (ra.deposit_cutoff_date is None
                        or ra.deposit_cutoff_date == original_date):
                    ra.deposit_cutoff_date = target_date
                    session.add(ra)
                    propagated_count += 1

        session.commit()
        msg = "Card deadline updated."
        if propagated_count:
            msg += f" Pushed to {propagated_count} assignment(s)."
        raise HTTPRedirect('lottery_run_detail?id={}&message={}', id, msg)

    def update_assignment_deadline(self, session, id, deposit_cutoff_date='',
                                   csrf_token=None):
        """Override deposit_cutoff_date on a single RoomAssignment.

        Empty value clears the override, letting the run-level deadline
        govern again.
        """
        from uber.utils import check_csrf
        from uber.models import RoomAssignment
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('index')
        check_csrf(csrf_token)

        assignment = session.query(RoomAssignment).get(id)
        if not assignment:
            raise HTTPRedirect('index?message={}', 'Assignment not found.')

        if deposit_cutoff_date.strip():
            try:
                assignment.deposit_cutoff_date = date.fromisoformat(
                    deposit_cutoff_date.strip())
            except ValueError:
                raise HTTPRedirect('assign_room?id={}&message={}', id,
                                   'Could not parse the deadline.')
        else:
            assignment.deposit_cutoff_date = None
        session.add(assignment)
        session.commit()
        raise HTTPRedirect('assign_room?id={}&message={}', id,
                           'Deadline updated.')

    def award_run(self, session, id, **params):
        from uber.models import RoomAssignment

        _require_post_csrf(params, redirect=f'lottery_run_detail?id={id}')
        lottery_run = session.query(LotteryRun).get(id)
        if lottery_run.status != c.LOTTERY_PENDING:
            raise HTTPRedirect('lottery_run_detail?id={}&message={}', id, 'This run cannot be awarded.')

        applications = session.query(LotteryApplication).join(LotteryApplication.attendee).filter(
            LotteryApplication.lottery_run_id == id,
            LotteryApplication.status == c.PROCESSED,
            Attendee.hotel_lottery_eligible == True,
        ).all()

        # Compute the per-run deposit_cutoff_date once and stamp it on
        # every RoomAssignment in this run that doesn't already carry an
        # override. The application's own status flips to AWARDED.
        run_deadline_date = None
        if c.HOTEL_LOTTERY_GUARANTEE_HOURS:
            dt = (localized_now() + timedelta(hours=c.HOTEL_LOTTERY_GUARANTEE_HOURS)).strftime('%Y-%m-%d')
            run_deadline_date = datetime.strptime(dt + ' 23:59', '%Y-%m-%d %H:%M').date()

        for app in applications:
            app.status = c.AWARDED
            session.add(app)
            if run_deadline_date:
                for ra in session.query(RoomAssignment).filter_by(
                        lottery_application_id=app.id,
                        lottery_run_id=lottery_run.id).all():
                    if not ra.deposit_cutoff_date:
                        ra.deposit_cutoff_date = run_deadline_date
                        session.add(ra)

        lottery_run.status = c.LOTTERY_AWARDED
        lottery_run.awarded_at = datetime.now(UTC)
        session.commit()
        raise HTTPRedirect('lottery_run_detail?id={}&message={}', id,
                           f"{len(applications)} entries awarded.")

    def revert_run(self, session, id, **params):
        from uber.models import RoomAssignment

        _require_post_csrf(params, redirect=f'lottery_run_detail?id={id}')
        lottery_run = session.query(LotteryRun).get(id)
        if lottery_run.status != c.LOTTERY_PENDING:
            raise HTTPRedirect('lottery_run_detail?id={}&message={}', id, 'This run cannot be reverted.')

        applications = session.query(LotteryApplication).filter(
            LotteryApplication.lottery_run_id == id,
            LotteryApplication.status == c.PROCESSED,
        ).all()

        for app in applications:
            app.status = c.COMPLETE
            app.partition_id = None
            app.lottery_run_id = None
            session.add(app)

        # Drop the RoomAssignment rows materialized by this run - connectors
        # included. parent_assignment_id rows resolve through CASCADE on the
        # FK once we delete the parent, but we delete connectors explicitly
        # first for clarity.
        deleted_assignments = session.query(RoomAssignment).filter_by(
            lottery_run_id=lottery_run.id).count()
        session.query(RoomAssignment).filter_by(
            lottery_run_id=lottery_run.id).delete(synchronize_session=False)

        lottery_run.status = c.LOTTERY_REVERTED
        lottery_run.reverted_at = datetime.now(UTC)
        session.commit()
        raise HTTPRedirect('lottery_runs?message={}',
                           f"Run '{lottery_run.name}' reverted. {len(applications)} entries reset to complete, "
                           f"{deleted_assignments} room assignment(s) cleared.")

    def delete_run(self, session, id, **params):
        from uber.models import RoomAssignment

        _require_post_csrf(params, redirect=f'lottery_run_detail?id={id}')
        lottery_run = session.query(LotteryRun).get(id)
        if lottery_run.status != c.LOTTERY_REVERTED:
            raise HTTPRedirect('lottery_run_detail?id={}&message={}', id, 'Only reverted runs can be deleted.')

        # Defensive: clear any stray RoomAssignments still pointing at this run.
        session.query(RoomAssignment).filter_by(
            lottery_run_id=lottery_run.id).delete(synchronize_session=False)

        name = lottery_run.name
        session.delete(lottery_run)
        session.commit()
        raise HTTPRedirect('lottery_runs?message={}', f"Run '{name}' has been deleted.")

    def manage_inventory(self, session, message=''):
        inventory = session.query(HotelRoomInventory).order_by(
            HotelRoomInventory.hotel_id, HotelRoomInventory.is_suite, HotelRoomInventory.name).all()

        # Count assigned per block
        assigned_counts = session.query(
            RoomAssignment.inventory_id, func.count(RoomAssignment.id)
        ).filter(
            RoomAssignment.is_live,
            RoomAssignment.inventory_id.isnot(None),
        ).group_by(RoomAssignment.inventory_id).all()
        assigned_per_block = defaultdict(int, {str(inv_id): cnt for inv_id, cnt in assigned_counts})

        return {
            'inventory': inventory,
            'assigned_per_block': assigned_per_block,
            'message': message,
            **_picker_context(session),
        }

    def edit_inventory_item(self, session, id=None, message='', **params):
        if id in [None, '', 'None']:
            item = HotelRoomInventory()
        else:
            item = session.hotel_room_inventory(id)

        # Build hotel night dates for per-night quantity grid
        event_nights = _event_nights()

        forms = load_forms(params, item, ['HotelInventoryConfig'])

        if cherrypy.request.method == 'POST':
            config = forms['hotel_inventory_config']
            if any(getattr(config, f).data is None
                   for f in ('quantity', 'capacity', 'min_capacity')):
                raise HTTPRedirect('edit_inventory_item?id={}&message={}',
                                   '' if item.is_new else item.id,
                                   'Quantity, capacity, and min capacity must be numbers.')

            was_active = not item.is_new and item.active
            for form in forms.values():
                form.populate_obj(item, is_admin=True)
            # A block is either a room block or a suite block - blank out
            # whichever type doesn't apply.
            if item.is_suite:
                item.room_type_id = None
            else:
                item.suite_type_id = None
            item.vault_reference = item.vault_reference or None
            became_inactive = was_active and not item.active
            session.add(item)
            session.flush()

            # Save per-night quantities
            existing_nq = {nq.night_date: nq for nq in item.night_quantities}
            for night in event_nights:
                qty_str = params.get(f'night_qty_{night.isoformat()}', '')
                if qty_str != '':
                    try:
                        qty = int(qty_str)
                    except (ValueError, TypeError):
                        continue
                    if night in existing_nq:
                        existing_nq[night].quantity = qty
                    else:
                        nq = InventoryNightQuantity(inventory_id=item.id, night_date=night, quantity=qty)
                        session.add(nq)

            session.commit()

            # Notify applicants whose preferences referenced this block if it
            # was just deactivated. Async + best-effort - failures don't roll
            # back the inventory change.
            if became_inactive:
                _notify_applicants_of_inventory_change(session, item)

            # Auto-process waitlist for this inventory block
            waitlist_result = _fulfill_waitlist(session, inventory_id=str(item.id))
            save_msg = 'Inventory item saved.'
            if waitlist_result['fulfilled'] > 0:
                save_msg += f" Waitlist: {waitlist_result['fulfilled']} entries fulfilled."

            raise HTTPRedirect('manage_inventory?message={}', save_msg)

        return {
            'item': item,
            'forms': forms,
            'event_nights': event_nights,
            'message': message,
        }

    def settings(self, session, message=''):
        return {
            'message': message,
        }

    @ajax
    def vault_usage(self, session, month=''):
        if not c.VAULT_ENABLED:
            return {'error': 'Vault integration is not enabled.'}

        from uber.vault import get_usage, get_billing

        try:
            usage = get_usage(month=month if month else None)
            billing = get_billing()
            return {'success': True, 'usage': usage, 'billing': billing}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def manage_hotels(self, session, message=''):
        hotels = session.query(LotteryHotel).order_by(LotteryHotel.name).all()
        return {
            'hotels': hotels,
            'message': message,
        }

    def edit_hotel(self, session, id=None, message='', **params):
        if id in [None, '', 'None']:
            hotel = LotteryHotel()
        else:
            hotel = session.lottery_hotel(id)

        forms = load_forms(params, hotel, ['LotteryHotelConfig'])

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                form.populate_obj(hotel, is_admin=True)
            session.add(hotel)
            session.commit()
            raise HTTPRedirect('manage_hotels?message={}', f"Hotel '{hotel.name}' saved.")

        return {
            'hotel': hotel,
            'forms': forms,
            'message': message,
        }

    def manage_room_types(self, session, message=''):
        room_types = session.query(LotteryRoomType).order_by(
            LotteryRoomType.is_suite, LotteryRoomType.name).all()
        # Pre-compute parent/children maps the template uses for the chain
        # column - saves N+1 lookups when rendering. A parent's children
        # are all rows whose `connects_to_type_id` points back at it.
        by_id = {rt.id: rt for rt in room_types}
        children_by_parent = {rt.id: [] for rt in room_types}
        for rt in room_types:
            if rt.connects_to_type_id and rt.connects_to_type_id in children_by_parent:
                children_by_parent[rt.connects_to_type_id].append(rt)
        return {
            'room_types': room_types,
            'by_id': by_id,
            'children_by_parent': children_by_parent,
            'message': message,
        }

    def edit_room_type(self, session, id=None, message='', **params):
        if id in [None, '', 'None']:
            room_type = LotteryRoomType()
            is_new = True
        else:
            room_type = session.lottery_room_type(id)
            is_new = False

        # All other active types - drives the "Follows another room type"
        # select. Sorted by suite-first then name so visually grouped.
        siblings = (session.query(LotteryRoomType)
                    .filter(LotteryRoomType.id != room_type.id)
                    .order_by(LotteryRoomType.is_suite.desc(), LotteryRoomType.name)
                    .all()) if not is_new else (
                        session.query(LotteryRoomType)
                        .order_by(LotteryRoomType.is_suite.desc(), LotteryRoomType.name)
                        .all())
        # Types that follow *this* one - when non-empty, this type is a
        # parent and cannot itself be a child (no chaining), so the
        # template renders the connector controls read-only.
        children = (session.query(LotteryRoomType)
                    .filter(LotteryRoomType.connects_to_type_id == room_type.id)
                    .order_by(LotteryRoomType.name).all()) if not is_new else []

        forms = load_forms(params, room_type, ['LotteryRoomTypeConfig'])
        # The "follows" options depend on the row being edited (no self,
        # no types that already follow another), so they're filled in
        # per-request rather than via dynamic_choices_fields.
        forms['lottery_room_type_config'].connects_to_type_id.choices = (
            [('', '(None - standalone room type)')] +
            [(str(sib.id), '{}{}'.format(sib.name, ' (suite)' if sib.is_suite else ''))
             for sib in siblings if not sib.connects_to_type_id])

        if cherrypy.request.method == 'POST':
            config = forms['lottery_room_type_config']
            return_id = '' if room_type.is_new else room_type.id

            # Connector ("follows") config. The cycle/chain guard runs
            # both here (clear feedback) and in the model_checks.py
            # validator (catches API/back-door writes).
            raw_parent = (config.connects_to_type_id.data or '').strip()
            parent = None
            if raw_parent:
                if children:
                    raise HTTPRedirect(
                        'edit_room_type?id={}&message={}', return_id,
                        "Cannot make this room type follow another while other "
                        "room types follow it. Detach the children first.")
                if raw_parent == room_type.id:
                    raise HTTPRedirect(
                        'edit_room_type?id={}&message={}', return_id,
                        "A room type cannot follow itself.")
                parent = session.query(LotteryRoomType).get(raw_parent)
                if not parent:
                    raise HTTPRedirect(
                        'edit_room_type?id={}&message={}', return_id,
                        "Selected parent room type not found.")
                # Don't allow chains: refuse if the chosen parent itself
                # follows another type.
                if parent.connects_to_type_id:
                    raise HTTPRedirect(
                        'edit_room_type?id={}&message={}', return_id,
                        "Cannot follow a room type that already follows another. "
                        "Chains are not supported.")

            for form in forms.values():
                form.populate_obj(room_type, is_admin=True)

            if parent:
                room_type.connects_to_type_id = parent.id
                room_type.connector_quantity = max(1, config.connector_quantity.data or 1)
            else:
                room_type.connects_to_type_id = None
                room_type.connector_quantity = 0

            session.add(room_type)
            session.commit()
            raise HTTPRedirect('manage_room_types?message={}', f"Room type '{room_type.name}' saved.")

        return {
            'room_type': room_type,
            'forms': forms,
            'siblings': siblings,
            'children': children,
            'message': message,
        }

    # The booking spreadsheet layout (and the guard rails around CC
    # data) lives in uber.hotel_exports; these handlers are the routes
    # that serve it per hotel.

    @csv_file
    def export_hotel_bookings_csv(self, out, session, hotel_id):
        """Per-hotel booking CSV. CC tokens omitted by design."""
        hotel, rows = booking_export_data(session, hotel_id)
        if hotel is None:
            return
        out.writerow(booking_columns())
        for row in rows:
            out.writerow(row)

    @xlsx_file
    def export_hotel_bookings_xlsx(self, out, session, hotel_id):
        """Per-hotel booking XLSX. CC tokens omitted by design."""
        hotel, rows = booking_export_data(session, hotel_id)
        if hotel is None:
            return
        out.writerow(booking_columns())
        for row in rows:
            out.writerow(row)

    def import_hotel_bookings_csv(self, session, hotel_id, csrf_token=None,
                                  bookings_csv=None, bookings_file=None, **params):
        """Back-import the same CSV/XLSX layout we export, populating
        hotel_confirmation_number (and cancellation_confirmation_number on
        the corresponding RoomAssignment, when present). Refuses any file
        that includes a column starting with `cc_token` - those don't
        belong in a spreadsheet.

        Accepts either a `.csv` or `.xlsx` upload. The form's file input
        is named `bookings_file`; the older `bookings_csv` name is kept
        as a fallback so any in-flight bookmarks keep working.
        """
        from uber.models import RoomAssignment
        from uber.utils import check_csrf as _check_csrf

        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('export_tracking')
        _check_csrf(csrf_token)

        upload = bookings_file or bookings_csv
        if not upload or not getattr(upload, 'file', None):
            raise HTTPRedirect(
                'export_tracking?message={}',
                'No file uploaded.')

        filename = (getattr(upload, 'filename', '') or '').lower()
        raw = upload.file.read()
        is_xlsx = filename.endswith(('.xlsx', '.xlsm')) or raw[:2] == b'PK'

        # Shared CSV/XLSX parser (uber.hotel_imports): case-insensitive
        # headers, XLSX date cells rendered as ISO strings.
        reader_fieldnames, reader_iter, parse_error = parse_spreadsheet(raw, filename)
        if parse_error:
            raise HTTPRedirect(
                'export_tracking?message={}',
                f"Could not read uploaded file: {parse_error}")

        # Guard against any column carrying CC vault tokens.
        sensitive = [
            f for f in (reader_fieldnames or [])
            if f and f.lower().startswith('cc_token')
        ]
        if sensitive:
            raise HTTPRedirect(
                'export_tracking?message={}',
                f"Refusing to import: file contains credit-card token "
                f"column(s) ({', '.join(sensitive)}). "
                f"Strip them and re-upload.")

        updated = 0
        cancelled = 0
        date_updates = 0
        unmatched = []

        for row in reader_iter:
            app_id = (row.get('lottery_application_id') or '').strip()
            conf = (row.get('confirmation_num') or '').strip()
            new_conf = (row.get('hotel_confirmation_number') or '').strip()
            cancel_num = (row.get('cancellation_confirmation_number') or '').strip()
            new_ci = parse_iso_date(row.get('check_in_date'))
            new_co = parse_iso_date(row.get('check_out_date'))

            if not (new_conf or cancel_num or new_ci or new_co):
                continue  # Nothing to update for this row.

            app = None
            if app_id:
                app = session.query(LotteryApplication).filter_by(id=app_id).first()
            if not app and conf:
                app = (session.query(LotteryApplication)
                       .filter_by(confirmation_num=conf).first())
            if not app:
                unmatched.append(conf or app_id or '(blank)')
                continue

            if new_conf:
                # Hotel confirmation number lives on RoomAssignment only.
                # Write to every assignment for this app whose value differs.
                ras = (session.query(RoomAssignment)
                       .filter_by(lottery_application_id=app.id).all())
                touched_any = False
                for ra in ras:
                    if (ra.hotel_confirmation_number or '') != new_conf:
                        ra.hotel_confirmation_number = new_conf
                        session.add(ra)
                        _send_confirmation_updated_email(session, ra)
                        touched_any = True
                if touched_any:
                    updated += 1

            if cancel_num:
                ras = (session.query(RoomAssignment)
                       .filter_by(lottery_application_id=app.id).all())
                for ra in ras:
                    if ra.cancellation_confirmation_number != cancel_num:
                        ra.cancellation_confirmation_number = cancel_num
                        # The model's presave flips status to CANCELLED.
                        session.add(ra)
                        cancelled += 1

            # Date columns: persist directly to every matching
            # RoomAssignment row whose dates differ.
            ras_for_app = (session.query(RoomAssignment)
                           .filter_by(lottery_application_id=app.id).all())
            for ra in ras_for_app:
                touched = False
                if new_ci and ra.assigned_check_in_date != new_ci:
                    ra.assigned_check_in_date = new_ci
                    touched = True
                if new_co and ra.assigned_check_out_date != new_co:
                    ra.assigned_check_out_date = new_co
                    touched = True
                if touched:
                    session.add(ra)
                    date_updates += 1

        # One HotelExportLog entry summarizing the import.
        if updated or cancelled or date_updates:
            session.add(HotelExportLog(
                hotel_id=hotel_id,
                export_type='confirmation_import',
                record_count=updated + cancelled + date_updates,
                notes=(f"{('XLSX' if is_xlsx else 'CSV')} upload: "
                       f"{updated} confirmation(s), "
                       f"{cancelled} cancellation(s), "
                       f"{date_updates} date update(s)"),
            ))
        session.commit()

        msg_parts = []
        if updated:
            msg_parts.append(f"{updated} confirmation update(s)")
        if cancelled:
            msg_parts.append(f"{cancelled} cancellation(s)")
        if date_updates:
            msg_parts.append(f"{date_updates} date update(s)")
        if unmatched:
            msg_parts.append(
                f"{len(unmatched)} unmatched row(s): "
                f"{', '.join(unmatched[:5])}"
                f"{'...' if len(unmatched) > 5 else ''}")
        message = "; ".join(msg_parts) or "No matching rows to import."
        raise HTTPRedirect('export_tracking?message={}', message)

    def hotel_export_details(self, session, hotel_id, page='1', page_size='25'):
        """Per-room export/import detail for a single hotel, used by the
        modal on the export tracking page. Returns a server-rendered
        partial (no base layout) for direct injection into the modal body.

        Each booking gets a `sync_status` of:
          - in_sync:               exported, has confirmation #, not modified since
          - pending_export:        exported but modified after the export ran
          - awaiting_confirmation: exported, no hotel confirmation # yet
          - never_exported:        no export log for this hotel yet

        The list paginates server-side so a hotel with hundreds of bookings
        doesn't pile the full table into the modal at once. The modal's JS
        re-injects the partial when page links are clicked.
        """
        hotel = session.query(LotteryHotel).filter_by(id=hotel_id).first()
        if not hotel:
            return {'hotel': None, 'bookings': [], 'page': 1,
                    'page_size': 25, 'total': 0, 'page_count': 0}

        last_export = (session.query(HotelExportLog)
                       .filter(HotelExportLog.hotel_id == hotel.id,
                               HotelExportLog.export_type == 'room_export')
                       .order_by(HotelExportLog.exported_at.desc())
                       .first())

        try:
            page_num = max(1, int(page))
        except (TypeError, ValueError):
            page_num = 1
        try:
            ps = max(5, min(200, int(page_size)))
        except (TypeError, ValueError):
            ps = 25

        hotel_inventory_ids = [str(inv.id) for inv in
                               session.query(HotelRoomInventory).filter_by(hotel_id=hotel.id).all()]

        base_q = (session.query(RoomAssignment)
                  .filter(RoomAssignment.inventory_id.in_(hotel_inventory_ids),
                          RoomAssignment.is_live))
        total = base_q.count()
        page_count = max(1, (total + ps - 1) // ps)
        if page_num > page_count:
            page_num = page_count

        assignments = (base_q
                       .order_by(RoomAssignment.parent_assignment_id.asc().nullsfirst(),
                                 RoomAssignment.created.asc())
                       .offset((page_num - 1) * ps)
                       .limit(ps)
                       .all())

        bookings = [{
            'assignment': ra,
            'app': ra.lottery_application,
            'sync_status': derive_sync_status(ra, last_export),
        } for ra in assignments]

        return {
            'hotel': hotel,
            'last_export': last_export,
            'bookings': bookings,
            'page': page_num,
            'page_size': ps,
            'total': total,
            'page_count': page_count,
        }

    def export_tracking(self, session, message=''):
        hotels = compute_export_tracking(session)

        import_files = session.query(HotelImportFile).order_by(
            HotelImportFile.uploaded_at.desc()).all()

        return {
            'hotels': hotels,
            'message': message,
            'import_files': import_files,
            'all_hotels': session.query(LotteryHotel).order_by(LotteryHotel.name).all(),
        }

    def upload_confirmation_file(self, session, hotel_id=None, message='', **params):
        """Admin upload of a hotel confirmation/cancellation file.

        Uses the same parsing, application, and file retention as the
        uber-vault hotel portal, so admin-uploaded files appear in the exports
        list alongside portal uploads.
        """
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('export_tracking')

        upload = params.get('import_file')
        if upload is None or not getattr(upload, 'file', None):
            raise HTTPRedirect('export_tracking?message={}', 'Please choose a file to upload.')

        raw = upload.file.read()
        if len(raw) > 5 * 1024 * 1024:
            raise HTTPRedirect('export_tracking?message={}', 'File is too large (5 MB max).')

        hotel = session.query(LotteryHotel).get(hotel_id) if hotel_id else None
        account = session.current_admin_account()
        uploaded_by = account.attendee.full_name if account and account.attendee else 'Admin'

        from uber.hotel_imports import import_confirmation_file
        result = import_confirmation_file(
            session, raw, getattr(upload, 'filename', ''), hotel=hotel,
            source='admin', uploaded_by=uploaded_by,
            content_type=getattr(upload, 'content_type', '') or '')

        if result.get('error'):
            message = f"File saved, but could not be parsed: {result['error']}"
        else:
            message = f"Imported {result['updated']} update(s), {result['unchanged']} unchanged."
        raise HTTPRedirect('export_tracking?message={}', message)

    def download_import_file(self, session, id):
        """Download a previously uploaded hotel import file."""
        record = session.query(HotelImportFile).get(id)
        if not record or not record.filepath or not os.path.exists(record.filepath):
            raise cherrypy.HTTPError(404, "File not found")
        return serve_file(record.filepath, disposition='attachment',
                          name=record.filename or os.path.basename(record.filepath),
                          content_type=record.content_type or 'application/octet-stream')

    def run_lottery(self, session, lottery_group="attendee", lottery_type="room", run_name="", **params):
        # Running a lottery mutates dozens of applications and creates
        # RoomAssignment rows - it must never fire on a bare GET.
        _require_post_csrf(params)

        if lottery_type == "room":
            lottery_type_val = c.ROOM_ENTRY
        elif lottery_type == "suite":
            lottery_type_val = c.SUITE_ENTRY
        else:
            return {'error': f'Invalid lottery type: {lottery_type}'}
        cutoff = None
        if params.get('cutoff', ''):
            cutoff = dateparser.parse(params['cutoff']).replace(tzinfo=c.EVENT_TIMEZONE)

        confirmation_window_start = None
        if params.get('confirmation_window_start', ''):
            confirmation_window_start = dateparser.parse(
                params['confirmation_window_start']).replace(tzinfo=c.EVENT_TIMEZONE)

        # Eligibility (status, cutoff, optional re-confirmation gate,
        # entry-type + staff/attendee scoping) lives with the solver.
        applications = build_eligible_applications(
            session, lottery_type_val, lottery_group,
            cutoff=cutoff, confirmation_window_start=confirmation_window_start)

        # Count already-assigned rooms per inventory block per night,
        # sourced from RoomAssignment. Connector rooms count against their
        # own inventory's capacity; primary rooms count against theirs -
        # both are RoomAssignment rows.
        already_assigned_query = session.query(RoomAssignment).filter(
            RoomAssignment.is_live,
            RoomAssignment.inventory_id.isnot(None),
        )

        # Partition filter: only count same-partition assignments toward capacity
        partition_filter = params.get('partition_filter', '')
        inventory_filter = params.get('inventory_filter', '')

        if partition_filter:
            already_assigned = already_assigned_query.filter(
                RoomAssignment.partition_id == partition_filter).all()
        else:
            already_assigned = already_assigned_query.filter(
                RoomAssignment.partition_id == None).all()  # noqa: E711

        assigned_per_block_night = count_assigned_per_block_night(already_assigned)

        is_suite = lottery_type_val == c.SUITE_ENTRY
        inventory_table = HotelRoomInventory.get_inventory(session, is_suite=is_suite)

        # Apply filters
        hotel_filter = params.get('hotel_filter', '')
        room_type_filter = params.get('room_type_filter', '')
        inventory_table = filter_inventory_table(
            inventory_table, hotel_filter, room_type_filter, inventory_filter)

        # Build partition allocation maps
        partition_qty_map = {}  # {block_id: cap} for the selected partition
        total_partitioned_map = {}  # {block_id: total across all partitions}
        if partition_filter:
            for pb in session.query(InventoryPartitionBlock).filter_by(partition_id=partition_filter).all():
                partition_qty_map[str(pb.inventory_id)] = pb.quantity
        else:
            # For non-partitioned runs, compute total partitioned allocation per block
            for pb in session.query(InventoryPartitionBlock).all():
                bid = str(pb.inventory_id)
                total_partitioned_map[bid] = total_partitioned_map.get(bid, 0) + pb.quantity

        available_rooms = adjust_available_rooms(
            inventory_table, partition_filter, partition_qty_map,
            total_partitioned_map, assigned_per_block_night)

        rooms_available_before = sum([x['quantity'] for x in available_rooms])

        # Build type-level connector map for the solver. Each child type
        # points at its parent + how many of itself the parent needs.
        connector_map = {}
        for rt in session.query(LotteryRoomType).filter(
                LotteryRoomType.connects_to_type_id.isnot(None),
                LotteryRoomType.connector_quantity > 0).all():
            connector_map[str(rt.id)] = (str(rt.connects_to_type_id), rt.connector_quantity)

        allocations = solve_lottery(
            applications, available_rooms,
            lottery_type=lottery_type_val,
            connector_map=connector_map,
        ) or []

        # Create LotteryRun record
        lottery_run = LotteryRun(
            name=run_name or f"{lottery_group}_{lottery_type}_{localized_now().strftime('%Y%m%d_%H%M%S')}",
            lottery_group=lottery_group,
            lottery_type=lottery_type,
            cutoff=cutoff,
            confirmation_window_start=confirmation_window_start,
            hotel_filter=hotel_filter or None,
            room_type_filter=room_type_filter or None,
            inventory_filter=inventory_filter or None,
            partition_filter=partition_filter or None,
            entries_considered=len([x for x in applications if x.entry_type != c.GROUP_ENTRY]),
            rooms_available_before=rooms_available_before,
        )
        session.add(lottery_run)
        session.flush()

        # Deadline stamped on every RoomAssignment from this run (per-assignment
        # override remains possible later).
        run_deadline = lottery_run.card_deadline.date() if lottery_run.card_deadline else None

        # Move the awarded leaders' apps to PROCESSED so they can be moved
        # to AWARDED in the award_run step. Group members come along via
        # parent_application_id; they stay COMPLETE on the app side and
        # are added as occupants of the leader's RoomAssignment rows.
        awarded_leader_ids = {leader_id for leader_id, _inv, _role in allocations}
        for application in applications:
            if application.id in awarded_leader_ids and not application.parent_application:
                application.lottery_run_id = lottery_run.id
                application.status = c.PROCESSED
                if partition_filter:
                    application.partition_id = partition_filter
                session.add(application)

        # Materialize RoomAssignment rows (primary + connectors) per leader.
        num_rooms_assigned = materialize_room_assignments(
            session, applications, allocations, lottery_run, run_deadline,
            partition_filter)

        lottery_run.rooms_assigned = num_rooms_assigned
        session.commit()

        raise HTTPRedirect('lottery_run_detail?id={}&message={}', lottery_run.id,
                           f"Lottery run complete: {num_rooms_assigned} rooms assigned.")
    
    def hotel_inventory(self, session, message='', partition='all'):
        # Build event night dates
        event_nights = _event_nights()

        partitions = session.query(InventoryPartition).filter_by(active=True).order_by(InventoryPartition.name).all()

        # Determine partition filter for assigned/waitlist counting
        # partition='all' -> count all apps, show full capacity
        # partition='default' -> count only non-partitioned apps, show capacity minus partition allocations
        # partition=<uuid> -> count only that partition's apps, show partition allocation as capacity
        filter_partition_id = None
        filtering_default = False
        if partition == 'default':
            filtering_default = True
        elif partition not in ('all', ''):
            filter_partition_id = partition

        # Get assigned rooms, optionally filtered by partition, sourced from
        # RoomAssignment. Waitlist demand is read straight off the
        # assignment's waitlisted_* columns, which reflect the current
        # per-room request rather than the original lottery entry.
        ra_query = (session.query(RoomAssignment)
                    .filter(RoomAssignment.is_live,
                            RoomAssignment.inventory_id.isnot(None)))
        if filter_partition_id:
            ra_query = ra_query.filter(RoomAssignment.partition_id == filter_partition_id)
        elif filtering_default:
            ra_query = ra_query.filter(RoomAssignment.partition_id == None)  # noqa: E711
        assigned_ras = ra_query.all()

        (assigned_per_block_night, status_per_block,
         waitlist_per_block_night) = _count_inventory_usage(assigned_ras)

        # Build partition allocation maps for capacity adjustments
        partition_alloc_per_block = {}  # {block_id: allocation} for the selected partition
        total_partitioned_per_block = defaultdict(int)  # {block_id: sum of all partition allocations}
        if filter_partition_id:
            for pb in session.query(InventoryPartitionBlock).filter_by(partition_id=filter_partition_id).all():
                partition_alloc_per_block[str(pb.inventory_id)] = pb.quantity
        for pb in session.query(InventoryPartitionBlock).all():
            total_partitioned_per_block[str(pb.inventory_id)] += pb.quantity

        hotel_lookup = {str(h.id): h for h in session.query(LotteryHotel).all()}

        def effective_capacity(block_id, block_qty):
            if filter_partition_id:
                return min(partition_alloc_per_block.get(block_id, 0), block_qty)
            elif filtering_default:
                return max(0, block_qty - total_partitioned_per_block.get(block_id, 0))
            else:
                return block_qty

        def build_inventory_data(is_suite):
            inventory = defaultdict(list)
            for inv in session.query(HotelRoomInventory).filter_by(is_suite=is_suite, active=True).all():
                hotel_obj = hotel_lookup.get(str(inv.hotel_id))
                block_id = str(inv.id)
                nq_map = inv.night_quantity_map

                night_data = []
                for night in event_nights:
                    raw_qty = nq_map.get(night, inv.quantity) if nq_map else inv.quantity
                    available = effective_capacity(block_id, raw_qty)
                    assigned = assigned_per_block_night.get(block_id, {}).get(night, 0)
                    waitlisted = waitlist_per_block_night.get(block_id, {}).get(night, 0)
                    night_data.append({
                        'night': night,
                        'available': available,
                        'assigned': assigned,
                        'remaining': max(0, available - assigned),
                        'waitlisted': waitlisted,
                    })

                total_assigned = sum(status_per_block.get(block_id, {}).values())
                info = {
                    'inventory': inv,
                    'room_type': inv.suite_type if is_suite else inv.room_type,
                    'quantity': effective_capacity(block_id, inv.quantity),
                    'nights': night_data,
                    'total_assigned': total_assigned,
                    c.PROCESSED: status_per_block.get(block_id, {}).get(c.PROCESSED, 0),
                    c.AWARDED: status_per_block.get(block_id, {}).get(c.AWARDED, 0),
                    c.SECURED: status_per_block.get(block_id, {}).get(c.SECURED, 0),
                }
                inventory[hotel_obj].append(info)
            return inventory

        # Build chart data: per-night totals by hotel
        chart_data = {}
        for inv in session.query(HotelRoomInventory).filter_by(active=True).all():
            hotel_name = hotel_lookup.get(str(inv.hotel_id), None)
            hotel_name = hotel_name.name if hotel_name else 'Unknown'
            if hotel_name not in chart_data:
                chart_data[hotel_name] = {
                    'available': [0] * len(event_nights),
                    'assigned': [0] * len(event_nights),
                    'waitlisted': [0] * len(event_nights),
                }
            nq_map = inv.night_quantity_map
            block_id = str(inv.id)
            for i, night in enumerate(event_nights):
                raw_qty = nq_map.get(night, inv.quantity) if nq_map else inv.quantity
                chart_data[hotel_name]['available'][i] += effective_capacity(block_id, raw_qty)
                chart_data[hotel_name]['assigned'][i] += assigned_per_block_night.get(block_id, {}).get(night, 0)
                chart_data[hotel_name]['waitlisted'][i] += waitlist_per_block_night.get(block_id, {}).get(night, 0)

        # Build combined total across all hotels
        total = {'available': [0] * len(event_nights), 'assigned': [0] * len(event_nights), 'waitlisted': [0] * len(event_nights)}
        for data in chart_data.values():
            for i in range(len(event_nights)):
                total['available'][i] += data['available'][i]
                total['assigned'][i] += data['assigned'][i]
                total['waitlisted'][i] += data['waitlisted'][i]
        chart_data['_total'] = total

        return {
            'room_inventory': build_inventory_data(is_suite=False),
            'suite_inventory': build_inventory_data(is_suite=True),
            'event_nights': event_nights,
            'partitions': partitions,
            'chart_data': chart_data,
            'now': localized_now(),
            'current_partition': partition,
        }

    @ajax
    def inventory_assignees(self, session, inventory_id, night_date='', partition='all'):
        query = session.query(RoomAssignment).filter(
            RoomAssignment.inventory_id == inventory_id,
            RoomAssignment.is_live,
        )
        if night_date:
            nd = date.fromisoformat(night_date)
            query = query.filter(
                RoomAssignment.assigned_check_in_date <= nd,
                RoomAssignment.assigned_check_out_date > nd,
            )
        if partition == 'default':
            query = query.filter(RoomAssignment.partition_id == None)  # noqa: E711
        elif partition not in ('all', ''):
            query = query.filter(RoomAssignment.partition_id == partition)

        assignments = query.order_by(RoomAssignment.assigned_check_in_date).all()
        assignees = []
        for ra in assignments:
            app = ra.lottery_application
            assignees.append({
                'assignment_id': ra.id,
                'app_id': ra.lottery_application_id or '',
                'attendee_id': str(ra.attendee_id) if ra.attendee_id else '',
                'name': (app.attendee_name if app else (ra.attendee.full_name if ra.attendee else '')),
                'conf_num': (app.confirmation_num if app else '') or '',
                'status': ra.status_label,
                'check_in': ra.assigned_check_in_date.strftime('%a %-m/%-d') if ra.assigned_check_in_date else '',
                'check_out': ra.assigned_check_out_date.strftime('%a %-m/%-d') if ra.assigned_check_out_date else '',
                'partition': ra.partition.name if ra.partition_id and ra.partition else '',
            })
        return {'assignees': assignees}

    @csv_file
    def assigned_entries(self, out, session, lock_entries=''):
        out.writerow(['LotteryRunName', 'StaffEntry?', 'AssignmentReason',
                      'CheckInDate', 'CheckOutDate', 'NumberofGuests', 'HotelName', 'RoomType', 'SpecialRequest', 'AccessibleRoom',
                      'RewardsNumber',
                      'Guest1CheckInDate', 'Guest1CheckOutDate', 'Guest1FirstName', 'Guest1LastName', 'Guest1Phone', 'Guest1Email',
                      'Guest2CheckInDate', 'Guest2CheckOutDate', 'Guest2FirstName', 'Guest2LastName', 'Guest2Phone', 'Guest2Email',
                      'Guest3CheckInDate', 'Guest3CheckOutDate', 'Guest3FirstName', 'Guest3LastName', 'Guest3Phone', 'Guest3Email',
                      'Guest4CheckInDate', 'Guest4CheckOutDate', 'Guest4FirstName', 'Guest4LastName', 'Guest4Phone', 'Guest4Email',])

        # Source is RoomAssignment: one row per assigned room
        # (connectors included). Each line is the hotel's view of one
        # physical reservation.
        assignments = (session.query(RoomAssignment)
                       .filter(RoomAssignment.is_live)
                       .order_by(RoomAssignment.inventory_id, RoomAssignment.created))

        if lock_entries:
            # Lock the SOURCE applications (one app may produce many rooms).
            app_ids_to_lock = {ra.lottery_application_id for ra in assignments
                               if ra.lottery_application_id}
            if app_ids_to_lock:
                for app in session.query(LotteryApplication).filter(
                        LotteryApplication.id.in_(app_ids_to_lock)).all():
                    if not app.export_locked:
                        app.export_locked = True
                        session.add(app)
                session.commit()

        for ra in assignments:
            app = ra.lottery_application
            inv = ra.inventory
            check_in_date = ra.assigned_check_in_date
            check_out_date = ra.assigned_check_out_date
            occupants = ra.effective_occupants
            num_guests = len(occupants)
            hotel_name = (inv.hotel.name if inv and inv.hotel else '')
            if inv and inv.is_suite and inv.suite_type:
                room_type_name = inv.suite_type.name
            elif inv and not inv.is_suite and inv.room_type:
                room_type_name = inv.room_type.name
            else:
                room_type_name = ''
            row = [
                lottery_run := (ra.lottery_run.name if ra.lottery_run else ''),
                (app.is_staff_entry if app else False),
                ra.assignment_reason_label,
                check_in_date, check_out_date, num_guests, hotel_name, room_type_name,
                (app.ada_requests if app else '') or '',
                (app.wants_ada if app else False),
                ra.hotel_rewards_number or '',
            ]
            for i in range(4):
                if i < len(occupants):
                    a = occupants[i]
                    row.extend([check_in_date, check_out_date,
                                a.effective_hotel_first_name or '',
                                a.effective_hotel_last_name or '',
                                a.cellphone or '',
                                a.email or ''])
                else:
                    row.extend(['', '', '', '', '', ''])
            out.writerow(row)
    
    @xlsx_file
    def hotel_inventory_xlsx(self, out, session, hotel_id):
        write_hotel_inventory_xlsx(out, session, hotel_id)

    @multifile_zipfile
    def hotel_inventory_zip(self, zip_file, session):
        for hotel in session.query(LotteryHotel).filter_by(active=True).all():
            hotel_inv_ids = [str(inv.id) for inv in
                             session.query(HotelRoomInventory).filter_by(hotel_id=hotel.id).all()]
            has_assignments = session.query(RoomAssignment).filter(
                RoomAssignment.is_live,
                RoomAssignment.inventory_id.in_(hotel_inv_ids),
            ).first()
            if has_assignments:
                output = self.hotel_inventory_xlsx(hotel_id=hotel.id, set_headers=False)
                zip_file.writestr(f'hotel_inventory_{hotel.name}.xlsx', output)

    @csv_file
    def accepted_dealers(self, out, session):
        out.writerow(['Group Name', 'Group ID', 'Reg ID'])

        for dealer in session.query(Attendee).join(Group, Attendee.group_id == Group.id).filter(
            Group.is_dealer, Group.status.in_(c.DEALER_ACCEPTED_STATUSES)):
            out.writerow([dealer.group.name, dealer.group.id, dealer.id])

    @csv_file
    def interchange_export(self, out, session, staff_lottery=False):
        write_interchange_export(out, session, staff_lottery)

    def manage_partitions(self, session, message=''):
        partitions = session.query(InventoryPartition).order_by(InventoryPartition.name).all()

        # Count assigned per partition (RoomAssignment-sourced).
        assigned_per_partition = defaultdict(int)
        for ra in session.query(RoomAssignment).filter(
            RoomAssignment.is_live,
            RoomAssignment.inventory_id.isnot(None),
        ).all():
            key = str(ra.partition_id) if ra.partition_id else '_none'
            assigned_per_partition[key] += 1

        # Compute total allocation and non-partitioned capacity
        total_partition_alloc = 0
        for p in partitions:
            for b in p.blocks:
                total_partition_alloc += b.quantity

        total_inventory = sum(inv.quantity for inv in session.query(HotelRoomInventory).filter_by(active=True).all())

        return {
            'partitions': partitions,
            'assigned_per_partition': assigned_per_partition,
            'non_partitioned_capacity': max(0, total_inventory - total_partition_alloc),
            'message': message,
        }

    def request_confirmation(self, session, id=None, clear='', csrf_token=None):
        """Set or clear LotteryApplication.confirmation_requested_at.

        When set, the attendee's status page surfaces the Confirm / Withdraw
        prompt and the reconfirm email fires. Clearing removes the prompt
        without touching last_confirmed_at.
        """
        from uber.utils import check_csrf
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('form?id={}', id)
        check_csrf(csrf_token)

        app = session.query(LotteryApplication).get(id)
        if not app:
            raise HTTPRedirect('index?message={}', 'Application not found.')
        if clear:
            app.confirmation_requested_at = None
            msg = 'Confirmation request cleared.'
        else:
            app.confirmation_requested_at = datetime.now(UTC)
            msg = 'Confirmation request sent.'
        session.add(app)
        session.commit()
        raise HTTPRedirect('form?id={}&message={}', id, msg)

    def bulk_request_confirmation(self, session, app_ids='', csrf_token=None):
        """Stamp confirmation_requested_at on many applications at once.

        Accepts a comma-separated string of application IDs from a search-
        results checkbox UI.
        """
        from uber.utils import check_csrf
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('index')
        check_csrf(csrf_token)

        ids = [x.strip() for x in app_ids.split(',') if x.strip()]
        if not ids:
            raise HTTPRedirect('index?message={}', 'No applications selected.')

        apps = session.query(LotteryApplication).filter(
            LotteryApplication.id.in_(ids)).all()
        now = datetime.now(UTC)
        for app in apps:
            app.confirmation_requested_at = now
            session.add(app)
        session.commit()
        raise HTTPRedirect(
            'index?message={}',
            f'Confirmation requested for {len(apps)} application(s).')

    def _apply_cancellation_rows(self, session, rows, apply_changes):
        """Row loop for import_hotel_cancellations. Returns the preview dict.

        confirmation_num matches RoomAssignment.hotel_confirmation_number;
        cancellation_confirmation_number is the hotel's cancel record id
        (optional). Setting cancellation_confirmation_number triggers the
        model presave that flips status to CANCELLED; the cancellation
        email fires on the next email tick.
        """
        from uber.models import RoomAssignment

        preview = {'matched': [], 'already': [], 'unmatched': [], 'applied': 0}

        for row in rows:
            conf = (row.get('confirmation_num') or '').strip()
            cancel_num = (row.get('cancellation_confirmation_number') or '').strip()
            if not conf:
                continue

            assignment = session.query(RoomAssignment).filter_by(
                hotel_confirmation_number=conf).first()
            if not assignment:
                preview['unmatched'].append({
                    'confirmation_num': conf,
                    'cancellation_confirmation_number': cancel_num,
                })
                continue

            if assignment.status == c.CANCELLED:
                preview['already'].append({
                    'assignment': assignment,
                    'cancellation_confirmation_number': cancel_num,
                })
                if apply_changes and cancel_num and not assignment.cancellation_confirmation_number:
                    assignment.cancellation_confirmation_number = cancel_num
                    session.add(assignment)
                    preview['applied'] += 1
                continue

            preview['matched'].append({
                'assignment': assignment,
                'cancellation_confirmation_number': cancel_num,
            })

            if apply_changes:
                assignment.cancellation_confirmation_number = cancel_num or 'imported'
                # cancellation_flips_status presave on the model takes
                # care of status = CANCELLED.
                session.add(assignment)
                preview['applied'] += 1

        return preview

    def _apply_confirmation_rows(self, session, rows, apply_changes):
        """Row loop for import_hotel_confirmations. Returns the preview dict.

        lottery_application_id (preferred) or confirmation_num (matching
        RoomAssignment.hotel_confirmation_number) identify the assignment;
        new_confirmation_num is the value to write.
        """
        from uber.models import RoomAssignment

        preview = {'new': [], 'changed': [], 'unchanged': [], 'unmatched': [], 'applied': 0}

        for row in rows:
            app_id = (row.get('lottery_application_id') or '').strip()
            conf = (row.get('confirmation_num') or '').strip()
            new_conf = (row.get('new_confirmation_num') or '').strip()
            if not new_conf:
                continue

            assignment = None
            if app_id:
                assignment = session.query(RoomAssignment).filter_by(
                    lottery_application_id=app_id).first()
            if not assignment and conf:
                assignment = session.query(RoomAssignment).filter_by(
                    hotel_confirmation_number=conf).first()

            if not assignment:
                preview['unmatched'].append({
                    'lottery_application_id': app_id,
                    'confirmation_num': conf,
                    'new_confirmation_num': new_conf,
                })
                continue

            existing = assignment.hotel_confirmation_number or ''
            if existing == new_conf:
                preview['unchanged'].append({'assignment': assignment})
                continue

            bucket = 'changed' if existing else 'new'
            preview[bucket].append({
                'assignment': assignment,
                'old': existing,
                'new': new_conf,
            })

            if apply_changes:
                assignment.hotel_confirmation_number = new_conf
                session.add(assignment)
                preview['applied'] += 1
                _send_confirmation_updated_email(session, assignment)

        return preview

    # ------------------------------------------------------------------
    # Physical-room catalog: the per-hotel map of real rooms
    # (PhysicalRoom / PhysicalRoomConnection). Logic in uber.hotel_physical.
    # ------------------------------------------------------------------

    def physical_rooms(self, session, hotel_id='', message=''):
        """Per-hotel catalog of physical rooms, grouped by floor."""
        from uber import hotel_physical

        picker = _picker_context(session)
        hotels = picker['hotels']
        hotel = None
        if hotel_id:
            hotel = session.query(LotteryHotel).get(hotel_id)
        elif len(hotels) == 1:
            hotel = hotels[0]

        floors, connections, bookings, blocks = [], {}, {}, []
        if hotel:
            floors = hotel_physical.rooms_by_floor(session, hotel.id)
            connections = hotel_physical.connection_map(session, hotel.id)
            bookings = hotel_physical.live_bookings_by_room(session, hotel.id)
            blocks = [inv for inv in picker['inventory_blocks']
                      if inv.hotel_id == hotel.id]

        return {
            'message': message,
            'hotels': hotels,
            'hotel': hotel,
            'floors': floors,
            'connections': connections,
            'bookings': bookings,
            'blocks': blocks,
            'total_rooms': sum(len(rooms) for _, rooms in floors),
        }

    def edit_physical_room(self, session, id=None, hotel_id='', message='',
                           **params):
        """Create or edit one PhysicalRoom, including its connections."""
        from uber import hotel_physical
        from uber.models.hotel import PhysicalRoom

        if id in [None, '', 'None']:
            room = PhysicalRoom()
            if hotel_id:
                room.hotel_id = hotel_id
        else:
            room = session.physical_room(id)

        forms = load_forms(params, room, ['PhysicalRoomConfig'])

        if cherrypy.request.method == 'POST':
            check_csrf(params.get('csrf_token'))
            for form in forms.values():
                form.populate_obj(room, is_admin=True)
            room.inventory_id = room.inventory_id or None
            if not (room.hotel_id and (room.room_number or '').strip()):
                message = 'Hotel and room number are required.'
            else:
                room.room_number = room.room_number.strip()
                duplicate = session.query(PhysicalRoom).filter(
                    PhysicalRoom.hotel_id == room.hotel_id,
                    PhysicalRoom.room_number == room.room_number,
                    PhysicalRoom.id != room.id).first()
                if duplicate:
                    message = (f'Room {room.room_number} already exists '
                               'at this hotel.')
            if not message:
                session.add(room)
                session.flush()
                connects = (params.get('connects_to') or '').split(',')
                error = hotel_physical.set_connections(session, room, connects)
                if error:
                    session.rollback()
                    message = error
                else:
                    session.commit()
                    raise HTTPRedirect('physical_rooms?hotel_id={}&message={}',
                                       room.hotel_id,
                                       f'Room {room.room_number} saved.')

        from uber.hotel_physical import connection_map
        current_connections = ''
        if not room.is_new:
            current_connections = ', '.join(
                connection_map(session, room.hotel_id).get(room.id, []))

        return {
            'room': room,
            'forms': forms,
            'connects_to': params.get('connects_to', current_connections),
            'message': message,
        }

    def delete_physical_room(self, session, id, csrf_token=None):
        from uber.models.hotel import PhysicalRoom
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('physical_rooms')
        check_csrf(csrf_token)
        room = session.query(PhysicalRoom).get(id)
        if not room:
            raise HTTPRedirect('physical_rooms?message={}', 'Room not found.')
        live = session.query(RoomAssignment).filter(
            RoomAssignment.physical_room_id == room.id,
            RoomAssignment.is_live).count()
        if live:
            raise HTTPRedirect(
                'physical_rooms?hotel_id={}&message={}', room.hotel_id,
                f'Room {room.room_number} has {live} live booking(s) - '
                'unassign them first.')
        hotel_id, number = room.hotel_id, room.room_number
        session.delete(room)  # connection edges cascade via FK
        session.commit()
        raise HTTPRedirect('physical_rooms?hotel_id={}&message={}',
                           hotel_id, f'Room {number} deleted.')

    def bulk_add_physical_rooms(self, session, hotel_id, floor='',
                                prefix='', start='', end='', pad='0',
                                inventory_id='', csrf_token=None):
        from uber import hotel_physical
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('physical_rooms?hotel_id={}', hotel_id)
        check_csrf(csrf_token)
        try:
            start_n, end_n = int(start), int(end)
            pad_n = int(pad or 0)
        except (TypeError, ValueError):
            raise HTTPRedirect('physical_rooms?hotel_id={}&message={}',
                               hotel_id, 'Start, end, and pad must be numbers.')
        if end_n < start_n or end_n - start_n > 999:
            raise HTTPRedirect('physical_rooms?hotel_id={}&message={}',
                               hotel_id,
                               'End must be >= start (max 1000 rooms per add).')
        created, skipped = hotel_physical.bulk_add_rooms(
            session, hotel_id, floor, start_n, end_n,
            prefix=prefix.strip(), pad=pad_n, inventory_id=inventory_id or None)
        session.commit()
        raise HTTPRedirect(
            'physical_rooms?hotel_id={}&message={}', hotel_id,
            f'{created} room(s) created, {skipped} already existed.')

    def import_physical_rooms(self, session, hotel_id='', message='', **params):
        """Spreadsheet import for the physical-room catalog. Two-step
        preview/apply like the confirmation imports; CSV and XLSX via the
        shared parser. Re-imports update rooms in place (keyed by
        room_number within the hotel)."""
        from uber import hotel_physical
        from uber.hotel_imports import parse_spreadsheet

        if cherrypy.request.method == 'POST':
            check_csrf(params.get('csrf_token'))

        picker = _picker_context(session)
        hotel = session.query(LotteryHotel).get(hotel_id) if hotel_id else None
        preview = None
        applied = False

        upload = params.get('import_file')
        if hotel and upload is not None and getattr(upload, 'file', None):
            raw = upload.file.read()
            fieldnames, rows, parse_error = parse_spreadsheet(
                raw, getattr(upload, 'filename', ''))
            if parse_error:
                message = parse_error
            elif 'room_number' not in (fieldnames or []):
                message = 'The file needs a room_number column.'
            else:
                blocks = [inv for inv in picker['inventory_blocks']
                          if inv.hotel_id == hotel.id]
                apply_changes = params.get('apply') == 'true'
                preview = hotel_physical.import_rows(
                    session, hotel, blocks, rows,
                    apply_changes=apply_changes)
                if apply_changes and not preview['errors']:
                    session.commit()
                    applied = True
                    message = (f"Imported {len(preview['created'])} new and "
                               f"{len(preview['updated'])} updated room(s).")

        return {
            'message': message,
            'hotels': picker['hotels'],
            'hotel': hotel,
            'preview': preview,
            'applied': applied,
        }

    # ------------------------------------------------------------------
    # Rooming board: place bookings onto physical rooms.
    # ------------------------------------------------------------------

    def room_board(self, session, hotel_id='', message=''):
        """Per-hotel assignment board: unroomed live bookings on top,
        the catalog by floor (with current occupants) below."""
        from uber import hotel_physical
        from uber.hotel_room_queries import vacant_physical_rooms

        picker = _picker_context(session)
        hotels = picker['hotels']
        hotel = session.query(LotteryHotel).get(hotel_id) if hotel_id else (
            hotels[0] if len(hotels) == 1 else None)

        floors, connections, bookings_by_room = [], {}, {}
        unroomed = []
        if hotel:
            floors = hotel_physical.rooms_by_floor(session, hotel.id)
            connections = hotel_physical.connection_map(session, hotel.id)
            bookings_by_room = hotel_physical.live_bookings_by_room(
                session, hotel.id)
            hotel_inv_ids = [inv.id for inv in picker['inventory_blocks']
                             if inv.hotel_id == hotel.id]
            if hotel_inv_ids:
                pending = (session.query(RoomAssignment).filter(
                    RoomAssignment.physical_room_id.is_(None),
                    RoomAssignment.is_live,
                    RoomAssignment.inventory_id.in_(hotel_inv_ids))
                    .order_by(
                        RoomAssignment.assigned_check_in_date.asc().nullsfirst(),
                        RoomAssignment.created.asc()).all())
                for ra in pending:
                    options = vacant_physical_rooms(
                        session, hotel.id, ra.assigned_check_in_date,
                        ra.assigned_check_out_date,
                        inventory_id=ra.inventory_id)
                    unroomed.append({'ra': ra, 'options': options})

        return {
            'message': message,
            'hotels': hotels,
            'hotel': hotel,
            'floors': floors,
            'connections': connections,
            'bookings': bookings_by_room,
            'unroomed': unroomed,
        }

    def board_assign(self, session, assignment_id, physical_room_id,
                     hotel_id='', csrf_token=None):
        from uber.hotel_room_queries import physical_room_conflicts
        from uber.models.hotel import PhysicalRoom
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('room_board?hotel_id={}', hotel_id)
        check_csrf(csrf_token)
        ra = session.query(RoomAssignment).get(assignment_id)
        room = session.query(PhysicalRoom).get(physical_room_id)
        if not ra or not room:
            raise HTTPRedirect('room_board?hotel_id={}&message={}',
                               hotel_id, 'Booking or room not found.')
        error = _validate_physical_room(session, ra, room)
        if error:
            raise HTTPRedirect('room_board?hotel_id={}&message={}',
                               hotel_id or room.hotel_id, error)
        ra.physical_room_id = room.id
        session.add(ra)
        session.commit()
        raise HTTPRedirect(
            'room_board?hotel_id={}&message={}', hotel_id or room.hotel_id,
            f'Room {room.room_number} assigned.')

    def board_unassign(self, session, assignment_id, hotel_id='',
                       csrf_token=None):
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('room_board?hotel_id={}', hotel_id)
        check_csrf(csrf_token)
        ra = session.query(RoomAssignment).get(assignment_id)
        if not ra:
            raise HTTPRedirect('room_board?hotel_id={}&message={}',
                               hotel_id, 'Booking not found.')
        ra.physical_room_id = None
        session.add(ra)
        session.commit()
        raise HTTPRedirect('room_board?hotel_id={}&message={}', hotel_id,
                           'Physical room unassigned (the room number text '
                           'is kept for reference).')

    def auto_assign_physical(self, session, hotel_id, csrf_token=None):
        from uber import hotel_physical
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('room_board?hotel_id={}', hotel_id)
        check_csrf(csrf_token)
        result = hotel_physical.auto_assign_physical_rooms(session, hotel_id)
        msg = f"Auto-assigned {result['assigned']} booking(s)."
        if result['skipped']:
            msg += f" {len(result['skipped'])} could not be placed."
        raise HTTPRedirect('room_board?hotel_id={}&message={}', hotel_id, msg)

    def clear_physical_assignments(self, session, hotel_id, csrf_token=None):
        from uber.models.hotel import PhysicalRoom
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('room_board?hotel_id={}', hotel_id)
        check_csrf(csrf_token)
        room_ids = [r.id for r in session.query(PhysicalRoom.id)
                    .filter_by(hotel_id=hotel_id).all()]
        cleared = 0
        if room_ids:
            for ra in session.query(RoomAssignment).filter(
                    RoomAssignment.physical_room_id.in_(room_ids),
                    RoomAssignment.is_live).all():
                ra.physical_room_id = None
                session.add(ra)
                cleared += 1
            session.commit()
        raise HTTPRedirect('room_board?hotel_id={}&message={}', hotel_id,
                           f'Cleared {cleared} physical assignment(s).')

    @csv_file
    def front_desk_csv(self, out, session, hotel_id):
        """Front-desk / housekeeping export: every catalogued room in
        floor order with its current booking, for handing to the hotel.
        They may reassign at check-in; we don't get that back."""
        from uber import hotel_physical
        out.writerow(['floor', 'room_number', 'block', 'ada',
                      'out_of_service', 'status', 'guest_first_name',
                      'guest_last_name', 'check_in', 'check_out',
                      'hotel_confirmation_number', 'notes'])
        bookings = hotel_physical.live_bookings_by_room(session, hotel_id)
        for floor, rooms in hotel_physical.rooms_by_floor(session, hotel_id):
            for room in rooms:
                ras = bookings.get(room.id, [])
                if not ras:
                    out.writerow([floor, room.room_number,
                                  room.inventory.display_name if room.inventory else '',
                                  'yes' if room.ada else '',
                                  'yes' if room.out_of_service else '',
                                  'vacant', '', '', '', '', '', room.notes])
                for ra in ras:
                    att = ra.attendee
                    out.writerow([
                        floor, room.room_number,
                        room.inventory.display_name if room.inventory else '',
                        'yes' if room.ada else '',
                        'yes' if room.out_of_service else '',
                        ra.status_label,
                        att.effective_hotel_first_name if att else '',
                        att.effective_hotel_last_name if att else '',
                        ra.assigned_check_in_date or '',
                        ra.assigned_check_out_date or '',
                        ra.hotel_confirmation_number or '',
                        room.notes])

    def _import_hotel_numbers(self, session, kind, message='', **params):
        """Shared implementation behind import_hotel_confirmations and
        import_hotel_cancellations.

        Parses the upload with uber.hotel_imports.parse_confirmation_rows -
        the same parser as the hotel portal - so both pages accept CSV and
        XLSX with case-insensitive headers (spaces treated as underscores).

        Two-step UX: upload shows a preview of what would change. The admin
        then ticks "apply" and resubmits the file to write. Matching
        semantics per kind live in _apply_confirmation_rows /
        _apply_cancellation_rows.
        """
        upload = (params.get('import_file')
                  or params.get('confirmations_csv')
                  or params.get('cancellations_csv'))
        apply_changes = params.get('apply') == 'true'

        if cherrypy.request.method == 'POST':
            check_csrf(params.get('csrf_token'))

        preview = None

        if upload is not None and getattr(upload, 'file', None):
            raw = upload.file.read()
            rows, parse_error = parse_confirmation_rows(raw, getattr(upload, 'filename', ''))
            if parse_error:
                return {'kind': kind, 'preview': None, 'message': parse_error}

            if kind == 'cancellation':
                preview = self._apply_cancellation_rows(session, rows, apply_changes)
            else:
                preview = self._apply_confirmation_rows(session, rows, apply_changes)

            if apply_changes and preview['applied']:
                session.commit()
                message = (
                    f"Applied {preview['applied']} {kind} update(s). "
                    f"{len(preview['unmatched'])} row(s) couldn't be matched."
                )

        return {
            'kind': kind,
            'preview': preview,
            'message': message,
        }

    def import_hotel_cancellations(self, session, message='', **params):
        """Back-import cancellations from the hotel (CSV or XLSX).

        Expected columns (header row required, case-insensitive):
          - confirmation_num         (matches RoomAssignment.hotel_confirmation_number)
          - cancellation_confirmation_number  (the hotel's cancel record id, optional)

        See _import_hotel_numbers for the shared preview/apply flow.
        """
        return self._import_hotel_numbers(session, 'cancellation', message, **params)

    def import_hotel_confirmations(self, session, message='', **params):
        """Back-import confirmation numbers from the hotel (CSV or XLSX).

        Expected columns (case-insensitive):
          - lottery_application_id   (preferred) OR
          - confirmation_num         (matches RoomAssignment.hotel_confirmation_number,
                                      when updating an existing record)
          - new_confirmation_num     (the value to write)

        See _import_hotel_numbers for the shared preview/apply flow.
        """
        return self._import_hotel_numbers(session, 'confirmation', message, **params)

    def waitlist_reveals(self, session, message=''):
        """List configured waitlist reveals."""
        reveals = session.query(WaitlistReveal).order_by(
            WaitlistReveal.reveal_at.desc().nullsfirst()).all()
        return {'reveals': reveals, 'message': message}

    def edit_waitlist_reveal(self, session, id=None, message='', **params):
        """Create or edit one WaitlistReveal."""
        if id in [None, '', 'None']:
            reveal = WaitlistReveal()
        else:
            reveal = session.waitlist_reveal(id)

        forms = load_forms(params, reveal, ['WaitlistRevealConfig'])

        if cherrypy.request.method == 'POST':
            # Pre-validate the reveal time: populate_obj's DateTime coercion
            # raises on unparseable text, and we want a friendly message
            # (with the submitted values still on the form) instead.
            raw = (forms['waitlist_reveal_config'].reveal_at.data or '').strip()
            if raw:
                try:
                    dateparser.parse(raw)
                except (ValueError, TypeError, OverflowError):
                    message = "Could not parse reveal time."

            if not message:
                for form in forms.values():
                    form.populate_obj(reveal, is_admin=True)
                session.add(reveal)
                session.commit()
                raise HTTPRedirect('waitlist_reveals?message={}',
                                   f"Reveal '{reveal.name}' saved.")

        return {'reveal': reveal, 'forms': forms, 'message': message}

    def send_waitlist_reveal_emails(self, session, id, csrf_token=None):
        """Materialize one WaitlistRevealLink per eligible attendee (anyone
        hotel-lottery-eligible without an active RoomAssignment) and queue
        the reveal email. Idempotent for already-emailed (attendee, reveal)
        pairs - running this again only emails new candidates.
        """
        from uber.utils import check_csrf
        from uber.models import Attendee, RoomAssignment
        import secrets

        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('waitlist_reveals')
        check_csrf(csrf_token)

        reveal = session.query(WaitlistReveal).get(id)
        if not reveal or not reveal.active:
            raise HTTPRedirect('waitlist_reveals?message={}',
                               'Reveal is missing or inactive.')

        eligible_subq = session.query(Attendee.id).outerjoin(
            RoomAssignment,
            sa.and_(
                RoomAssignment.attendee_id == Attendee.id,
                RoomAssignment.is_live,
            )
        ).filter(
            Attendee.hotel_lottery_eligible == True,  # noqa: E712
            RoomAssignment.id.is_(None),
        ).subquery()

        eligible_ids = [row[0] for row in session.query(eligible_subq.c.id).all()]
        existing_attendee_ids = {
            row[0] for row in session.query(WaitlistRevealLink.attendee_id).filter_by(
                waitlist_reveal_id=reveal.id).all()}

        new_links = []
        for aid in eligible_ids:
            if aid in existing_attendee_ids:
                continue
            link = WaitlistRevealLink(
                waitlist_reveal_id=reveal.id,
                attendee_id=aid,
                token=secrets.token_urlsafe(24),
            )
            session.add(link)
            new_links.append(link)
        session.flush()

        for link in new_links:
            attendee = session.query(Attendee).get(link.attendee_id)
            if not attendee:
                continue
            EmailService.queue_email(
                session, 'hotel_lottery_waitlist_reveal', attendee,
                subject=f"{c.EVENT_NAME_AND_YEAR}: Hotel waitlist link",
                data={'attendee': attendee, 'reveal': reveal, 'link': link})
            link.emailed_at = datetime.now(UTC)
            session.add(link)

        session.commit()
        raise HTTPRedirect(
            'waitlist_reveals?message={}',
            f"Queued {len(new_links)} new waitlist email{'s' if len(new_links) != 1 else ''}.")

    def assign_room(self, session, id=None, message='', **params):
        """Create or edit a RoomAssignment outside the lottery flow.

        Lottery admins assign with reason=MANUAL. Partition owners with
        can_edit_assignments_in their partition assign with reason=PARTITION_GRANT;
        partition_id is locked to their grant's scope. Used by Marketplace,
        Belvedere, Panels, Accessibility to assign exhibitor/panelist rooms.
        """
        from uber.models import RoomAssignment
        from uber.lottery_perms import is_lottery_admin, can_edit_assignments_in

        assignment = None
        if id and id not in ('None', ''):
            assignment = session.query(RoomAssignment).get(id)
        if assignment is None:
            assignment = RoomAssignment()

        # Permission gate: hotel-section access already required the user be
        # an admin; the partition-aware checks scope further.
        if cherrypy.request.method == 'POST':
            picked_attendee = params.get('attendee_id', '').strip()
            picked_inventory = params.get('inventory_id', '').strip()
            picked_partition = params.get('partition_id', '').strip() or None

            if not is_lottery_admin() and not can_edit_assignments_in(
                    session, picked_partition):
                message = "You don't have permission to edit assignments in this partition."
            elif not picked_attendee or not picked_inventory:
                message = "Attendee and inventory are required."
            elif picked_partition and not session.query(
                    InventoryPartitionBlock).filter_by(
                    partition_id=picked_partition,
                    inventory_id=picked_inventory).first():
                # Server-side twin of the dropdown cascade: a partitioned
                # assignment must use one of that partition's blocks.
                message = ("That inventory block is not allocated to the "
                           "selected partition.")
            else:
                assignment.attendee_id = picked_attendee
                assignment.inventory_id = picked_inventory
                assignment.partition_id = picked_partition
                if not assignment.assignment_reason or assignment.assignment_reason == c.MANUAL:
                    assignment.assignment_reason = (
                        c.PARTITION_GRANT if picked_partition and not is_lottery_admin()
                        else c.MANUAL)
                assignment.require_cc = params.get('require_cc') == 'true'

                ci = params.get('assigned_check_in_date', '').strip()
                co = params.get('assigned_check_out_date', '').strip()
                assignment.assigned_check_in_date = date.fromisoformat(ci) if ci else None
                assignment.assigned_check_out_date = date.fromisoformat(co) if co else None

                dcd = params.get('deposit_cutoff_date', '').strip()
                assignment.deposit_cutoff_date = date.fromisoformat(dcd) if dcd else None

                assignment.room_number = params.get('room_number', '').strip() or None
                assignment.admin_notes = params.get('admin_notes', '').strip()
                session.add(assignment)
                try:
                    session.commit()
                except Exception as e:
                    session.rollback()
                    message = f"Could not save assignment: {e}"
                else:
                    raise HTTPRedirect(
                        'assign_room?id={}&message={}',
                        assignment.id,
                        'Assignment saved.')

        # Scope option lists to what the actor is allowed to see
        picker = _picker_context(session)
        partitions = picker['partitions']
        if not is_lottery_admin():
            partitions = [
                p for p in partitions
                if can_edit_assignments_in(session, p.id)
            ]

        # Pre-select the attendee when arriving from an attendee-scoped
        # page (e.g. the registration form's Hotel Rooms tab). FK only on
        # the transient row - setting the relationship would cascade-add
        # it to the session - so the display name rides along separately.
        prefill_attendee = None
        if assignment.is_new and params.get('attendee_id'):
            prefill_attendee = session.query(Attendee).get(
                params['attendee_id'])
            if prefill_attendee:
                assignment.attendee_id = prefill_attendee.id

        # Availability per inventory block, per scope: '' keys the main
        # (unpartitioned) pool, partition ids key their blocks. Simple
        # live-count accounting (same convention as the partition
        # dashboard): capacity minus live assignments in that scope.
        from sqlalchemy import func
        live = {}
        for inv_id, part_id, n in (
                session.query(RoomAssignment.inventory_id,
                              RoomAssignment.partition_id,
                              func.count(RoomAssignment.id))
                .filter(RoomAssignment.is_live,
                        RoomAssignment.inventory_id.isnot(None))
                .group_by(RoomAssignment.inventory_id,
                          RoomAssignment.partition_id)):
            live[(str(inv_id), str(part_id) if part_id else '')] = n

        block_qty, partitioned_total, inventory_partitions_map = {}, {}, {}
        for b in session.query(InventoryPartitionBlock).all():
            iid, pid = str(b.inventory_id), str(b.partition_id)
            block_qty[(iid, pid)] = b.quantity
            partitioned_total[iid] = partitioned_total.get(iid, 0) + b.quantity
            inventory_partitions_map.setdefault(iid, []).append(pid)

        inventory_avail_map = {}
        for inv in picker['inventory_blocks']:
            iid = str(inv.id)
            scopes = {'': max(0, (inv.quantity or 0)
                              - partitioned_total.get(iid, 0)
                              - live.get((iid, ''), 0))}
            for pid in inventory_partitions_map.get(iid, []):
                scopes[pid] = max(0, block_qty[(iid, pid)]
                                  - live.get((iid, pid), 0))
            inventory_avail_map[iid] = scopes

        return {
            'assignment': assignment,
            'prefill_attendee': prefill_attendee,
            'partitions': partitions,
            'inventory_rows': picker['inventory_blocks'],
            'inventory_partitions_map': inventory_partitions_map,
            'inventory_avail_map': inventory_avail_map,
            'message': message,
        }

    @ajax_gettable
    def search_attendees(self, session, q='', **params):
        """JSON helper for the assign-room attendee picker.

        Mirrors partition_admin.search_attendees but without partition
        scoping: access here is gated by this section's admin ACL, the
        same gate as the assign_room page itself. Reuses Session.search()
        so every field the normal admin search covers (names, legal name,
        email, badge ID, badge number, UUID, promo group, etc.) works.
        """
        q = (q or '').strip()
        if len(q) < 2:
            return []

        try:
            results, _ = session.search(q)
        except Exception:
            return []

        out = []
        for a in results.limit(25).all():
            badge = ''
            try:
                badge = str(a.badge_num) if a.badge_num else ''
            except Exception:
                pass
            out.append({
                'id': a.id,
                'name': a.full_name,
                'email': a.email or '',
                'badge_num': badge,
                'badge_type': a.badge_type_label or '',
            })
        return out

    def partition_owners(self, session, partition_id=None, message=''):
        """List PartitionOwner grants, optionally filtered to one partition."""
        from uber.models import AdminAccount

        query = session.query(PartitionOwner).options(
            sa.orm.joinedload(PartitionOwner.admin_account).joinedload(AdminAccount.attendee),
            sa.orm.joinedload(PartitionOwner.partition),
        )
        partition = None
        if partition_id:
            partition = session.query(InventoryPartition).get(partition_id)
            if partition:
                query = query.filter(PartitionOwner.partition_id == partition.id)
        grants = query.all()
        grants.sort(key=lambda g: (g.partition.name if g.partition else '',
                                   g.admin_account.attendee.full_name if g.admin_account and g.admin_account.attendee else ''))
        return {
            'grants': grants,
            'partition': partition,
            'message': message,
        }

    def edit_partition_owner(self, session, id=None, partition_id=None, message='', **params):
        """Create or edit one (admin, partition) grant with its flag bundle."""
        from uber.models import AdminAccount

        grant = None
        if id and id not in ('None', ''):
            grant = session.query(PartitionOwner).get(id)
        if grant is None:
            grant = PartitionOwner()
            if partition_id:
                grant.partition_id = partition_id

        if cherrypy.request.method == 'POST':
            picked_account = params.get('admin_account_id', '').strip()
            # `partition_id` is bound to the function arg (named in the
            # signature for GET pre-fill), so the form's partition_id field
            # lands there, not in **params.
            picked_partition = (partition_id or '').strip()
            if not picked_account or not picked_partition:
                message = "Admin account and partition are both required."
            else:
                is_new = grant.id is None
                grant.admin_account_id = picked_account
                grant.partition_id = picked_partition

                # Three scoped access levels are submitted as
                # `<scope>_level` = none | view | edit. We unpack each
                # into the underlying view/edit flag pair so the
                # invariant "edit implies view" is enforced at the UI
                # layer rather than runtime - view-without-edit is the
                # only intermediate state the dropdown can produce.
                level_scopes = [
                    ('inventory_level',  'can_view_inventory',  'can_edit_inventory'),
                    ('assignments_level', 'can_view_assignments', 'can_edit_assignments'),
                ]
                for level_field, view_flag, edit_flag in level_scopes:
                    level = (params.get(level_field) or '').strip()
                    if level == 'edit':
                        setattr(grant, view_flag, True)
                        setattr(grant, edit_flag, True)
                    elif level == 'view':
                        setattr(grant, view_flag, True)
                        setattr(grant, edit_flag, False)
                    else:
                        # 'none' or missing - both off.
                        setattr(grant, view_flag, False)
                        setattr(grant, edit_flag, False)

                # Guest names are view-only: no guest-name editing feature
                # exists, so the UI offers None / View only. The reserved
                # can_edit_guest_names / can_send_emails columns are always
                # cleared until real features enforce them.
                grant.can_view_guest_names = \
                    (params.get('guest_names_level') or '').strip() == 'view'
                grant.can_edit_guest_names = False
                grant.can_send_emails = False
                session.add(grant)
                session.flush()
                record_partition_audit(
                    session, grant.partition_id,
                    action='partition_owner.granted' if is_new else 'partition_owner.updated',
                    description=("Granted partition access" if is_new
                                 else "Updated partition access capabilities"),
                    target_type='partition_owner', target_id=grant.id)
                try:
                    session.commit()
                except Exception as e:
                    session.rollback()
                    message = f"Could not save grant: {e}"
                else:
                    if params.get('return_to') == 'edit_partition':
                        raise HTTPRedirect(
                            'edit_partition?id={}&message={}',
                            grant.partition_id, 'Grant saved.')
                    raise HTTPRedirect('partition_owners?partition_id={}&message={}',
                                       grant.partition_id, 'Grant saved.')

        admin_accounts = session.query(AdminAccount).all()
        admin_accounts.sort(key=lambda a: a.attendee.full_name if a.attendee else '')
        partitions = session.query(InventoryPartition).filter_by(active=True).order_by(
            InventoryPartition.name).all()
        return {
            'grant': grant,
            'admin_accounts': admin_accounts,
            'partitions': partitions,
            'message': message,
        }

    def delete_partition_owner(self, session, id, csrf_token=None, return_to=''):
        from uber.utils import check_csrf
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('partition_owners')
        check_csrf(csrf_token)
        grant = session.query(PartitionOwner).get(id)
        if grant:
            partition_id = grant.partition_id
            record_partition_audit(
                session, partition_id,
                action='partition_owner.revoked',
                description="Revoked partition access",
                target_type='partition_owner', target_id=grant.id)
            session.delete(grant)
            session.commit()
            if return_to == 'edit_partition':
                raise HTTPRedirect('edit_partition?id={}&message={}',
                                   partition_id, 'Grant revoked.')
            raise HTTPRedirect('partition_owners?partition_id={}&message={}',
                               partition_id, 'Grant revoked.')
        raise HTTPRedirect('partition_owners?message={}', 'Grant not found.')

    def edit_partition(self, session, id=None, message='', **params):
        if id in [None, '', 'None']:
            partition = InventoryPartition()
        else:
            partition = session.inventory_partition(id)

        inventory_blocks = _picker_context(session)['inventory_blocks']
        existing_blocks = {str(pb.inventory_id): pb.quantity for pb in partition.blocks}

        forms = load_forms(params, partition, ['InventoryPartitionConfig'])

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                form.populate_obj(partition, is_admin=True)
            session.add(partition)
            session.flush()

            existing_pb = {str(pb.inventory_id): pb for pb in partition.blocks}
            change_lines = []
            for inv in inventory_blocks:
                qty_str = params.get(f'block_qty_{inv.id}', '')
                inv_label = inv.name or 'inventory'
                if qty_str != '' and int(qty_str) > 0:
                    qty = int(qty_str)
                    if str(inv.id) in existing_pb:
                        old_qty = existing_pb[str(inv.id)].quantity
                        if old_qty != qty:
                            existing_pb[str(inv.id)].quantity = qty
                            change_lines.append(f"{inv_label}: {old_qty} -> {qty}")
                    else:
                        pb = InventoryPartitionBlock(
                            partition_id=partition.id, inventory_id=str(inv.id), quantity=qty)
                        session.add(pb)
                        change_lines.append(f"{inv_label}: added with {qty}")
                elif str(inv.id) in existing_pb:
                    old_qty = existing_pb[str(inv.id)].quantity
                    session.delete(existing_pb[str(inv.id)])
                    change_lines.append(f"{inv_label}: removed (was {old_qty})")

            session.commit()

            # Notify partition owners of block edits.
            if change_lines and partition.id:
                _notify_partition_owners_of_inventory_change(
                    session, partition,
                    change_description='; '.join(change_lines))

            raise HTTPRedirect('manage_partitions?message={}', f"Partition '{partition.name}' saved.")

        # Existing partition-owner grants + admin pool for the inline manager
        # at the bottom of the page.
        from uber.models import AdminAccount
        if partition.id:
            grants = (session.query(PartitionOwner)
                      .filter_by(partition_id=partition.id)
                      .options(
                          sa.orm.joinedload(PartitionOwner.admin_account)
                          .joinedload(AdminAccount.attendee))
                      .all())
            grants.sort(key=lambda g: (
                g.admin_account.attendee.full_name
                if g.admin_account and g.admin_account.attendee else ''))
        else:
            grants = []

        granted_account_ids = {g.admin_account_id for g in grants}
        ungranted_admins = [a for a in session.query(AdminAccount).all()
                            if a.id not in granted_account_ids and a.attendee]
        ungranted_admins.sort(key=lambda a: a.attendee.full_name if a.attendee else '')

        # Current usage per block within THIS partition, so admins can
        # see how much is already committed before changing the
        # allocation. `usage_by_block` is the PEAK per-night count of
        # live (ASSIGNED/SECURED) RoomAssignments tagged with this
        # partition for each inventory block - that's the number the
        # per-night `quantity` allocation has to cover, so reducing
        # below it would over-commit the busiest night.
        # `rooms_by_block` is the total distinct live rooms (handy
        # context, not the binding constraint).
        usage_by_block = {}
        rooms_by_block = {}
        if partition.id:
            live_ras = (session.query(RoomAssignment)
                        .filter(RoomAssignment.partition_id == partition.id,
                                RoomAssignment.is_live,
                                RoomAssignment.inventory_id.isnot(None))
                        .all())
            per_block_night = {}
            for ra in live_ras:
                bid = str(ra.inventory_id)
                rooms_by_block[bid] = rooms_by_block.get(bid, 0) + 1
                if ra.assigned_check_in_date and ra.assigned_check_out_date:
                    nights = per_block_night.setdefault(bid, {})
                    d = ra.assigned_check_in_date
                    while d < ra.assigned_check_out_date:
                        nights[d] = nights.get(d, 0) + 1
                        d += timedelta(days=1)
            for bid, total in rooms_by_block.items():
                nights = per_block_night.get(bid)
                # Peak per-night usage; fall back to the room count for
                # rows with no dates so they still register as in-use.
                usage_by_block[bid] = max(nights.values()) if nights else total

        return {
            'partition': partition,
            'forms': forms,
            'inventory_blocks': inventory_blocks,
            'existing_blocks': existing_blocks,
            'usage_by_block': usage_by_block,
            'rooms_by_block': rooms_by_block,
            'grants': grants,
            'ungranted_admins': ungranted_admins,
            'message': message,
        }

    @ajax
    def reduce_awards(self, session, inventory_id, night_date, target_count):
        try:
            target_count = int(target_count)
            night = date.fromisoformat(night_date)
        except (ValueError, TypeError):
            return {"error": "Invalid target count or date."}

        # Reduce by ejecting RoomAssignment rows for the given block + night
        # at random. The owning LotteryApplication is rolled back to
        # COMPLETE once all its assignments are gone (RoomAssignment's
        # after_delete listener handles the status flip).
        candidate_ras = session.query(RoomAssignment).filter(
            RoomAssignment.inventory_id == inventory_id,
            RoomAssignment.is_live,
            RoomAssignment.assigned_check_in_date <= night,
            RoomAssignment.assigned_check_out_date > night,
        ).all()

        current_count = len(candidate_ras)
        if target_count >= current_count:
            return {"success": True, "message": f"No reduction needed ({current_count} currently assigned)."}

        # Prefer ejecting assignments whose source app has no group members.
        def _has_group(ra):
            app = ra.lottery_application
            return bool(app and app.group_members)

        ejectable = [ra for ra in candidate_ras if not _has_group(ra)]
        if len(ejectable) < current_count - target_count:
            ejectable = candidate_ras

        to_eject = random.sample(ejectable, min(len(ejectable), current_count - target_count))

        impacted_apps = {ra.lottery_application_id for ra in to_eject
                         if ra.lottery_application_id}
        for ra in to_eject:
            session.delete(ra)
        session.commit()

        # Clear partition + lottery_run linkage on apps whose last assignment
        # was just removed (the after_delete listener flips status back to
        # COMPLETE; we just clean the run linkage here).
        for app_id in impacted_apps:
            app = session.query(LotteryApplication).get(app_id)
            if not app:
                continue
            remaining = session.query(RoomAssignment).filter_by(
                lottery_application_id=app.id).count()
            if remaining == 0:
                app.partition_id = None
                app.lottery_run_id = None
                session.add(app)
        session.commit()

        return {"success": True, "message": f"Ejected {len(to_eject)} entries. {target_count} remain for {night_date}."}

    @ajax
    def unlock_application(self, session, id):
        app = session.lottery_application(id)
        app.export_locked = False
        session.add(app)
        session.commit()
        return {"success": True}

    # Wrappers around the underlying RoomAssignment CRUD that live in
    # partition_admin. Each redirects back to the application edit form
    # so the lottery admin stays on the same screen they came from.
    # Authority gate is HAS_HOTEL_LOTTERY_ADMIN_ACCESS (the @all_renderable
    # at the top of this class). The partition-scoped gating in the
    # partition_admin handlers ALSO short-circuits to True for lottery
    # admins via `can_edit_assignments_in`, so this just bypasses the
    # redirect dance.

    def add_room_assignment(self, session, application_id, inventory_id='',
                            partition_id='', csrf_token=None, **params):
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('form?id={}', application_id)
        check_csrf(csrf_token)
        app = session.lottery_application(application_id)
        if not inventory_id:
            raise HTTPRedirect('form?id={}&message={}', application_id,
                               'Inventory is required to add a room.')

        ra = RoomAssignment(
            attendee_id=app.attendee_id,
            lottery_application_id=app.id,
            inventory_id=inventory_id,
            partition_id=partition_id or None,
            assignment_reason=c.MANUAL,
            status=c.ASSIGNED,
            require_cc=params.get('require_cc') == 'true',
        )
        ci = params.get('assigned_check_in_date', '').strip()
        co = params.get('assigned_check_out_date', '').strip()
        if ci:
            try:
                ra.assigned_check_in_date = date.fromisoformat(ci)
            except ValueError:
                pass
        if co:
            try:
                ra.assigned_check_out_date = date.fromisoformat(co)
            except ValueError:
                pass
        session.add(ra)
        session.flush()
        if partition_id:
            record_partition_audit(
                session, partition_id,
                action='assignment.created',
                description=f"Manually added room to attendee {app.attendee_id}",
                target_type='assignment', target_id=ra.id)
        session.commit()
        raise HTTPRedirect('form?id={}&message={}', application_id, 'Room added.')

    def _apply_room_assignment_edits(self, session, ra, params,
                                     audit_prefix, fail):
        """Shared save path for the two RoomAssignment edit surfaces (the
        application form's per-room modal and the standalone edit page).

        Only touches fields actually present in `params`, so each surface
        keeps its own field set: the modal posts inventory / partition /
        billing / dates; the standalone page additionally posts status,
        deposit cutoff, confirmation numbers, and special requests.

        `fail(message)` is called on invalid input and must raise (both
        callers redirect back to their own page with the message).
        Returns the user-facing result message; commits when anything
        changed and writes one partition audit row prefixed with
        `audit_prefix`.
        """
        changes = []

        if 'inventory_id' in params:
            new_inv = params.get('inventory_id', '').strip()
            if new_inv and new_inv != ra.inventory_id:
                changes.append('inventory'); ra.inventory_id = new_inv
        if 'partition_id' in params:
            new_part = params.get('partition_id', '').strip() or None
            if new_part != ra.partition_id:
                changes.append('partition'); ra.partition_id = new_part
        if 'require_cc' in params:
            new_require_cc = params.get('require_cc') == 'true'
            if new_require_cc != ra.require_cc:
                changes.append('billing'); ra.require_cc = new_require_cc

        for name, label in (('assigned_check_in_date', 'check-in'),
                            ('assigned_check_out_date', 'check-out'),
                            ('deposit_cutoff_date', 'deposit cutoff')):
            if name not in params:
                continue
            raw = (params.get(name, '') or '').strip()
            if raw:
                try:
                    new_val = date.fromisoformat(raw)
                except ValueError:
                    fail(f"Could not parse the {label} date.")
            else:
                new_val = None
            if new_val != getattr(ra, name):
                changes.append(label); setattr(ra, name, new_val)

        raw_status = (params.get('status', '') or '').strip()
        if raw_status:
            try:
                new_status = int(raw_status)
            except ValueError:
                fail("Invalid status.")
            if new_status != ra.status:
                changes.append('status'); ra.status = new_status

        if 'physical_room_id' in params:
            from uber.models.hotel import PhysicalRoom
            new_room_id = params.get('physical_room_id', '').strip() or None
            if new_room_id != (ra.physical_room_id or None):
                if new_room_id:
                    room = session.query(PhysicalRoom).get(new_room_id)
                    if not room:
                        fail('Physical room not found.')
                    error = _validate_physical_room(session, ra, room)
                    if error:
                        fail(error)
                # Unlinking keeps the room_number text for reference; the
                # presave re-stamps it whenever a room is linked.
                changes.append('physical room')
                ra.physical_room_id = new_room_id

        for field, nullable in (('hotel_confirmation_number', True),
                                ('cancellation_confirmation_number', True),
                                ('room_number', True),
                                ('special_requests', False),
                                ('admin_notes', False)):
            if field not in params:
                continue
            raw = (params.get(field, '') or '').strip()
            if raw != (getattr(ra, field) or ''):
                changes.append(field.replace('_', ' '))
                # NOT NULL string columns clear to '' rather than None.
                setattr(ra, field, raw or (None if nullable else ''))

        if changes:
            session.add(ra)
            if ra.partition_id:
                record_partition_audit(
                    session, ra.partition_id,
                    action='assignment.updated',
                    description=f"{audit_prefix} {', '.join(changes)}",
                    target_type='assignment', target_id=ra.id)
            session.commit()
            return f"Updated {', '.join(changes)}."
        return 'No changes.'

    def update_room_assignment(self, session, application_id, assignment_id,
                               csrf_token=None, **params):
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('form?id={}', application_id)
        check_csrf(csrf_token)
        ra = session.query(RoomAssignment).get(assignment_id)
        if not ra:
            raise HTTPRedirect('form?id={}&message={}', application_id,
                               'Assignment not found.')

        def fail(msg):
            raise HTTPRedirect('form?id={}&message={}', application_id, msg)

        msg = self._apply_room_assignment_edits(
            session, ra, params, 'Lottery admin updated', fail)
        raise HTTPRedirect('form?id={}&message={}', application_id, msg)

    def delete_room_assignment(self, session, assignment_id,
                               application_id='', attendee_id='',
                               csrf_token=None):
        # `application_id` sends the admin back to the lottery entry form;
        # `attendee_id` back to that attendee's scoped rooms list; neither
        # falls back to the full rooms list.
        def _back(message=''):
            if application_id:
                raise HTTPRedirect('form?id={}&message={}', application_id, message)
            if attendee_id:
                raise HTTPRedirect('rooms?attendee_id={}&message={}',
                                   attendee_id, message)
            raise HTTPRedirect('rooms?message={}', message)

        if cherrypy.request.method != 'POST':
            _back()
        check_csrf(csrf_token)
        ra = session.query(RoomAssignment).get(assignment_id)
        if not ra:
            _back('Assignment not found.')

        # Cascade-delete connector children - they only exist as long as
        # their parent does.
        children = (session.query(RoomAssignment)
                    .filter_by(parent_assignment_id=ra.id).all())
        for child in children:
            if ra.partition_id:
                record_partition_audit(
                    session, ra.partition_id,
                    action='assignment.deleted',
                    description="Connector cascade",
                    target_type='assignment', target_id=child.id)
            session.delete(child)
        if ra.partition_id:
            record_partition_audit(
                session, ra.partition_id,
                action='assignment.deleted',
                description="Lottery admin removed assignment",
                target_type='assignment', target_id=ra.id)
        session.delete(ra)
        session.commit()
        _back('Room removed.')

    # Works for both lottery-tied and non-lottery (manual / partition
    # grant) RoomAssignments. The per-application form has its own modal
    # editor for rooms in the context of an application; this page is
    # the canonical "edit this specific room" surface, reachable from
    # the cross-section Rooms list.

    def edit_room_assignment(self, session, id, message=''):
        ra = session.query(RoomAssignment).get(id)
        if not ra:
            raise HTTPRedirect('rooms?message={}', 'Assignment not found.')

        picker = _picker_context(session)
        # {inventory_id: [partition_id, ...]} for the partition-filter JS.
        inventory_partitions_map = {}
        for pb in session.query(InventoryPartitionBlock).all():
            inventory_partitions_map.setdefault(
                str(pb.inventory_id), []).append(str(pb.partition_id))

        from uber import hotel_physical
        return {
            'assignment': ra,
            'partitions': picker['partitions'],
            'inventory_blocks': picker['inventory_blocks'],
            'inventory_partitions_map': inventory_partitions_map,
            'assignable_rooms': hotel_physical.assignable_rooms(session, ra),
            'message': message,
        }

    def save_room_assignment(self, session, assignment_id,
                             csrf_token=None, **params):
        """Standalone-page version of update_room_assignment. Shares
        _apply_room_assignment_edits; the standalone page additionally
        posts status, hotel confirmation, cancellation, deposit cutoff,
        and special requests, which the shared path picks up because
        they're present in params. Redirects back to the standalone edit
        page."""
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('edit_room_assignment?id={}', assignment_id)
        check_csrf(csrf_token)
        ra = session.query(RoomAssignment).get(assignment_id)
        if not ra:
            raise HTTPRedirect('rooms?message={}', 'Assignment not found.')

        def fail(msg):
            raise HTTPRedirect('edit_room_assignment?id={}&message={}',
                               assignment_id, msg)

        msg = self._apply_room_assignment_edits(
            session, ra, params, 'Edit page updated', fail)
        raise HTTPRedirect('edit_room_assignment?id={}&message={}',
                           assignment_id, msg)

    @ajax
    def bulk_unlock(self, session, ids):
        id_list = [x.strip() for x in ids.split(',') if x.strip()]
        count = 0
        for app_id in id_list:
            app = session.query(LotteryApplication).get(app_id)
            if app and app.export_locked:
                app.export_locked = False
                session.add(app)
                count += 1
        session.commit()
        return {"success": True, "count": count}

    # Cross-application view: every RoomAssignment in the system,
    # paginated. Useful when an admin knows the room (hotel + date) but
    # not the attendee/application, or wants to scan the whole population
    # for sanity-check. Filters are deliberately minimal - for fine-grained
    # searching the application search box on the Applications page is
    # still the right tool.

    def rooms(self, session, message='', page='1', page_size='50',
              status='live', hotel_id='', partition_id='', search='',
              attendee_id=''):
        ps = clamp_page_size(page_size)
        search_term = (search or '').strip()

        # Scope to one attendee's rooms - this is where the registration
        # page's "Hotel Rooms" tab lands. The shared query layer widens a
        # 'live' status filter to 'all' in that case; mirror that here so
        # the status dropdown in the template reflects what's shown.
        if attendee_id and status == 'live':
            status = 'all'

        q = build_room_assignment_query(
            session, status=status, hotel_id=hotel_id,
            partition_id=partition_id, search=search_term,
            attendee_id=attendee_id)

        # Sort: check-in date (nulls first so missing dates pop to the
        # top and get noticed), then created order.
        q = q.order_by(RoomAssignment.assigned_check_in_date.asc().nullsfirst(),
                       RoomAssignment.created.asc())
        assignments, total, page_num, page_count = paginate(q, page, ps)

        hotels = (session.query(LotteryHotel)
                  .filter_by(active=True)
                  .order_by(LotteryHotel.name).all())
        partitions = (session.query(InventoryPartition)
                      .filter_by(active=True)
                      .order_by(InventoryPartition.name).all())

        scoped_attendee = (session.query(Attendee).get(attendee_id)
                           if attendee_id else None)

        return {
            'message': message,
            'assignments': assignments,
            'page': page_num,
            'page_size': ps,
            'total': total,
            'page_count': page_count,
            'status': status,
            'hotel_id': hotel_id,
            'partition_id': partition_id,
            'search': search_term,
            'attendee_id': attendee_id,
            'scoped_attendee': scoped_attendee,
            'hotels': hotels,
            'partitions': partitions,
            'status_opts': c.HOTEL_ASSIGNMENT_STATUS_OPTS,
        }

    @ajax
    def process_waitlist(self, session, inventory_id='', night_date=''):
        inv_id = inventory_id if inventory_id else None
        nd = date.fromisoformat(night_date) if night_date else None
        result = _fulfill_waitlist(session, inventory_id=inv_id, night_date=nd)
        return result

    def waitlist(self, session, message='', page='1', search_text=''):
        """Admin Waitlist dashboard.

        Two views on the same data:

          1. **Per-block demand** - for every inventory block with at
             least one waitlisted RoomAssignment, the per-night
             waitlist count (how many distinct rooms are queued for
             that specific night). Helps the admin see which nights
             are oversubscribed.

          2. **Per-room queue** - every waitlisted RoomAssignment in
             FIFO order, with the inventory block, attendee, requested
             vs confirmed range, and waitlist start timestamp. Each
             row gets an Accept button that calls `accept_waitlist`
             to immediately extend `assigned_*` to cover the
             `waitlisted_*` range for that single row (admin override,
             no capacity check - the admin is explicitly choosing to
             accept this person off the queue).

        Process Waitlist (the cron-style fulfillment that respects
        capacity) also lives here now; the old button on the inventory
        overview was redundant once this page existed.

        **Search** (`search_text=`) - case-insensitive substring match
        against the attendee's first/last name, email, lottery
        confirmation number, hotel name, inventory block name, and
        room/suite type name. The block-demand histogram re-derives
        from the filtered set so both views stay consistent.

        **Pagination** (`page=`) - the FIFO queue paginates at 100 rows
        per page (matches the rest of the admin section's convention,
        e.g. `hotel_lottery_admin/index`). The histogram itself is
        small (one row per inventory block, capped by inventory size)
        so it's never paginated.
        """
        from uber.models.hotel import RoomAssignment

        PER_PAGE = 100

        search_text = (search_text or '').strip()

        # Base query - every waitlisted row, FIFO-ordered. We eagerly
        # load the relationships the search filter and the template
        # both need (attendee, inventory.hotel, inventory.room_type,
        # inventory.suite_type, lottery_application) in one shot so
        # the row-loop below doesn't trigger N+1 lookups.
        waitlist_filter = sa.or_(
            RoomAssignment.waitlisted_check_in_date.isnot(None),
            RoomAssignment.waitlisted_check_out_date.isnot(None))
        q = (session.query(RoomAssignment)
             .options(
                 joinedload(RoomAssignment.attendee),
                 joinedload(RoomAssignment.inventory)
                     .joinedload(HotelRoomInventory.hotel),
                 joinedload(RoomAssignment.lottery_application))
             .filter(waitlist_filter)
             .order_by(
                 RoomAssignment.waitlist_started_at.asc().nullsfirst(),
                 RoomAssignment.created.asc()))

        if search_text:
            # Push the search down to SQL via joins + ILIKE OR-chain so
            # the planner can use indexes on attendee/email and we
            # don't pull the entire waitlisted-row population into
            # Python just to throw most of it away.
            term = f'%{search_text}%'
            inv_alias = HotelRoomInventory
            from sqlalchemy.orm import aliased
            # Room and suite type aliases - same table, different
            # column on inventory points at them.
            room_type_a = aliased(LotteryRoomType)
            suite_type_a = aliased(LotteryRoomType)

            q = (q.outerjoin(Attendee,
                             RoomAssignment.attendee_id == Attendee.id)
                  .outerjoin(LotteryApplication,
                             RoomAssignment.lottery_application_id == LotteryApplication.id)
                  .outerjoin(inv_alias,
                             RoomAssignment.inventory_id == inv_alias.id)
                  .outerjoin(LotteryHotel,
                             inv_alias.hotel_id == LotteryHotel.id)
                  .outerjoin(room_type_a,
                             inv_alias.room_type_id == room_type_a.id)
                  .outerjoin(suite_type_a,
                             inv_alias.suite_type_id == suite_type_a.id)
                  .filter(sa.or_(
                      Attendee.first_name.ilike(term),
                      Attendee.last_name.ilike(term),
                      (Attendee.first_name + ' ' + Attendee.last_name).ilike(term),
                      Attendee.email.ilike(term),
                      LotteryApplication.confirmation_num.ilike(term),
                      LotteryHotel.name.ilike(term),
                      inv_alias.name.ilike(term),
                      room_type_a.name.ilike(term),
                      suite_type_a.name.ilike(term),
                  ))
                  # Duplicates appear if multiple joined rows match -
                  # one assignment with two LIKE-matching fields would
                  # come back twice. distinct() collapses them; the
                  # ordering above survives because both order columns
                  # are on RoomAssignment itself.
                  .distinct())

        filtered = q.all()
        total_count = len(filtered)

        # Unfiltered population - used by the template to distinguish
        # "the waitlist is genuinely empty" (show the friendly empty
        # state, hide the search form) from "your search has zero
        # matches" (keep the search form so the admin can revise or
        # clear it). Cheap separate count query when search is active;
        # we already have it when search is empty.
        if search_text:
            waitlist_size = session.query(RoomAssignment.id).filter(
                waitlist_filter).count()
        else:
            waitlist_size = total_count

        # Per-block per-night demand histogram. Rebuilt from the
        # filtered set so the histogram and the FIFO table represent
        # the same population - search "hampton" and you see only the
        # Hampton blocks light up.
        block_rows = _waitlist_block_rows(session, filtered)

        # Pagination. `get_page` is the same helper the rest of the
        # admin uses (`uber.utils.get_page`), but its 100-per-page
        # default is baked in, so we mirror it here for the page
        # count math.
        try:
            page = max(1, int(page or 1))
        except (TypeError, ValueError):
            page = 1
        total_pages = max(1, math.ceil(total_count / PER_PAGE)) if total_count else 1
        if page > total_pages:
            page = total_pages
        page_slice = filtered[(page - 1) * PER_PAGE: page * PER_PAGE]
        pages = range(1, total_pages + 1)

        return {
            'message': message,
            'block_rows': block_rows,
            'queue': page_slice,
            'total_count': total_count,
            'waitlist_size': waitlist_size,
            'page': page,
            'pages': pages,
            'per_page': PER_PAGE,
            'search_text': search_text,
        }

    def export_waitlist_xlsx(self, session):
        """One-XLSX-per-call export of the current waitlist demand, with
        one worksheet per hotel that has any waitlisted rooms. The sheet
        layout lives with the builder (uber.hotel_exports.build_waitlist_xlsx).

        Built manually (no `@xlsx_file` decorator) because that helper
        only hands out a single worksheet. We still match the decorator's
        response shape: same Content-Type, a filename derived from the
        handler name plus a timestamp, and we participate in
        `track_report` so admin exports show up in the usage log.
        """
        output = build_waitlist_xlsx(session)
        cherrypy.response.headers['Content-Type'] = (
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        # Real `datetime.now()` rather than the project's `localized_now()`
        # because the file name doesn't need timezone fidelity - same
        # convention as `@xlsx_file`.
        stamp = datetime.now().strftime('%Y%m%d_%H%M')
        cherrypy.response.headers['Content-Disposition'] = (
            f'attachment; filename="export_waitlist_xlsx{stamp}.xlsx"')
        return output

    @ajax
    def accept_waitlist(self, session, assignment_id=''):
        """FIFO-bypass accept: serve a single waitlisted RoomAssignment
        out of order, but ONLY for the nights where its block has
        actual capacity.

        Difference from `process_waitlist`: that endpoint sweeps the
        whole queue in `waitlist_started_at` order (earliest entrants
        first) and extends nights up to capacity. This endpoint picks
        ONE row by `assignment_id` and extends that row's nights up to
        capacity, regardless of where it sits in the FIFO order. So
        admins can promote a specific attendee past the queue without
        also handing them nights that don't actually exist.

        Per-night capacity uses `_partition_capacity` (same helper the
        cron uses) so a partition-bound row only competes with other
        rows in the same partition, and the cron and this endpoint
        agree on what "full" means.

        If the row's full waitlisted range is satisfied, the model's
        `clear_waitlist_when_satisfied` presave zeros the waitlist
        columns and `waitlist_started_at` so the row drops out of the
        queue. If only some of the requested nights had capacity, the
        row keeps its tightened waitlist demand on whatever's left.
        """
        from uber.models.hotel import RoomAssignment

        if not assignment_id:
            return {'error': 'Missing assignment_id.'}
        ra = session.query(RoomAssignment).get(assignment_id)
        if not ra:
            return {'error': 'Assignment not found.'}
        if not (ra.waitlisted_check_in_date or ra.waitlisted_check_out_date):
            return {'error': 'That assignment is not currently on the waitlist.'}
        if ra.export_locked:
            return {'error': 'That assignment has been exported to the hotel '
                             'and cannot be edited from here.'}
        if not ra.inventory:
            return {'error': 'Assignment has no inventory block; cannot run '
                             'the capacity check.'}

        wl_ci = ra.waitlisted_check_in_date or ra.assigned_check_in_date
        wl_co = ra.waitlisted_check_out_date or ra.assigned_check_out_date

        # Walk the FRONT extension one night at a time, closest-to-now
        # first. `_partition_capacity` counts every currently-confirmed
        # assignment whose `assigned_check_in_date <= night <
        # assigned_check_out_date` - that excludes the row we're
        # extending (whose current `assigned_check_in_date` is strictly
        # after `night`), so we don't double-count ourselves.
        nights_extended_front = 0
        while ra.assigned_check_in_date and wl_ci and wl_ci < ra.assigned_check_in_date:
            candidate_night = ra.assigned_check_in_date - timedelta(days=1)
            _, _, open_slots = _partition_capacity(
                session, ra.inventory, candidate_night, ra.partition_id)
            if open_slots <= 0:
                break
            ra.assigned_check_in_date = candidate_night
            nights_extended_front += 1
            # Flush so the next iteration's `_partition_capacity` sees
            # the in-memory change (otherwise we'd over-extend by
            # racing our own writes).
            session.flush()

        # Walk the BACK extension one night at a time, earliest first.
        # Same self-exclusion logic: `assigned_check_out_date > night`
        # filters us out for any night >= our current check-out.
        nights_extended_back = 0
        while ra.assigned_check_out_date and wl_co and wl_co > ra.assigned_check_out_date:
            candidate_night = ra.assigned_check_out_date
            _, _, open_slots = _partition_capacity(
                session, ra.inventory, candidate_night, ra.partition_id)
            if open_slots <= 0:
                break
            ra.assigned_check_out_date = candidate_night + timedelta(days=1)
            nights_extended_back += 1
            session.flush()

        total_extended = nights_extended_front + nights_extended_back

        # Cascade the new confirmed range to any connector children
        # (their dates always mirror the parent), then sync the
        # remaining waitlist demand too so the cron and the children
        # stay consistent.
        for child in session.query(RoomAssignment).filter_by(
                parent_assignment_id=ra.id).all():
            child.assigned_check_in_date = ra.assigned_check_in_date
            child.assigned_check_out_date = ra.assigned_check_out_date
            # The parent's `waitlisted_*` is either cleared (fully satisfied)
            # or holds the original request (partial); copy it to the children.
            child.waitlisted_check_in_date = ra.waitlisted_check_in_date
            child.waitlisted_check_out_date = ra.waitlisted_check_out_date
            child.waitlist_started_at = ra.waitlist_started_at
            session.add(child)

        session.add(ra)
        session.commit()

        if total_extended == 0:
            return {
                'error': 'No capacity available on any of the requested '
                         'nights for this block. The row remains on the '
                         'waitlist for the cron to retry.',
            }

        # Notify the attendee that some/all of their requested nights
        # came through. Same template the cron uses.
        if ra.attendee and ra.lottery_application:
            try:
                EmailService.queue_email(
                    session, 'hotel_lottery_waitlist_fulfilled', ra.lottery_application,
                    subject=f'{c.EVENT_NAME} Hotel Lottery - Room Dates Updated',
                    data={'assignment': ra, 'app': ra.lottery_application})
            except Exception:
                log.exception('accept_waitlist: notification failed')

        still_waiting = bool(ra.waitlisted_check_in_date
                             or ra.waitlisted_check_out_date)
        msg = (f'Accepted {total_extended} night(s) off waitlist. '
               f'New range: {ra.assigned_check_in_date} - '
               f'{ra.assigned_check_out_date}.')
        if still_waiting:
            msg += ' Remaining nights still on waitlist (no capacity yet).'

        return {
            'success': True,
            'message': msg,
            'still_waiting': still_waiting,
        }

    # A read-only "what's wrong with our room data" report. Issues are
    # surfaced as a flat list, each one carrying severity (error/warning),
    # a human label, and a deep-link to wherever the admin can fix it
    # (usually the application's edit form). The checks themselves live
    # in uber.hotel_room_audit (all in Python - no SQL view - so it's
    # easy to add new ones); this section keeps the routes.

    def room_issues(self, session, message='', severity='all', kind='all',
                    search='', show_hidden=''):
        """Cross-check every live RoomAssignment and produce a list of
        validation issues.

        Issue types currently detected:
          - orphan_connector: connector's parent_assignment_id doesn't
            resolve to a live assignment for the same attendee.
          - childless_parent: parent suite is awarded but one or more
            of its required connector children are missing or short.
          - over_capacity: occupants count > inventory.capacity.
          - under_capacity: occupants count < inventory.min_capacity.
          - empty_room: zero occupants assigned (no booker name on file
            for the hotel - they'll reject the reservation).
          - missing_dates: assigned_check_in_date or
            assigned_check_out_date is null.
          - inverted_dates: check_in_date >= check_out_date.
          - too_short: stay length < 1 night.
          - out_of_range: check-in before HOTEL_LOTTERY_CHECKIN_START
            or check-out after HOTEL_LOTTERY_CHECKOUT_END.
          - status_mismatch: app.status doesn't match its rooms
            (e.g. has rooms but status==COMPLETE; no rooms but
            status==AWARDED). Caught by the model listener under normal
            use; this is the audit backstop.
          - double_booked: same attendee is an occupant on two rooms
            whose dates overlap.
          - secured_without_payment: self-pay room flipped to SECURED
            without a captured CC vault token. The hotel will treat the
            reservation as unguaranteed; master-bill rooms exempt.

        Plus the inventory/configuration checks registered in
        uber.hotel_room_audit.INVENTORY_CHECKS (oversubscription,
        partition misconfiguration, connector capacity, etc.).
        """
        issues, inv_issues = collect_issues(session)

        # Issues are recomputed every load, so admin hide-flags + notes
        # live in HotelRoomIssueNote keyed to each issue's STABLE identity
        # (kind, target_type, target_id). Annotate every issue with its
        # note + hidden flag, then split shown vs hidden.
        notes_by_key = load_issue_notes(session)
        annotate_issues(issues, notes_by_key)
        annotate_issues(inv_issues, notes_by_key)

        shown_room = [i for i in issues if not i['hidden']]
        hidden_room = [i for i in issues if i['hidden']]
        shown_inv = [i for i in inv_issues if not i['hidden']]
        hidden_inv = [i for i in inv_issues if i['hidden']]

        # Tab + kind counts reflect the SHOWN (non-hidden) issues, since
        # hidden ones are acknowledged; the hidden total gets its own
        # count. Filters then narrow the working lists before grouping.
        counts = {'error': 0, 'warning': 0}
        for iss in shown_room:
            counts[iss['severity']] = counts.get(iss['severity'], 0) + 1
        inv_counts = {'error': 0, 'warning': 0}
        for iss in shown_inv:
            inv_counts[iss['severity']] = inv_counts.get(iss['severity'], 0) + 1
        hidden_count = len(hidden_room) + len(hidden_inv)

        # Per-kind counts across the SHOWN issue sets, for the dropdown.
        kind_counts = {}
        for iss in shown_room + shown_inv:
            k = iss.get('kind') or 'unknown'
            kind_counts[k] = kind_counts.get(k, 0) + 1
        kind_options = sorted(kind_counts.items())

        # Free-text search matches on the lowercased needle; keep the
        # original-case string for redisplay.
        search = (search or '').strip()
        needle = search.lower()

        shown_room = filter_issues(shown_room, severity, kind, needle)
        shown_inv = filter_issues(shown_inv, severity, kind, needle)
        hidden_room = filter_issues(hidden_room, severity, kind, needle)
        hidden_inv = filter_issues(hidden_inv, severity, kind, needle)

        groups = group_room_issues(shown_room)
        inv_groups = group_inventory_issues(shown_inv)
        hidden_groups = group_room_issues(hidden_room)
        hidden_inv_groups = group_inventory_issues(hidden_inv)

        return {
            'groups': groups,
            'counts': counts,
            'inv_groups': inv_groups,
            'inv_counts': inv_counts,
            'hidden_groups': hidden_groups,
            'hidden_inv_groups': hidden_inv_groups,
            'hidden_count': hidden_count,
            'show_hidden': str(show_hidden).lower() in ('1', 'true', 'on', 'yes'),
            'severity': severity,
            'kind': kind,
            'kind_options': kind_options,
            'search': search,
            'message': message,
        }

    def hide_issue(self, session, issue_kind='', target_type='',
                   target_id='', admin_notes='', severity='all', kind='all',
                   search='', show_hidden='', csrf_token=None):
        """Hide a single issue (by its stable identity) from the active
        report and optionally attach a note. Idempotent."""
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect(_room_issues_url())
        check_csrf(csrf_token)
        if not (issue_kind and target_type and target_id):
            raise HTTPRedirect(_room_issues_url(
                'Could not identify which issue to hide.',
                severity, kind, search, show_hidden))
        note = get_or_make_issue_note(
            session, issue_kind, target_type, target_id)
        note.hidden = True
        note.admin_notes = (admin_notes or '').strip()
        session.add(note)
        session.commit()
        raise HTTPRedirect(_room_issues_url(
            'Issue hidden.', severity, kind, search, show_hidden))

    def unhide_issue(self, session, issue_kind='', target_type='',
                     target_id='', admin_notes='', severity='all', kind='all', search='',
                     show_hidden='1', csrf_token=None):
        """Un-hide an issue so it returns to the active report. The note
        text is preserved (the row stays, just `hidden=False`); `admin_notes`
        is accepted from the shared form but intentionally ignored here."""
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect(_room_issues_url())
        check_csrf(csrf_token)
        note = (session.query(HotelRoomIssueNote)
                .filter_by(issue_kind=issue_kind, target_type=target_type,
                           target_id=str(target_id))
                .one_or_none())
        if note:
            note.hidden = False
            session.add(note)
            session.commit()
        raise HTTPRedirect(_room_issues_url(
            'Issue restored to the active report.',
            severity, kind, search, show_hidden))

    def save_issue_note(self, session, issue_kind='', target_type='',
                        target_id='', admin_notes='', severity='all',
                        kind='all', search='', show_hidden='',
                        csrf_token=None):
        """Save (or update) an issue's admin note without changing its
        hidden state. An empty note on a not-hidden issue deletes the
        row so we don't accumulate empty records."""
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect(_room_issues_url())
        check_csrf(csrf_token)
        if not (issue_kind and target_type and target_id):
            raise HTTPRedirect(_room_issues_url(
                'Could not identify which issue to annotate.',
                severity, kind, search, show_hidden))
        notes = (admin_notes or '').strip()
        existing = (session.query(HotelRoomIssueNote)
                    .filter_by(issue_kind=issue_kind, target_type=target_type,
                               target_id=str(target_id))
                    .one_or_none())
        if not notes and (not existing or not existing.hidden):
            # Nothing to keep - drop an empty, non-hidden row.
            if existing:
                session.delete(existing)
                session.commit()
            raise HTTPRedirect(_room_issues_url(
                'Note cleared.', severity, kind, search, show_hidden))
        note = existing or get_or_make_issue_note(
            session, issue_kind, target_type, target_id)
        note.admin_notes = notes
        session.add(note)
        session.commit()
        raise HTTPRedirect(_room_issues_url(
            'Note saved.', severity, kind, search, show_hidden))
