"""Staff shift-compliance computation against NightShiftRequirement rules.

A staffer sleeping in a staff crash space RoomAssignment (imported from tuber;
see RoomAssignment.shift_requirements_apply) must satisfy any
NightShiftRequirement that exists for the nights they stay. That is every
occupant for their own dates, or the booker when no occupants are listed.
Rooms won in a lottery or assigned by hand carry no shift requirements.

- Setup/teardown nights - they need at least one shift overlapping the
  configured window
- Core nights - their total weighted hours must be >= required_weighted_hours

All computation is real-time. The expensive query (NightShiftRequirement
lookup) is one query for the whole table; cache it once per request via
`load_requirements()` when computing for many staffers.
"""

from collections import defaultdict
from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import selectinload

from uber.config import c
from uber.hotel.queries import staff_rooming_query
from uber.models import Attendee, Job, NightShiftRequirement, RoomAssignment, Shift
from uber.models.hotel import room_assignment_occupant as occupant


def load_requirements(session):
    """Return {date: NightShiftRequirement} for batch compliance computation."""
    return {r.night_date: r for r in session.query(NightShiftRequirement).all()}


def _subject():
    return sa.and_(RoomAssignment.is_live, RoomAssignment.shift_requirements_apply)


def crash_space_stays(session, attendee_ids):
    """Return {attendee_id: [(check_in, check_out), ...]} for the live crash
    space the given attendees sleep in.

    A room with an occupant list counts for each occupant, over their own
    dates when set; a room without one counts for its booker.
    """
    stays = defaultdict(list)
    for attendee_id, check_in, check_out in session.query(
            RoomAssignment.attendee_id, RoomAssignment.assigned_check_in_date,
            RoomAssignment.assigned_check_out_date).filter(
            RoomAssignment.attendee_id.in_(attendee_ids), _subject(),
            ~sa.exists().where(occupant.c.room_assignment_id == RoomAssignment.id)):
        stays[attendee_id].append((check_in, check_out))
    for attendee_id, check_in, check_out in session.query(
            occupant.c.attendee_id,
            sa.func.coalesce(occupant.c.check_in_date, RoomAssignment.assigned_check_in_date),
            sa.func.coalesce(occupant.c.check_out_date, RoomAssignment.assigned_check_out_date)).join(
            RoomAssignment, RoomAssignment.id == occupant.c.room_assignment_id).filter(
            occupant.c.attendee_id.in_(attendee_ids), _subject()):
        stays[attendee_id].append((check_in, check_out))
    return stays


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

    Empty list means the attendee is compliant (or has no crash space, or
    no requirements exist).
    """
    session = sa_inspect(attendee).session
    if session is None:
        return []

    if requirements_by_date is None:
        requirements_by_date = load_requirements(session)

    if not requirements_by_date:
        return []

    # Check-in date X with check-out date X+N means nights X ... X+N-1.
    nights = _nights(crash_space_stays(session, [attendee.id])[attendee.id])
    if not nights:
        return []

    shift_spans = [(s.job.start_time, s.job.start_time + timedelta(minutes=s.job.duration or 0))
                   for s in attendee.shifts if s.job]
    return _violations(nights, attendee.weighted_hours, shift_spans, requirements_by_date)


def is_compliant(attendee, requirements_by_date=None):
    return not compliance_violations(attendee, requirements_by_date)


def non_compliant_staffers(session, department_id=None):
    """Return [(attendee, violations), ...], ordered by name, for staff in a
    live crash space room who aren't compliant, optionally only members of
    `department_id`.
    """
    reqs = load_requirements(session)
    if not reqs:
        return []

    staff = staff_rooming_query(session).filter(sa.or_(
        Attendee.room_assignments.any(_subject()), Attendee.occupied_rooms.any(_subject())))
    if department_id:
        staff = staff.filter(Attendee.dept_memberships.any(department_id=department_id))
    nonshift_minutes = dict(staff.with_entities(Attendee.id, Attendee.nonshift_minutes))
    if not nonshift_minutes:
        return []
    ids = list(nonshift_minutes)

    stays = crash_space_stays(session, ids)

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
