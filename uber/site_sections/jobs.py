from uber.common import *


def job_dict(job, shifts=None):
    return {
        'id': job.id,
        'name': job.name,
        'slots': job.slots,
        'weight': job.weight,
        'restricted': job.restricted,
        'required_roles_ids': job.required_roles_ids,
        'timespan': job.timespan(),
        'department_id': job.department_id,
        'department_name': job.department_name,
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

    @department_id_adapter
    def index(self, session, department_id=None, message='', time=None):
        if not department_id:
            if c.AT_THE_CON:
                raise HTTPRedirect('signups')
            else:
                department_id = c.DEFAULT_DEPARTMENT_ID

        department_id = None if department_id == 'All' else department_id
        department = session.query(Department).get(department_id) if department_id else None
        jobs = session.jobs(department_id).all()
        by_start = defaultdict(list)
        for job in jobs:
            if job.type == c.REGULAR:
                by_start[job.start_time_local].append(job)
        times = [c.EPOCH + timedelta(hours=i) for i in range(c.CON_LENGTH)]
        return {
            'department_id': department_id,
            'department': department,
            'setup': [j for j in jobs if j.type == c.SETUP],
            'teardown': [j for j in jobs if j.type == c.TEARDOWN],
            'normal': [j for j in jobs if j.type != c.SETUP and j.type != c.TEARDOWN],
            'checklist': department_id and session.checklist_status('creating_shifts', department_id),
            'times': [(t, t + timedelta(hours=1), by_start[t]) for i, t in enumerate(times)],
            'jobs': jobs
        }

    @department_id_adapter
    def signups(self, session, department_id=None, message=''):
        if not department_id:
            department_id = cherrypy.session.get('prev_department_id') or c.DEFAULT_DEPARTMENT_ID
        department_id = None if department_id == 'All' else department_id
        cherrypy.session['prev_department_id'] = department_id

        return {
            'message': message,
            'department_id': department_id,
            'attendees': session.staffers_for_dropdown(),
            'jobs': [job_dict(job) for job in session.jobs(department_id)],
            'checklist': department_id and session.checklist_status('postcon_hours', department_id)
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

    @department_id_adapter
    def staffers(self, session, department_id=None, message=''):
        if not department_id:
            department_id = cherrypy.session.get('prev_department_id') or c.DEFAULT_DEPARTMENT_ID
        department_id = None if department_id == 'All' else department_id

        if department_id:
            department = session.query(Department).filter_by(id=department_id).first()
            if not department:
                department_id = None

        dept_filter = [] if not department_id \
            else [Attendee.dept_memberships.any(department_id=department_id)]
        attendees = session.staffers().filter(*dept_filter).all()
        for attendee in attendees:
            attendee.is_dept_head_here = attendee.is_dept_head_of(department_id) if department_id else attendee.is_dept_head
            attendee.trusted_here = attendee.trusted_in(department_id) if department_id else attendee.has_role_somewhere
            attendee.hours_here = attendee.weighted_hours_in(department_id)

        counts = defaultdict(int)
        for job in session.jobs(department_id):
            update_counts(job, counts)

        return {
            'counts': counts,
            'department_id': department_id,
            'attendees': attendees,
            'emails': ','.join(a.email for a in attendees),
            'checklist': session.checklist_status('assigned_volunteers', department_id)
        }

    def form(self, session, message='', **params):
        defaults = {}
        if params.get('id') == 'None' and cherrypy.request.method != 'POST':
            defaults = cherrypy.session.get('job_defaults', defaultdict(dict))[params['department_id']]
            params.update(defaults)

        job = session.job(params, bools=['extra15'],
                                  allowed=['department_id', 'start_time', 'type'] + list(defaults.keys()))
        if cherrypy.request.method == 'POST':
            message = check(job)
            if not message:
                session.add(job)
                if params.get('id') == 'None':
                    defaults = cherrypy.session.get('job_defaults', defaultdict(dict))
                    defaults[params['department_id']] = {field: getattr(job, field) for field in c.JOB_DEFAULTS}
                    cherrypy.session['job_defaults'] = defaults
                tgt_start_time = str(job.start_time_local).replace(" ", "T")
                raise HTTPRedirect('index?department_id={}&time={}', job.department_id, tgt_start_time)

        if 'start_time' in params and 'type' not in params:
            local_start_time = c.EVENT_TIMEZONE.localize(datetime.strptime(params['start_time'], "%Y-%m-%d %H:%M:%S"))
            if c.EPOCH <= local_start_time < c.ESCHATON:
                job.type = c.REGULAR
            else:
                job.type = c.SETUP if local_start_time < c.EPOCH else c.TEARDOWN

        dept_roles = defaultdict(list)
        for d in session.query(DeptRole):
            dept_roles[d.department_id].append((d.id, d.name, d.description))

        return {
            'job': job,
            'message': message,
            'dept_roles': dept_roles,
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
        raise HTTPRedirect('index?department_id={}#{}', job.department_id, job.start_time)

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

    @ajax
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
        departments = defaultdict(lambda: defaultdict(int))
        for job in session.jobs().options(subqueryload(Job.department)):
            update_counts(job, departments[job.department_name])
            update_counts(job, departments['All Departments Combined'])

        return {'departments': sorted(departments.items(), key=lambda d: d[1]['regular_signups'] - d[1]['regular_total'])}

    def all_shifts(self, session):
        departments = session.query(Department).options(
            subqueryload(Department.jobs)).order_by(Department.name)
        return {
            'depts': [(d.name, d.jobs) for d in departments]
        }

    @department_id_adapter
    def add_volunteers_by_dept(self, session, message='', department_id=None):
        department_id = department_id or c.DEFAULT_DEPARTMENT_ID
        return {
            'message': message,
            'department_id': department_id,
            'not_already_here': [
                (a.id, a.full_name)
                for a in session.query(Attendee)
                                .filter(Attendee.email != '',
                                         ~Attendee.dept_memberships.any(department_id=department_id))
                                .order_by(Attendee.full_name).all()
            ]
        }
