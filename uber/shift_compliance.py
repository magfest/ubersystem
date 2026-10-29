"""Staff shift-compliance computation against NightShiftRequirement rules.

Someone holding or sharing a checked room (see `is_checked_room`) must satisfy
any NightShiftRequirement that exists for the nights that room covers:

- Setup/teardown nights - they need at least one shift overlapping the
  configured window
- Core nights - their total weighted hours must be >= required_weighted_hours

Admins choose the checked badges and rooms on the Staff Rooming page; they are
stored in `staff_rooming_config`.

All computation is real-time. The expensive query (NightShiftRequirement
lookup) is one query for the whole table; cache it once per request via
`load_requirements()` when computing for many staffers.
"""

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import and_, inspect as sa_inspect, or_
from sqlalchemy.orm import selectinload

from uber.config import c, DatabaseConfigSection
from uber.models import Attendee, Job, NightShiftRequirement, RoomAssignment, Shift
from uber.models.hotel import room_assignment_occupant


def load_requirements(session):
    """Return {date: NightShiftRequirement} for batch compliance computation."""
    return {r.night_date: r for r in session.query(NightShiftRequirement).all()}


class StaffRoomingConfig(DatabaseConfigSection):
    """Which badges and rooms the night requirements apply to.

    The defaults check Staff badges on master-bill rooms outside the lottery:
    crash space, manual and department block rooms. Lottery Award and Suite
    Connector are the two reasons the lottery solver assigns.
    """
    section_name = 'staff_rooming'
    defaults = {
        'badge_types': [c.STAFF_BADGE],
        'room_reasons': [reason for reason, _ in c.HOTEL_ASSIGNMENT_REASON_OPTS
                         if reason not in (c.LOTTERY_AWARD, c.SUITE_CONNECTOR)],
        # [hotel_lottery] [[payment_types]] section names, as RoomAssignment stores them.
        'payment_types': [key for key in c.HOTEL_PAYMENT_TYPES if key not in c.HOTEL_PAYMENT_TYPES_REQUIRING_CC],
    }


staff_rooming_config = StaffRoomingConfig()

# Admin-facing names for [[hotel_assignment_reason]]. The configured labels
# name the code path, not what an admin did.
_ROOM_REASON_NAMES = {
    c.LOTTERY_AWARD: ('Won in the lottery', 'Awarded by a lottery run'),
    c.SUITE_CONNECTOR: ('Lottery suite connecting room', 'Added with an awarded suite'),
    c.MANUAL: ('Hotel admin assigned', 'Crash space and other rooms a hotel lottery admin adds'),
    c.PARTITION_GRANT: ('Department room block', 'Given by a department from its block of rooms'),
    c.STAFF_AUTO: ('Automatic staff room', 'No current admin screen assigns this'),
    c.MIGRATED: ('Old hotel system', 'Carried over when the hotel lottery replaced the old tables'),
}


def room_reason_opts():
    """Return (value, name, hint) for each room assignment reason, for the Staff Rooming page."""
    return [(value, *_ROOM_REASON_NAMES.get(value, (label, '')))
            for value, label in c.HOTEL_ASSIGNMENT_REASON_OPTS]


def is_checked_room(ra, rules):
    """Return whether this room puts its holder under the night requirements.

    `checked_room_clause` is the SQL form; keep the two in step.
    """
    return bool(ra.is_live and ra.assignment_reason in rules['room_reasons']
                and ra.payment_type in rules['payment_types'])


def checked_room_clause(rules):
    return and_(RoomAssignment.is_live, RoomAssignment.assignment_reason.in_(rules['room_reasons']),
                RoomAssignment.payment_type.in_(rules['payment_types']))


def assigned_nights(room_assignments, rules):
    """Return the set of dates the given checked rooms cover.

    Check-in date X with check-out date X+N means the staffer sleeps in the
    room on nights X, X+1, ..., X+N-1. Rooms with missing dates are skipped.
    """
    return _nights((ra.assigned_check_in_date, ra.assigned_check_out_date)
                   for ra in room_assignments if is_checked_room(ra, rules))


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

    Rooms the attendee holds and rooms they share as an occupant both count.
    Empty list means the attendee is compliant, their badge type or rooms are
    not checked, or no requirements exist.
    """
    session = sa_inspect(attendee).session
    if session is None:
        return []
    rules = staff_rooming_config.load(session)
    if attendee.badge_type not in rules['badge_types']:
        return []

    rooms = list(attendee.room_assignments) + list(attendee.occupied_rooms)
    if not rooms:
        return []

    if requirements_by_date is None:
        requirements_by_date = load_requirements(session)
    if not requirements_by_date:
        return []

    nights = assigned_nights(rooms, rules)
    if not nights:
        return []

    shift_spans = [(s.job.start_time, s.job.start_time + timedelta(minutes=s.job.duration or 0))
                   for s in attendee.shifts if s.job]
    return _violations(nights, attendee.weighted_hours, shift_spans, requirements_by_date)


def is_compliant(attendee, requirements_by_date=None):
    return not compliance_violations(attendee, requirements_by_date)


def non_compliant_staffers(session, department_id=None):
    """Return [(attendee, violations), ...], ordered by name, for people with a
    checked badge who hold or share a checked room and aren't compliant,
    optionally only members of `department_id`.
    """
    reqs = load_requirements(session)
    if not reqs:
        return []

    rules = staff_rooming_config.load(session)
    checked_room = checked_room_clause(rules)
    staff = session.query(Attendee).filter(Attendee.badge_type.in_(rules['badge_types']), or_(
        Attendee.room_assignments.any(checked_room), Attendee.occupied_rooms.any(checked_room)))
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
            RoomAssignment.attendee_id.in_(ids), checked_room):
        stays[attendee_id].append((check_in, check_out))
    occupant_id = room_assignment_occupant.c.attendee_id
    for attendee_id, check_in, check_out in session.query(
            occupant_id, RoomAssignment.assigned_check_in_date, RoomAssignment.assigned_check_out_date).join(
            RoomAssignment, RoomAssignment.id == room_assignment_occupant.c.room_assignment_id).filter(
            occupant_id.in_(ids), checked_room):
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
