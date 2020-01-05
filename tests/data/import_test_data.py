import json
import os
import random
import re
import uuid
from datetime import timedelta
from os.path import join

from sideboard.lib import entry_point

from uber.config import c, create_namespace_uuid
from uber.models import AssignedPanelist, Attendee, Department, Event, FoodRestrictions, Group, HotelRequests, Job
from uber.models import Session, Shift


DEPT_HEAD_RIBBON_STR = str(c.DEPT_HEAD_RIBBON)
DEPARTMENT_NAMESPACE = create_namespace_uuid('Department')


def _trusted_dept_role_id(department_id):
    return str(uuid.uuid5(DEPARTMENT_NAMESPACE, department_id))


def _dept_membership_id(department_id, attendee_id):
    return str(uuid.uuid5(DEPARTMENT_NAMESPACE, department_id + attendee_id))


def _dept_id_from_location(location):
    department_id = '{:07x}'.format(location) + str(uuid.uuid5(DEPARTMENT_NAMESPACE, str(location)))[7:]
    return department_id


def existing_location_from_dept_id(department_id):
    location = int(department_id[:7], 16)
    if job_location_to_department_id.get(location):
        return location
    return None


def single_dept_id_from_existing_locations(locations):
    for location in str(locations).split(','):
        if location:
            location = int(location)
            department_id = job_location_to_department_id.get(location)
            if department_id:
                return department_id
    return None


def all_dept_ids_from_existing_locations(locations):
    dept_ids = []
    for location in str(locations).split(','):
        if location:
            location = int(location)
            department_id = job_location_to_department_id.get(location)
            if department_id:
                dept_ids.append(department_id)
    return dept_ids


job_location_to_department_id = {i: _dept_id_from_location(i) for i in c.JOB_LOCATIONS.keys()}
job_interests_to_department_id = {
    i: job_location_to_department_id[i] for i in c.JOB_INTERESTS.keys() if i in job_location_to_department_id}


TEST_DATA_FILE = join(os.path.dirname(__file__), 'test_data.json')
words = []
offset_from = c.EPOCH
dump, groups, attendees = {}, {}, {}
skipped_attendees = []


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
        g['cost'] = int(float(g.pop('amount_owed')))
        g['name'] = random_group_name()
        del g['amount_paid']
        groups[secret_id] = Group(**g)
        session.add(groups[secret_id])


def import_attendees(session):
    for a in dump['attendees']:
        a['group'] = groups.get(a.pop('group_id', None))
        secret_id = a.pop('secret_id')
        a['assigned_depts_ids'] = all_dept_ids_from_existing_locations(a.pop('assigned_depts', ''))
        a['requested_depts_ids'] = all_dept_ids_from_existing_locations(a.pop('requested_depts', ''))
        del a['amount_paid']
        del a['amount_refunded']
        if a['badge_type'] == 67489953:  # Supporter is no longer a badge type
            skipped_attendees.append(secret_id)
            continue
        attendees[secret_id] = Attendee(**a)
        session.add(attendees[secret_id])

    for f in dump['food']:
        attendee_id = f.pop('attendee_id')
        if attendee_id in skipped_attendees:
            continue
        f['attendee'] = attendees[attendee_id]
        f.setdefault('sandwich_pref', str(c.PEANUT_BUTTER))  # sandwich_pref didn't exist when the dump was taken
        session.add(FoodRestrictions(**f))

    for h in dump['hotel']:
        attendee_id = h.pop('attendee_id')
        if attendee_id in skipped_attendees:
            continue
        h['attendee'] = attendees[attendee_id]
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
    depts_known = []
    for j in dump['jobs']:
        if j['location'] in job_locs:
            j.pop('restricted', '')
            location = j.pop('location', '')
            dept_id = _dept_id_from_location(location)
            j['department_id'] = dept_id
            if dept_id not in depts_known and not session.query(Department).filter(Department.id == dept_id).count():
                session.add(Department(id=dept_id, name=location))
                depts_known.append(dept_id)
            j['start_time'] = offset_to_datetime(j['start_time'])
            shifts = j.pop('shifts')
            job = Job(**j)
            session.add(job)
            for secret_id in shifts:
                if secret_id not in skipped_attendees:
                    job.shifts.append(Shift(attendee=attendees[secret_id]))


@entry_point
def import_uber_test_data(test_data_file):
    if not c.JOB_LOCATION_OPTS:
        print("JOB_LOCATION_OPTS is empty! "
        "Try copying the [[job_location]] section from test-defaults.ini to your development.ini.")
        exit(1)

    with open(test_data_file) as f:
        global dump
        dump = json.load(f)

    Session.initialize_db(initialize=True)
    with Session() as session:
        import_groups(session)
        import_attendees(session)
        import_events(session)
        import_jobs(session)


if __name__ == '__main__':
    import_uber_test_data(TEST_DATA_FILE)
