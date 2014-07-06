from uber.common import *

@all_renderable(PEOPLE, angular=True)
class Root:
    def index(self, session):
        by_dept = defaultdict(list)
        for attendee in session.query(Attendee).filter_by(badge_type=STAFF_BADGE).order_by(Attendee.full_name).all():
            for dept, disp in zip(attendee.assigned_depts_ints, attendee.assigned_depts_labels):
                by_dept[dept, disp].append(attendee)
        return {'by_dept': sorted(by_dept.items())}

    def requests(self, session):
        requests = session.query(HotelRequests).join(HotelRequests.attendee).order_by(Attendee.full_name).all()
        return {
            'staffer_count': session.query(Attendee).filter_by(badge_type=STAFF_BADGE).count(),
            'declined_count': len([r for r in requests if r.nights == '']),
            'requests': [r for r in requests if r.nights != '']
        }

    def hours(self, session):
        staffers = session.query(Attendee).filter_by(badge_type=STAFF_BADGE).order_by(Attendee.full_name).all()
        staffers = [s for s in staffers if s.hotel_shifts_required and s.weighted_hours < 30]
        return {'staffers': staffers}

    @ajax
    def approve(self, session, id, approved):
        hr = session.hotel_requests(id)
        if approved == 'approved':
            hr.approved = True
        else:
            hr.decline()
        session.commit()
        return {'nights': ' / '.join(hr.attendee.hotel_nights)}

    @csv_file
    def ordered(self, out, session):
        reqs = [hr for hr in session.query(HotelRequests).options(joinedload(HotelRequests.attendee)).all() if hr.nights]
        assigned = {ra.attendee for ra in session.query(RoomAssignment).options(joinedload(RoomAssignment.attendee), joinedload(RoomAssignment.room)).all()}
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
                    except:
                        pass

        writerow = lambda a, hr: out.writerow([a.full_name, a.email, a.phone, ' / '.join(a.hotel_nights), ' / '.join(a.assigned_depts_labels),
                                               hr.wanted_roommates, hr.unwanted_roommates, hr.special_needs])

        grouped = {frozenset(group) for group in lookup.values()}
        out.writerow(['Name','Email','Phone','Nights','Departments','Roomate Requests','Roomate Anti-Requests','Special Needs'])
        # TODO: for better efficiency, a multi-level joinedload would be preferable here
        for room in session.query(Room).options(joinedload(Room.room_assignments)).order_by(Room.department).all():
            for i in range(3):
                out.writerow([])
            out.writerow([room.department_label + ' room created by department heads for ' + room.nights_display + (' ({})'.format(room.notes) if room.notes else '')])
            for ra in room.room_assignments:
                writerow(ra.attendee, ra.attendee.hotel_requests)
        for group in sorted(grouped, key=len, reverse=True):
            for i in range(3):
                out.writerow([])
            for a in group:
                writerow(a, a.hotel_requests)

    @ng_renderable
    def assignments(self, session, department):
        if ROOMS_LOCKED_IN:
            cherrypy.response.headers['Content-Type'] = 'text/plain'
            return json.dumps({
                'message': 'Hotel rooms are currently locked in, email stops@magfest.org if you need a last-minute adjustment',
                'rooms': [room.to_dict() for room in session.query(Room).filter_by(department=department).all()]
            }, indent=4, cls=serializer)
        else:
            return {
                'department': department,
                'dump': _hotel_dump(session, department),
                'department_name': dict(JOB_LOC_OPTS)[int(department)]
            }

    @ajax
    def create_room(self, session, **params):
        params['nights'] = list(filter(bool, [params.pop(night, None) for night in NIGHT_NAMES]))
        session.add(session.room(params))
        session.commit()
        return _hotel_dump(session, params['department'])

    @ajax
    def edit_room(self, session, **params):
        params['nights'] = list(filter(bool, [params.pop(night, None) for night in NIGHT_NAMES]))
        session.room(params)
        session.commit()
        return _hotel_dump(session, params['department'])

    @ajax
    def delete_room(self, id):
        session.delete(session.room(id))
        session.commit()
        return _hotel_dump(session, room.department)

    # TODO: default approval room nights need to be configurable
    @ajax
    def assign_to_room(self, session, attendee_id, room_id):
        if not session.query(RoomAssignment).filter_by(attendee_id=attendee_id).all():
            ra = RoomAssignment(attendee_id=attendee_id, room_id=room_id)
            session.add(ra)
            hr = ra.attendee.hotel_requests
            if ra.room.wednesday or ra.room.sunday:
                hr.approved = True
            else:
                hr.wednesday = hr.sunday = False
            session.commit()
        return _hotel_dump(session, session.room(room_id).department)

    @ajax
    def unassign_from_room(self, session, attendee_id, department):
        for ra in RoomAssignment.objects.filter(attendee_id=attendee_id).all():
            session.delete(ra)
            session.commit()
        return _hotel_dump(session, department)


