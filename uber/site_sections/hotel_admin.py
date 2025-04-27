from datetime import timedelta

import cherrypy
from sqlalchemy.orm import subqueryload

from uber.config import c
from uber.decorators import ajax, all_renderable
from uber.errors import HTTPRedirect
from uber.models import Attendee, Room, RoomAssignment, Shift


@all_renderable()
class Root:
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
