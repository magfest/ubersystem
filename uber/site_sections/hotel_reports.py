from collections import defaultdict, OrderedDict
from datetime import timedelta
import random

from pockets.autolog import log
from sqlalchemy import and_, or_
from sqlalchemy.orm import joinedload, subqueryload

from uber.config import c
from uber.decorators import all_renderable, csv_file
from uber.models import Attendee, HotelRequests, Job, Room, RoomAssignment, Shift
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


def _attendee_hotel_nights(session):
    query = session.query(Attendee).filter(Attendee.assigned_depts.any()).options(
        subqueryload(Attendee.depts_where_working),
        subqueryload(Attendee.shifts).subqueryload(Shift.job).subqueryload(Job.department),
        subqueryload(Attendee.hotel_requests)).order_by(Attendee.full_name, Attendee.id)

    attendee_hotel_nights = []

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

        attendee_hotel_nights.append(dict(
            attendee=attendee,
            hotel_nights=hotel_nights,
            hotel_shoulder_nights=hotel_shoulder_nights,
            hotel_night_dates=hotel_night_dates,
            first_hotel_night=first_hotel_night,
            last_hotel_night=last_hotel_night,
        ))
    return attendee_hotel_nights


def _hours_vs_rooms(session):
    attendee_hotel_nights = _attendee_hotel_nights(session)
    for report in attendee_hotel_nights:
        attendee = report['attendee']
        report.update(
            weighted_hours=attendee.weighted_hours - attendee.nonshift_hours,
            worked_hours=attendee.worked_hours - attendee.nonshift_hours,
            unweighted_hours=attendee.unweighted_hours - attendee.nonshift_hours,
            unweighted_worked_hours=attendee.unweighted_worked_hours - attendee.nonshift_hours,
            nonshift_hours=attendee.nonshift_hours,
        )
    return attendee_hotel_nights


def _hours_vs_rooms_by_dept(session):
    departments = defaultdict(lambda: dict(
        attendees=[],
        total_weighted_hours=0,
        total_worked_hours=0,
        total_unweighted_hours=0,
        total_unweighted_worked_hours=0,
        total_hotel_nights=0,
        total_hotel_shoulder_nights=0,
    ))
    attendee_hotel_nights = _attendee_hotel_nights(session)
    for attendee_report in attendee_hotel_nights:
        attendee = attendee_report['attendee']
        for dept in attendee.depts_where_working:
            attendee_report = dict(attendee_report)
            attendee_report.update(
                department=dept,
                weighted_hours=attendee.weighted_hours_in(dept),
                worked_hours=attendee.worked_hours_in(dept),
                unweighted_hours=attendee.unweighted_hours_in(dept),
                unweighted_worked_hours=attendee.unweighted_worked_hours_in(dept),
                nonshift_hours=attendee.nonshift_hours,
            )

            dept_report = departments[dept]
            dept_report['attendees'].append(attendee_report)
            dept_report['total_weighted_hours'] += attendee_report['weighted_hours']
            dept_report['total_worked_hours'] += attendee_report['worked_hours']
            dept_report['total_unweighted_hours'] += attendee_report['unweighted_hours']
            dept_report['total_unweighted_worked_hours'] += attendee_report['unweighted_worked_hours']
            dept_report['total_hotel_nights'] += len(attendee_report['hotel_nights'])
            dept_report['total_hotel_shoulder_nights'] += len(attendee_report['hotel_shoulder_nights'])

    return OrderedDict(sorted(departments.items(), key=lambda d: d[0].name))


def _generate_hotel_pin():
    """
    Returns a 7 digit number formatted as a zero padded string.
    """
    return '{:07d}'.format(random.randint(0, 9999999))