def _attendee_dict(attendee):
    return {
        'id': attendee.id,
        'name': attendee.full_name,
        'nights': getattr(attendee.hotel_requests, 'nights_display', ''),
        'special_needs': getattr(attendee.hotel_requests, 'special_needs', ''),
        'wanted_roommates': getattr(attendee.hotel_requests, 'wanted_roommates', ''),
        'unwanted_roommates': getattr(attendee.hotel_requests, 'unwanted_roommates', ''),
        'approved': int(getattr(attendee.hotel_requests, 'approved', False)),
        'departments': ' / '.join(attendee.assigned_depts_labels)
    }

def _room_dict(session, room):
    return dict({
        'id': room.id,
        'notes': room.notes,
        'nights': room.nights_display,
        'department': room.department,
        'attendees': [_attendee_dict(ra.attendee) for ra in sorted(room.room_assignments, key=lambda ra: ra.attendee.full_name)]
    }, **{
        night: getattr(room, night) for night in NIGHT_NAMES
    })

def _get_declined(session, department):
    return [_attendee_dict(a) for a in session.query(Attendee)
                                              .order_by(Attendee.full_name)
                                              .join(Attendee.hotel_requests)
                                              .filter(hotelrequests__isnull=False,
                                                      hotelrequests__nights='',
                                                      assigned_depts__contains=department).all()]

def _get_unconfirmed(session, department, assigned_ids):
    return [_attendee_dict(a) for a in session.query(Attendee)
                                              .order_by(Attendee.full_name)
                                              .filter(Attendee.badge_type == STAFF_BADGE,
                                                      Attendee.hotel_requests == None,
                                                      Attendee.assigned_depts.like('%{}%'.format(department))).all()
                              if a not in assigned_ids]

def _get_unassigned(session, department, assigned_ids):
    return [_attendee_dict(a) for a in session.query(Attendee)
                                              .order_by(Attendee.full_name)
                                              .join(Attendee.hotel_requests)
                                              .filter(Attendee.hotel_requests != None,
                                                      Attendee.assigned_depts.like('%{}%'.format(department)),
                                                      HotelRequests.nights != '').all()
                              if a.id not in assigned_ids]

def _get_assigned_elsewhere(session, department):
    return [_attendee_dict(ra.attendee)
            for ra in session.query(RoomAssignment)
                             .options(joinedload(RoomAssignment.attendee), joinedload(RoomAssignment.room))
                             .join(RoomAssignment.room, RoomAssignment.attendee)
                             .filter(Room.department != department,
                                     Attendee.assigned_depts.like('%{}%'.format(department))).all()]

def _hotel_dump(session, department):
    rooms = [_room_json(session, room) for room in session.query(Room).filter_by(department=department).order_by(Room.created).all()]
    assigned = sum([r['attendees'] for r in rooms], [])
    assigned_elsewhere = _get_assigned_elsewhere(session, department)
    assigned_ids = [a['id'] for a in assigned + assigned_elsewhere]
    return {
        'rooms': rooms,
        'assigned': assigned,
        'assigned_elsewhere': assigned_elsewhere,
        'declined': _get_declined(session, department),
        'unconfirmed': _get_unconfirmed(session, department, assigned_ids),
        'unassigned': _get_unassigned(session, department, assigned_ids)
    }
