from collections import defaultdict, OrderedDict
from datetime import timedelta
import random

from pockets.autolog import log
from sqlalchemy import or_
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
        approved_nights = set(attendee.hotel_requests.nights_ints)
        approved_shoulder_nights = approved_nights.difference(c.CORE_NIGHTS)
        shifts_by_night = defaultdict(list)
        departments = set()
        for shift in attendee.shifts:
            job = shift.job
            dept = job.department
            departments.add(dept)
            shifts_by_night[job.hotel_night].append(shift)

        discrepencies = approved_shoulder_nights.difference(set(shifts_by_night.keys()))
        if discrepencies:
            if not attendee.shifts:
                shoulder_nights_missing_shifts['none'][attendee] = list(discrepencies)
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
            weighted_hours=attendee.weighted_hours - attendee.nonshift_minutes / 60,
            worked_hours=attendee.worked_hours - attendee.nonshift_minutes / 60,
            unweighted_hours=attendee.unweighted_hours - attendee.nonshift_minutes / 60,
            unweighted_worked_hours=attendee.unweighted_worked_hours - attendee.nonshift_minutes / 60,
            nonshift_hours=attendee.nonshift_minutes / 60,
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
                nonshift_hours=attendee.nonshift_minutes / 60,
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
        no_shifts_attendees = []
        no_shifts = shoulder_nights_missing_shifts.pop('none', None)
        if no_shifts:
            for attendee in sorted(no_shifts, key=lambda a: a.full_name):
                nights = no_shifts[attendee]
                night_names = ' / '.join([c.NIGHTS[n] for n in c.NIGHT_DISPLAY_ORDER if n in nights])
                attendee.night_names = night_names
                no_shifts_attendees.append(attendee)

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
        return {
            'departments': departments,
            'no_shifts': no_shifts,
            'no_shifts_attendees': no_shifts_attendees,
        }

    @csv_file
    def inconsistent_shoulder_shifts_csv(self, out, session):
        shoulder_nights_missing_shifts = _inconsistent_shoulder_shifts(session)

        rows = []
        no_shifts = shoulder_nights_missing_shifts.pop('none', None)
        if no_shifts:
            for attendee in sorted(no_shifts, key=lambda a: a.full_name):
                nights = no_shifts[attendee]
                night_names = ' / '.join([c.NIGHTS[n] for n in c.NIGHT_DISPLAY_ORDER if n in nights])
                attendee.night_names = night_names
                rows.append(['No Shifts', attendee.full_name, attendee.email, night_names])
        
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
    def hotel_audit(self, out, session):
        """All valid attendees provided to the hotels team for Maritz' audit"""
        out.writerow([
            'First Name',
            'Last Name',
            'Legal Name',
            'City',
            'State',
            'Zip Code',
            'Non-US?'
        ])
        engine = None
        if c.MAPS_ENABLED:
            from uszipcode import SearchEngine
            try:
                engine = SearchEngine(db_file_dir=c.MAPS_DIR)
            except Exception as e:
                log.error("Error calling SearchEngine: " + e)

        for attendee in session.valid_attendees().filter(Attendee.is_unassigned == False):  # noqa: E712
            city = ''
            state = ''
            if engine and attendee.zip_code and not attendee.international:
                simple_zip = engine.by_zipcode(attendee.zip_code[:5])
                city = simple_zip.city
                state = simple_zip.state
            out.writerow([
                attendee.first_name,
                attendee.last_name,
                attendee.legal_name,
                city,
                state,
                attendee.zip_code,
                "Yes" if attendee.international else "No",
            ])

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
    def attendee_hotel_pins(self, out, session):
        hotel_query = session.query(Attendee).filter(Attendee.email != '', Attendee.is_valid == True,  # noqa: E712
                                                     ~Attendee.badge_status.in_([c.REFUNDED_STATUS,
                                                                                 c.NOT_ATTENDING,
                                                                                 c.DEFERRED_STATUS]),
                                                     or_(Attendee.badge_type != c.STAFF_BADGE,
                                                         Attendee.hotel_eligible == True))  # noqa: E712

        attendees_without_hotel_pin = hotel_query.filter(or_(
            Attendee.hotel_pin == None,  # noqa: E711
            Attendee.hotel_pin == '',
        )).all()  # noqa: E711

        if attendees_without_hotel_pin:
            hotel_pin_rows = session.query(Attendee.hotel_pin).filter(
                Attendee.hotel_pin != None,  # noqa: E711
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

        headers = ['First Name', 'Last Name', 'Email Address', 'LoginID']
        for count in range(2, 21):
            headers.append('LoginID{}'.format(count))

        out.writerow(headers)
        added = set()

        hotel_results = sorted(hotel_query.all(), key=lambda a: a.legal_name or a.full_name)

        for a in hotel_results:
            row = [a.legal_first_name, a.legal_last_name, a.email, a.hotel_pin]

            if a.hotel_pin not in added:
                added.add(a.hotel_pin)
                out.writerow(row)
