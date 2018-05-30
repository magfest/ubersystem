from collections import defaultdict
from datetime import timedelta

from sqlalchemy.orm import joinedload, subqueryload

from uber.config import c
from uber.decorators import all_renderable, csv_file
from uber.models import Attendee, HotelRequests, Job, Shift
from uber.utils import noon_datetime


def _inconsistent_shoulder_shifts(session):
    query = session.query(Attendee).join(HotelRequests) \
        .options(
            subqueryload(Attendee.depts_where_working),
            subqueryload(Attendee.shifts).subqueryload(Shift.job).subqueryload(Job.department),
            subqueryload(Attendee.hotel_requests)) \
        .filter(HotelRequests.approved == True).order_by(Attendee.full_name, Attendee.id)  # noqa: E712

    shoulder_nights_missing_shifts = defaultdict(lambda: defaultdict(list))

    for attendee in query:
        if attendee.is_dept_head:
            continue
        approved_nights = set(attendee.hotel_requests.nights_ints)
        approved_shoulder_nights = approved_nights.difference(c.CORE_NIGHTS)
        shifts_by_night = defaultdict(list)
        departments = set()
        for shift in attendee.shifts:
            job = shift.job
            dept = job.department
            departments.add(dept)
            start_time = job.start_time.astimezone(c.EVENT_TIMEZONE)
            shift_night = getattr(c, start_time.strftime('%A').upper())
            shifts_by_night[shift_night].append(shift)

            if start_time <= noon_datetime(start_time):
                day_before = start_time - timedelta(days=1)
                shift_night = getattr(c, day_before.strftime('%A').upper())
                shifts_by_night[shift_night].append(shift)

        discrepencies = approved_shoulder_nights.difference(set(shifts_by_night.keys()))
        if discrepencies:
            for dept in departments:
                shoulder_nights_missing_shifts[dept][attendee] = list(discrepencies)

    return shoulder_nights_missing_shifts


def _hours_vs_rooms(session):
    query = session.query(Attendee).filter(Attendee.assigned_depts.any()).options(
        subqueryload(Attendee.depts_where_working),
        subqueryload(Attendee.shifts).subqueryload(Shift.job).subqueryload(Job.department),
        subqueryload(Attendee.hotel_requests)).order_by(Attendee.full_name, Attendee.id)

    hours_vs_rooms = []

    for attendee in query:
        if attendee.hotel_requests and attendee.hotel_requests.approved:
            hotel_nights = set(attendee.hotel_requests.nights_ints)
            hotel_shoulder_nights = hotel_nights.difference(c.CORE_NIGHTS)
            hotel_night_dates = sorted(map(lambda x: c.NIGHT_DATES[c.NIGHTS[x]], hotel_nights))
        else:
            hotel_nights = set()
            hotel_shoulder_nights = set()
            hotel_night_dates = []

        if hotel_night_dates:
            first_hotel_night = min(hotel_night_dates)
            last_hotel_night = max(hotel_night_dates)
        else:
            first_hotel_night = None
            last_hotel_night = None

        by_dept = {}
        for dept in attendee.depts_where_working:
            by_dept[dept] = dict(
                weighted_hours=attendee.weighted_hours_in(dept),
                worked_hours=attendee.worked_hours_in(dept),
                unweighted_hours=attendee.unweighted_hours_in(dept),
                unweighted_worked_hours=attendee.unweighted_worked_hours_in(dept),
            )

        hours_vs_rooms.append(dict(
            attendee=attendee,
            weighted_hours=attendee.weighted_hours - attendee.nonshift_hours,
            worked_hours=attendee.worked_hours - attendee.nonshift_hours,
            unweighted_hours=attendee.unweighted_hours - attendee.nonshift_hours,
            unweighted_worked_hours=attendee.unweighted_worked_hours - attendee.nonshift_hours,
            nonshift_hours=attendee.nonshift_hours,
            hotel_nights=hotel_nights,
            hotel_shoulder_nights=hotel_shoulder_nights,
            hotel_night_dates=hotel_night_dates,
            first_hotel_night=first_hotel_night,
            last_hotel_night=last_hotel_night,
        ))

    return hours_vs_rooms



