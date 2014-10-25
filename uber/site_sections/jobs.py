from uber.common import *

@all_renderable(PEOPLE)
class Root:
    def index(self, session, location=None, message=''):
        if location is None:
            if AT_THE_CON:
                raise HTTPRedirect('signups')
            else:
                location = JOB_LOCATION_OPTS[0][0]

        jobs, shifts, attendees = session.everything(location)
        by_start = defaultdict(list)
        for job in jobs:
            by_start[job.start_time_local].append(job)
        times = [EPOCH + timedelta(hours=i) for i in range(CON_LENGTH)]
        return {
            'location': location,
            'times':    [(t, t + timedelta(hours=1), by_start[t]) for i, t in enumerate(times)]
        }

    def signups(self, session, location=None, message=''):
        if location is None:
            location = cherrypy.session.get('prev_location') or JOB_LOCATION_OPTS[0][0]
        cherrypy.session['prev_location'] = location

        jobs, shifts, attendees = session.everything(location)
        return {
            'location': location,
            'jobs':     jobs,
            'shifts':   Shift.dump(shifts)
        }

    def everywhere(self, session, message='', show_restricted=''):
        jobs, shifts, attendees = session.everything()
        return {
            'message':   message,
            'attendees': attendees,
            'shifts':    Shift.dump(shifts),
            'show_restricted': show_restricted,
            'jobs':      [job for job in jobs if (show_restricted or not job.restricted)
                                             and job.location != MOPS  # TODO: make this configurable
                                             and localized_now() < job.start_time + timedelta(hours = job.duration)]
        }

    def staffers(self, session, location=None, message=''):
        attendee = session.admin_attendee()
        location = int(location or JOB_LOCATION_OPTS[0][0])
        jobs, shifts, attendees = session.everything(location)
        attendees = [a for a in attendees if int(location) in a.assigned_depts_ints]
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
                                  allowed=['location', 'start_time'] + list(defaults.keys()))
        if cherrypy.request.method == 'POST':
            message = check(job)
            if not message:
                session.add(job)
                if params['id'] == 'None':
                    defaults = cherrypy.session.get('job_defaults', defaultdict(dict))
                    defaults[params['location']] = {field: getattr(job,field) for field in JOB_DEFAULTS}
                    cherrypy.session['job_defaults'] = defaults

                raise HTTPRedirect('index?location={}#{}', job.location, job.start_time)

        return {
            'job':      job,
            'message':  message,
            'defaults': 'defaults' in locals() and defaults
        }

    def staffers_by_job(self, session, id, message = ''):
        jobs, shifts, attendees = session.everything()
        [job] = [job for job in jobs if job.id == id]
        job._all_staffers = attendees
        return {
            'job':     job,
            'message': message
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
    def assign_from_everywhere(self, session, job_id, staffer_id):
        message = session.assign(staffer_id, job_id) or 'Staffer assigned to shift'
        raise HTTPRedirect('everywhere?message={}#{}', message, job_id)

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

    @csrf_protected
    def unassign_from_everywhere(self, session, id):
        shift = session.shift(id)
        session.delete(shift)
        raise HTTPRedirect('everywhere?#{}', shift.job_id)

    # TODO: @ajax calls should probably just be objects all the time
    @ajax
    def set_worked(self, session, id, worked):
        try:
            shift = session.shift(id)
            shift.worked = int(worked)
            session.commit()
            return shift.worked_label
        except:
            return 'an unexpected error occured'

    @csrf_protected
    def undo_worked(self, session, id):
        shift = session.shift(id)
        shift.worked = SHIFT_UNMARKED
        raise HTTPRedirect(cherrypy.request.headers['Referer'])

    @ajax
    def rate(self, session, shift_id, rating, comment = ''):
        shift = session.shift(shift_id)
        shift.rating, shift.comment = int(rating), comment
        session.commit()
        return {}

    def summary(self):
        all_jobs, all_shifts, attendees = session.everything()
        locations = {}
        for loc, name in JOB_LOCATION_OPTS:
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
        return {'locations': sorted(locations.items(), key = lambda loc: loc[1]['regular_signups'] - loc[1]['regular_total'])}

    # TODO: fix this to work with SQLAlchemy
    @csv_file
    def all_shifts(self, out):
        for loc,name in JOB_LOCATION_OPTS:
            out.writerow([name])
            for shift in session.Shift.objects.filter(job__location = loc).order_by('job__start_time','job__name').select_related():
                out.writerow([shift.job.start_time.strftime('%I%p %a').lstrip('0'),
                              '{} hours'.format(shift.job.real_duration),
                              shift.job.name,
                              shift.attendee.full_name,
                              'Circle One: worked / unworked',
                              'Comments:'])
            out.writerow([])
