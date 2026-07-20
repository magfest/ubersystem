"""Shared query layer for the three hotel-section room lists.

hotel_lottery_admin.rooms, staff_rooming.staffer_rooms, and
partition_admin.dashboard each present a paginated list of
RoomAssignment rows with overlapping filter semantics (status, hotel,
partition, free-text search). Historically each controller re-implemented
the same query scaffold and the same try/int page-clamp block. This
module is the single definition of both:

  * build_room_assignment_query - the filter semantics, exactly as the
    hotel_lottery_admin Rooms page defines them, plus the optional
    badge-type predicate the staff-rooming pages need.
  * clamp_page_size / paginate - the shared pagination behavior
    (page-size clamping, last-page clamping, count/offset/limit).

Access control is intentionally NOT handled here: each section keeps its
own controller, ACL checks, and templates. This module only deduplicates
the query construction underneath them.
"""

from sqlalchemy import or_

from uber.models import Attendee
from uber.models.hotel import (HotelRoomInventory, LotteryApplication,
                               RoomAssignment)


def build_room_assignment_query(session, *, status='live', hotel_id='',
                                partition_id='', search='', attendee_id='',
                                badge_types=None):
    """Build the standard RoomAssignment listing query.

    Filter semantics (mirrors the hotel_lottery_admin Rooms page):

      status      - 'live' (default) = ASSIGNED + SECURED via
                    RoomAssignment.is_live; 'all' (or '') = no status
                    filter; anything else is coerced to an exact status
                    int, silently ignored if not parseable.
      hotel_id    - restrict to assignments whose inventory block belongs
                    to this hotel (resolved via an inventory-id lookup).
      partition_id- exact partition match, or the sentinel 'none' for
                    rows with no partition.
      search      - case-insensitive substring match over the lottery
                    application's confirmation #, the hotel confirmation
                    #, and the attendee's email / first / last name.
                    Joins LotteryApplication and Attendee as outer joins
                    so rows missing either still match on other fields.
      attendee_id - scope to one attendee's rooms. In that case a 'live'
                    status filter is widened to 'all', since the caller
                    wants the attendee's full history.
      badge_types - optional list of badge-type consts; inner-joins
                    Attendee and requires the booker's badge_type to be
                    in the list (staff_rooming passes
                    [c.STAFF_BADGE, c.CONTRACTOR_BADGE]).

    Ordering is left to the caller. Additional caller-specific filters
    (e.g. staffer_rooms' billing filter) can be chained onto the returned
    query. When badge_types is passed, Attendee is inner-joined, so the
    caller may also order by / filter on Attendee columns.
    """
    q = session.query(RoomAssignment)

    # Scope to one attendee's rooms - show every status in that case,
    # since the admin wants the attendee's full history.
    if attendee_id:
        q = q.filter(RoomAssignment.attendee_id == attendee_id)
        if status == 'live':
            status = 'all'

    # `live` (default) = ASSIGNED + SECURED. `all` = no status filter.
    # Anything else = exact status int from the model's status enum.
    if status == 'live':
        q = q.filter(RoomAssignment.is_live)
    elif status and status != 'all':
        try:
            q = q.filter(RoomAssignment.status == int(status))
        except (TypeError, ValueError):
            pass

    attendee_joined = False
    if badge_types:
        q = (q.join(Attendee, Attendee.id == RoomAssignment.attendee_id)
              .filter(Attendee.badge_type.in_(badge_types)))
        attendee_joined = True

    if hotel_id:
        inv_ids = [str(inv.id) for inv in
                   session.query(HotelRoomInventory)
                   .filter_by(hotel_id=hotel_id).all()]
        q = q.filter(RoomAssignment.inventory_id.in_(inv_ids))

    if partition_id:
        if partition_id == 'none':
            q = q.filter(RoomAssignment.partition_id.is_(None))
        else:
            q = q.filter(RoomAssignment.partition_id == partition_id)

    # Search hits the application's confirmation #, attendee email/name,
    # and the hotel confirmation #. Outer joins so assignments without
    # an application (or, pathologically, an attendee) still match on
    # their other fields.
    search_term = (search or '').strip()
    if search_term:
        like = f'%{search_term}%'
        q = q.join(LotteryApplication,
                   LotteryApplication.id == RoomAssignment.lottery_application_id,
                   isouter=True)
        if not attendee_joined:
            q = q.join(Attendee,
                       Attendee.id == RoomAssignment.attendee_id,
                       isouter=True)
        q = q.filter(or_(
            LotteryApplication.confirmation_num.ilike(like),
            RoomAssignment.hotel_confirmation_number.ilike(like),
            Attendee.email.ilike(like),
            Attendee.first_name.ilike(like),
            Attendee.last_name.ilike(like),
        ))

    return q