@all_renderable(c.PEOPLE)
class Root:
    # TODO: handle people who didn't request setup / teardown but who were assigned to a setup / teardown room
    def setup_teardown(self, session):
        attendees = []
        hotel_requests = session.query(HotelRequests).filter_by(approved=True).options(
            joinedload(HotelRequests.attendee).subqueryload(Attendee.shifts).joinedload(Shift.job))

        for hr in hotel_requests:
            badge_new_or_complete = hr.attendee.badge_status in [c.NEW_STATUS, c.COMPLETED_STATUS]
            if hr.setup_teardown and hr.attendee.takes_shifts and badge_new_or_complete:
                reasons = []
                if hr.attendee.setup_hotel_approved \
                        and not any([shift.job.is_setup for shift in hr.attendee.shifts]):
                    reasons.append('has no setup shifts')

                if hr.attendee.teardown_hotel_approved \
                        and not any([shift.job.is_teardown for shift in hr.attendee.shifts]):
                    reasons.append('has no teardown shifts')

                if reasons:
                    attendees.append([hr.attendee, reasons])

        attendees = sorted(attendees, key=lambda tup: tup[0].full_name)

        return {
            'attendees': [
                ('Department Heads', [tup for tup in attendees if tup[0].is_dept_head]),
                ('Regular Staffers', [tup for tup in attendees if not tup[0].is_dept_head])
            ]
        }

    def inconsistent_shoulder_shifts(self, session):
        shoulder_nights_missing_shifts = _inconsistent_shoulder_shifts(session)

        departments = []
        for dept in sorted(set(shoulder_nights_missing_shifts.keys()), key=lambda d: d.name):
            dept_heads = sorted(dept.dept_heads, key=lambda a: a.full_name)
            dept_head_emails = ', '.join([
                a.full_name + (' <{}>'.format(a.email) if a.email else '') for a in dept_heads])
            dept.dept_head_emails = dept_head_emails
            dept.inconsistent_attendees = []
            departments.append(dept)
            for attendee in sorted(shoulder_nights_missing_shifts[dept], key=lambda a: a.full_name):
                nights = shoulder_nights_missing_shifts[dept][attendee]
                night_names = ' / '.join([c.NIGHTS[n] for n in c.NIGHT_DISPLAY_ORDER if n in nights])
                attendee.night_names = night_names
                dept.inconsistent_attendees.append(attendee)
        return {'departments': departments}

    @csv_file
    def inconsistent_shoulder_shifts_csv(self, out, session):
        shoulder_nights_missing_shifts = _inconsistent_shoulder_shifts(session)

        rows = []
        departments = set(shoulder_nights_missing_shifts.keys())
        for dept in sorted(departments, key=lambda d: d.name):
            for attendee in sorted(shoulder_nights_missing_shifts[dept], key=lambda a: a.full_name):
                nights = shoulder_nights_missing_shifts[dept][attendee]
                night_names = ' / '.join([c.NIGHTS[n] for n in c.NIGHT_DISPLAY_ORDER if n in nights])
                rows.append([dept.name, attendee.full_name, attendee.email, night_names])

        out.writerow(['Department', 'Attendee', 'Attendee Email', 'Inconsistent Nights'])
        for row in rows:
            out.writerow(row)

    def hours_vs_rooms(self, session):
        return {'hours_vs_rooms_report': _hours_vs_rooms(session) }

    @csv_file
    def hours_vs_rooms_csv(self, out, session):
        hours_vs_rooms_report = _hours_vs_rooms(session)

        rows = []
        for report in hours_vs_rooms_report:
            rows.append([
                report.attendee.full_name,
                map(lambda d: d.name, report.attendee.depts_where_working).join(' / '),
                report.weighted_hours,
                report.worked_hours,
                report.nonshift_hours,
                report.first_hotel_night.strftime('%Y-%m-%d') if report.first_hotel_night else '',
                report.last_hotel_night.strftime('%Y-%m-%d') if report.last_hotel_night else '',
                len(report.hotel_nights),
                len(report.hotel_shoulder_nights),
            ])

        out.writerow([
            'Attendee',
            'Depts Where Working',
            'Assigned Shift Hours (weighted)',
            'Worked Shift Hours (weighted)',
            'Nonshift Hours',
            'First Hotel Night',
            'Last Hotel Night',
            'Total Hotel Nights',
            'Total Shoulder Nights',
        ])
        for row in rows:
            out.writerow(row)
