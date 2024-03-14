from datetime import timedelta

import cherrypy
from sqlalchemy.orm import subqueryload

from uber.config import c
from uber.decorators import ajax, all_renderable
from uber.errors import HTTPRedirect
from uber.models import Attendee, Room, RoomAssignment, Shift


@all_renderable()
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
        raise HTTPRedirect('../staffing/hotel')

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

    def mark_hotel_eligible(self, session, id):
        """
        Force mark a non-staffer as eligible for hotel space.
        This is outside the normal workflow, used for when we have a staffer
        that only has an attendee badge for some reason, and we want to mark
        them as being OK to crash in a room.
        """
        attendee = session.attendee(id)
        attendee.hotel_eligible = True
        session.commit()
        return '{} has now been overridden as being hotel eligible'.format(
            attendee.full_name)


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
            Attendee.hotel_requests != None,  # noqa: E711
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
            Attendee.hotel_eligible == True,  # noqa: E712
            Attendee.hotel_requests == None,  # noqa: E711
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
