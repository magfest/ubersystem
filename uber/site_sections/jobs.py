from uber.common import *


def shift_dict(shift):
    return {
        'id': shift.id,
        'rating': shift.rating,
        'worked': shift.worked,
        'comment': shift.comment,
        'worked_label': shift.worked_label,
        'attendee_id': shift.attendee.id,
        'attendee_name': shift.attendee.full_name
    }


def job_dict(job, shifts=None):
    return {
        'id': job.id,
        'name': job.name,
        'slots': job.slots,
        'weight': job.weight,
        'restricted': job.restricted,
        'timespan': custom_tags.timespan.pretty(job),
        'location_label': job.location_label,
        'shifts': shifts or [shift_dict(shift) for shift in job.shifts]
    }


@all_renderable(c.PEOPLE)
class Root:
    def index(self, session, location=None, message=''):
        if location is None:
            if c.AT_THE_CON:
                raise HTTPRedirect('signups')
            else:
                location = c.JOB_LOCATION_OPTS[0][0]

        jobs = session.query(Job).filter_by(location=location).order_by(Job.name, Job.start_time).all()
        by_start = defaultdict(list)
        for job in jobs:
            if job.type == c.REGULAR:
                by_start[job.start_time_local].append(job)
        times = [c.EPOCH + timedelta(hours=i) for i in range(c.CON_LENGTH)]
        return {
            'location':  location,
            'setup':     [j for j in jobs if j.type == c.SETUP],
            'teardown':  [j for j in jobs if j.type == c.TEARDOWN],
            'checklist': session.checklist_status('creating_shifts', location),
            'times':     [(t, t + timedelta(hours=1), by_start[t]) for i, t in enumerate(times)]
        }

    def signups(self, session, location=None, message=''):
        if location is None:
            location = cherrypy.session.get('prev_location') or c.JOB_LOCATION_OPTS[0][0]
        cherrypy.session['prev_location'] = location

        jobs, shifts, attendees = session.everything(location)
        return {
            'message':   message,
            'location':  location,
            'jobs':      jobs,
            'shifts':    Shift.dump(shifts),
            'checklist': session.checklist_status('postcon_hours', location)
        }

    def everywhere(self, session, message='', show_restricted=''):
        shifts = defaultdict(list)
        for shift in session.query(Shift).options(joinedload(Shift.attendee)).all():
            shifts[shift.job_id].append(shift_dict(shift))
        return {
            'message': message,
            'show_restricted': show_restricted,
            'attendees': [{
                'id': id,
                'full_name': full_name.title()
            } for id, full_name in session.query(Attendee.id, Attendee.full_name)
                                          .filter_by(staffing=True)
                                          .order_by(Attendee.full_name).all()],
            'jobs': [job_dict(job, shifts[job.id])
                     for job in session.query(Job)
                                       .filter(Job.start_time > localized_now() - timedelta(hours=2))
                                       .filter_by(**({} if show_restricted else {'restricted': False}))
                                       .order_by(Job.start_time, Job.location).all()]
        }

    @ajax
    def assign_from_everywhere(self, session, job_id, staffer_id):
        message = session.assign(staffer_id, job_id)
        if message:
            return {'error': message}
        else:
            return job_dict(session.job(job_id))

    @ajax
    def unassign_from_everywhere(self, session, id):
        try:
            shift = session.shift(id)
            session.delete(shift)
            session.commit()
        except:
            return {'error': 'Shift was already deleted'}
        else:
            return job_dict(session.job(shift.job_id))

    @ajax
    def set_worked_from_everywhere(self, session, id, status):
        try:
            shift = session.shift(id)
            shift.worked = int(status)
            session.commit()
        except:
            return {'error': 'Unexpected error setting status'}
        else:
            return job_dict(session.job(shift.job_id))

    def staffers(self, session, location=None, message=''):
        attendee = session.admin_attendee()
        if location == 'All':
            location = None
        else:
            location = int(location or c.JOB_LOCATION_OPTS[0][0])
        jobs, shifts, attendees = session.everything(location)
        if location:
            attendees = [a for a in attendees if a.assigned_to(location)]
        hours_here = defaultdict(int)
        for shift in shifts:
            hours_here[shift.attendee] += shift.job.weighted_hours
        for attendee in attendees:
            attendee.hours_here = hours_here[attendee]
            attendee.trusted_here = attendee.trusted_in(location) if location else attendee.trusted_somewhere
        return {
            'location':           location,
            'attendees':          attendees,
            'checklist':          session.checklist_status('assigned_volunteers', location),
            'emails':             ','.join(a.email for a in attendees),
            'regular_total':      sum(j.total_hours for j in jobs if not j.restricted),
            'restricted_total':   sum(j.total_hours for j in jobs if j.restricted),
            'all_total':          sum(j.total_hours for j in jobs),
            'regular_signups':    sum(s.job.weighted_hours for s in shifts if not s.job.restricted),
            'restricted_signups': sum(s.job.weighted_hours for s in shifts if s.job.restricted),
            'all_signups':        sum(s.job.weighted_hours for s in shifts)
        }

    def form(self, session, message='', **params):
        defaults = {}
        if params['id'] == 'None' and cherrypy.request.method != 'POST':
            defaults = cherrypy.session.get('job_defaults', defaultdict(dict))[params['location']]
            params.update(defaults)

        job = session.job(params, bools=['restricted', 'extra15'],
                                  allowed=['location', 'start_time', 'type'] + list(defaults.keys()))
        if cherrypy.request.method == 'POST':
            message = check(job)
            if not message:
                session.add(job)
                if params['id'] == 'None':
                    defaults = cherrypy.session.get('job_defaults', defaultdict(dict))
                    defaults[params['location']] = {field: getattr(job, field) for field in c.JOB_DEFAULTS}
                    cherrypy.session['job_defaults'] = defaults

                raise HTTPRedirect('index?location={}#{}', job.location, job.start_time_local)

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
            'attendees': job.capable_staff_opts
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
    def assign_from_list(self, session, job_id, staffer_id):
        location = session.job(job_id).location
        message = session.assign(staffer_id, job_id)
        if message:
            raise HTTPRedirect('signups?location={}&message={}', location, message)
        else:
            raise HTTPRedirect('signups?location={}#{}', location, job_id)

    @csrf_protected
    def unassign_from_job(self, session, id):
        shift = session.shift(id)
        session.delete(shift)
        raise HTTPRedirect('staffers_by_job?id={}&message={}', shift.job_id, 'Staffer unassigned')

    @csrf_protected
    def unassign_from_list(self, session, id):
        shift = session.shift(id)
        session.delete(shift)
        raise HTTPRedirect('signups?location={}#{}', shift.job.location, shift.job_id)

    @ajax
    def set_worked(self, session, id, worked):
        try:
            shift = session.shift(id)
            shift.worked = int(worked)
            session.commit()
            return {'status_label': shift.worked_label}
        except:
            return {'error': 'an unexpected error occured'}

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
        all_jobs, all_shifts, attendees = session.everything()
        locations = {}
        for loc, name in c.JOB_LOCATION_OPTS:
            jobs = [j for j in all_jobs if j.location == loc]
            shifts = [s for s in all_shifts if s.job.location == loc]
            locations[name] = {
                'regular_total':      sum(j.total_hours for j in jobs if not j.restricted),
                'restricted_total':   sum(j.total_hours for j in jobs if j.restricted),
                'all_total':          sum(j.total_hours for j in jobs),
                'regular_signups':    sum(s.job.weighted_hours for s in shifts if not s.job.restricted),
                'restricted_signups': sum(s.job.weighted_hours for s in shifts if s.job.restricted),
                'all_signups':        sum(s.job.weighted_hours for s in shifts)
            }
        totals = [('All Departments Combined', {
            attr: sum(loc[attr] for loc in locations.values())
            for attr in locations[name].keys()
        })]
        return {'locations': totals + sorted(locations.items(), key=lambda loc: loc[1]['regular_signups'] - loc[1]['regular_total'])}

    def all_shifts(self, session):
        return {
            'depts': [(name, session.query(Job)
                                    .filter_by(location=loc)
                                    .order_by(Job.start_time, Job.name).all())
                      for loc, name in c.JOB_LOCATION_OPTS]
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
