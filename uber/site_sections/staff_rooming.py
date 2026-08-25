"""Staff Rooming admin - configures the per-date shift-compliance
requirements that gate staff hotel rooms.

Setup/teardown dates require staff with a RoomAssignment to have at least
one shift overlapping a configured time window. Core dates require a total
weighted-hour minimum across the whole con.

The page auto-populates with sensible defaults on first visit
"""

from datetime import datetime, time, timedelta

import cherrypy

from sqlalchemy import or_

from uber.config import c
from uber.decorators import all_renderable
from uber.errors import HTTPRedirect
from uber.hotel.queries import (build_room_assignment_query,
                                     clamp_page_size, paginate)
from uber.models import (Attendee, Department, NightShiftRequirement,
                         RoomAssignment)
from uber.models.hotel import LotteryHotel
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
                      billing='all', hotel_id='', search=''):
        ps = clamp_page_size(page_size)
        staff_badges = [c.STAFF_BADGE, c.CONTRACTOR_BADGE]

        # Only live (ASSIGNED + SECURED) RAs whose booker is staff.
        # badge_types inner-joins Attendee, so the ordering below can
        # sort on Attendee.last_name.
        q = build_room_assignment_query(
            session, status='live', hotel_id=hotel_id, search=search,
            badge_types=staff_badges)

        if billing == 'self_pay':
            q = q.filter(RoomAssignment.require_cc.is_(True))
        elif billing == 'master_bill':
            q = q.filter(RoomAssignment.require_cc.is_(False))

        q = q.order_by(RoomAssignment.assigned_check_in_date.asc().nullsfirst(),
                       Attendee.last_name.asc())
        assignments, total, page_num, page_count = paginate(q, page, ps)

        # Aggregates ignore page / billing filter so the badges always
        # show the full picture (lets the admin gauge how the filter
        # narrows the view).
        live_q = build_room_assignment_query(
            session, status='live', badge_types=staff_badges)
        total_self = live_q.filter(RoomAssignment.require_cc.is_(True)).count()
        total_master = live_q.filter(RoomAssignment.require_cc.is_(False)).count()

        hotels = (session.query(LotteryHotel)
                  .filter_by(active=True)
                  .order_by(LotteryHotel.name).all())

        return {
            'message': message,
            'assignments': assignments,
            'page': page_num,
            'page_size': ps,
            'total': total,
            'page_count': page_count,
            'billing': billing,
            'hotel_id': hotel_id,
            'search': search,
            'hotels': hotels,
            'total_self': total_self,
            'total_master': total_master,
        }

    # List all staff with toggleable `hotel_eligible` flag. Default
    # filter shows currently-eligible staff so the admin can scan who
    # would be invited into the next staff lottery without scrolling
    # through everyone who's been disqualified historically.

    def hotel_eligibility(self, session, message='', page='1', page_size='50',
                          show='eligible', search=''):
        ps = clamp_page_size(page_size)

        q = session.query(Attendee).filter(Attendee.badge_type.in_(
            [c.STAFF_BADGE, c.CONTRACTOR_BADGE]))
        if show == 'eligible':
            q = q.filter(Attendee.hotel_eligible.is_(True))
        elif show == 'ineligible':
            q = q.filter(Attendee.hotel_eligible.is_(False))

        if search:
            like = f'%{search.strip()}%'
            q = q.filter(or_(
                Attendee.first_name.ilike(like),
                Attendee.last_name.ilike(like),
                Attendee.email.ilike(like),
            ))

        q = q.order_by(Attendee.last_name.asc(), Attendee.first_name.asc())
        staffers, total, page_num, page_count = paginate(q, page, ps)

        # Cross-status counts for the header badges.
        all_staff_q = session.query(Attendee).filter(Attendee.badge_type.in_(
            [c.STAFF_BADGE, c.CONTRACTOR_BADGE]))
        total_eligible = all_staff_q.filter(Attendee.hotel_eligible.is_(True)).count()
        total_ineligible = all_staff_q.filter(Attendee.hotel_eligible.is_(False)).count()

        return {
            'message': message,
            'staffers': staffers,
            'page': page_num,
            'page_size': ps,
            'total': total,
            'page_count': page_count,
            'show': show,
            'search': search,
            'total_eligible': total_eligible,
            'total_ineligible': total_ineligible,
        }

    def set_hotel_eligibility(self, session, attendee_id, eligible='false',
                              csrf_token=None, return_url=''):
        """Toggle one staffer's `hotel_eligible` flag. Posted from the
        hotel_eligibility page; the row's checkbox doubles as the
        submit input via a per-row tiny form."""
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('hotel_eligibility')
        check_csrf(csrf_token)

        attendee = session.query(Attendee).get(attendee_id)
        if not attendee:
            _redirect_back(return_url, 'hotel_eligibility',
                           'Attendee not found.')
        new_val = (str(eligible).lower() == 'true')
        attendee.hotel_eligible = new_val
        session.add(attendee)
        session.commit()

        msg = (f"{attendee.full_name} is now "
               f"{'eligible' if new_val else 'ineligible'} for the staff hotel lottery.")
        _redirect_back(return_url, 'hotel_eligibility', msg)

    def bulk_set_hotel_eligibility(self, session, attendee_ids='',
                                   eligible='false', csrf_token=None,
                                   return_url=''):
        """Bulk flip - the checkboxes on the eligibility page can be
        submitted together via 'Set selected to eligible/ineligible'."""
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('hotel_eligibility')
        check_csrf(csrf_token)

        ids = [i.strip() for i in (attendee_ids or '').split(',') if i.strip()]
        if not ids:
            _redirect_back(return_url, 'hotel_eligibility',
                           'No attendees selected.')
        new_val = (str(eligible).lower() == 'true')
        rows = session.query(Attendee).filter(Attendee.id.in_(ids)).all()
        for a in rows:
            a.hotel_eligible = new_val
            session.add(a)
        session.commit()

        msg = (f"Marked {len(rows)} staffer(s) "
               f"{'eligible' if new_val else 'ineligible'} "
               f"for the staff hotel lottery.")
        _redirect_back(return_url, 'hotel_eligibility', msg)