def clamp_page_size(page_size, default_size=50, min_size=10, max_size=500):
    """Coerce a request's page_size param to a sane int.

    Unparseable values fall back to default_size; parseable values are
    clamped into [min_size, max_size]. Exposed separately from paginate
    because handlers echo the clamped size back into their template
    context (per-page picker, "Showing X-Y of Z" summary).
    """
    try:
        return max(min_size, min(max_size, int(page_size)))
    except (TypeError, ValueError):
        return default_size


def paginate(query, page, page_size=None,
             default_size=50, min_size=10, max_size=500):
    """Run the standard count/clamp/offset/limit dance.

    Returns (rows, total, page, page_count).

      * page is coerced via int() (falling back to 1), floored at 1, and
        clamped down to the last page when it overshoots.
      * page_size is clamped via clamp_page_size with the same bounds.
      * page_count is always >= 1, even with zero rows.

    Accepts either a SQLAlchemy query (count/offset/limit) or a plain
    list/tuple (len/slice) - compliance_report paginates an in-Python
    list of result tuples. Ordering is the caller's job: apply order_by
    (or pre-sort the list) before calling.
    """
    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1
    size = clamp_page_size(page_size, default_size=default_size,
                           min_size=min_size, max_size=max_size)

    if isinstance(query, (list, tuple)):
        total = len(query)
    else:
        total = query.count()

    page_count = max(1, (total + size - 1) // size)
    if page > page_count:
        page = page_count

    offset = (page - 1) * size
    if isinstance(query, (list, tuple)):
        rows = list(query[offset:offset + size])
    else:
        rows = query.offset(offset).limit(size).all()
    return rows, total, page, page_count


def physical_room_conflicts(session, physical_room_id, check_in, check_out,
                            exclude_assignment_id=None):
    """Live RoomAssignments already occupying a physical room for any night
    in [check_in, check_out).

    One booking per room per night: two bookings conflict when their date
    ranges overlap, with checkout day exclusive so back-to-back turnover
    (A checks out the morning B checks in) is allowed. Assignments with no
    dates never conflict - they can't be placed on specific nights.
    """
    from uber.models.hotel import RoomAssignment

    if not (physical_room_id and check_in and check_out):
        return []
    q = session.query(RoomAssignment).filter(
        RoomAssignment.physical_room_id == physical_room_id,
        RoomAssignment.is_live,
        RoomAssignment.assigned_check_in_date.isnot(None),
        RoomAssignment.assigned_check_out_date.isnot(None),
        RoomAssignment.assigned_check_in_date < check_out,
        RoomAssignment.assigned_check_out_date > check_in,
    )
    if exclude_assignment_id:
        q = q.filter(RoomAssignment.id != exclude_assignment_id)
    return q.all()


def vacant_physical_rooms(session, hotel_id, check_in, check_out,
                          inventory_id=None, ada_only=False):
    """In-service physical rooms at a hotel with no live booking on any
    night of [check_in, check_out), optionally limited to one sellable
    block. Returns rooms in floor/room-number order."""
    from uber.models.hotel import PhysicalRoom, RoomAssignment

    rooms = session.query(PhysicalRoom).filter(
        PhysicalRoom.hotel_id == hotel_id,
        PhysicalRoom.out_of_service.is_(False))
    if inventory_id:
        rooms = rooms.filter(PhysicalRoom.inventory_id == inventory_id)
    if ada_only:
        rooms = rooms.filter(PhysicalRoom.ada.is_(True))
    rooms = rooms.all()

    if check_in and check_out:
        busy = {row[0] for row in session.query(
            RoomAssignment.physical_room_id).filter(
            RoomAssignment.physical_room_id.isnot(None),
            RoomAssignment.is_live,
            RoomAssignment.assigned_check_in_date.isnot(None),
            RoomAssignment.assigned_check_out_date.isnot(None),
            RoomAssignment.assigned_check_in_date < check_out,
            RoomAssignment.assigned_check_out_date > check_in).all()}
        rooms = [r for r in rooms if r.id not in busy]
    return sorted(rooms, key=lambda r: r.sort_key)
