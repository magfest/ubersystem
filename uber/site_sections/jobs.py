from uber.common import *


def job_dict(job, shifts=None):
    return {
        'id': job.id,
        'name': job.name,
        'slots': job.slots,
        'weight': job.weight,
        'restricted': job.restricted,
        'timespan': custom_tags.timespan.pretty(job),
        'location_label': job.location_label,
        'shifts': [{
            'id': shift.id,
            'rating': shift.rating,
            'worked': shift.worked,
            'comment': shift.comment,
            'worked_label': shift.worked_label,
            'attendee_id': shift.attendee.id,
            'attendee_name': shift.attendee.full_name,
            'attendee_badge': shift.attendee.badge_num
        } for shift in job.shifts]
    }


def update_counts(job, counts):
    counts['all_total'] += job.total_hours
    counts['all_signups'] += job.weighted_hours * len(job.shifts)
    if job.restricted:
        counts['restricted_total'] += job.total_hours
        counts['restricted_signups'] += job.weighted_hours * len(job.shifts)
    else:
        counts['regular_total'] += job.total_hours
        counts['regular_signups'] += job.weighted_hours * len(job.shifts)


@all_renderable(c.PEOPLE)
class Root:

    def index(self, session, location=None, message='', time=None):
        if not location:
            if c.AT_THE_CON:
                raise HTTPRedirect('signups')
            else:
                location = c.JOB_LOCATION_OPTS[0][0]

        location = None if location == 'All' else location
        jobs = session.jobs(location).all()
        by_start = defaultdict(list)
        for job in jobs:
            if job.type == c.REGULAR:
                by_start[job.start_time_local].append(job)
        times = [c.EPOCH + timedelta(hours=i) for i in range(c.CON_LENGTH)]
        return {
            'location':  location,
            'setup':     [j for j in jobs if j.type == c.SETUP],
            'teardown':  [j for j in jobs if j.type == c.TEARDOWN],
            'normal': [j for j in jobs if j.type != c.SETUP and j.type != c.TEARDOWN],
            'checklist': location and session.checklist_status('creating_shifts', location),
            'times':     [(t, t + timedelta(hours=1), by_start[t]) for i, t in enumerate(times)],
            'jobs': jobs
        }

    def signups(self, session, location=None, message=''):
        if not location:
            location = cherrypy.session.get('prev_location') or c.JOB_LOCATION_OPTS[0][0]
        location = None if location == 'All' else location
        cherrypy.session['prev_location'] = location

        return {
            'message':   message,
            'location':  location,
            'attendees': session.staffers_for_dropdown(),
            'jobs':      [job_dict(job) for job in session.jobs(location)],
            'checklist': location and session.checklist_status('postcon_hours', location)
        }

    def everywhere(self, session, message='', show_restricted=''):
        return {
            'message': message,
            'show_restricted': show_restricted,
            'attendees': session.staffers_for_dropdown(),
            'jobs': [job_dict(job) for job in session.jobs()
                                                     .filter(Job.start_time > localized_now() - timedelta(hours=2))
                                                     .filter_by(**{} if show_restricted else {'restricted': False})]
        }

    def staffers(self, session, location=None, message=''):
        location = None if location == 'All' else int(location or c.JOB_LOCATION_OPTS[0][0])
        attendees = session.staffers().filter(*[Attendee.assigned_depts.contains(str(location))] if location else []).all()
        for attendee in attendees:
            attendee.trusted_here = attendee.trusted_in(location) if location else attendee.trusted_somewhere
            attendee.hours_here = sum(shift.job.weighted_hours for shift in attendee.shifts if shift.job.location == location) if location else attendee.weighted_hours

        counts = defaultdict(int)
        for job in session.jobs(location):
            update_counts(job, counts)

        return {
            'counts':    counts,
            'location':  location,
            'attendees': attendees,
            'emails':    ','.join(a.email for a in attendees),
            'checklist': session.checklist_status('assigned_volunteers', location)
        }

    def form(self, session, message='', **params):
        defaults = {}
        if params.get('id') == 'None' and cherrypy.request.method != 'POST':
            defaults = cherrypy.session.get('job_defaults', defaultdict(dict))[params['location']]
            params.update(defaults)

        job = session.job(params, bools=['restricted', 'extra15'],
                                  allowed=['location', 'start_time', 'type'] + list(defaults.keys()))
        if cherrypy.request.method == 'POST':
            message = check(job)
            if not message:
                session.add(job)
                if params.get('id') == 'None':
                    defaults = cherrypy.session.get('job_defaults', defaultdict(dict))
                    defaults[params['location']] = {field: getattr(job, field) for field in c.JOB_DEFAULTS}
                    cherrypy.session['job_defaults'] = defaults
                tgt_start_time = str(job.start_time_local).replace(" ", "T")
                raise HTTPRedirect('index?location=' + str(job.location) + '&time=' + tgt_start_time)

        if 'start_time' in params and 'type' not in params:
            local_start_time = c.EVENT_TIMEZONE.localize(datetime.strptime(params['start_time'], "%Y-%m-%d %H:%M:%S"))
            if c.EPOCH <= local_start_time < c.ESCHATON:
                job.type = c.REGULAR
            else:
                job.type = c.SETUP if local_start_time < c.EPOCH else c.TEARDOWN

        return {
            'job':      job,
            'message':  message,
            'defaults': 'defaults' in locals() and defaults
        }

    def staffers_by_job(self, session, id, message=''):
        job = session.job(id)
        return {
            'job':       job,
            'message':   message,
            'attendees': job.capable_volunteers_opts
        }

    @csrf_protected
    def delete(self, session, id):
        job = session.job(id)
        for shift in job.shifts:
            session.delete(shift)
        session.delete(job)
        raise HTTPRedirect('index?location={}#{}', job.location, job.start_time)

    @csrf_protected
    def assign_from_job(self, session, job_id, staffer_id):
        message = session.assign(staffer_id, job_id) or 'Staffer assigned to shift'
        raise HTTPRedirect('staffers_by_job?id={}&message={}', job_id, message)

    @csrf_protected
    def unassign_from_job(self, session, id):
        shift = session.shift(id)
        session.delete(shift)
        raise HTTPRedirect('staffers_by_job?id={}&message={}', shift.job_id, 'Staffer unassigned')

    @ajax
    def assign(self, session, job_id, staffer_id):
        message = session.assign(staffer_id, job_id)
        if message:
            return {'error': message}
        else:
            return job_dict(session.job(job_id))

    @ajax
    def unassign(self, session, id):
        try:
            shift = session.shift(id)
            session.delete(shift)
            session.commit()
        except:
            return {'error': 'Shift was already deleted'}
        else:
            return job_dict(session.job(shift.job_id))

    @ajax
    def set_worked(self, session, id, status):
        try:
            shift = session.shift(id)
            shift.worked = int(status)
            session.commit()
        except:
            return {'error': 'Unexpected error setting status'}
        else:
            return job_dict(session.job(shift.job_id))

    @csrf_protected
    def undo_worked(self, session, id):
        shift = session.shift(id)
        shift.worked = c.SHIFT_UNMARKED
        raise HTTPRedirect(cherrypy.request.headers['Referer'])

    @ajax
    def rate(self, session, shift_id, rating, comment=''):
        shift = session.shift(shift_id)
        shift.rating, shift.comment = int(rating), comment
        session.commit()
        return {}

    def summary(self, session):
        locations = defaultdict(lambda: defaultdict(int))
        for job in session.jobs():
            update_counts(job, locations[job.location_label])
            update_counts(job, locations['All Departments Combined'])

        return {'locations': sorted(locations.items(), key=lambda loc: loc[1]['regular_signups'] - loc[1]['regular_total'])}

    def all_shifts(self, session):
        jobs = defaultdict(list)
        for job in session.jobs():
            jobs[job.location].append(job)
        return {
            'depts': [(name, jobs[loc]) for loc, name in c.JOB_LOCATION_OPTS]
        }

    def add_volunteers_by_dept(self, session, message='', location=None):
        location = location or c.JOB_LOCATION_OPTS[0][0]
        return {
            'message': message,
            'location': location,
            'not_already_here': [
                (a.id, a.full_name)
                for a in session.query(Attendee)
                                .filter(Attendee.email != '',
                                         ~Attendee.assigned_depts.contains(str(location)))
                                .order_by(Attendee.full_name).all()
            ]
        }
