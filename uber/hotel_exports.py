"""Builders for the hotel lottery admin's export/import surfaces.

The CSV/XLSX/ZIP handlers in uber.site_sections.hotel_lottery_admin stay
as thin decorated routes; this module owns the row/workbook construction
underneath them:

  * booking_columns / booking_row / booking_export_data - the per-hotel
    booking spreadsheet layout (also the layout the back-import accepts).
  * derive_sync_status / compute_export_tracking - the per-booking and
    per-hotel export/import bookkeeping shown on the tracking page.
  * write_interchange_export - the legacy survey-interchange CSV.
  * write_hotel_inventory_xlsx - per-hotel occupancy-by-night grid.
  * build_waitlist_xlsx - the one-sheet-per-hotel waitlist demand
    workbook.
"""
from collections import defaultdict
from datetime import datetime, timedelta
from io import BytesIO

import pycountry
import xlsxwriter
from sqlalchemy import or_

from uber.config import c
from uber.custom_tags import datetime_local_filter
from uber.models import Attendee, LotteryApplication
from uber.models.hotel import (HotelExportLog, HotelRoomInventory,
                               LotteryHotel, LotteryRoomType, RoomAssignment)


# CSV/XLSX export + CSV import used by the export-tracking modal. The
# column layout intentionally mirrors the JSON shape of the
# `HotelLookup.export_room_bookings` API so that a hotel that prefers
# spreadsheets to API calls can use the same field names.
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


