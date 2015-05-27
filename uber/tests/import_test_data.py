from uber.common import *

words = []
offset_from = c.EPOCH

groups, attendees = {}, {}
with open(join(c.MODULE_ROOT, 'tests', 'test_data.json')) as f:
    dump = json.load(f)


def offset_to_datetime(offset):
    return offset_from + timedelta(hours=offset)


def random_group_name():
    if not words:
        with open('/usr/share/dict/words') as f:
            words[:] = [s.strip() for s in f if len(s) > 3 and re.match('^[a-z]+$', s)]
    return ' '.join(random.choice(words).title() for i in range(2))


def import_groups(session):
    for g in dump['groups']:
        secret_id = g.pop('secret_id')
        g['cost'] = g.pop('amount_owed')
        g['name'] = random_group_name()
        groups[secret_id] = Group(**g)
        session.add(groups[secret_id])


def import_attendees(session):
    for a in dump['attendees']:
        a['group'] = groups.get(a.pop('group_id', None))
        secret_id = a.pop('secret_id')
        attendees[secret_id] = Attendee(**a)
        session.add(attendees[secret_id])

    for f in dump['food']:
        f['attendee'] = attendees[f.pop('attendee_id')]
        f.setdefault('sandwich_pref', PBJ)  # sandwich_pref didn't exist when the dump was taken
        session.add(FoodRestrictions(**f))

    for h in dump['hotel']:
        h['attendee'] = attendees[h.pop('attendee_id')]
        session.add(HotelRequests(**h))


def import_events(session):
    event_locs, _ = zip(*c.EVENT_LOCATION_OPTS)
    for e in dump['events']:
        if e['location'] in event_locs:
            e['start_time'] = offset_to_datetime(e['start_time'])
            panelists = e.pop('panelists')
            event = Event(**e)
            session.add(event)
            for secret_id in panelists:
                session.add(AssignedPanelist(event=event, attendee=attendees[secret_id]))


def import_jobs(session):
    job_locs, _ = zip(*c.JOB_LOCATION_OPTS)
    for j in dump['jobs']:
        if j['location'] in job_locs:
            j['start_time'] = offset_to_datetime(j['start_time'])
            shifts = j.pop('shifts')
            job = Job(**j)
            session.add(job)
            for secret_id in shifts:
                job.shifts.append(Shift(attendee=attendees[secret_id]))


@entry_point
def import_uber_test_data():
    with Session() as session:
        import_groups(session)
        import_attendees(session)
        import_events(session)
        import_jobs(session)

if __name__ == '__main__':
    import_uber_test_data()
