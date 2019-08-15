from collections import defaultdict, OrderedDict
from datetime import timedelta

import cherrypy
from sqlalchemy import or_
from sqlalchemy.orm import joinedload, subqueryload

from uber.config import c
from uber.decorators import ajax, all_renderable, csv_file
from uber.errors import HTTPRedirect
from uber.models import Attendee, HotelRequests, Room, RoomAssignment, Shift
from uber.models.attendee import _generate_hotel_pin


@all_renderable(c.STAFF_ROOMS)
class Root:
    def index(self, session):
        three_days_before = (c.EPOCH - timedelta(days=3)).strftime('%A')
        two_days_before = (c.EPOCH - timedelta(days=2)).strftime('%A')
        day_before = (c.EPOCH - timedelta(days=1)).strftime('%A')
        last_day = c.ESCHATON.strftime('%A')
        return {
            'dump': _hotel_dump(session),
            'nights': [{
                'core': False,
                'name': three_days_before.lower(),
                'val': getattr(c, three_days_before.upper()),
                'desc': three_days_before + ' night (for super-early setup volunteers)'
            }, {
                'core': False,
                'name': two_days_before.lower(),
                'val': getattr(c, two_days_before.upper()),
                'desc': two_days_before + ' night (for early setup volunteers)'
            }, {
                'core': False,
                'name': day_before.lower(),
                'val': getattr(c, day_before.upper()),
                'desc': day_before + ' night (for setup volunteers)'
            }] + [{
                'core': True,
                'name': c.NIGHTS[night].lower(),
                'val': night,
                'desc': c.NIGHTS[night]
            } for night in c.CORE_NIGHTS] + [{
                'core': False,
                'name': last_day.lower(),
                'val': getattr(c, last_day.upper()),
                'desc': last_day + ' night (for teardown volunteers)'
            }]
        }

    def goto_staffer_requests(self, id):
        cherrypy.session['staffer_id'] = id
        raise HTTPRedirect('../hotel/index')

    @ajax
    def create_room(self, session, **params):
        params['nights'] = list(filter(bool, [params.pop(night, None) for night in c.NIGHT_NAMES]))
        loops = int(params['count']) if params.get("count") else 1
        for x in range(loops):
            session.add(session.room(params))
        session.commit()
        return _hotel_dump(session)

    @ajax
    def edit_room(self, session, **params):
        params['nights'] = list(filter(bool, [params.pop(night, None) for night in c.NIGHT_NAMES]))
        params['locked_in'] = str(params.get('locked_in', 'false')).lower() == 'true'
        session.room(params)
        session.commit()
        return _hotel_dump(session)

    @ajax
    def delete_room(self, session, id):
        room = session.room(id)
        session.delete(room)
        session.commit()
        return _hotel_dump(session)

    @ajax
    def lock_in_room(self, session, id):
        room = session.room(id)
        room.locked_in = True
        session.commit()
        return _hotel_dump(session)

    @ajax
    def assign_to_room(self, session, attendee_id, room_id):
        message = ''
        room = session.room(room_id)
        for other in session.query(RoomAssignment).filter_by(attendee_id=attendee_id).all():
            if set(other.room.nights_ints).intersection(room.nights_ints):
                message = "Warning: this attendee already has a room which overlaps with this room's nights"
        else:
            attendee = session.attendee(attendee_id)
            ra = RoomAssignment(attendee=attendee, room=room)
            session.add(ra)
            hr = attendee.hotel_requests
            if room.setup_teardown:
                hr.approved = True
            elif not hr.approved:
                hr.decline()
            session.commit()
        return dict(_hotel_dump(session), message=message)

    @ajax
    def unassign_from_room(self, session, attendee_id, room_id):
        for ra in session.query(RoomAssignment).filter_by(attendee_id=attendee_id, room_id=room_id).all():
            session.delete(ra)
        session.commit()
        return _hotel_dump(session)

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
                    last_name,              # Last Name
                    first_name,             # First Name
                    arrival,                # Arrival
                    departure,              # Departure
                    '',                     # Hide
                    'Q2',                   # Room Type ('Q2' is 2 queen beds, 'K1' is 1 king bed)
                    '',                     # Hide
                    len(assignments),       # Number of Adults
                    '',                     # Hide
                    '',                     # Hide
                    '',                     # IPO
                    '',                     # Individual Pays Own-
                    '',                     # Credit Card Name
                    '',                     # Credit Card Number
                    ''                      # Credit Card Expiration
                ] + sum(roommates, []) + [  # Last Name, First Name 2-4
                    room.notes,             # Comments
                    ','.join(room.email),   # Emails
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
                        suffix = '-{}'.format(i+1) if i != 2 else str(i+1)
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
            eligibility_filters.append(Attendee.registered <= c.PREREG_HOTEL_ELIGIBILITY_CUTOFF)

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

        out.writerow(['First Name', 'Last Name', 'E-mail Address', 'Password'])
        for a in sorted(hotel_query.all(), key=lambda a: a.legal_name or a.full_name):
            out.writerow([a.legal_first_name, a.legal_last_name, a.email, a.hotel_pin])


def _attendee_nights_without_shifts(attendee):
    nights = []
    if attendee.hotel_requests:
        discrepancies = attendee.hotel_nights_without_shifts_that_day
        for night in sorted(attendee.hotel_requests.nights_ints, key=c.NIGHT_DISPLAY_ORDER.index):
            nights.append((c.NIGHTS[night], night in discrepancies))
    return nights


def _attendee_dict(attendee, verbose=False):
    return {
        'id': attendee.id,
        'name': attendee.full_name,
        'nights': getattr(attendee.hotel_requests, 'nights_display', ''),
        'nights_without_shifts': _attendee_nights_without_shifts(attendee),
        'special_needs': getattr(attendee.hotel_requests, 'special_needs', ''),
        'wanted_roommates': getattr(attendee.hotel_requests, 'wanted_roommates', ''),
        'unwanted_roommates': getattr(attendee.hotel_requests, 'unwanted_roommates', ''),
        'approved': int(getattr(attendee.hotel_requests, 'approved', False)),
        'departments': ' / '.join(attendee.assigned_depts_labels),
        'nights_lookup': {night: getattr(attendee.hotel_requests, night, False) for night in c.NIGHT_NAMES},
        'multiply_assigned': len(attendee.room_assignments) > 1
    }


def _room_dict(room):
    return dict({
        'id': room.id,
        'notes': room.notes,
        'message': room.message,
        'locked_in': room.locked_in,
        'nights': room.nights_display,
        'attendees': [
            _attendee_dict(ra.attendee) for ra in sorted(room.assignments, key=lambda ra: ra.attendee.full_name)]
    }, **{night: getattr(room, night) for night in c.NIGHT_NAMES})


def _get_confirmed(session):
    attendee_query = session.query(Attendee) \
        .options(
            subqueryload(Attendee.hotel_requests),
            subqueryload(Attendee.assigned_depts),
            subqueryload(Attendee.room_assignments),
            subqueryload(Attendee.shifts).subqueryload(Shift.job)) \
        .filter(
            Attendee.hotel_requests != None,
            Attendee.badge_status.in_([c.NEW_STATUS, c.COMPLETED_STATUS])) \
        .order_by(Attendee.full_name, Attendee.id)  # noqa: E711
    return attendee_query


def _get_unconfirmed(session):
    attendee_query = session.query(Attendee) \
        .options(
            subqueryload(Attendee.hotel_requests),
            subqueryload(Attendee.assigned_depts),
            subqueryload(Attendee.room_assignments),
            subqueryload(Attendee.shifts).subqueryload(Shift.job)) \
        .filter(
            Attendee.hotel_eligible == True,
            Attendee.hotel_requests == None,
            Attendee.badge_status.in_([c.NEW_STATUS, c.COMPLETED_STATUS])) \
        .order_by(Attendee.full_name, Attendee.id)  # noqa: E712
    return attendee_query


def _hotel_dump(session):
    room_query = session.query(Room).options(
        subqueryload(Room.assignments).subqueryload(RoomAssignment.attendee).subqueryload(Attendee.hotel_requests),
        subqueryload(Room.assignments).subqueryload(RoomAssignment.attendee).subqueryload(Attendee.assigned_depts),
        subqueryload(Room.assignments).subqueryload(RoomAssignment.attendee).subqueryload(Attendee.room_assignments),
        subqueryload(Room.assignments).subqueryload(RoomAssignment.attendee).subqueryload(Attendee.shifts)
        .subqueryload(Shift.job)) \
        .order_by(Room.locked_in.desc(), Room.created)

    rooms = [_room_dict(room) for room in room_query]

    assigned = sum([r['attendees'] for r in rooms], [])
    assigned_ids = set([a['id'] for a in assigned])

    declined = []
    unassigned = []
    for attendee in _get_confirmed(session):
        if attendee.hotel_requests.nights == '':
            declined.append(_attendee_dict(attendee))
        elif attendee.id not in assigned_ids:
            unassigned.append(_attendee_dict(attendee))

    unconfirmed = []
    for attendee in _get_unconfirmed(session):
        if attendee.id not in assigned_ids:
            unconfirmed.append(_attendee_dict(attendee))

    eligible = sorted(assigned + unassigned, key=lambda a: a['name'])

    return {
        'rooms': rooms,
        'assigned': assigned,
        'unassigned': unassigned,
        'declined': declined,
        'unconfirmed': unconfirmed,
        'eligible': eligible
    }
