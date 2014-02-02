from uber.common import *

groups, attendees = {}, {}
with open(join(MODULE_ROOT, 'tests', 'dump.json')) as f:
    dump = json.load(f)

offset_from = EPOCH
def offset_to_datetime(offset):
    return offset_from + timedelta(hours=offset)

def import_groups():
    for g in dump['groups']:
        groups[g['secret_id']], _ = Group.objects.get_or_create(**g)

def import_attendees():
    for a in dump['attendees']:
        a['group'] = groups.get(a.pop('group_id', None))
        attendees[a['secret_id']], _ = Attendee.objects.get_or_create(**a)

    for f in dump['food']:
        f['attendee'] = attendees[f.pop('attendee_id')]
        FoodRestrictions.objects.get_or_create(**f)

    for h in dump['hotel']:
        h['attendee'] = attendees[h.pop('attendee_id')]
        HotelRequests.objects.get_or_create(**h)

def import_events():
    event_locs, _ = zip(*EVENT_LOC_OPTS)
    for e in dump['events']:
        if e['location'] in event_locs:
            e['start_time'] = offset_to_datetime(e['start_time'])
            panelists = e.pop('panelists')
            event = Event.objects.get_or_create(**e)
            for secret_id in panelists:
                AssignedPanelist.objects.get_or_create(event=event, attendee=attendees[secret_id])

def import_jobs():
    job_locs, _ = zip(*JOB_LOC_OPTS)
    for j in dump['jobs']:
        if j['location'] in job_locs:
            j['start_time'] = offset_to_datetime(j['start_time'])
            shifts = j.pop('shifts')
            job, _ = Job.objects.get_or_create(**j)
            for secret_id in shifts:
                Shift.objects.get_or_create(job=job, attendee=attendees[secret_id])

def import_everything():
    import_groups()
    import_attendees()
    import_events()
    import_jobs()

if __name__ == '__main__':
    import_everything()
