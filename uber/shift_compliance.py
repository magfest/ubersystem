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

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import selectinload

from uber.config import c
from uber.hotel.queries import staff_rooming_query
from uber.models import Attendee, Job, NightShiftRequirement, RoomAssignment, Shift


def load_requirements(session):
    """Return {date: NightShiftRequirement} for batch compliance computation."""
    return {r.night_date: r for r in session.query(NightShiftRequirement).all()}


def assigned_nights(room_assignments):
    """Return the set of dates the given assignments cover.

    Check-in date X with check-out date X+N means the staffer sleeps in the
    room on nights X, X+1, ..., X+N-1. Skipped: assignments in EXPIRED or
    CANCELLED status, or with missing dates.
    """
    return _nights((ra.assigned_check_in_date, ra.assigned_check_out_date)
                   for ra in room_assignments if ra.status not in (c.EXPIRED, c.CANCELLED))


def _nights(stays):
    nights = set()
    for check_in, check_out in stays:
        if not check_in or not check_out:
            continue
        cur = check_in
        while cur < check_out:
            nights.add(cur)
            cur += timedelta(days=1)
    return nights


def _violations(nights, weighted_hours, shift_spans, requirements_by_date):
    """The requirements broken on `nights`, given total weighted hours and
    the (start, end) of each shift."""
    violations = []
    for night in sorted(nights):
        req = requirements_by_date.get(night)
        if not req or req.kind == c.NONE:
            continue
        if req.kind == c.CORE:
            if weighted_hours < req.required_weighted_hours:
                violations.append(req)
        elif req.kind in (c.SETUP, c.TEARDOWN):
            start, end = req.shift_window_start, req.shift_window_end
            if not (start and end and any(s < end and e > start for s, e in shift_spans)):
                violations.append(req)
    return violations


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

    shift_spans = [(s.job.start_time, s.job.start_time + timedelta(minutes=s.job.duration or 0))
                   for s in attendee.shifts if s.job]
    return _violations(nights, attendee.weighted_hours, shift_spans, requirements_by_date)


def is_compliant(attendee, requirements_by_date=None):
    return not compliance_violations(attendee, requirements_by_date)


def non_compliant_staffers(session, department_id=None):
    """Return [(attendee, violations), ...], ordered by name, for staff with a
    live room who aren't compliant, optionally only members of `department_id`.
    """
    reqs = load_requirements(session)
    if not reqs:
        return []

    staff = staff_rooming_query(session).filter(Attendee.room_assignments.any(RoomAssignment.is_live))
    if department_id:
        staff = staff.filter(Attendee.dept_memberships.any(department_id=department_id))
    nonshift_minutes = dict(staff.with_entities(Attendee.id, Attendee.nonshift_minutes))
    if not nonshift_minutes:
        return []
    ids = list(nonshift_minutes)

    stays = defaultdict(list)
    for attendee_id, check_in, check_out in session.query(
            RoomAssignment.attendee_id, RoomAssignment.assigned_check_in_date,
            RoomAssignment.assigned_check_out_date).filter(
            RoomAssignment.attendee_id.in_(ids), RoomAssignment.is_live):
        stays[attendee_id].append((check_in, check_out))

    hours = {attendee_id: (minutes or 0) / 60 for attendee_id, minutes in nonshift_minutes.items()}
    spans = defaultdict(list)
    for attendee_id, start, duration, extra15, weight in session.query(
            Shift.attendee_id, Job.start_time, Job.duration, Job.extra15, Job.weight).join(
            Job, Job.id == Shift.job_id).filter(Shift.attendee_id.in_(ids)):
        # Matches Job.weighted_hours.
        hours[attendee_id] += weight * (duration + (15 if extra15 else 0)) / 60
        spans[attendee_id].append((start, start + timedelta(minutes=duration or 0)))

    violations = {}
    for attendee_id in ids:
        broken = _violations(_nights(stays[attendee_id]), hours[attendee_id], spans[attendee_id], reqs)
        if broken:
            violations[attendee_id] = broken
    if not violations:
        return []

    attendees = session.query(Attendee).filter(Attendee.id.in_(list(violations))).options(
        selectinload(Attendee.assigned_depts)).order_by(Attendee.full_name)
    return [(attendee, violations[attendee.id]) for attendee in attendees]
