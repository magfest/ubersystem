"""Room change waitlist system
"""

from collections import defaultdict, namedtuple
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from uber.config import c
from uber.hotel.queries import capacity_for
from uber.models import LotteryApplication
from uber.models.hotel import HotelRoomInventory, RoomAssignment

# FIFO tiebreak for rows with waitlisted_* set but no start timestamp
# (should never happen post-migration): treat them as "as early as
# possible" rather than silently dropping them.
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class WaitlistError(Exception):
    """User-facing failure in a waitlist operation. `.message` is safe
    to show the requester; each route handler maps it onto its own
    redirect / JSON error contract."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


#: Result of `resize_assignment`: the final confirmed range, the sorted
#: requested nights that ended up outside it (i.e. waitlisted), and the
#: sorted previously-held nights the request gave up (released back to
#: the block; they reach queued rows on the next admin sweep).
ResizeResult = namedtuple(
    'ResizeResult',
    'confirmed_ci confirmed_co waitlisted_nights released_nights')

#: Result of `fulfill_waitlist`: the set of RoomAssignments that gained
#: at least one night, the total night-extensions granted, and how many
#: export-locked rows were skipped.
FulfillResult = namedtuple(
    'FulfillResult', 'fulfilled_assignments fulfilled skipped_locked')

#: Result of `accept_waitlist_entry`: nights granted on each end and
#: whether the row still has unmet waitlist demand.
AcceptResult = namedtuple(
    'AcceptResult', 'nights_front nights_back still_waiting')


def sweep_eligible(ra):
    """True iff the sweep may serve this assignment: SECURED, bound to
    an inventory block, not export-locked, not a group-entry sub-app row
    (those don't hold their own room - the leader's row covers the
    group), and actually waiting on at least one night.

    The single definition of "who is in the queue": `fulfill_waitlist`
    serves exactly these rows, the attendee editor's queue gate
    (reconciliation 2) blocks on exactly these rows, and the admin
    demand counts (reconciliation 6) count exactly these rows.
    """
    if ra.status != c.SECURED or not ra.inventory_id:
        return False
    app = ra.lottery_application
    if app is not None and app.entry_type == c.GROUP_ENTRY:
        return False
    if ra.export_locked:
        return False
    return bool(ra.waitlisted_gap_nights)


def _fifo_key(ra):
    """FIFO sort key: earliest `waitlist_started_at` first, stable on
    `id` so same-instant entries get a deterministic order."""
    return (ra.waitlist_started_at or _EPOCH, str(ra.id))


def _cascade_to_children(session, ra):
    """Connector children always mirror the parent's dates AND waitlist
    state - assigned range, waitlisted window, and `waitlist_started_at`
    (reconciliation 4). Every path that moves a parent's dates funnels
    through here."""
    for child in ra.child_assignments:
        child.assigned_check_in_date = ra.assigned_check_in_date
        child.assigned_check_out_date = ra.assigned_check_out_date
        child.waitlisted_check_in_date = ra.waitlisted_check_in_date
        child.waitlisted_check_out_date = ra.waitlisted_check_out_date
        child.waitlist_started_at = ra.waitlist_started_at
        session.add(child)


def resize_assignment(session, ra, new_ci, new_co, *, respect_queue=True):
    """Attendee-style resize: move `ra`'s confirmed range toward
    [new_ci, new_co), confirming whatever contiguous extension nights
    have open capacity, releasing held nights the request no longer
    wants, and stashing the full requested window on the row's
    `waitlisted_*` columns when any of it couldn't be confirmed.

    With `respect_queue`, an
    extension night is also refused when another sweep-eligible row in
    the same partition scope is already queued for it. Requests are
    served as FIFO when there is limited inventory.

    Returns ResizeResult; `waitlisted_nights` is the sorted list of
    requested nights left outside the final confirmed range (all of
    them extension nights, by construction) and `released_nights` the
    sorted list of previously-held nights no longer in it.

    Raises WaitlistError if the row has no inventory block, no
    confirmed range to move, the request is empty (check-out on or
    before check-in), or none of the requested nights can be held.
    """
    inv = ra.inventory
    if inv is None:
        raise WaitlistError('This room has no inventory block, so its '
                            'dates cannot be adjusted here.')
    cur_ci, cur_co = ra.assigned_check_in_date, ra.assigned_check_out_date
    if not (cur_ci and cur_co):
        raise WaitlistError('This room has no confirmed dates to adjust.')
    if new_co <= new_ci:
        raise WaitlistError('Check-out must be at least one night after '
                            'check-in.')

    # Nights already claimed by someone else's queue position
    # (reconciliation 2): other sweep-eligible rows in the same
    # (inventory, partition) scope, on the specific nights they want.
    queued_nights = set()
    if respect_queue:
        part_filter = (RoomAssignment.partition_id == ra.partition_id
                       if ra.partition_id
                       else RoomAssignment.partition_id.is_(None))
        others = session.query(RoomAssignment).filter(
            RoomAssignment.inventory_id == ra.inventory_id,
            RoomAssignment.id != ra.id,
            part_filter,
            sa.or_(RoomAssignment.waitlisted_check_in_date.isnot(None),
                   RoomAssignment.waitlisted_check_out_date.isnot(None)),
        ).all()
        for other in others:
            if sweep_eligible(other):
                queued_nights.update(other.waitlisted_gap_nights)

    # Evaluate each requested EXTENSION night: open capacity (as if this
    # row weren't there) and no earlier queue claim.
    available = set()
    day = new_ci
    while day < new_co:
        if not (cur_ci <= day < cur_co):  # held nights are never re-checked
            if day not in queued_nights:
                _, _, open_slots = capacity_for(
                    session, inv, day, ra.partition_id,
                    exclude_assignment_id=ra.id)
                if open_slots > 0:
                    available.add(day)
        day += timedelta(days=1)

    runs, run = [], []
    day = new_ci
    while day < new_co:
        if (cur_ci <= day < cur_co) or day in available:
            run.append(day)
        elif run:
            runs.append(run)
            run = []
        day += timedelta(days=1)
    if run:
        runs.append(run)
    if not runs:
        raise WaitlistError(
            "None of those nights are available right now, so your "
            "current dates were kept.")
    kept = [r for r in runs if any(cur_ci <= d < cur_co for d in r)]
    chosen = kept[0] if kept else max(runs, key=len)
    confirmed_ci, confirmed_co = chosen[0], chosen[-1] + timedelta(days=1)

    released_nights = []
    day = cur_ci
    while day < cur_co:
        if day < confirmed_ci or day >= confirmed_co:
            released_nights.append(day)
        day += timedelta(days=1)

    ra.assigned_check_in_date = confirmed_ci
    ra.assigned_check_out_date = confirmed_co

    # Stash the wider request on the row when we couldn't confirm all of
    # it; clear when fully satisfied. The presaves stamp
    # `waitlist_started_at` on queue entry and zero all three columns on
    # exit, so flushing here leaves the row internally consistent.
    if confirmed_ci > new_ci or confirmed_co < new_co:
        ra.waitlisted_check_in_date = new_ci
        ra.waitlisted_check_out_date = new_co
    else:
        ra.waitlisted_check_in_date = None
        ra.waitlisted_check_out_date = None

    session.add(ra)
    session.flush()

    _cascade_to_children(session, ra)
    session.flush()

    waitlisted_nights = []
    day = new_ci
    while day < new_co:
        if day < confirmed_ci or day >= confirmed_co:
            waitlisted_nights.append(day)
        day += timedelta(days=1)

    return ResizeResult(confirmed_ci, confirmed_co, waitlisted_nights,
                        released_nights)


def _extendable_direction(ra, night):
    """'front' / 'back' / None: can this row be extended by exactly this
    night right now? Front means the night immediately before the
    current check-in (and inside the requested window); back means the
    current check-out night. One night at a time - the sweep's outer
    walk order supplies contiguity."""
    wl_ci, wl_co = ra.effective_waitlist_window
    ci, co = ra.assigned_check_in_date, ra.assigned_check_out_date
    if (wl_ci and ci and night < ci and night >= wl_ci
            and night == ci - timedelta(days=1)):
        return 'front'
    if (wl_co and co and night >= co and night < wl_co
            and night == co):
        return 'back'
    return None


def fulfill_waitlist(session, inventory_id=None, night_date=None):
    """The sweep: extend sweep-eligible rows into open capacity, FIFO
    per night. Nothing schedules it - it runs on demand from the admin
    Process Waitlist button and after an inventory block is saved.

    Per (inventory, partition) scope, front-gap nights are processed
    DESCENDING - closest to the current check-in first - so a
    multi-night front gap completes in one sweep (reconciliation 3);
    back-gap nights ascend. Each night is filled up to
    `capacity_for(...)`'s open slots, earliest `waitlist_started_at`
    first, flushing between rounds so capacity math and the model
    presaves see every extension. Fulfilled rows cascade to connector
    children (reconciliation 4).

    Args:
        inventory_id: only process this inventory block.
        night_date: only process this specific night.

    Returns FulfillResult. `fulfilled` counts night-extensions (one row
    gaining two nights counts twice); `skipped_locked` counts the
    export-locked rows with waitlist columns set that the sweep refused
    to touch. Flushes only - the caller commits and queues the
    "waitlist fulfilled" emails for `fulfilled_assignments`.
    """
    base_q = (session.query(RoomAssignment)
              .outerjoin(LotteryApplication,
                         RoomAssignment.lottery_application_id == LotteryApplication.id)
              .filter(RoomAssignment.status == c.SECURED,
                      RoomAssignment.inventory_id.isnot(None),
                      # entry_type can be NULL (the unset_entry_type
                      # presave nulls a 0), and SQL three-valued logic
                      # would silently drop those rows from `!=` alone -
                      # sweep_eligible's python side serves them, so the
                      # SQL prefilter must too.
                      sa.or_(LotteryApplication.id.is_(None),
                             LotteryApplication.entry_type.is_(None),
                             LotteryApplication.entry_type != c.GROUP_ENTRY),
                      sa.or_(RoomAssignment.waitlisted_check_in_date.isnot(None),
                             RoomAssignment.waitlisted_check_out_date.isnot(None))))
    if inventory_id:
        base_q = base_q.filter(
            RoomAssignment.inventory_id == str(inventory_id))

    rows = base_q.all()
    skipped_locked = sum(1 for ra in rows if ra.export_locked)

    total_fulfilled = 0
    fulfilled_assignments = set()

    by_block = defaultdict(list)
    for ra in rows:
        if sweep_eligible(ra):
            by_block[str(ra.inventory_id)].append(ra)

    for block_id in sorted(by_block):
        inv = session.query(HotelRoomInventory).get(block_id)
        if not inv:
            continue
        for part_id in {ra.partition_id for ra in by_block[block_id]}:
            part_rows = [ra for ra in by_block[block_id]
                         if ra.partition_id == part_id]

            # The nights this scope is waiting on, split by which end of
            # the stay they'd extend.
            front_nights, back_nights = set(), set()
            for ra in part_rows:
                ci = ra.assigned_check_in_date
                for night in ra.waitlisted_gap_nights:
                    (front_nights if ci and night < ci
                     else back_nights).add(night)
            if night_date:
                front_nights &= {night_date}
                back_nights &= {night_date}

            # Front gaps walk DESCENDING (reconciliation 3): serving the
            # night adjacent to check-in first makes the next-earlier
            # night adjacent in turn, so a whole gap can close in one
            # sweep. Back gaps walk ascending for the same reason.
            plan = ([('front', n) for n in sorted(front_nights, reverse=True)]
                    + [('back', n) for n in sorted(back_nights)])

            for direction, night in plan:
                # Inner loop re-evaluates after each flush: served rows
                # drop out (their gap shrank or their waitlist columns
                # cleared) and open slots shrink until the night is full
                # or nobody extendable remains. Bounded for safety.
                for _iteration in range(500):
                    _, _, open_slots = capacity_for(
                        session, inv, night, part_id)
                    if open_slots <= 0:
                        break
                    eligible = [
                        ra for ra in part_rows
                        if sweep_eligible(ra)
                        and _extendable_direction(ra, night) == direction]
                    if not eligible:
                        break
                    eligible.sort(key=_fifo_key)
                    for ra in eligible[:open_slots]:
                        if direction == 'front':
                            ra.assigned_check_in_date = night
                        else:
                            ra.assigned_check_out_date = (
                                night + timedelta(days=1))
                        # `clear_waitlist_when_satisfied` zeros the
                        # waitlist columns at flush once the assigned
                        # range covers the request, so served rows drop
                        # out of later scans without an extra branch.
                        session.add(ra)
                        total_fulfilled += 1
                        fulfilled_assignments.add(ra)
                    session.flush()

    for ra in fulfilled_assignments:
        _cascade_to_children(session, ra)
    if fulfilled_assignments:
        session.flush()

    return FulfillResult(fulfilled_assignments=fulfilled_assignments,
                         fulfilled=total_fulfilled,
                         skipped_locked=skipped_locked)


def accept_waitlist_entry(session, ra, *, require_secured=False):
    """Single-row FIFO-bypass accept: extend THIS row's nights up to
    capacity, regardless of where it sits in the queue. The admin is
    explicitly choosing to promote this attendee; per-night
    `capacity_for` checks still apply so they can't be handed nights
    that don't exist.

    Looser gate than the sweep (reconciliation 1): by default this does
    NOT require SECURED status or a non-group entry - a documented
    admin override. It still refuses export-locked rows and rows with
    no inventory block. Pass require_secured=True to enforce the
    sweep's status gate as well.

    The front gap walks closest-to-check-in first and the back gap
    earliest-first, flushing after each granted night so the next
    capacity check sees the extension. Cascades to connector children
    (reconciliation 4). Never commits.

    Returns AcceptResult; `still_waiting` is True when some requested
    nights remain unmet (the row keeps its queue position - the presave
    only clears the waitlist columns on full coverage).
    """
    if not (ra.waitlisted_check_in_date or ra.waitlisted_check_out_date):
        raise WaitlistError('That assignment is not currently on the waitlist.')
    if ra.export_locked:
        raise WaitlistError('That assignment has been exported to the hotel '
                            'and cannot be edited from here.')
    if not ra.inventory:
        raise WaitlistError('Assignment has no inventory block; cannot run '
                            'the capacity check.')
    if require_secured:
        if ra.status != c.SECURED:
            raise WaitlistError('That assignment is not secured, so the '
                                'sweep would not serve it.')
        app = ra.lottery_application
        if app is not None and app.entry_type == c.GROUP_ENTRY:
            raise WaitlistError('Group-entry sub-applications do not hold '
                                'their own room.')

    wl_ci, wl_co = ra.effective_waitlist_window

    # FRONT extension, one night at a time, closest-to-check-in first.
    # `capacity_for` counts confirmed rows covering the night; our own
    # current check-in is strictly after the candidate night, so we
    # never double-count ourselves.
    nights_front = 0
    while (ra.assigned_check_in_date and wl_ci
            and wl_ci < ra.assigned_check_in_date):
        candidate_night = ra.assigned_check_in_date - timedelta(days=1)
        _, _, open_slots = capacity_for(
            session, ra.inventory, candidate_night, ra.partition_id)
        if open_slots <= 0:
            break
        ra.assigned_check_in_date = candidate_night
        nights_front += 1
        # Flush so the next iteration's capacity_for sees this change
        # (otherwise we'd over-extend by racing our own writes).
        session.flush()

    # BACK extension, one night at a time, earliest first. Same
    # self-exclusion logic: our check-out is <= the candidate night.
    nights_back = 0
    while (ra.assigned_check_out_date and wl_co
            and wl_co > ra.assigned_check_out_date):
        candidate_night = ra.assigned_check_out_date
        _, _, open_slots = capacity_for(
            session, ra.inventory, candidate_night, ra.partition_id)
        if open_slots <= 0:
            break
        ra.assigned_check_out_date = candidate_night + timedelta(days=1)
        nights_back += 1
        session.flush()

    session.add(ra)
    session.flush()
    _cascade_to_children(session, ra)
    session.flush()

    still_waiting = bool(ra.waitlisted_check_in_date
                         or ra.waitlisted_check_out_date)
    return AcceptResult(nights_front=nights_front, nights_back=nights_back,
                        still_waiting=still_waiting)
