from uber.common import *

@all_renderable(PEOPLE, angular=True)
class Root:
    def index(self):
        by_dept = defaultdict(list)
        for attendee in Attendee.objects.filter(badge_type = STAFF_BADGE).order_by('first_name', 'last_name'):
            for dept,disp in zip(attendee.assigned, attendee.assigned_display):
                by_dept[dept,disp].append(attendee)
        return {'by_dept': sorted(by_dept.items())}

    def requests(self):
        requests = HotelRequests.objects.order_by('attendee__first_name', 'attendee__last_name')
        return {
            'staffer_count': Attendee.objects.filter(badge_type = STAFF_BADGE).count(),
            'declined_count': requests.filter(nights = '').count(),
            'requests': requests.exclude(nights = '')
        }

    def hours(self):
        staffers = list(Attendee.objects.filter(badge_type = STAFF_BADGE).order_by('first_name','last_name'))
        staffers = [s for s in staffers if s.hotel_shifts_required and s.weighted_hours < 30]
        return {'staffers': staffers}

    @ajax
    def approve(self, id, approved):
        hr = HotelRequests.objects.get(id = id)
        if approved == 'approved':
            hr.approved = True
        else:
            hr.decline()
        hr.save()
        return {'nights': ' / '.join(hr.attendee.hotel_nights)}

    @csv_file
    def ordered(self, out):
        reqs = [hr for hr in HotelRequests.objects.select_related() if hr.nights]
        assigned = {ra.attendee for ra in RoomAssignment.objects.select_related()}
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

        writerow = lambda a, hr: out.writerow([a.full_name, a.email, a.phone, ' / '.join(a.hotel_nights), ' / '.join(a.assigned_display),
                                               hr.wanted_roommates, hr.unwanted_roommates, hr.special_needs])

        grouped = {frozenset(group) for group in lookup.values()}
        out.writerow(['Name','Email','Phone','Nights','Departments','Roomate Requests','Roomate Anti-Requests','Special Needs'])
        for room in Room.objects.order_by('department'):
            for i in range(3):
                out.writerow([])
            out.writerow([room.get_department_display() + ' room created by department heads for ' + room.nights_display + (' ({})'.format(room.notes) if room.notes else '')])
            for ra in room.roomassignment_set.select_related():
                writerow(ra.attendee, ra.attendee.hotel_requests)
        for group in sorted(grouped, key=len, reverse=True):
            for i in range(3):
                out.writerow([])
            for a in group:
                writerow(a, a.hotel_requests)

    @ng_renderable
    def assignments(self, department):
        if ROOMS_LOCKED_IN:
            cherrypy.response.headers['Content-Type'] = 'text/plain'
            return json.dumps({
                'message': 'Hotel rooms are currently locked in, email stops@magfest.org if you need a last-minute adjustment',
                'rooms': [room.to_dict() for room in Room.objects.filter(department=department)]
            }, indent=4)
        else:
            return {
                'department': department,
                'dump': _hotel_dump(department),
                'department_name': dict(JOB_LOC_OPTS)[int(department)]
            }

    @ajax
    def create_room(self, **params):
        params['nights'] = list(filter(bool, [params.pop(night, None) for night in NIGHT_NAMES]))
        Room.get(params).save()
        return _hotel_dump(params['department'])

    @ajax
    def edit_room(self, **params):
        params['nights'] = list(filter(bool, [params.pop(night, None) for night in NIGHT_NAMES]))
        Room.get(params).save()
        return _hotel_dump(params['department'])

    @ajax
    def delete_room(self, id):
        room = Room.objects.get(id=id)
        room.delete()
        return _hotel_dump(room.department)

    @ajax
    def assign_to_room(self, attendee_id, room_id):
        if not RoomAssignment.objects.filter(attendee_id=attendee_id):
            ra, created = RoomAssignment.objects.get_or_create(attendee_id=attendee_id, room_id=room_id)
            hr = ra.attendee.hotel_requests
            if ra.room.wednesday or ra.room.sunday:
                hr.approved = True
            else:
                hr.wednesday = hr.sunday = False
            hr.save()
        return _hotel_dump(Room.objects.get(id=room_id).department)

    @ajax
    def unassign_from_room(self, attendee_id, department):
        ra = RoomAssignment.objects.filter(attendee_id = attendee_id)
        if ra:
            ra[0].delete()
        return _hotel_dump(department)


def _attendee_dict(attendee):
    return {
        'id': attendee.id,
        'name': attendee.full_name,
        'nights': getattr(attendee.hotel_requests, 'nights_display', ''),
        'special_needs': getattr(attendee.hotel_requests, 'special_needs', ''),
        'wanted_roommates': getattr(attendee.hotel_requests, 'wanted_roommates', ''),
        'unwanted_roommates': getattr(attendee.hotel_requests, 'unwanted_roommates', ''),
        'approved': int(getattr(attendee.hotel_requests, 'approved', False)),
        'departments': attendee.assigned_display
    }

def _room_dict(room):
    return dict({
        'id': room.id,
        'notes': room.notes,
        'nights': room.nights_display,
        'department': room.department,
        'attendees': [_attendee_dict(ra.attendee) for ra in room.roomassignment_set.order_by('attendee__first_name', 'attendee__last_name').select_related()]
    }, **{
        night: getattr(room, night) for night in NIGHT_NAMES
    })

def _get_declined(department):
    return [_attendee_dict(a) for a in Attendee.objects.order_by('first_name', 'last_name')
                                                       .filter(hotelrequests__isnull=False,
                                                               hotelrequests__nights='',
                                                               assigned_depts__contains=department)]

def _get_unconfirmed(department, assigned_ids):
    return [_attendee_dict(a) for a in Attendee.objects.order_by('first_name', 'last_name')
                                                       .filter(badge_type=STAFF_BADGE,
                                                               hotelrequests__isnull=True,
                                                               assigned_depts__contains=department)
                              if a not in assigned_ids]

def _get_unassigned(department, assigned_ids):
    return [_attendee_dict(a) for a in Attendee.objects.filter(hotelrequests__isnull=False,
                                                               assigned_depts__contains=department)
                                                       .exclude(hotelrequests__nights='')
                                                       .order_by('first_name', 'last_name')
                              if a.id not in assigned_ids]

def _get_assigned_elsewhere(department):
    return [_attendee_dict(ra.attendee)
            for ra in RoomAssignment.objects.select_related()
                                            .exclude(room__department = department)
                                            .filter(attendee__assigned_depts__contains = department)]

def _hotel_dump(department):
    rooms = [_room_json(room) for room in Room.objects.filter(department = department).order_by('id')]
    assigned = sum([r['attendees'] for r in rooms], [])
    assigned_elsewhere = _get_assigned_elsewhere(department)
    assigned_ids = [a['id'] for a in assigned + assigned_elsewhere]
    return {
        'rooms': rooms,
        'assigned': assigned,
        'assigned_elsewhere': assigned_elsewhere,
        'declined': _get_declined(department),
        'unconfirmed': _get_unconfirmed(department, assigned_ids),
        'unassigned': _get_unassigned(department, assigned_ids)
    }
