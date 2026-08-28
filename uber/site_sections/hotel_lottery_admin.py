import os
import re
import cherrypy
import logging
from cherrypy.lib.static import serve_file
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pytz import UTC
from dateutil import parser as dateparser
import sqlalchemy as sa
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload
from sqlalchemy.types import String

from uber.config import c
from uber.decorators import (all_renderable, log_pageview, ajax, ajax_gettable, xlsx_file, csv_file,
                             multifile_zipfile, render)
from uber.errors import HTTPRedirect
from uber.forms import load_forms
from uber.models import (AdminAccount, Attendee, AutomatedEmail, Group,
                         LotteryApplication, Email, Tracking, PageViewTracking)
from uber.hotel import pricing
from uber.hotel.deletion import (DeletionError, RESOURCE_SPECS, has_blocking,
                                 inspect_conflicts, perform_delete,
                                 resolve_conflict)
from uber.hotel.perms import is_lottery_admin, record_partition_audit
from uber.models.hotel import (HotelRoomInventory, InventoryNightQuantity, InventoryPartition,
                               InventoryPartitionBlock, LotteryRun, HotelExportLog, LotteryHotel, LotteryRoomType,
                               PartitionOwner, RoomAssignment,
                               WaitlistReveal, WaitlistRevealLink, HotelRoomIssueNote,
                               HotelImportFile)
from uber.email import EmailService
from uber.hotel.exports import (booking_columns, booking_export_data,
                                build_waitlist_xlsx, changed_rooms_between,
                                compute_export_tracking, derive_sync_status,
                                hotel_activity_timeline, import_changes,
                                read_stored_file, render_booking_export,
                                store_export_file, write_hotel_inventory_xlsx,
                                write_interchange_export)
from uber.hotel.imports import (apply_cancellation_rows, apply_confirmation_rows,
                                match_assignments, parse_confirmation_rows,
                                parse_iso_date, parse_spreadsheet)
from uber.hotel.service import (RoomAssignmentError, apply_room_assignment_edits,
                                assign_physical_room, create_room_assignment,
                                validate_physical_room)
from uber.hotel.solver import (LOTTERY_TYPE_BOTH,
                                       adjust_available_rooms,
                                       build_eligible_applications,
                                       count_assigned_per_block_night,
                                       filter_inventory_table,
                                       materialize_room_assignments,
                                       solve_lottery)
from uber.hotel.audit import (annotate_issues, collect_issues,
                                   filter_issues, get_or_make_issue_note,
                                   group_inventory_issues, group_room_issues,
                                   load_issue_notes)
from uber.hotel.queries import (attendee_search_results, block_availability,
                                build_room_assignment_query,
                                clamp_page_size, paginate)
from uber.hotel.waitlist import (WaitlistError, accept_waitlist_entry,
                                 cron_eligible, fulfill_waitlist)
from uber.utils import (Order, check_csrf, get_page, localized_now,
                        redirect_with_params, validate_model)

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


def _change_rows_json(rows):
    """JSON shape shared by the exports page's two change modals."""
    return [{
        'assignment_id': row['assignment_id'],
        'number': row['number'],
        'guest': row['guest'],
        'when': row['when'].isoformat() if row['when'] else '',
        'who': row['who'],
        'action': row['action'],
        'fields': [{'field': f, 'old': o, 'new': n}
                   for f, o, n in row['changes']],
    } for row in rows]


def _unroomed_order(sort):
    """ORDER BY clauses for the physical-rooms page's unroomed-bookings
    table. Missing check-in dates sort first so they get noticed.
    'attendee' expects the caller to have joined Attendee."""
    if sort == 'attendee':
        return (Attendee.last_name.asc(), Attendee.first_name.asc())
    if sort == 'block':
        return (RoomAssignment.inventory_id.asc(),)
    if sort == 'status':
        return (RoomAssignment.status.asc(),)
    if sort == 'checkout':
        return (RoomAssignment.assigned_check_out_date.asc().nullsfirst(),)
    return (RoomAssignment.assigned_check_in_date.asc().nullsfirst(),)


def _waitlist_reveal_candidates(session, reveal):
    """(eligible_ids, emailed_ids, pending_ids, new_ids) for one reveal.

    Shared by the sender, the link generator, and the recipient preview, so
    the preview cannot drift from what a send would actually do.

    Eligible: lottery-eligible attendees holding no live room.
    """
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

    emailed_ids, pending_ids = set(), set()
    for attendee_id, emailed_at in session.query(
            WaitlistRevealLink.attendee_id,
            WaitlistRevealLink.emailed_at).filter_by(waitlist_reveal_id=reveal.id):
        (emailed_ids if emailed_at else pending_ids).add(attendee_id)

    # Anyone eligible who has no link row at all yet.
    new_ids = [aid for aid in eligible_ids
               if aid not in emailed_ids and aid not in pending_ids]
    return eligible_ids, emailed_ids, pending_ids, new_ids


def _mint_reveal_links(session, reveal, attendee_ids):
    """Create the missing link rows and return every row that still needs
    emailing, which includes ones generated earlier without sending."""
    import secrets

    for attendee_id in attendee_ids:
        session.add(WaitlistRevealLink(
            waitlist_reveal_id=reveal.id,
            attendee_id=attendee_id,
            token=secrets.token_urlsafe(24)))
    session.flush()

    return session.query(WaitlistRevealLink).filter(
        WaitlistRevealLink.waitlist_reveal_id == reveal.id,
        WaitlistRevealLink.emailed_at.is_(None)).all()


def _prepare_import_review(session, record, raw, filename, template_id=''):
    """Freeze a template-mapped read of an upload onto its HotelImportFile.

    Frozen rather than re-parsed on view because templates stay editable: an
    admin fixing a template mid-review must not silently change what a
    half-reviewed file is recorded as having said. The comparison against
    live bookings is still recomputed on every view, so a synced value stops
    showing as changed immediately.

    Returns a summary, or None when no template applies and the older
    confirmation-number import already handled the file.
    """
    from uber.hotel import mapping

    fieldnames, _rows, error = mapping.parse_with_template(raw, filename, None)
    if error:
        record.parse_error = error
        record.status = 'pending'
        session.add(record)
        return None

    template = mapping.detect_template(session, fieldnames, hotel=record.hotel,
                                       template_id=template_id or None)
    if template is None:
        return None

    rows, error = mapping.build_rows(
        session, raw, filename, template,
        hotel_id=record.hotel_id if record.hotel_id else None)
    if error:
        record.parse_error = error
        record.status = 'pending'
        session.add(record)
        return None

    counts = mapping.counts_for(rows)
    record.parsed_rows = rows
    record.parse_error = ''
    record.status = 'pending'
    record.template_id = getattr(template, 'id', None)
    record.matched_count = counts['matched']
    record.ambiguous_count = counts['ambiguous']
    record.unmatched_count = counts['unmatched']
    session.add(record)

    return {'total': len(rows), 'template_name': template.name, 'counts': counts}


def _deletion_label(obj):
    return (getattr(obj, 'name', None) or getattr(obj, 'display_name', None)
            or 'this item')


