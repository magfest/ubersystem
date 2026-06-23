"""Staff shift-compliance computation against NightShiftRequirement rules.

A staffer holding a RoomAssignment must satisfy any NightShiftRequirement
that exists for the nights their assignment covers:

- Setup/teardown nights - they need at least one shift overlapping the
  configured window
- Core nights - their total weighted hours must be >= required_weighted_hours

All computation is real-time. The expensive query (NightShiftRequirement
lookup) is one query for the whole table; cache it once per request via
`load_requirements()` when computing for many staffers.
"""

from datetime import timedelta

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import joinedload, subqueryload

from uber.config import c


def load_requirements(session):
    """Return {date: NightShiftRequirement} for batch compliance computation."""
    from uber.models import NightShiftRequirement
    return {r.night_date: r for r in session.query(NightShiftRequirement).all()}


def assigned_nights(room_assignments):
    """Return the set of dates the given assignments cover.

    Check-in date X with check-out date X+N means the staffer sleeps in the
    room on nights X, X+1, ..., X+N-1. Skipped: assignments in EXPIRED or
    CANCELLED status, or with missing dates.
    """
    nights = set()
    for ra in room_assignments:
        if ra.status in (c.EXPIRED, c.CANCELLED):
            continue
        if not ra.assigned_check_in_date or not ra.assigned_check_out_date:
            continue
        cur = ra.assigned_check_in_date
        while cur < ra.assigned_check_out_date:
            nights.add(cur)
            cur += timedelta(days=1)
    return nights


def _shift_overlaps_window(shift, window_start, window_end):
    job = shift.job
    if not job or not window_start or not window_end:
        return False
    shift_start = job.start_time
    shift_end = shift_start + timedelta(minutes=job.duration or 0)
    return shift_start < window_end and shift_end > window_start


def _attendee_has_window_shift(attendee, window_start, window_end):
    for shift in attendee.shifts:
        if _shift_overlaps_window(shift, window_start, window_end):
            return True
    return False


def compliance_violations(attendee, requirements_by_date=None):
    """Return the list of NightShiftRequirement rows this attendee violates.

    Empty list means the attendee is compliant (or has no room assignment,
    or no requirements exist).
    """
    if not attendee.room_assignments:
        return []

    if requirements_by_date is None:
        session = sa_inspect(attendee).session
        if session is None:
            return []
        requirements_by_date = load_requirements(session)

    if not requirements_by_date:
        return []

    nights = assigned_nights(attendee.room_assignments)
    if not nights:
        return []

    weighted_hours = attendee.weighted_hours

    violations = []
    for night in sorted(nights):
        req = requirements_by_date.get(night)
        if not req or req.kind == c.NONE:
            continue
        if req.kind == c.CORE:
            if weighted_hours < req.required_weighted_hours:
                violations.append(req)
        elif req.kind in (c.SETUP, c.TEARDOWN):
            if not _attendee_has_window_shift(
                    attendee, req.shift_window_start, req.shift_window_end):
                violations.append(req)
    return violations


def is_compliant(attendee, requirements_by_date=None):
    return not compliance_violations(attendee, requirements_by_date)


def non_compliant_staffers(session, department_id=None):
    """Return [(attendee, violations), ...] for staff who aren't compliant.

    Restricted to attendees with at least one RoomAssignment. If
    `department_id` is given, only attendees in that department.
    Eager-loads room_assignments and shifts.job so the per-attendee
    compliance check stays in memory.
    """
    from uber.models import Attendee, Shift
    reqs = load_requirements(session)
    if not reqs:
        return []

    query = session.query(Attendee).filter(
        Attendee.room_assignments.any(),
    ).options(
        subqueryload(Attendee.room_assignments),
        subqueryload(Attendee.shifts).joinedload(Shift.job),
    )

    if department_id:
        query = query.filter(
            Attendee.dept_memberships.any(department_id=department_id))

    results = []
    for attendee in query.order_by(Attendee.full_name).all():
        violations = compliance_violations(attendee, reqs)
        if violations:
            results.append((attendee, violations))
    return results