@all_renderable()
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
        return {'hours_vs_rooms_report': _hours_vs_rooms(session)}

    @csv_file
    def hours_vs_rooms_csv(self, out, session):
        hours_vs_rooms_report = _hours_vs_rooms(session)

        rows = []
        for report in hours_vs_rooms_report:
            rows.append([
                report['attendee'].full_name,
                report['attendee'].email,
                ' / '.join(sorted(map(lambda d: d.name, report['attendee'].depts_where_working))),
                report['weighted_hours'],
                report['worked_hours'],
                report['unweighted_hours'],
                report['unweighted_worked_hours'],
                report['nonshift_hours'],
                report['first_hotel_night'].strftime('%Y-%m-%d') if report['first_hotel_night'] else '',
                report['last_hotel_night'].strftime('%Y-%m-%d') if report['last_hotel_night'] else '',
                len(report['hotel_nights']),
                len(report['hotel_shoulder_nights']),
            ])

        out.writerow([
            'Attendee',
            'Email',
            'Depts Where Working',
            'Assigned Shift Hours (weighted)',
            'Worked Shift Hours (weighted)',
            'Assigned Shift Hours (unweighted)',
            'Worked Shift Hours (unweighted)',
            'Nonshift Hours',
            'First Hotel Night',
            'Last Hotel Night',
            'Total Hotel Nights',
            'Total Shoulder Nights',
        ])
        for row in rows:
            out.writerow(row)

    def hours_vs_rooms_by_dept(self, session):
        return {'departments': _hours_vs_rooms_by_dept(session)}

    @csv_file
    def hours_vs_rooms_by_dept_csv(self, out, session):
        departments = _hours_vs_rooms_by_dept(session)

        rows = []
        for department, hours_vs_rooms_report in departments.items():
            for report in hours_vs_rooms_report['attendees']:
                rows.append([
                    report['attendee'].full_name,
                    report['attendee'].email,
                    department.name,
                    report['weighted_hours'],
                    report['worked_hours'],
                    report['unweighted_hours'],
                    report['unweighted_worked_hours'],
                    report['nonshift_hours'],
                    report['first_hotel_night'].strftime('%Y-%m-%d') if report['first_hotel_night'] else '',
                    report['last_hotel_night'].strftime('%Y-%m-%d') if report['last_hotel_night'] else '',
                    len(report['hotel_nights']),
                    len(report['hotel_shoulder_nights']),
                ])

        out.writerow([
            'Attendee',
            'Email',
            'Department',
            'Assigned Shift Hours (weighted)',
            'Worked Shift Hours (weighted)',
            'Assigned Shift Hours (unweighted)',
            'Worked Shift Hours (unweighted)',
            'Nonshift Hours (everywhere)',
            'First Hotel Night',
            'Last Hotel Night',
            'Total Hotel Nights',
            'Total Shoulder Nights',
        ])
        for row in rows:
            out.writerow(row)

    @csv_file
    def ordered(self, out, session):
        reqs = [
            hr for hr in session.query(HotelRequests).options(joinedload(HotelRequests.attendee)).all()
            if hr.nights and hr.attendee.badge_status in (c.NEW_STATUS, c.COMPLETED_STATUS)]

        assigned = {
            ra.attendee for ra in session.query(RoomAssignment).options(
            joinedload(RoomAssignment.attendee), joinedload(RoomAssignment.room)).all()}

        unassigned = {hr.attendee for hr in reqs if hr.attendee not in assigned}

        names = {}
        for attendee in unassigned:
            names.setdefault(attendee.last_name.lower(), set()).add(attendee)

        lookup = defaultdict(set)
        for xs in names.values():
            for attendee in xs:
                lookup[attendee] = xs

        for req in reqs:
            if req.attendee in unassigned:
                for word in req.wanted_roommates.lower().replace(',', '').split():
                    try:
                        combined = lookup[list(names[word])[0]] | lookup[req.attendee]
                        for attendee in combined:
                            lookup[attendee] = combined
                    except Exception:
                        pass

        def writerow(a, hr):
            out.writerow([
                a.full_name, a.email, a.cellphone,
                a.hotel_requests.nights_display, ' / '.join(a.assigned_depts_labels),
                hr.wanted_roommates, hr.unwanted_roommates, hr.special_needs
            ])

        grouped = {frozenset(group) for group in lookup.values()}
        out.writerow([
            'Name',
            'Email',
            'Phone',
            'Nights',
            'Departments',
            'Roomate Requests',
            'Roomate Anti-Requests',
            'Special Needs'])

        # TODO: for better efficiency, a multi-level joinedload would be preferable here
        for room in session.query(Room).options(joinedload(Room.assignments)).all():
            for i in range(3):
                out.writerow([])
            out.writerow([
                ('Locked-in ' if room.locked_in else '')
                + 'room created by STOPS for '
                + room.nights_display
                + (' ({})'.format(room.notes) if room.notes else '')])

            for ra in room.assignments:
                writerow(ra.attendee, ra.attendee.hotel_requests)
        for group in sorted(grouped, key=len, reverse=True):
            for i in range(3):
                out.writerow([])
            for a in group:
                writerow(a, a.hotel_requests)

    @csv_file
    def hotel_email_info(self, out, session):
        fields = [
            'CheckIn Date', 'CheckOut Date', 'Number of Guests', 'Room Notes',
            'Guest1 First Name', 'Guest1 Last Name', 'Guest1 Legal Name',
            'Guest2 First Name', 'Guest2 Last Name', 'Guest2 Legal Name',
            'Guest3 First Name', 'Guest3 Last Name', 'Guest3 Legal Name',
            'Guest4 First Name', 'Guest4 Last Name', 'Guest4 Legal Name',
            'Guest5 First Name', 'Guest5 Last Name', 'Guest5 Legal Name',
            'Emails',
        ]

        blank = OrderedDict([(field, '') for field in fields])
        out.writerow(fields)
        for room in session.query(Room).order_by(Room.created).all():
            if room.assignments:
                row = blank.copy()
                row.update({
                    'Room Notes': room.notes,
                    'Number of Guests': min(4, len(room.assignments)),
                    'CheckIn Date': room.check_in_date.strftime('%m/%d/%Y'),
                    'CheckOut Date': room.check_out_date.strftime('%m/%d/%Y'),
                    'Emails': ','.join(room.email),
                })
                for i, attendee in enumerate([ra.attendee for ra in room.assignments[:4]]):
                    prefix = 'Guest{}'.format(i + 1)
                    row.update({
                        prefix + ' First Name': attendee.first_name,
                        prefix + ' Last Name': attendee.last_name,
                        prefix + ' Legal Name': attendee.legal_name,
                    })
                out.writerow(list(row.values()))

    @csv_file
    def mark_center(self, out, session):
        """spreadsheet in the format requested by the Hilton Mark Center"""
        out.writerow([
            'Last Name',
            'First Name',
            'Arrival',
            'Departure',
            'Hide',
            'Room Type',
            'Hide',
            'Number of Adults',
            'Hide',
            'Hide',
            'IPO',
            'Individual Pays Own-',
            'Credit Card Name',
            'Credit Card Number',
            'Credit Card Expiration',
            'Last Name 2',
            'First Name 2',
            'Last Name 3',
            'First Name 3',
            'Last Name 4',
            'First Name 4',
            'Comments',
            'Emails',
        ])
        for room in session.query(Room).order_by(Room.created).all():
            if room.assignments:
                assignments = [ra.attendee for ra in room.assignments[:4]]
                roommates = [
                                [a.legal_last_name, a.legal_first_name]
                                for a in assignments[1:]] + [['', '']] * (4 - len(assignments))

                last_name = assignments[0].legal_last_name
                first_name = assignments[0].legal_first_name
                arrival = room.check_in_date.strftime('%-m/%-d/%Y')
                departure = room.check_out_date.strftime('%-m/%-d/%Y')
                out.writerow([
                                 last_name,  # Last Name
                                 first_name,  # First Name
                                 arrival,  # Arrival
                                 departure,  # Departure
                                 '',  # Hide
                                 'Q2',  # Room Type ('Q2' is 2 queen beds, 'K1' is 1 king bed)
                                 '',  # Hide
                                 len(assignments),  # Number of Adults
                                 '',  # Hide
                                 '',  # Hide
                                 '',  # IPO
                                 '',  # Individual Pays Own-
                                 '',  # Credit Card Name
                                 '',  # Credit Card Number
                                 ''  # Credit Card Expiration
                             ] + sum(roommates, []) + [  # Last Name, First Name 2-4
                                 room.notes,  # Comments
                                 ','.join(room.email),  # Emails
                             ])

    @csv_file
    def gaylord(self, out, session):
        fields = [
            'First Name', 'Last Name', 'Guest Email Address for confirmation purposes', 'Special Requests',
            'Arrival', 'Departure', 'City', 'State', 'Zip', 'GUEST COUNTRY', 'Telephone',
            'Payment Type', 'Card #', 'Exp.',
            'BILLING ADDRESS', 'BILLING CITY', 'BILLING STATE', 'BILLING ZIP CODE', 'BILLING COUNTRY',
            'Additional Guest First Name-2', 'Additional Guest Last Name-2',
            'Additional Guest First Name-3', 'Additional Guest Last Name3',  # No, this is not a typo
            'Additional Guest First Name-4', 'Additional Guest Last Name-4',
            'Notes', 'Emails',
        ]

        blank = OrderedDict([(field, '') for field in fields])
        out.writerow(fields)
        for room in session.query(Room).order_by(Room.created).all():
            if room.assignments:
                row = blank.copy()
                row.update({
                    'Notes': room.notes,
                    'Arrival': room.check_in_date.strftime('%m/%d/%Y'),
                    'Departure': room.check_out_date.strftime('%m/%d/%Y'),
                    'Emails': ','.join(room.email),
                })
                for i, attendee in enumerate([ra.attendee for ra in room.assignments[0:4]]):
                    if i == 0:
                        prefix, suffix = '', ''
                        row.update({'Guest Email Address for confirmation purposes': attendee.email})
                    else:
                        prefix = 'Additional Guest'
                        suffix = '-{}'.format(i + 1) if i != 2 else str(i + 1)
                    row.update({
                        prefix + 'First Name' + suffix: attendee.legal_first_name,
                        prefix + 'Last Name' + suffix: attendee.legal_last_name
                    })
                out.writerow(list(row.values()))

    @csv_file
    def requested_hotel_info(self, out, session):
        eligibility_filters = []
        if c.PREREG_REQUEST_HOTEL_INFO_DURATION > 0:
            eligibility_filters.append(Attendee.requested_hotel_info == True)  # noqa: E711
        if c.PREREG_HOTEL_ELIGIBILITY_CUTOFF:
            eligibility_filters.append(or_(
                Attendee.registered <= c.PREREG_HOTEL_ELIGIBILITY_CUTOFF,
                and_(Attendee.paid == c.NEED_NOT_PAY, Attendee.promo_code == None))
            )

        hotel_query = session.query(Attendee).filter(*eligibility_filters).filter(
            Attendee.badge_status.notin_([c.INVALID_STATUS, c.REFUNDED_STATUS]),
            Attendee.email != '',
        )  # noqa: E712

        attendees_without_hotel_pin = hotel_query.filter(*eligibility_filters).filter(or_(
            Attendee.hotel_pin == None,
            Attendee.hotel_pin == '',
        )).all()  # noqa: E711

        if attendees_without_hotel_pin:
            hotel_pin_rows = session.query(Attendee.hotel_pin).filter(*eligibility_filters).filter(
                Attendee.hotel_pin != None,
                Attendee.hotel_pin != '',
            ).all()  # noqa: E711

            hotel_pins = set(map(lambda r: r[0], hotel_pin_rows))
            for a in attendees_without_hotel_pin:
                new_hotel_pin = _generate_hotel_pin()
                while new_hotel_pin in hotel_pins:
                    new_hotel_pin = _generate_hotel_pin()
                hotel_pins.add(new_hotel_pin)
                a.hotel_pin = new_hotel_pin
            session.commit()

        headers = ['First Name', 'Last Name', 'E-mail Address', 'LoginID']
        for count in range(2, 21):
            headers.append('LoginID{}'.format(count))

        out.writerow(headers)
        added = set()

        hotel_results = sorted(hotel_query.all(), key=lambda a: a.legal_name or a.full_name)

        matching_attendees = defaultdict(list)
        for a in hotel_results:
            matching_attendees[a.first_name, a.last_name, a.email].append(a)

        for a in hotel_results:
            row = [a.legal_first_name, a.legal_last_name, a.email, a.hotel_pin]

            if a.hotel_pin not in added:
                added.add(a.hotel_pin)

                for matching_attendee in matching_attendees[a.first_name, a.last_name, a.email]:
                    if matching_attendee.id != a.id:
                        row.append(matching_attendee.hotel_pin)
                        added.add(matching_attendee.hotel_pin)

                out.writerow(row)