LOTTERY_TYPE_VALUES = {
    'room': c.ROOM_ENTRY,
    'suite': c.SUITE_ENTRY,
    'both': LOTTERY_TYPE_BOTH,
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


def _parse_price(raw):
    """One submitted price box. '' means "not set"; anything unparseable or
    negative raises so the admin sees it rather than losing the value.

    Prices bypass WTForms entirely: coerce_column_data's Numeric branch does
    int(float(value)), which would silently drop the cents.
    """
    raw = str(raw or '').strip().replace('$', '').replace(',', '')
    if not raw:
        return None
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        raise ValueError('not a number')
    if amount < 0:
        raise ValueError('negative')
    return amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _save_inventory_prices(session, item, params, event_nights):
    """Replace this block's InventoryPrice rows from the posted grid.

    Rows are deleted and reinserted wholesale rather than merged, so turning a
    dimension off cannot leave orphaned cells that reappear if it is turned
    back on. Returns an error message, or '' on success.
    """
    from uber.models.hotel import InventoryPrice

    item.price_per_night = params.get('price_per_night') == '1'
    item.price_per_occupancy = params.get('price_per_occupancy') == '1'
    item.pricing_notes = (params.get('pricing_notes') or '').strip()

    occupancies = list(range(item.min_capacity, item.capacity + 1))
    nights = event_nights if item.price_per_night else []

    # (field prefix, is_staff) for the two scopes the grid collects.
    scopes = (('price', False), ('staff_price', True))

    parsed = []
    for prefix, is_staff in scopes:
        try:
            base = _parse_price(params.get(f'{prefix}_base'))
        except ValueError:
            return f'Could not read the {"staff " if is_staff else ""}base price.'
        if is_staff:
            item.base_staff_price = base
        else:
            item.base_price = base

        if item.price_per_night and item.price_per_occupancy:
            cells = [(night, occ, f'{prefix}_cell_{night.isoformat()}_{occ}')
                     for night in nights for occ in occupancies]
        elif item.price_per_night:
            cells = [(night, None, f'{prefix}_night_{night.isoformat()}')
                     for night in nights]
        elif item.price_per_occupancy:
            cells = [(None, occ, f'{prefix}_occ_{occ}') for occ in occupancies]
        else:
            cells = []

        for night, occupancy, field in cells:
            try:
                amount = _parse_price(params.get(field))
            except ValueError:
                where = []
                if night:
                    where.append(night.strftime('%b %-d'))
                if occupancy:
                    where.append(f'{occupancy} occupants')
                return (f'Could not read the {"staff " if is_staff else ""}price for '
                        f'{" / ".join(where)}.')
            if amount is not None:
                parsed.append((night, occupancy, is_staff, amount))

    session.query(InventoryPrice).filter_by(inventory_id=item.id).delete(
        synchronize_session=False)
    for night, occupancy, is_staff, amount in parsed:
        session.add(InventoryPrice(inventory_id=item.id, night_date=night,
                                   occupancy=occupancy, is_staff=is_staff,
                                   price=amount))
    return ''


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


def _count_inventory_usage(assigned_ras):
    """Tally the live assignments for the inventory overview.

    Builds per-block per-night assignment counts + per-block status
    counts, plus per-block per-night waitlist demand. Demand counts
    exactly the rows the waitlist sweep would serve (`cron_eligible`),
    iterating each row's `waitlisted_gap_nights`, so this tally and the
    Waitlist dashboard's per-block rows agree.

    Returns (assigned_per_block_night, status_per_block,
    waitlist_per_block_night).
    """
    from uber.hotel.queries import occupancy_by_block_night

    assigned_per_block_night = occupancy_by_block_night(assigned_ras)
    status_per_block = defaultdict(lambda: defaultdict(int))
    for ra in assigned_ras:
        status_per_block[str(ra.inventory_id)][ra.status] += 1

    waitlist_per_block_night = defaultdict(lambda: defaultdict(int))
    for ra in assigned_ras:
        if not cron_eligible(ra):
            continue
        block_id = str(ra.inventory_id)
        for night in ra.waitlisted_gap_nights:
            waitlist_per_block_night[block_id][night] += 1

    return assigned_per_block_night, status_per_block, waitlist_per_block_night


def _waitlist_block_rows(session, filtered):
    """Per-block per-night waitlist demand rows for the admin Waitlist
    dashboard, derived from the (possibly search-filtered) set of
    waitlisted assignments. Demand counts exactly the rows the sweep
    would serve (`cron_eligible`), iterating each row's
    `waitlisted_gap_nights`. One row per inventory block, with the
    per-night queue depth and total demand, sorted by hotel then block
    name."""
    demand_by_block = defaultdict(lambda: defaultdict(list))
    for ra in filtered:
        if not cron_eligible(ra):
            continue
        block_id = str(ra.inventory_id)
        for night in ra.waitlisted_gap_nights:
            demand_by_block[block_id][night].append(ra)

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
    hotel_id = str(inventory.hotel_id) if inventory.hotel_id else None
    type_id = (str(inventory.suite_type_id) if inventory.is_suite
               else str(inventory.room_type_id))

    # Pre-filter in SQL with LIKE over the CSV preference columns so we
    # don't load every COMPLETE/PROCESSED application. The ids are UUIDs,
    # so a substring collision is effectively impossible; the exact
    # set-membership checks below still confirm on the loaded rows.
    candidates_q = session.query(LotteryApplication).filter(
        LotteryApplication.status.in_([c.COMPLETE, c.PROCESSED]),
    )
    if hotel_id:
        candidates_q = candidates_q.filter(
            LotteryApplication.hotel_preference.like(f'%{hotel_id}%'))
    if type_id:
        type_col = (LotteryApplication.suite_type_preference if inventory.is_suite
                    else LotteryApplication.room_type_preference)
        candidates_q = candidates_q.filter(type_col.like(f'%{type_id}%'))

    for app in candidates_q:
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
    hide/unhide/note POST handlers redirect back to the same view (see
    redirect_with_params for the HTTPRedirect footgun this avoids).
    'all' filter values are the defaults and are omitted."""
    return redirect_with_params(
        'room_issues',
        severity=severity if severity != 'all' else '',
        kind=kind if kind != 'all' else '',
        search=search,
        show_hidden='1' if show_hidden else '',
        message=message)



def _parse_index_filters(params):
    """The index page's advanced-filter params (filter_*), keyed by param
    name with empty values dropped - the exact dict the template gets
    back as `advanced_filters` to re-render the active filter chips."""
    return {k: v for k, v in params.items() if k.startswith('filter_') and v}


def _apps_with_rooms_in(session, applications, inventory_filter):
    """Narrow a LotteryApplication query to applications holding at least
    one RoomAssignment in the given inventory scope.

    `inventory_filter` is the RoomAssignment.inventory_id criterion (an
    `== id` or an `.in_(ids)`). No matching rooms yields an always-false
    filter rather than no filter, so an empty result stays empty instead
    of silently widening to every application.
    """
    matched_app_ids = [
        row[0] for row in session.query(
            RoomAssignment.lottery_application_id
        ).filter(
            inventory_filter,
            RoomAssignment.lottery_application_id.isnot(None),
        ).distinct().all()
    ]
    if not matched_app_ids:
        return applications.filter(sa.false())
    return applications.filter(LotteryApplication.id.in_(matched_app_ids))


def _apply_index_filters(session, applications, filters):
    """Chain the index page's advanced filters onto a LotteryApplication
    query. Hotel/inventory filters resolve through RoomAssignment (an
    application matches when any of its rooms sits at that hotel /
    inventory block)."""
    filter_status = filters.get('filter_status', '')
    filter_entry_type = filters.get('filter_entry_type', '')
    filter_hotel = filters.get('filter_hotel', '')
    filter_inventory = filters.get('filter_inventory', '')
    filter_partition = filters.get('filter_partition', '')
    filter_export_locked = filters.get('filter_export_locked', '')
    filter_staff = filters.get('filter_staff', '')

    if filter_status:
        applications = applications.filter(LotteryApplication.status == int(filter_status))
    if filter_entry_type:
        applications = applications.filter(LotteryApplication.entry_type == int(filter_entry_type))
    if filter_hotel:
        inv_ids = [str(inv.id) for inv in
                   session.query(HotelRoomInventory).filter_by(hotel_id=filter_hotel).all()]
        applications = (
            _apps_with_rooms_in(session, applications,
                                RoomAssignment.inventory_id.in_(inv_ids))
            if inv_ids else applications.filter(sa.false()))
    if filter_inventory:
        applications = _apps_with_rooms_in(
            session, applications,
            RoomAssignment.inventory_id == filter_inventory)
    if filter_partition:
        applications = applications.filter(LotteryApplication.partition_id == filter_partition)
    if filter_export_locked == 'true':
        applications = applications.filter(LotteryApplication.export_locked == True)  # noqa: E712
    elif filter_export_locked == 'false':
        applications = applications.filter(LotteryApplication.export_locked == False)  # noqa: E712
    if filter_staff == 'true':
        applications = applications.filter(LotteryApplication.is_staff_entry == True)  # noqa: E712
    elif filter_staff == 'false':
        applications = applications.filter(LotteryApplication.is_staff_entry == False)  # noqa: E712
    return applications


def _index_stats(session):
    """Headline entry counts for the index page: every application, the
    complete + hotel-eligible pool, and that pool's suite/room splits."""
    complete_valid_entries = session.query(LotteryApplication.id).filter(
        LotteryApplication.status == c.COMPLETE).join(
        LotteryApplication.attendee).filter(
        Attendee.hotel_lottery_eligible == True)  # noqa: E712
    room_count_base = complete_valid_entries.filter(
        LotteryApplication.entry_type != c.GROUP_ENTRY)
    return {
        'total_count': session.query(LotteryApplication.id).count(),
        'complete_count': complete_valid_entries.count(),
        'suite_count': room_count_base.filter(
            LotteryApplication.entry_type == c.SUITE_ENTRY).count(),
        'room_count': room_count_base.filter(or_(
            LotteryApplication.entry_type == c.ROOM_ENTRY,
            LotteryApplication.room_opt_out == False)).count(),  # noqa: E712
    }


@all_renderable()
class Root:
    def index(self, session, message='', page='0', search_text='', order='status', **params):
        if c.DEV_BOX and not int(page):
            page = 1

        stats = _index_stats(session)
        search_text = search_text.strip()
        advanced_filters = _parse_index_filters(params)

        # `applications` stays None until free-text search or the
        # advanced filters pick a population; None at the end means the
        # default everything view.
        applications = None
        count = 0

        if search_text:
            search_results, message = _search(session, search_text)
            if search_results and search_results.count():
                applications = search_results
                count = applications.count()
                if count == stats['total_count']:
                    message = 'Every lottery application matched this search.'
            elif not message:
                message = 'No matches found. Try searching the lottery tracking history instead.'

        if advanced_filters:
            if applications is None:
                # No (matching) free-text search: filter the full population.
                applications = session.query(LotteryApplication)
            applications = _apply_index_filters(
                session, applications, advanced_filters)
            count = applications.count()
            if not count and not message:
                message = 'No applications matched those filters.'

        if applications is None:
            if search_text:
                # The free-text search matched nothing: show an empty
                # result list (with the "no matches" message above)
                # instead of silently resetting to every application.
                applications = session.query(LotteryApplication).filter(sa.false())
            else:
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
            'search_results': bool(search_text) or bool(advanced_filters),
            'applications':   applications,
            'order':          Order(order),
            'search_count':   count,
            'advanced_filters': advanced_filters,
            **stats,
            **_picker_context(session),
        }

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
            # Export-lock chip on the Rooms section header (previously a
            # namespace() loop in the template).
            'any_export_locked': any(
                ra.export_locked for ra in
                (application.attendee.room_assignments
                 if application.attendee else [])),
        }

    def history(self, session, id):
        application = session.lottery_application(id)
        return {
            'application':  application,
            'changes': session.query(Tracking).filter(Tracking.model == 'LotteryApplication', Tracking.fk_id == id
                                                      ).order_by(Tracking.when).all(),
            'pageviews': session.query(PageViewTracking).filter(PageViewTracking.which == repr(application)
                                                                ).order_by(PageViewTracking.when).all(),
        }

    def emails(self, session, id):
        """The Emails tab of the per-application nav (see the nav_menu in
        form.html / history.html / emails.html)."""
        application = session.lottery_application(id)
        return {
            'application':  application,
            'emails': session.query(Email).filter(Email.fk_id == id
                                                  ).order_by(Email.generated).all(),
            'depts_by_sender': EmailService.emails_from_depts(session),
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

        # Filter chips: resolve the run's CSV filter-id lists to names
        # once here instead of re-splitting per badge in the template.
        hotel_filter_names, room_type_filter_names = [], []
        if lottery_run and lottery_run.hotel_filter:
            filter_ids = lottery_run.hotel_filter.split(',')
            hotel_filter_names = [h.name for h in picker['hotels']
                                  if str(h.id) in filter_ids]
        if lottery_run and lottery_run.room_type_filter:
            filter_ids = lottery_run.room_type_filter.split(',')
            room_type_filter_names = [
                rt.name for rt in picker['room_types'] + picker['suite_types']
                if str(rt.id) in filter_ids]

        # {application_id: [that attendee's rooms from this run]} -
        # previously a per-row selectattr over every room in the template
        # (O(apps x rooms)).
        run_rooms_by_app = {
            app.id: [ra for ra in (app.attendee.room_assignments
                                   if app.attendee else [])
                     if ra.lottery_run_id == lottery_run.id]
            for app in applications}

        return {
            'lottery_run': lottery_run,
            'applications': applications,
            'partition_lookup': partition_lookup,
            'hotel_filter_names': hotel_filter_names,
            'room_type_filter_names': room_type_filter_names,
            'run_rooms_by_app': run_rooms_by_app,
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

    def award_run(self, session, id, **params):

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

            price_error = _save_inventory_prices(session, item, params, event_nights)
            if price_error:
                session.rollback()
                raise HTTPRedirect('edit_inventory_item?id={}&message={}',
                                   '' if item.is_new else item.id, price_error)

            session.commit()

            # Notify applicants whose preferences referenced this block if it
            # was just deactivated. Async + best-effort - failures don't roll
            # back the inventory change.
            if became_inactive:
                _notify_applicants_of_inventory_change(session, item)

            # Auto-process waitlist for this inventory block. The engine
            # only flushes; commit here, then queue the notification
            # emails post-commit.
            waitlist_result = fulfill_waitlist(session, inventory_id=str(item.id))
            session.commit()
            for ra in waitlist_result.fulfilled_assignments:
                if ra.attendee and ra.lottery_application:
                    EmailService.queue_email(
                        session, 'hotel_lottery_waitlist_fulfilled', ra.lottery_application,
                        subject=f'{c.EVENT_NAME} Hotel Lottery - Room Dates Updated',
                        data={'assignment': ra, })
            save_msg = 'Inventory item saved.'
            if waitlist_result.fulfilled > 0:
                save_msg += f" Waitlist: {waitlist_result.fulfilled} entries fulfilled."

            raise HTTPRedirect('manage_inventory?message={}', save_msg)

        # Distinct catalog type codes per hotel, for the physical-room-
        # types checkbox dropdown (tracks the hotel select client-side).
        from uber.models.hotel import PhysicalRoom
        type_codes_by_hotel = defaultdict(list)
        for hotel_id, code in (session.query(PhysicalRoom.hotel_id,
                                             PhysicalRoom.type_code)
                               .filter(PhysicalRoom.type_code != '')
                               .distinct()
                               .order_by(PhysicalRoom.type_code)):
            type_codes_by_hotel[str(hotel_id)].append(code)

        return {
            'item': item,
            'forms': forms,
            'event_nights': event_nights,
            'type_codes_by_hotel': type_codes_by_hotel,
            'price_matrices': pricing.price_matrices(item) if not item.is_new else None,
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

    def upload_hotel_map(self, session, hotel_id, map_file=None,
                         csrf_token=None):
        """Store a hotel's floor map from a YAML upload. The SVG the
        picker consumes is rendered here, and the physical-room catalog
        is synced from the same file (see uber.hotel.floormap for the
        schema)."""
        from uber.hotel import floormap
        from uber.hotel import physical as hotel_physical
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('physical_rooms?hotel_id={}', hotel_id)
        check_csrf(csrf_token)
        hotel = session.query(LotteryHotel).get(hotel_id)
        if not hotel:
            raise HTTPRedirect('physical_rooms?message={}',
                               'Hotel not found.')
        if map_file is None or not getattr(map_file, 'file', None):
            raise HTTPRedirect('physical_rooms?hotel_id={}&message={}',
                               hotel.id, 'Choose a YAML file to upload.')
        raw = map_file.file.read()
        if len(raw) > 5 * 1024 * 1024:
            raise HTTPRedirect('physical_rooms?hotel_id={}&message={}',
                               hotel.id, 'The map is over the 5MB limit.')
        try:
            data = floormap.parse(raw.decode('utf-8-sig'))
            svg = floormap.render(data)
        except (UnicodeDecodeError, floormap.FloorMapError) as e:
            raise HTTPRedirect('physical_rooms?hotel_id={}&message={}',
                               hotel.id, f'Map rejected: {e}')

        blocks = session.query(HotelRoomInventory).filter_by(
            hotel_id=hotel.id, active=True).all()
        result = hotel_physical.import_rows(
            session, hotel, blocks, floormap.catalog_rows(data),
            apply_changes=True)
        if result['errors']:
            session.rollback()
            raise HTTPRedirect(
                'physical_rooms?hotel_id={}&message={}', hotel.id,
                f"Map rejected: {'; '.join(result['errors'][:3])}")
        hotel.map_yaml = raw.decode('utf-8-sig')
        hotel.map_svg = svg
        session.commit()
        floors = floormap.extract(svg)
        rooms = sum(len(f['rooms']) for f in floors)
        raise HTTPRedirect(
            'physical_rooms?hotel_id={}&message={}', hotel.id,
            f'Map saved: {len(floors)} floor(s), {rooms} '
            f"room shape(s); catalog {len(result['created'])} created, "
            f"{len(result['updated'])} updated"
            + (f", {len(result['uncategorized'])} with no matching block."
               if result['uncategorized'] else '.'))

    def delete_hotel_map(self, session, hotel_id, csrf_token=None):
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('physical_rooms?hotel_id={}', hotel_id)
        check_csrf(csrf_token)
        hotel = session.query(LotteryHotel).get(hotel_id)
        if not hotel:
            raise HTTPRedirect('physical_rooms?message={}',
                               'Hotel not found.')
        hotel.map_yaml = ''
        hotel.map_svg = ''
        session.commit()
        raise HTTPRedirect('physical_rooms?hotel_id={}&message={}',
                           hotel.id, 'Map removed.')

    def hotel_map(self, session, hotel_id):
        """The rendered floor-map SVG; the room-picker JS fetches this
        and inlines it."""
        hotel = session.query(LotteryHotel).get(hotel_id)
        if not hotel or not hotel.map_svg:
            raise cherrypy.HTTPError(404)
        cherrypy.response.headers['Content-Type'] = 'image/svg+xml'
        cherrypy.response.headers['Cache-Control'] = 'no-store'
        return hotel.map_svg.encode('utf-8')

    def hotel_map_yaml(self, session, hotel_id):
        """The floor map re-exported with the current physical-room
        catalog merged in, for offline editing and re-upload."""
        from uber.hotel import floormap
        from uber.hotel.physical import connection_map
        from uber.models.hotel import PhysicalRoom
        hotel = session.query(LotteryHotel).get(hotel_id)
        if not hotel:
            raise cherrypy.HTTPError(404)
        rooms = session.query(PhysicalRoom).filter_by(
            hotel_id=hotel.id).all()
        if not hotel.map_yaml and not rooms:
            raise cherrypy.HTTPError(404)
        connections = connection_map(session, hotel.id)
        catalog = [{
            'number': room.room_number,
            'floor': room.floor,
            'type': room.type_code,
            'ada': room.ada,
            'accessibility': room.accessibility_list,
            'connects_to': connections.get(room.id, []),
            'notes': room.notes,
        } for room in rooms]
        text = floormap.export_yaml(hotel.map_yaml, catalog)
        cherrypy.response.headers['Content-Type'] = 'text/yaml'
        cherrypy.response.headers['Content-Disposition'] = \
            f'attachment; filename="{hotel.export_name or "hotel"}-map.yaml"'
        return text.encode('utf-8')

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
    # data) lives in uber.hotel.exports; these handlers are the routes
    # that serve it per hotel.

    def _serve_booking_export(self, session, hotel_id, fmt):
        """Build, retain, and serve one per-hotel booking file.

        The bytes are stored (store_export_file) before they go out, so
        the exports page can hand back exactly what the hotel received.
        CC tokens are omitted from the layout by design.
        """
        hotel, filename, content_type, data = render_booking_export(
            session, hotel_id, fmt)
        if hotel is None:
            raise cherrypy.HTTPError(404, 'Hotel not found.')
        _, rows = booking_export_data(session, hotel_id)
        store_export_file(
            session, hotel, data, filename, content_type,
            source='admin', record_count=len(rows),
            exported_by=AdminAccount.admin_name() or '')
        session.commit()
        cherrypy.response.headers['Content-Type'] = content_type
        cherrypy.response.headers['Content-Disposition'] = \
            f'attachment; filename="{filename}"'
        return data

    def export_hotel_bookings_csv(self, session, hotel_id):
        return self._serve_booking_export(session, hotel_id, 'csv')

    def export_hotel_bookings_xlsx(self, session, hotel_id):
        return self._serve_booking_export(session, hotel_id, 'xlsx')

    def hotel_export_file(self, session, id):
        """Download a retained export exactly as the hotel received it."""
        entry = session.query(HotelExportLog).get(id)
        if not entry or not entry.filepath \
                or not os.path.exists(entry.filepath):
            raise cherrypy.HTTPError(404, 'That export file is not retained.')
        return serve_file(entry.filepath,
                          name=entry.filename or 'export',
                          content_type=entry.content_type or
                          'application/octet-stream')

    @ajax_gettable
    def hotel_change_details(self, session, hotel_id, start='', end=''):
        """Room changes for the exports page's change-row modal."""
        def parse(value):
            if not value:
                return None
            # A '+00:00' offset arrives as ' 00:00' when a caller forgets
            # to encode the '+'; restore it so the window still matches.
            value = re.sub(r' (\d{2}:\d{2})$', r'+\1', value.strip())
            parsed = dateparser.parse(value)
            return parsed.replace(tzinfo=UTC) if parsed and not parsed.tzinfo \
                else parsed

        # Gap rows are "what WE changed"; an import's own writes are
        # reported on that import's row instead.
        return {'changes': _change_rows_json(changed_rooms_between(
            session, hotel_id, parse(start), parse(end),
            exclude_imports=True))}

    @ajax_gettable
    def hotel_import_changes(self, session, id):
        """Room changes one uploaded import file caused."""
        entry = session.query(HotelImportFile).get(id)
        if not entry:
            return {'changes': []}
        return {'changes': _change_rows_json(import_changes(session, entry))}

    @ajax_gettable
    def hotel_file_rows(self, session, kind, id, page='1', page_size='50'):
        """One retained export/import file as table rows. Paginated - a
        real booking export runs to thousands of rows."""
        model = HotelExportLog if kind == 'export' else HotelImportFile
        entry = session.query(model).get(id)
        if not entry:
            return {'error': 'That file is gone.', 'columns': [], 'rows': []}

        columns, rows, error = read_stored_file(entry)
        if error:
            return {'error': error, 'columns': [], 'rows': []}

        size = clamp_page_size(page_size, default_size=50, max_size=200)
        try:
            page_num = max(1, int(page))
        except (TypeError, ValueError):
            page_num = 1
        start_row = (page_num - 1) * size
        return {
            'error': None,
            'filename': entry.filename,
            'columns': columns,
            'rows': [[row.get(col, '') for col in columns]
                     for row in rows[start_row:start_row + size]],
            'total': len(rows),
            'page': page_num,
            'pages': max(1, -(-len(rows) // size)),
        }

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

        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('export_tracking')
        check_csrf(csrf_token)

        upload = bookings_file or bookings_csv
        if not upload or not getattr(upload, 'file', None):
            raise HTTPRedirect(
                'export_tracking?message={}',
                'No file uploaded.')

        filename = (getattr(upload, 'filename', '') or '').lower()
        raw = upload.file.read()
        is_xlsx = filename.endswith(('.xlsx', '.xlsm')) or raw[:2] == b'PK'

        # Shared CSV/XLSX parser (uber.hotel.imports): case-insensitive
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

        rows = list(reader_iter)

        # Confirmation and cancellation numbers go through the shared
        # row-appliers (uber.hotel.imports): every-assignment matching, one
        # applied count per assignment touched. Email behavior stays here.
        conf_preview = apply_confirmation_rows(
            session, rows, apply_changes=True,
            on_update=lambda ra: _send_confirmation_updated_email(session, ra))
        updated = conf_preview['applied']

        # Unlike the cancellations import page - where a row's presence
        # means "cancelled" - this file lists every booking, so only rows
        # actually carrying a cancellation number cancel anything.
        cancel_rows = [
            row for row in rows
            if (row.get('cancellation_confirmation_number') or '').strip()]
        cancel_preview = apply_cancellation_rows(
            session, cancel_rows, apply_changes=True)
        cancelled = cancel_preview['applied']

        date_updates = 0
        unmatched = []

        for row in rows:
            app_id = (row.get('lottery_application_id') or '').strip()
            conf = (row.get('confirmation_num') or '').strip()
            new_conf = (row.get('hotel_confirmation_number') or '').strip()
            cancel_num = (row.get('cancellation_confirmation_number') or '').strip()
            new_ci = parse_iso_date(row.get('check_in_date'))
            new_co = parse_iso_date(row.get('check_out_date'))

            if not (new_conf or cancel_num or new_ci or new_co):
                continue  # Nothing to update for this row.

            ras = match_assignments(session, app_id, conf)
            if not ras:
                unmatched.append(conf or app_id or '(blank)')
                continue

            # Date columns: persist directly to every matching
            # RoomAssignment row whose dates differ.
            for ra in ras:
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

        hotel_inventory_ids = [str(inv.id) for inv in
                               session.query(HotelRoomInventory).filter_by(hotel_id=hotel.id).all()]

        base_q = (session.query(RoomAssignment)
                  .filter(RoomAssignment.inventory_id.in_(hotel_inventory_ids),
                          RoomAssignment.is_live)
                  .order_by(RoomAssignment.parent_assignment_id.asc().nullsfirst(),
                            RoomAssignment.created.asc()))
        assignments, total, page_num, page_count = paginate(
            base_q, page, page_size, default_size=25, min_size=5, max_size=200)
        ps = clamp_page_size(page_size, default_size=25, min_size=5, max_size=200)

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

    def export_tracking(self, session, message='', hotel_id=''):
        hotels = compute_export_tracking(session)
        all_hotels = session.query(LotteryHotel).order_by(
            LotteryHotel.name).all()

        # The chronological view is per hotel: everything sent to and
        # received from one hotel, with the room churn between.
        timeline_hotel = None
        if hotel_id:
            timeline_hotel = session.query(LotteryHotel).get(hotel_id)
        elif all_hotels:
            timeline_hotel = all_hotels[0]

        from uber.hotel.exports import unprocessed_imports
        from uber.models.hotel import ImportMappingTemplate

        return {
            'hotels': hotels,
            'message': message,
            'timeline_hotel': timeline_hotel,
            'timeline': (hotel_activity_timeline(session, timeline_hotel.id)
                         if timeline_hotel else []),
            'all_hotels': all_hotels,
            'pending_uploads': unprocessed_imports(session),
            'import_templates': session.query(ImportMappingTemplate).filter_by(
                active=True).order_by(ImportMappingTemplate.name).all(),
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

        from uber.hotel.imports import import_confirmation_file
        result = import_confirmation_file(
            session, raw, getattr(upload, 'filename', ''), hotel=hotel,
            source='admin', uploaded_by=uploaded_by,
            content_type=getattr(upload, 'content_type', '') or '')
        # Commit even when parsing failed: the retained-upload record
        # (HotelImportFile) must persist either way, and the service layer
        # only flushes.
        session.commit()

        record = result.get('record')
        if record is not None:
            review = _prepare_import_review(
                session, record, raw, getattr(upload, 'filename', ''),
                template_id=params.get('template_id', ''))
            session.commit()
            if review:
                raise HTTPRedirect(
                    'review_import?id={}&message={}', record.id,
                    f"Read {review['total']} row(s) with the "
                    f"{review['template_name']} format. Review the changes below.")

        if result.get('error'):
            message = f"File saved, but could not be parsed: {result['error']}"
        else:
            message = f"Imported {result['updated']} update(s), {result['unchanged']} unchanged."
        raise HTTPRedirect('export_tracking?message={}', message)

    def import_templates(self, session, message=''):
        """The saved upload formats, with what each one is used by."""
        from uber.models.hotel import ImportMappingTemplate

        templates = session.query(ImportMappingTemplate).order_by(
            ImportMappingTemplate.name).all()
        hotels_by_template = defaultdict(list)
        for hotel in session.query(LotteryHotel).filter(
                LotteryHotel.default_import_template_id.isnot(None)).all():
            hotels_by_template[str(hotel.default_import_template_id)].append(hotel.name)

        usage = dict(session.query(
            HotelImportFile.template_id, sa.func.count(HotelImportFile.id)).filter(
            HotelImportFile.template_id.isnot(None)).group_by(
            HotelImportFile.template_id).all())

        return {
            'templates': templates,
            'hotels_by_template': hotels_by_template,
            'usage': {str(k): v for k, v in usage.items()},
            'message': message,
        }

    def edit_import_template(self, session, id='', message='', **params):
        """Build one hotel's format: which column feeds which field, how they
        spell our enum values, and what date formats they use.

        The maps are edited as raw params rather than through WTForms: the
        column set is whatever the sample file happens to have.
        """
        from uber.hotel import mapping
        from uber.models.hotel import ImportMappingTemplate

        if id and id not in ('None', ''):
            template = session.query(ImportMappingTemplate).get(id)
            if not template:
                raise HTTPRedirect('import_templates?message={}', 'Format not found.')
        else:
            template = ImportMappingTemplate()

        if cherrypy.request.method == 'POST':
            check_csrf(params.get('csrf_token'))
            template.name = (params.get('name') or '').strip()
            template.description = (params.get('description') or '').strip()
            template.sheet_name = (params.get('sheet_name') or '').strip()
            try:
                template.header_row = max(1, int(params.get('header_row') or 1))
            except ValueError:
                template.header_row = 1
            template.active = params.get('active', 'true') != 'false'

            column_map, format_map, enum_map = {}, {}, {}
            for key, value in params.items():
                if key.startswith('column__') and value:
                    column_map[key[len('column__'):]] = value
                elif key.startswith('format__') and value:
                    format_map[key[len('format__'):]] = value
                elif key.startswith('enum__') and value:
                    # enum__<target>__<source value>
                    rest = key[len('enum__'):]
                    target, _, source_value = rest.partition('__')
                    if target and source_value:
                        enum_map.setdefault(target, {})[source_value] = value

            template.column_map = column_map
            template.format_map = format_map
            template.enum_map = enum_map
            template.source_signature = mapping.signature_for(column_map.keys())
            session.add(template)
            session.commit()
            raise HTTPRedirect('import_templates?message={}',
                               f'{template.name or "Format"} saved.')

        return {
            'template': template,
            'target_fields': mapping.TARGET_FIELDS,
            'payment_types': c.HOTEL_PAYMENT_TYPE_OPTS,
            'message': message,
        }

    @ajax
    def preview_import_template(self, session, maps='', hotel_id='',
                                sample_file_id='', csrf_token=None, **params):
        """Read a sample file with the maps currently on screen.

        Nothing is written, so an admin can get the mapping right before
        saving the format or touching a real upload.
        """
        import json as _json
        from uber.hotel import mapping

        if cherrypy.request.method != 'POST':
            return {'error': 'This endpoint requires a POST.'}
        check_csrf(csrf_token)

        upload = params.get('sample_file')
        raw = None
        filename = ''
        if upload is not None and getattr(upload, 'file', None):
            raw = upload.file.read()
            filename = getattr(upload, 'filename', '')
            if len(raw) > 5 * 1024 * 1024:
                return {'error': 'Sample file is too large (5 MB max).'}
        elif sample_file_id:
            record = session.query(HotelImportFile).get(sample_file_id)
            if not record or not record.filepath or not os.path.exists(record.filepath):
                return {'error': 'That stored upload is no longer on disk.'}
            with open(record.filepath, 'rb') as f:
                raw = f.read()
            filename = record.filename or ''

        if raw is None:
            return {'error': 'Choose a sample file first.'}

        try:
            supplied = _json.loads(maps or '{}')
        except ValueError:
            return {'error': 'Could not read the mapping.'}

        draft = mapping.draft_template(supplied)

        fieldnames, _rows, error = mapping.parse_with_template(raw, filename, draft)
        if error:
            return {'error': error}

        rows, error = mapping.build_rows(session, raw, filename, draft,
                                         hotel_id=hotel_id or None)
        if error:
            return {'error': error}

        counts = mapping.counts_for(rows)
        sample = []
        for row in rows[:10]:
            sample.append({
                'status': row['status'],
                'mapped': {mapping.TARGETS_BY_KEY[k]['label']: v
                           for k, v in row['mapped'].items()
                           if k in mapping.TARGETS_BY_KEY and v},
            })

        return {'ok': True, 'headers': fieldnames, 'total': len(rows),
                'counts': counts, 'sample': sample}

    def delete_import_template(self, session, id='', csrf_token=None):
        from uber.models.hotel import ImportMappingTemplate

        _require_post_csrf({'csrf_token': csrf_token}, redirect='import_templates')

        template = session.query(ImportMappingTemplate).get(id)
        if not template:
            raise HTTPRedirect('import_templates?message={}', 'Format not found.')

        used_by_hotel = session.query(LotteryHotel).filter_by(
            default_import_template_id=template.id).count()
        used_by_file = session.query(HotelImportFile).filter_by(
            template_id=template.id).count()
        if used_by_hotel or used_by_file:
            # Deleting would orphan the provenance of a completed review.
            template.active = False
            session.add(template)
            session.commit()
            raise HTTPRedirect(
                'import_templates?message={}',
                f'{template.name} is in use, so it was deactivated rather than '
                'deleted. It will no longer be detected automatically.')

        name = template.name
        session.delete(template)
        session.commit()
        raise HTTPRedirect('import_templates?message={}', f'{name} deleted.')

    def review_import(self, session, id='', page='1', filter='all', message=''):
        """Row-by-row review of one uploaded file.

        Its own page rather than an extension of the changes modal: per-value
        sync and disambiguation need CSRF-bearing posts and pagination, and a
        review worked through over several sittings needs to be linkable.
        """
        from uber.hotel import mapping

        record = session.query(HotelImportFile).get(id)
        if not record:
            raise HTTPRedirect('export_tracking?message={}', 'Upload not found.')

        rows = list(record.parsed_rows or [])
        assignment_ids = {aid for row in rows for aid in row.get('assignment_ids', [])}
        by_id = {}
        if assignment_ids:
            by_id = {str(ra.id): ra for ra in session.query(RoomAssignment).filter(
                RoomAssignment.id.in_(assignment_ids)).all()}

        # The comparison is recomputed here rather than stored, so a value
        # synced a moment ago stops showing as changed.
        prepared = []
        for row in rows:
            ids = row.get('assignment_ids', [])
            primary = by_id.get(ids[0]) if len(ids) == 1 else None
            diff = mapping.diff_row(primary, row.get('mapped', {})) if primary else []
            prepared.append({
                'index': row.get('index'),
                'status': row.get('status'),
                'source': row.get('source', {}),
                'mapped': row.get('mapped', {}),
                'assignment': primary,
                'candidates': [by_id[i] for i in ids if i in by_id],
                'diff': diff,
                'changed': [d for d in diff if d['changed']],
            })

        if filter == 'changed':
            prepared = [r for r in prepared if r['changed']]
        elif filter in ('ambiguous', 'unmatched', 'matched'):
            prepared = [r for r in prepared if r['status'] == filter]

        page_num = max(1, int(page or 1))
        page_size = 50
        total = len(prepared)
        page_count = max(1, (total + page_size - 1) // page_size)
        page_num = min(page_num, page_count)
        window = prepared[(page_num - 1) * page_size:page_num * page_size]

        return {
            'record': record,
            'rows': window,
            'total': total,
            'page': page_num,
            'page_count': page_count,
            'filter': filter,
            'counts': {
                'matched': record.matched_count,
                'ambiguous': record.ambiguous_count,
                'unmatched': record.unmatched_count,
            },
            'message': message,
        }

    @ajax
    def sync_import_value(self, session, file_id='', row_index='', field='',
                          assignment_id='', csrf_token=None):
        """Write one imported value onto its booking."""
        from uber.hotel import mapping

        if cherrypy.request.method != 'POST':
            return {'error': 'This endpoint requires a POST.'}
        check_csrf(csrf_token)

        record = session.query(HotelImportFile).get(file_id)
        ra = session.query(RoomAssignment).get(assignment_id) if assignment_id else None
        if not record or not ra:
            return {'error': 'That upload or booking no longer exists.'}

        row = next((r for r in (record.parsed_rows or [])
                    if str(r.get('index')) == str(row_index)), None)
        if row is None:
            return {'error': 'That row is no longer in this upload.'}

        value = (row.get('mapped') or {}).get(field, '')
        ok, message = mapping.sync_value(session, ra, field, value)
        if not ok:
            session.rollback()
            return {'error': message}
        session.commit()
        return {'ok': True, 'message': message,
                'current': mapping._current_value(ra, field)}

    @ajax
    def resolve_import_row(self, session, file_id='', row_index='',
                           assignment_id='', csrf_token=None):
        """Point an ambiguous row at one booking.

        Stamps the row's acknowledgement number onto the chosen booking, so
        that booking matches outright on every later upload rather than
        needing to be disambiguated again.
        """
        from uber.hotel import mapping

        if cherrypy.request.method != 'POST':
            return {'error': 'This endpoint requires a POST.'}
        check_csrf(csrf_token)

        record = session.query(HotelImportFile).get(file_id)
        ra = session.query(RoomAssignment).get(assignment_id) if assignment_id else None
        if not record or not ra:
            return {'error': 'That upload or booking no longer exists.'}

        rows = list(record.parsed_rows or [])
        row = next((r for r in rows if str(r.get('index')) == str(row_index)), None)
        if row is None:
            return {'error': 'That row is no longer in this upload.'}

        confirmation = (row.get('mapped') or {}).get(
            'assignment.hotel_confirmation_number', '').strip()
        if confirmation:
            ra.hotel_confirmation_number = confirmation
            session.add(ra)

        row['assignment_ids'] = [str(ra.id)]
        row['status'] = 'matched'
        record.parsed_rows = rows
        counts = mapping.counts_for(rows)
        record.matched_count = counts['matched']
        record.ambiguous_count = counts['ambiguous']
        record.unmatched_count = counts['unmatched']
        session.add(record)
        session.commit()

        return {'ok': True, 'message': f'Row matched to {ra.room_summary}.'}

    def mark_import_processed(self, session, id='', status='processed',
                              csrf_token=None):
        _require_post_csrf({'csrf_token': csrf_token}, redirect='export_tracking')

        record = session.query(HotelImportFile).get(id)
        if not record:
            raise HTTPRedirect('export_tracking?message={}', 'Upload not found.')

        account = session.current_admin_account()
        record.status = 'ignored' if status == 'ignored' else 'processed'
        record.processed_at = datetime.now(UTC)
        record.processed_by = (account.attendee.full_name
                               if account and account.attendee else 'Admin')
        session.add(record)
        session.commit()
        raise HTTPRedirect('export_tracking?message={}',
                           f'{record.filename or "Upload"} marked {record.status}.')

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

        lottery_type_val = LOTTERY_TYPE_VALUES.get(lottery_type)
        if lottery_type_val is None:
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

        # None for a combined run, which pulls room and suite blocks together.
        is_suite = {c.ROOM_ENTRY: False, c.SUITE_ENTRY: True}.get(lottery_type_val)
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

                night_data = []
                for night in event_nights:
                    available = effective_capacity(block_id, inv.quantity_for_night(night))
                    assigned = assigned_per_block_night.get(block_id, {}).get(night, 0)
                    waitlisted = waitlist_per_block_night.get(block_id, {}).get(night, 0)
                    night_data.append({
                        'night': night,
                        'available': available,
                        'assigned': assigned,
                        'remaining': max(0, available - assigned),
                        'waitlisted': waitlisted,
                    })

                # status_per_block is keyed by RoomAssignment.status
                # (assignment statuses), so those are the only counts
                # that can be non-zero here.
                total_assigned = sum(status_per_block.get(block_id, {}).values())
                info = {
                    'inventory': inv,
                    'room_type': inv.suite_type if is_suite else inv.room_type,
                    'quantity': effective_capacity(block_id, inv.quantity),
                    'nights': night_data,
                    'total_assigned': total_assigned,
                    'awaiting_card': status_per_block.get(
                        block_id, {}).get(c.ASSIGNED, 0),
                    'secured': status_per_block.get(
                        block_id, {}).get(c.SECURED, 0),
                }
                inventory[hotel_obj].append(info)
            return inventory

        room_inventory = build_inventory_data(is_suite=False)
        suite_inventory = build_inventory_data(is_suite=True)

        # Headline numbers for the summary cards. Everything except the
        # block count is room-nights (one room for one night), summed
        # over every block and event night.
        infos = [info for inventory in (room_inventory, suite_inventory)
                 for block_list in inventory.values()
                 for info in block_list]
        nights = [nd for i in infos for nd in i['nights']]
        summary = {
            'blocks': len(infos),
            'offered': sum(nd['available'] for nd in nights),
            'assigned': sum(nd['assigned'] for nd in nights),
            'remaining': sum(nd['remaining'] for nd in nights),
            'waitlisted': sum(nd['waitlisted'] for nd in nights),
        }

        # Per-hotel room-night totals, shown next to each hotel name.
        hotel_totals = defaultdict(lambda: {'assigned': 0, 'remaining': 0})
        for inventory in (room_inventory, suite_inventory):
            for hotel_obj, block_list in inventory.items():
                key = str(hotel_obj.id) if hotel_obj else ''
                for info in block_list:
                    for nd in info['nights']:
                        hotel_totals[key]['assigned'] += nd['assigned']
                        hotel_totals[key]['remaining'] += nd['remaining']

        return {
            'room_inventory': room_inventory,
            'suite_inventory': suite_inventory,
            'summary': summary,
            'hotel_totals': hotel_totals,
            'event_nights': event_nights,
            'partitions': partitions,
            'now': localized_now(),
            'current_partition': partition,
            'message': message,
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
                ra.lottery_run.name if ra.lottery_run else '',
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
        from sqlalchemy.orm import selectinload

        # Eager-load blocks: the template shows each partition's block
        # count and allocation, so fetch them in one IN query instead of
        # one lazy load per partition.
        partitions = session.query(InventoryPartition).options(
            selectinload(InventoryPartition.blocks)).order_by(
            InventoryPartition.name).all()

        # Count live assignments per partition in SQL instead of loading
        # every live RoomAssignment row just to count it.
        assigned_per_partition = defaultdict(int)
        for partition_id, n in (
                session.query(RoomAssignment.partition_id,
                              func.count(RoomAssignment.id))
                .filter(RoomAssignment.is_live,
                        RoomAssignment.inventory_id.isnot(None))
                .group_by(RoomAssignment.partition_id)):
            key = str(partition_id) if partition_id else '_none'
            assigned_per_partition[key] += n

        # Compute total allocation and non-partitioned capacity
        total_partition_alloc = sum(
            b.quantity for p in partitions for b in p.blocks)

        total_inventory = session.query(
            func.coalesce(func.sum(HotelRoomInventory.quantity), 0)).filter(
            HotelRoomInventory.active.is_(True)).scalar()

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

    # ------------------------------------------------------------------
    # Physical-room catalog: the per-hotel map of real rooms
    # (PhysicalRoom / PhysicalRoomConnection). Logic in uber.hotel.physical.
    # ------------------------------------------------------------------

    def physical_rooms(self, session, hotel_id='', message='', search='',
                       inventory_id='', type_code='', ada='', placement='',
                       service='', unroomed_page='1', unroomed_size='25',
                       unroomed_sort='dates'):
        """Per-hotel catalog AND assignment board: floor-map upload,
        unroomed live bookings, then the catalog by floor with current
        occupants. Absorbed the old room_board page."""
        from uber.hotel import floormap
        from uber.hotel import physical as hotel_physical
        from uber.hotel.queries import vacant_rooms_map

        picker = _picker_context(session)
        hotels = picker['hotels']
        hotel = None
        if hotel_id:
            hotel = session.query(LotteryHotel).get(hotel_id)
        elif hotels:
            # Default to the first hotel; hotel-physical-rooms.js swaps
            # in the admin's last-viewed hotel from localStorage.
            hotel = hotels[0]

        floors, connections, bookings, blocks = [], {}, {}, []
        unroomed, map_coverage = [], None
        type_codes, total_rooms = [], 0
        # The template does arithmetic with the page size, so clamp it to
        # an int here rather than passing the raw query param through.
        unroomed_size = clamp_page_size(unroomed_size, default_size=25)
        unroomed_total, unroomed_pages = 0, 1
        filters = {'search': search, 'inventory_id': inventory_id,
                   'type_code': type_code, 'ada': ada,
                   'placement': placement, 'service': service}
        if hotel:
            floors = hotel_physical.rooms_by_floor(session, hotel.id)
            connections = hotel_physical.connection_map(session, hotel.id)
            bookings = hotel_physical.live_bookings_by_room(session, hotel.id)
            blocks = [inv for inv in picker['inventory_blocks']
                      if inv.hotel_id == hotel.id]
            total_rooms = sum(len(rooms) for _, rooms in floors)
            type_codes = sorted({room.type_code for _, rooms in floors
                                 for room in rooms if room.type_code})

            hotel_inv_ids = [inv.id for inv in blocks]
            if hotel_inv_ids:
                pending_q = session.query(RoomAssignment).filter(
                    RoomAssignment.physical_room_id.is_(None),
                    RoomAssignment.is_live,
                    RoomAssignment.inventory_id.in_(hotel_inv_ids))
                if unroomed_sort == 'attendee':
                    pending_q = pending_q.outerjoin(
                        Attendee, Attendee.id == RoomAssignment.attendee_id)
                pending_q = pending_q.order_by(
                    *_unroomed_order(unroomed_sort),
                    RoomAssignment.created.asc())
                pending, unroomed_total, unroomed_page, unroomed_pages = \
                    paginate(pending_q, unroomed_page, unroomed_size)
                if pending:
                    # Two queries for the page instead of two per
                    # unroomed booking (see vacant_rooms_map). Only the
                    # COUNT is rendered; the options themselves load per
                    # dropdown from vacant_rooms_json.
                    options_by_ra = vacant_rooms_map(session, hotel.id, pending)
                    unroomed = [
                        {'ra': ra, 'option_count': len(options_by_ra[ra.id])}
                        for ra in pending]

            if hotel.map_svg:
                map_coverage = floormap.coverage(
                    hotel.map_svg,
                    [r.room_number for _, rooms in floors for r in rooms])

        # The map modal keeps the whole hotel; only the floor listing
        # below it responds to the filters.
        map_rooms = (hotel_physical.floor_map_rooms(floors, bookings)
                     if hotel and hotel.map_svg else [])
        filtering = any(filters.values())
        if hotel and filtering:
            floors = hotel_physical.filter_rooms(floors, bookings, **filters)

        # Rows are fetched per floor by hotel-physical-rooms.js on first
        # expand (physical_rooms_floor), so this page ships only the
        # headers - a full catalog is thousands of rows.
        floor_summaries = [{
            'floor': floor,
            'rooms': len(rooms),
            'occupied': sum(1 for room in rooms if bookings.get(room.id)),
        } for floor, rooms in floors]

        return {
            'message': message,
            'hotels': hotels,
            'hotel': hotel,
            'floor_summaries': floor_summaries,
            'blocks': blocks,
            'unroomed': unroomed,
            'unroomed_total': unroomed_total,
            'unroomed_page': unroomed_page,
            'unroomed_pages': unroomed_pages,
            'unroomed_size': unroomed_size,
            'unroomed_sort': unroomed_sort,
            'map_coverage': map_coverage,
            'map_rooms': map_rooms,
            'type_codes': type_codes,
            'filters': filters,
            'filtering': filtering,
            'shown_rooms': sum(len(rooms) for _, rooms in floors),
            'total_rooms': total_rooms,
        }

    def physical_rooms_floor(self, session, hotel_id, floor='', **filters):
        """One floor's room rows, fetched on demand by the accordion.
        Returns an HTML fragment rendered from the same macro the page
        would have used."""
        from uber.decorators import render
        from uber.hotel import physical as hotel_physical

        hotel = session.query(LotteryHotel).get(hotel_id)
        if not hotel:
            raise cherrypy.HTTPError(404)
        floors = hotel_physical.rooms_by_floor(session, hotel.id)
        bookings = hotel_physical.live_bookings_by_room(session, hotel.id)
        scoped = {k: v for k, v in filters.items()
                  if k in ('search', 'inventory_id', 'type_code', 'ada',
                           'placement', 'service') and v}
        if scoped:
            floors = hotel_physical.filter_rooms(floors, bookings, **scoped)
        rooms = next((r for f, r in floors if f == floor), [])
        cherrypy.response.headers['Content-Type'] = 'text/html'
        return render('hotel_lottery_admin/_floor_rows.html', {
            'rooms': rooms,
            'hotel': hotel,
            'bookings': bookings,
            'connections': hotel_physical.connection_map(session, hotel.id),
        })

    def room_board(self, session, hotel_id='', message=''):
        """Merged into physical_rooms; kept for bookmarks."""
        raise HTTPRedirect('physical_rooms?hotel_id={}&message={}',
                           hotel_id, message)

    def edit_physical_room(self, session, id=None, hotel_id='', message='',
                           **params):
        """Create or edit one PhysicalRoom, including its connections."""
        from uber.hotel import physical as hotel_physical
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

        from uber.hotel.physical import connection_map
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
        from uber.hotel import physical as hotel_physical
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
        from uber.hotel import physical as hotel_physical
        from uber.hotel.imports import parse_spreadsheet

        if cherrypy.request.method == 'POST':
            check_csrf(params.get('csrf_token'))

        picker = _picker_context(session)
        hotel = session.query(LotteryHotel).get(hotel_id) if hotel_id else None
        preview = None
        applied = False

        upload = params.get('import_file')
        if hotel and upload is not None and getattr(upload, 'file', None):
            raw = upload.file.read()
            if len(raw) > 5 * 1024 * 1024:
                message = 'The file is over the 5MB limit.'
            else:
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
                        message = (
                            f"Imported {len(preview['created'])} new and "
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

    def board_assign(self, session, assignment_id, physical_room_id,
                     hotel_id='', csrf_token=None):
        from uber.models.hotel import PhysicalRoom
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('physical_rooms?hotel_id={}', hotel_id)
        check_csrf(csrf_token)
        ra = session.query(RoomAssignment).get(assignment_id)
        room = session.query(PhysicalRoom).get(physical_room_id)
        if not ra or not room:
            raise HTTPRedirect('physical_rooms?hotel_id={}&message={}',
                               hotel_id, 'Booking or room not found.')
        placed, error = assign_physical_room(session, ra, room)
        if error:
            raise HTTPRedirect('physical_rooms?hotel_id={}&message={}',
                               hotel_id or room.hotel_id, error)
        session.commit()
        numbers = ', '.join(a.physical_room.room_number for a in placed)
        raise HTTPRedirect(
            'physical_rooms?hotel_id={}&message={}',
            hotel_id or room.hotel_id,
            f'Room {numbers} assigned.' if len(placed) == 1
            else f'Rooms {numbers} assigned (suite + connectors).')

    @ajax_gettable
    def vacant_rooms_json(self, session, assignment_id):
        """Rooms this booking could take, for the physical-rooms page's
        assign dropdowns. Fetched on first focus (hotel-physical-rooms
        .js) - a catalog of thousands would otherwise render tens of
        thousands of <option>s into the page."""
        from uber.hotel import physical as hotel_physical
        ra = session.query(RoomAssignment).get(assignment_id)
        if not ra or not ra.inventory:
            return {'options': []}
        options = []
        for room, picks in hotel_physical.connector_placements(session, ra):
            group = [room] + [target for _, target in picks]
            options.append({
                'id': room.id,
                'label': '{}{}{}{}'.format(
                    room.room_number,
                    f' + {len(picks)} connected' if picks else '',
                    f' (floor {room.floor})' if room.floor else '',
                    ' [ADA]' if room.ada else ''),
                # Every room the pick would take, for the map's
                # group highlight and for pruning other dropdowns.
                'group': [r.id for r in group],
                'group_numbers': [r.room_number for r in group],
            })
        return {'options': options}

    @ajax
    def board_assign_json(self, session, assignment_id='',
                          physical_room_id='', **params):
        """Instant-save variant of board_assign for the physical-rooms
        page dropdowns (hotel-physical-rooms.js). CSRF is checked by
        @ajax. The caller posts the whole assign form, so extra fields
        (hotel_id) arrive here and are ignored; missing ones answer with
        JSON rather than a 500 the caller can't parse."""
        from uber.models.hotel import PhysicalRoom
        if not (assignment_id and physical_room_id):
            return {'success': False, 'message': 'Pick a room first.'}
        ra = session.query(RoomAssignment).get(assignment_id)
        room = session.query(PhysicalRoom).get(physical_room_id)
        if not ra or not room:
            return {'success': False, 'message': 'Booking or room not found.'}
        placed, error = assign_physical_room(session, ra, room)
        if error:
            return {'success': False, 'message': error}
        session.commit()
        return {
            'success': True,
            'room_id': room.id,
            'room_number': room.room_number,
            # Connector rooms went with it; the caller drops all of them
            # from the other dropdowns.
            'room_ids': [a.physical_room_id for a in placed],
            'room_numbers': [a.physical_room.room_number for a in placed],
        }

    def board_unassign(self, session, assignment_id, hotel_id='',
                       csrf_token=None):
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('physical_rooms?hotel_id={}', hotel_id)
        check_csrf(csrf_token)
        ra = session.query(RoomAssignment).get(assignment_id)
        if not ra:
            raise HTTPRedirect('physical_rooms?hotel_id={}&message={}',
                               hotel_id, 'Booking not found.')
        ra.physical_room_id = None
        ra.physical_room_auto = False
        session.add(ra)
        session.commit()
        raise HTTPRedirect('physical_rooms?hotel_id={}&message={}', hotel_id,
                           'Physical room unassigned (the room number text '
                           'is kept for reference).')

    def auto_assign_physical(self, session, hotel_id, csrf_token=None):
        from uber.hotel import physical as hotel_physical
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('physical_rooms?hotel_id={}', hotel_id)
        check_csrf(csrf_token)
        result = hotel_physical.auto_assign_physical_rooms(session, hotel_id)
        session.commit()
        msg = f"Auto-assigned {result['assigned']} booking(s)."
        if result['skipped']:
            msg += f" {len(result['skipped'])} could not be placed."
        raise HTTPRedirect('physical_rooms?hotel_id={}&message={}',
                           hotel_id, msg)

    def clear_physical_assignments(self, session, hotel_id, scope='all',
                                   csrf_token=None):
        from uber.hotel import physical as hotel_physical
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('physical_rooms?hotel_id={}', hotel_id)
        check_csrf(csrf_token)
        cleared = hotel_physical.clear_physical_assignments(
            session, hotel_id, auto_only=scope == 'auto')
        session.commit()
        what = 'auto-placed' if scope == 'auto' else 'physical'
        raise HTTPRedirect('physical_rooms?hotel_id={}&message={}', hotel_id,
                           f'Cleared {cleared} {what} assignment(s).')

    @csv_file
    def front_desk_csv(self, out, session, hotel_id):
        """Front-desk / housekeeping export: every catalogued room in
        floor order with its current booking, for handing to the hotel.
        They may reassign at check-in; we don't get that back."""
        from uber.hotel import physical as hotel_physical
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

        Parses the upload with uber.hotel.imports.parse_confirmation_rows -
        the same parser as the hotel portal - so both pages accept CSV and
        XLSX with case-insensitive headers (spaces treated as underscores).

        Two-step UX: upload shows a preview of what would change. The admin
        then ticks "apply" and resubmits the file to write. Matching
        semantics per kind live in uber.hotel.imports.apply_confirmation_rows
        / apply_cancellation_rows (every-assignment matching: a matched
        booking's value is written to every assignment on its application).
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
                preview = apply_cancellation_rows(session, rows, apply_changes)
            else:
                # Email behavior stays with this controller: the admin
                # confirmation import notifies the attendee per change.
                preview = apply_confirmation_rows(
                    session, rows, apply_changes,
                    on_update=lambda ra: _send_confirmation_updated_email(session, ra))

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

    @ajax
    def waitlist_reveal_recipients(self, session, id='', csrf_token=None):
        """Who a send would reach right now, from the same query the sender
        uses."""
        if cherrypy.request.method != 'POST':
            return {'error': 'This endpoint requires a POST.'}
        check_csrf(csrf_token)

        reveal = session.query(WaitlistReveal).get(id)
        if not reveal:
            return {'error': 'Reveal not found.'}

        eligible, emailed, pending, new_ids = _waitlist_reveal_candidates(
            session, reveal)
        would_email = list(pending) + new_ids

        sample = []
        for attendee in session.query(Attendee).filter(
                Attendee.id.in_(would_email[:200])).all() if would_email else []:
            sample.append({'name': attendee.full_name, 'email': attendee.email,
                           'badge': attendee.badge_num or ''})
        sample.sort(key=lambda row: row['name'])

        return {
            'ok': True,
            'eligible': len(eligible),
            'already_emailed': len(emailed),
            'awaiting_send': len(pending),
            'new': len(new_ids),
            'would_email': len(would_email),
            'sample': sample,
            'truncated': len(would_email) > len(sample),
        }

    @ajax
    def preview_waitlist_reveal_email(self, session, id='', csrf_token=None):
        """The reveal email as one recipient would receive it."""
        if cherrypy.request.method != 'POST':
            return {'error': 'This endpoint requires a POST.'}
        check_csrf(csrf_token)

        reveal = session.query(WaitlistReveal).get(id)
        if not reveal:
            return {'error': 'Reveal not found.'}

        _eligible, _emailed, pending, new_ids = _waitlist_reveal_candidates(
            session, reveal)
        sample_ids = list(pending) + new_ids
        attendee = (session.query(Attendee).get(sample_ids[0]) if sample_ids
                    else session.query(Attendee).first())
        if not attendee:
            return {'error': 'No attendee available to preview against.'}

        automated = session.query(AutomatedEmail).filter_by(
            ident='hotel_lottery_waitlist_reveal').first()
        if not automated:
            return {'error': 'The reveal email is not configured yet.'}

        # Unflushed: previewing must not create a link row.
        link = WaitlistRevealLink(waitlist_reveal_id=reveal.id,
                                  attendee_id=attendee.id,
                                  token='PREVIEW-TOKEN')
        data = {'reveal': reveal, 'link': link}
        subject = automated.render_subject(attendee, data)
        body = automated.render_body(attendee, data)

        # The template only prints the ubersystem token URL today, but a later
        # edit could start printing the destination. Catching it here turns a
        # silent leak into a visible one.
        leaked = bool(reveal.external_url and reveal.external_url in body)
        if leaked:
            body = body.replace(reveal.external_url, '[HIDDEN UNTIL REVEAL TIME]')

        return {'ok': True, 'subject': subject, 'body': body,
                'recipient': f'{attendee.full_name} <{attendee.email}>',
                'leak_warning': leaked}

    def generate_waitlist_reveal_links(self, session, id='', csrf_token=None):
        """Create the link rows without emailing anyone, so the URLs can be
        handed out another way."""
        import secrets

        _require_post_csrf({'csrf_token': csrf_token}, redirect='waitlist_reveals')

        reveal = session.query(WaitlistReveal).get(id)
        if not reveal:
            raise HTTPRedirect('waitlist_reveals?message={}', 'Reveal not found.')

        _eligible, _emailed, _pending, new_ids = _waitlist_reveal_candidates(
            session, reveal)
        if not reveal.use_unique_links and not reveal.shared_token:
            reveal.shared_token = secrets.token_urlsafe(24)
            session.add(reveal)
        _mint_reveal_links(session, reveal, new_ids)
        session.commit()

        raise HTTPRedirect(
            'waitlist_reveals?message={}',
            f'Generated {len(new_ids)} link(s). Nothing was emailed.')

    def send_waitlist_reveal_emails(self, session, id, csrf_token=None):
        """Materialize one WaitlistRevealLink per eligible attendee (anyone
        hotel-lottery-eligible without an active RoomAssignment) and queue
        the reveal email.

        Idempotent on emailed_at, not on the link row existing: generating
        links without sending must not make a later send skip everyone.
        """
        import secrets

        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('waitlist_reveals')
        check_csrf(csrf_token)

        reveal = session.query(WaitlistReveal).get(id)
        if not reveal or not reveal.active:
            raise HTTPRedirect('waitlist_reveals?message={}',
                               'Reveal is missing or inactive.')

        _eligible, _emailed, _pending, new_ids = _waitlist_reveal_candidates(
            session, reveal)
        if not reveal.use_unique_links and not reveal.shared_token:
            reveal.shared_token = secrets.token_urlsafe(24)
            session.add(reveal)

        # Skip on emailed_at rather than on the row existing, so links
        # generated earlier without sending still get their email.
        unsent_links = _mint_reveal_links(session, reveal, new_ids)

        for link in unsent_links:
            attendee = session.query(Attendee).get(link.attendee_id)
            if not attendee:
                continue
            EmailService.queue_email(
                session, 'hotel_lottery_waitlist_reveal', attendee,
                subject=f"{c.EVENT_NAME_AND_YEAR}: Hotel waitlist link",
                data={'reveal': reveal, 'link': link})
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
        from uber.hotel.perms import can_edit_assignments_in

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
                is_new = assignment.is_new
                reason = (c.PARTITION_GRANT
                          if picked_partition and not is_lottery_admin()
                          else c.MANUAL)

                # Staged outside the try below: apply_room_assignment_edits
                # signals validation failures by raising HTTPRedirect through
                # `fail`, which a bare `except Exception` would swallow.
                if not is_new:
                    def fail(msg):
                        raise HTTPRedirect('assign_room?id={}&message={}',
                                           assignment.id, msg)

                    if picked_attendee != assignment.attendee_id:
                        assignment.attendee_id = picked_attendee
                        session.add(assignment)
                    if (not assignment.assignment_reason
                            or assignment.assignment_reason == c.MANUAL):
                        assignment.assignment_reason = reason
                    apply_room_assignment_edits(
                        session, assignment, params,
                        audit_prefix='Assign-room page updated', fail=fail)

                try:
                    if is_new:
                        assignment = create_room_assignment(
                            session,
                            attendee_id=picked_attendee,
                            inventory_id=picked_inventory,
                            partition_id=picked_partition,
                            assignment_reason=reason,
                            payment_type=params.get('payment_type'),
                            assigned_check_in_date=params.get('assigned_check_in_date', ''),
                            assigned_check_out_date=params.get('assigned_check_out_date', ''),
                            deposit_cutoff_date=params.get('deposit_cutoff_date', ''),
                            room_number=params.get('room_number', ''),
                            admin_notes=params.get('admin_notes', ''),
                        )
                    session.commit()
                except RoomAssignmentError as e:
                    message = e.message
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
        # (unpartitioned) pool, partition ids key their blocks.
        inventory_avail_map, inventory_partitions_map = block_availability(
            session, picker['inventory_blocks'])

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

        Result shaping lives in uber.hotel.queries.attendee_search_results
        (shared with partition_admin.search_attendees, which adds a
        partition gate); access here is gated by this section's admin
        ACL, the same gate as the assign_room page itself.
        """
        return attendee_search_results(session, q)

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

                # Scoped access levels are submitted as
                # `<scope>_level` = none | view | edit. We unpack each
                # into the underlying view/edit flag pair so the
                # invariant "edit implies view" is enforced at the UI
                # layer rather than runtime - view-without-edit is the
                # only intermediate state the dropdown can produce.
                level_scopes = [
                    ('inventory_level',  'can_view_inventory',  'can_edit_inventory'),
                    ('assignments_level', 'can_view_assignments', 'can_edit_assignments'),
                    ('room_numbers_level', 'can_view_room_numbers', 'can_edit_room_numbers'),
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

    @ajax
    def deletion_conflicts(self, session, kind='', id='', csrf_token=None):
        """What still points at this resource, rendered for the dialog.

        Returns HTML rather than a JSON tree so the modal and the no-JS
        interstitial page share one template.
        """
        if cherrypy.request.method != 'POST':
            return {'error': 'This endpoint requires a POST.'}
        check_csrf(csrf_token)
        try:
            obj, spec, groups = inspect_conflicts(session, kind, id)
        except DeletionError as e:
            return {'error': e.message}

        return {
            'ok': True,
            'kind': kind,
            'id': str(obj.id),
            'label': _deletion_label(obj),
            'title': spec['title'],
            'is_active': bool(getattr(obj, 'active', False)),
            'soft_delete_available': bool(spec.get('soft_delete')),
            'has_blocking': has_blocking(groups),
            'force_required': any(g['category'] == 'emailed_links' for g in groups),
            'html': render('hotel_lottery_admin/_deletion_conflicts.html', {
                'kind': kind, 'obj': obj, 'spec': spec, 'groups': groups,
            }).decode('utf-8'),
        }

    @ajax
    def resolve_deletion_conflict(self, session, kind='', id='', category='',
                                  action='', item_id='', target_id='',
                                  csrf_token=None):
        """Apply one resolution, then re-render so the dialog can never act on
        a stale view."""
        if cherrypy.request.method != 'POST':
            return {'error': 'This endpoint requires a POST.'}
        check_csrf(csrf_token)
        try:
            message = resolve_conflict(session, kind, id, category, action,
                                       item_id=item_id, target_id=target_id)
            session.commit()
        except DeletionError as e:
            session.rollback()
            return {'error': e.message}

        result = self.deletion_conflicts(session, kind=kind, id=id,
                                         csrf_token=csrf_token)
        if isinstance(result, dict):
            result['message'] = message
        return result

    def confirm_delete_resource(self, session, kind='', id='', return_to='',
                                message=''):
        """Full-page fallback for the same dialog, so the delete controls work
        without JavaScript."""
        try:
            obj, spec, groups = inspect_conflicts(session, kind, id)
        except DeletionError as e:
            raise HTTPRedirect('index?message={}', e.message)

        return {
            'kind': kind,
            'obj': obj,
            'spec': spec,
            'groups': groups,
            'label': _deletion_label(obj),
            'has_blocking': has_blocking(groups),
            'return_to': return_to or spec['list_page'],
            'message': message,
        }

    def delete_resource(self, session, kind='', id='', mode='soft', force='',
                        return_to='', csrf_token=None):
        spec = RESOURCE_SPECS.get(kind)
        list_page = spec['list_page'] if spec else 'index'
        _require_post_csrf({'csrf_token': csrf_token}, redirect=list_page)

        try:
            message = perform_delete(session, kind, id, mode=mode,
                                     force=force in ('1', 'true', 'True'))
            session.commit()
        except DeletionError as e:
            session.rollback()
            raise HTTPRedirect('{}?message={}', return_to or list_page, e.message)

        raise HTTPRedirect('{}?message={}', return_to or list_page, message)

    def delete_partition_owner(self, session, id, csrf_token=None, return_to=''):
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
            # Not is_admin=True: bill_reference is locked for anyone who is not
            # a full lottery admin, and that lock only applies when the form is
            # populated as a non-admin.
            for form in forms.values():
                form.populate_obj(partition, is_admin=is_lottery_admin())
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

        try:
            create_room_assignment(
                session,
                attendee_id=app.attendee_id,
                inventory_id=inventory_id,
                partition_id=partition_id or None,
                lottery_application_id=app.id,
                assignment_reason=c.MANUAL,
                status=c.ASSIGNED,
                payment_type=params.get('payment_type'),
                assigned_check_in_date=params.get('assigned_check_in_date', ''),
                assigned_check_out_date=params.get('assigned_check_out_date', ''),
                audit_description=f"Manually added room to attendee {app.attendee_id}",
            )
        except RoomAssignmentError as e:
            raise HTTPRedirect('form?id={}&message={}', application_id, e.message)
        session.commit()
        raise HTTPRedirect('form?id={}&message={}', application_id, 'Room added.')

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

        msg = apply_room_assignment_edits(
            session, ra, params, audit_prefix='Lottery admin updated', fail=fail)
        session.commit()
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
                    description=f"Connector cascade: {child.room_summary}",
                    target_type='assignment', target_id=child.id,
                    attendee_id=child.attendee_id)
            session.delete(child)
        if ra.partition_id:
            record_partition_audit(
                session, ra.partition_id,
                action='assignment.deleted',
                description="Lottery admin removed assignment: "
                            f"{ra.room_summary}",
                target_type='assignment', target_id=ra.id,
                attendee_id=ra.attendee_id)
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

        from uber.hotel import physical as hotel_physical
        map_hotel = ra.inventory.hotel if ra.inventory else None
        if map_hotel and not map_hotel.map_svg:
            map_hotel = None
        return {
            'assignment': ra,
            'partitions': picker['partitions'],
            'inventory_blocks': picker['inventory_blocks'],
            'inventory_partitions_map': inventory_partitions_map,
            'assignable_rooms': hotel_physical.assignable_rooms(session, ra),
            'map_hotel': map_hotel,
            'map_rooms': hotel_physical.floor_map_rooms(
                hotel_physical.rooms_by_floor(session, map_hotel.id),
                hotel_physical.live_bookings_by_room(session, map_hotel.id))
                if map_hotel else [],
            'message': message,
        }

    def save_room_assignment(self, session, assignment_id,
                             csrf_token=None, **params):
        """Standalone-page version of update_room_assignment. Shares
        uber.hotel.service.apply_room_assignment_edits; the standalone page additionally
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

        msg = apply_room_assignment_edits(
            session, ra, params, audit_prefix='Edit page updated', fail=fail)
        session.commit()
        raise HTTPRedirect('edit_room_assignment?id={}&message={}',
                           assignment_id, msg)

    # Cross-application view: every RoomAssignment in the system,
    # paginated. Useful when an admin knows the room (hotel + date) but
    # not the attendee/application, or wants to scan the whole population
    # for sanity-check. Filters are deliberately minimal - for fine-grained
    # searching the application search box on the Applications page is
    # still the right tool.

    def rooms(self, session, message='', page='1', page_size='50',
              status='live', hotel_id='', partition_id='', search='',
              attendee_id='', sort='dates', dir='asc'):
        from sqlalchemy.orm import aliased
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

        # Column sort. Joins use aliases so they can't collide with the
        # joins the shared query layer adds for searching. The default
        # keeps missing check-in dates first so they get noticed.
        direction = 'desc' if dir == 'desc' else 'asc'

        def ordered(*cols):
            return [col.desc() if direction == 'desc' else col.asc()
                    for col in cols]

        if sort == 'hotel':
            inv = aliased(HotelRoomInventory)
            hotel = aliased(LotteryHotel)
            q = (q.outerjoin(inv, inv.id == RoomAssignment.inventory_id)
                  .outerjoin(hotel, hotel.id == inv.hotel_id))
            order = ordered(hotel.name, inv.name)
        elif sort == 'attendee':
            att = aliased(Attendee)
            q = q.outerjoin(att, att.id == RoomAssignment.attendee_id)
            order = ordered(att.last_name, att.first_name)
        elif sort == 'status':
            order = ordered(RoomAssignment.status)
        elif sort == 'billing':
            order = ordered(RoomAssignment.payment_type,
                            RoomAssignment.cc_last_four)
        elif sort == 'partition':
            part = aliased(InventoryPartition)
            q = q.outerjoin(part,
                            part.id == RoomAssignment.partition_id)
            order = ordered(part.name)
        elif sort == 'conf':
            order = ordered(RoomAssignment.hotel_confirmation_number,
                            RoomAssignment.room_number)
        else:
            sort = 'dates'
            col = RoomAssignment.assigned_check_in_date
            order = [col.desc().nullslast() if direction == 'desc'
                     else col.asc().nullsfirst()]

        q = q.order_by(*order, RoomAssignment.created.asc())
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
            'sort': sort,
            'dir': direction,
            'scoped_attendee': scoped_attendee,
            'hotels': hotels,
            'partitions': partitions,
            'status_opts': c.HOTEL_ASSIGNMENT_STATUS_OPTS,
        }

    @ajax
    def process_waitlist(self, session, inventory_id='', night_date=''):
        inv_id = inventory_id if inventory_id else None
        nd = date.fromisoformat(night_date) if night_date else None
        result = fulfill_waitlist(session, inventory_id=inv_id, night_date=nd)
        session.commit()
        for ra in result.fulfilled_assignments:
            if ra.attendee and ra.lottery_application:
                EmailService.queue_email(
                    session, 'hotel_lottery_waitlist_fulfilled', ra.lottery_application,
                    subject=f'{c.EVENT_NAME} Hotel Lottery - Room Dates Updated',
                    data={'assignment': ra, })
        return {
            'success': True,
            'fulfilled': result.fulfilled,
            'skipped_locked': result.skipped_locked,
            'message': f"Fulfilled {result.fulfilled} waitlist entries." + (
                f" Skipped {result.skipped_locked} locked entries."
                if result.skipped_locked else "")
        }

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

        # Pagination via the shared helper (it slices plain lists too);
        # PER_PAGE matches the rest of the admin section's 100-per-page
        # convention.
        page_slice, _, page, total_pages = paginate(filtered, page, PER_PAGE)
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
        layout lives with the builder (uber.hotel.exports.build_waitlist_xlsx).

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

        Per-night capacity uses `capacity_for` (same helper the
        cron uses) so a partition-bound row only competes with other
        rows in the same partition, and the cron and this endpoint
        agree on what "full" means.

        If the row's full waitlisted range is satisfied, the model's
        `clear_waitlist_when_satisfied` presave zeros the waitlist
        columns and `waitlist_started_at` so the row drops out of the
        queue. If only some of the requested nights had capacity, the
        row keeps its tightened waitlist demand on whatever's left.

        The walk itself lives in the engine
        (uber.hotel.waitlist.accept_waitlist_entry), which also cascades
        the new dates + waitlist state to connector children. Its
        default gate is deliberately looser than the sweep's (no
        SECURED / non-group requirement) - this is an admin override.
        """
        if not assignment_id:
            return {'error': 'Missing assignment_id.'}
        ra = session.query(RoomAssignment).get(assignment_id)
        if not ra:
            return {'error': 'Assignment not found.'}

        try:
            result = accept_waitlist_entry(session, ra)
        except WaitlistError as e:
            return {'error': e.message}

        session.commit()

        total_extended = result.nights_front + result.nights_back
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
                    data={'assignment': ra, })
            except Exception:
                log.exception('accept_waitlist: notification failed')

        msg = (f'Accepted {total_extended} night(s) off waitlist. '
               f'New range: {ra.assigned_check_in_date} - '
               f'{ra.assigned_check_out_date}.')
        if result.still_waiting:
            msg += ' Remaining nights still on waitlist (no capacity yet).'

        return {
            'success': True,
            'message': msg,
            'still_waiting': result.still_waiting,
        }

    # A read-only "what's wrong with our room data" report. Issues are
    # surfaced as a flat list, each one carrying severity (error/warning),
    # a human label, and a deep-link to wherever the admin can fix it
    # (usually the application's edit form). The checks themselves live
    # in uber.hotel.audit (all in Python - no SQL view - so it's
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
        uber.hotel.audit.INVENTORY_CHECKS (oversubscription,
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