def booking_row(ra, app):
    """Build the base (no-guest) column values for one RoomAssignment.

    Dates and datetimes are explicitly serialized to ISO 8601 strings
    (`YYYY-MM-DD` / `YYYY-MM-DDTHH:MM:SS+00:00`) - without this, xlsxwriter
    treats date objects as numeric serial values, which Excel displays as
    bare integers that look like opaque IDs to anyone opening the file.
    """
    def iso(v):
        return v.isoformat() if v else ''

    inv = ra.inventory
    hotel_name = inv.hotel.name if inv and inv.hotel else ''
    room_type_name = (inv.room_type.name
                      if inv and not inv.is_suite and inv.room_type else '')
    suite_type_name = (inv.suite_type.name
                       if inv and inv.is_suite and inv.suite_type else '')

    return [
        ra.id, ra.lottery_application_id or '', ra.parent_assignment_id or '',
        (app.confirmation_num if app else ''),
        ra.assignment_reason_label if hasattr(ra, 'assignment_reason_label') else ra.assignment_reason,
        ra.status_label if hasattr(ra, 'status_label') else ra.status,
        hotel_name, room_type_name, suite_type_name,
        iso(ra.assigned_check_in_date),
        iso(ra.assigned_check_out_date),
        ra.hotel_confirmation_number or '',
        ra.cancellation_confirmation_number or '',
        ra.room_number or '',
        # Legal-name fields live on the attendee (hotel_first_name /
        # hotel_last_name with the legal/first/last fallback chain).
        (app.attendee.effective_hotel_first_name if app and app.attendee else '') or '',
        (app.attendee.effective_hotel_last_name if app and app.attendee else '') or '',
        (app.cellphone if app else '') or '',
        (app.email if app else '') or '',
        ra.address1 or '', ra.address2 or '', ra.city or '',
        ra.region or '', ra.zip_code or '', ra.country or '',
        ('yes' if (app and app.wants_ada) else ''),
        (app.ada_requests if app else '') or '',
        ra.special_requests or '',
        iso(ra.last_modified_at),
        iso(ra.cc_captured_at),
        ra.cc_last_four or '',
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

    inv_ids = [str(inv.id) for inv in
               session.query(HotelRoomInventory).filter_by(hotel_id=hotel.id).all()]
    if not inv_ids:
        return hotel, []

    assignments = (session.query(RoomAssignment)
                   .filter(RoomAssignment.inventory_id.in_(inv_ids),
                           RoomAssignment.is_live)
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
        row = booking_row(ra, app)

        # Guest columns: everyone sleeping in the room except the
        # booker, who already has their own columns. The model's
        # effective_occupants handles the occupants-vs-group-members
        # fallback and always returns Attendee records.
        members = [a for a in ra.effective_occupants
                   if a.id != ra.attendee_id]
        for i in range(BOOKING_MAX_GUESTS):
            if i < len(members):
                a = members[i]
                row += [a.effective_hotel_first_name or '',
                        a.effective_hotel_last_name or '',
                        a.cellphone or '',
                        a.email or '']
            else:
                row += ['', '', '', '']
        rows.append(row)

    return hotel, rows


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

        hotel_inventory_ids = [str(inv.id) for inv in
                                session.query(HotelRoomInventory).filter_by(hotel_id=hotel.id).all()]
        bookings = session.query(RoomAssignment).filter(
            RoomAssignment.inventory_id.in_(hotel_inventory_ids),
            RoomAssignment.is_live,
        )

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
        current_lottery_deadline = c.HOTEL_LOTTERY_STAFF_DEADLINE if app.is_staff_entry else c.HOTEL_LOTTERY_FORM_DEADLINE
        row.extend([datetime_local_filter(current_lottery_deadline), datetime_local_filter(c.HOTEL_LOTTERY_SUITE_CUTOFF),
                    c.EVENT_YEAR, app.response_id, app.confirmation_num, app.id, "RAMS_1", app.id, dealer_id])

        # Contact data
        base_cellphone = app.cellphone or app.attendee.cellphone
        row.extend([print_bool(attendee.badge_type == c.STAFF_BADGE or c.STAFF_RIBBON in attendee.ribbon_ints),
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
    room/suite type, one column per night in the assignment date range)
    to `out` (the writer provided by the @xlsx_file handler). Writes
    nothing when the hotel has no live assignments."""
    rows = []

    hotel_inventory_ids = [str(inv.id) for inv in
                           session.query(HotelRoomInventory).filter_by(hotel_id=hotel_id).all()]
    assignments_q = session.query(RoomAssignment).filter(
        RoomAssignment.is_live,
        RoomAssignment.inventory_id.in_(hotel_inventory_ids),
    )

    first_assignment = assignments_q.order_by(RoomAssignment.assigned_check_in_date).first()
    if not first_assignment:
        return  # No assignments for this hotel
    earliest_check_in = first_assignment.assigned_check_in_date
    latest_check_out = assignments_q.order_by(
        RoomAssignment.assigned_check_out_date.desc()).first().assigned_check_out_date
    date_range = [earliest_check_in + timedelta(days=x)
                  for x in range(0, (latest_check_out - earliest_check_in).days)] + [latest_check_out]

    inv_by_room_type = defaultdict(list)
    inv_by_suite_type = defaultdict(list)
    for inv in session.query(HotelRoomInventory).filter(
            HotelRoomInventory.id.in_(hotel_inventory_ids)).all():
        if inv.is_suite:
            inv_by_suite_type[str(inv.suite_type_id)].append(str(inv.id))
        else:
            inv_by_room_type[str(inv.room_type_id)].append(str(inv.id))

    header_row = [''] + [d.strftime("%A %-m/%-d") for d in date_range]
    for rt in session.query(LotteryRoomType).filter_by(
            is_suite=False, active=True).order_by(LotteryRoomType.name).all():
        inv_ids = inv_by_room_type.get(str(rt.id), [])
        row = [rt.name]
        for d in date_range:
            row.append(
                assignments_q.filter(
                    RoomAssignment.inventory_id.in_(inv_ids),
                    RoomAssignment.assigned_check_in_date <= d,
                    RoomAssignment.assigned_check_out_date >= d,
                ).count() if inv_ids else 0)
        rows.append(row)

    has_suites = any(inv_by_suite_type.values())
    if has_suites:
        for st in session.query(LotteryRoomType).filter_by(
                is_suite=True, active=True).order_by(LotteryRoomType.name).all():
            inv_ids = inv_by_suite_type.get(str(st.id), [])
            row = [st.name]
            for d in date_range:
                row.append(
                    assignments_q.filter(
                        RoomAssignment.inventory_id.in_(inv_ids),
                        RoomAssignment.assigned_check_in_date <= d,
                        RoomAssignment.assigned_check_out_date >= d,
                    ).count() if inv_ids else 0)
            rows.append(row)

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
        inv = ra.inventory
        if not inv or not inv.hotel:
            continue
        hotel = inv.hotel
        hotel_id = str(hotel.id)
        hotel_name_by_id[hotel_id] = hotel.name or '(unnamed hotel)'

        # Resolve a stable label for this room type. Suite types
        # and standard types both live in `LotteryRoomType`; an
        # inventory block points at one via `suite_type_id` or
        # `room_type_id` depending on `is_suite`.
        if inv.is_suite:
            rt = inv.suite_type
            label = (rt.name if rt else inv.name) + ' (suite)'
        else:
            rt = inv.room_type
            label = rt.name if rt else inv.name
        label = label or '(unnamed type)'

        if label not in type_seen_by_hotel[hotel_id]:
            type_seen_by_hotel[hotel_id].add(label)
            type_order_by_hotel[hotel_id].append(label)

        # Walk this assignment's waitlist gap and tick each
        # (type, night) cell. Front gap = nights before
        # assigned_check_in_date; back gap = nights at or after
        # assigned_check_out_date.
        wl_ci = ra.waitlisted_check_in_date or ra.assigned_check_in_date
        wl_co = ra.waitlisted_check_out_date or ra.assigned_check_out_date

        if wl_ci and ra.assigned_check_in_date and wl_ci < ra.assigned_check_in_date:
            d = wl_ci
            while d < ra.assigned_check_in_date:
                per_hotel[hotel_id][label][d] += 1
                nights_by_hotel[hotel_id].add(d)
                d += timedelta(days=1)
        if wl_co and ra.assigned_check_out_date and wl_co > ra.assigned_check_out_date:
            d = ra.assigned_check_out_date
            while d < wl_co:
                per_hotel[hotel_id][label][d] += 1
                nights_by_hotel[hotel_id].add(d)
                d += timedelta(days=1)

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
