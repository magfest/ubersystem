from collections import defaultdict
from datetime import datetime, timedelta

import cherrypy
from sqlalchemy import select
from sqlalchemy.orm import subqueryload

from uber.config import c
from uber.decorators import ajax, all_renderable, csrf_protected, department_id_adapter, \
    check_can_edit_dept, requires_shifts_admin
from uber.errors import HTTPRedirect
from uber.models import Attendee, Department, Job
from uber.utils import check, localized_now, redirect_to_allowed_dept


def job_dict(job, shifts=None):
    return {
        'id': job.id,
        'name': job.name,
        'slots': job.slots,
        'weight': job.weight,
        'restricted': job.restricted,
        'visibility': job.visibility,
        'is_public': job.is_public,
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


@all_renderable()
class Root:
    @department_id_adapter
    @requires_shifts_admin
    def index(self, session, department_id=None, message='', time=None):
        redirect_to_allowed_dept(session, department_id, 'index')

        if department_id == 'None':
            department_id = ''
        elif department_id == 'All':
            department_id = None

        jobs = []

        initial_date = max(datetime.now(c.EVENT_TIMEZONE), c.SHIFTS_START_DAY)
        if time:
            initial_date = max(initial_date, datetime.strptime(time, "%Y-%m-%dT%H:%M:%S%z"))

        department = session.query(Department).get(department_id) if department_id else None
        by_start = defaultdict(list)
        times = [c.EPOCH + timedelta(hours=i) for i in range(c.CON_LENGTH)]

        if department_id != '':
            jobs = session.jobs(department_id).all()
            for job in jobs:
                if job.type == c.REGULAR:
                    by_start[job.start_time_local].append(job)

        try:
            checklist = session.checklist_status('creating_shifts', department_id)
        except ValueError:
            checklist = {'conf': None, 'relevant': False, 'completed': None}

        return {
            'department_id': 'All' if department_id is None else department_id,
            'department': department,
            'setup': [j for j in jobs if j.type == c.SETUP],
            'teardown': [j for j in jobs if j.type == c.TEARDOWN],
            'normal': [j for j in jobs if j.type != c.SETUP and j.type != c.TEARDOWN],
            'checklist': department_id and checklist,
            'times': [(t, t + timedelta(hours=1), by_start[t]) for i, t in enumerate(times)],
            'jobs': jobs,
            'message': message,
            'initial_date': initial_date,
        }

    @department_id_adapter
    @requires_shifts_admin
    def signups(self, session, department_id=None, message='', toggle_filter=''):
        if not toggle_filter:
            redirect_to_allowed_dept(session, department_id, 'signups')

        if department_id == 'None':
            department_id = ''
        elif department_id == 'All':
            department_id = None

        cherrypy.session['prev_department_id'] = department_id

        for filter in ['signups_show_past_shifts', 'signups_show_restricted',
                       'signups_show_nonpublic', 'signups_show_filled_shifts']:
            cherrypy.session.setdefault(filter, True)

        if toggle_filter:
            cherrypy.session[toggle_filter] = not cherrypy.session.get(toggle_filter)

        show_past_shifts = cherrypy.session.get('signups_show_past_shifts')
        show_restricted = cherrypy.session.get('signups_show_restricted')
        show_nonpublic = cherrypy.session.get('signups_show_nonpublic')

        jobs = []

        if department_id != '':
            job_filters = [Job.department_id == department_id] if department_id else []
            if not show_past_shifts:
                job_filters.append(Job.start_time > localized_now() - timedelta(hours=2))
            if not show_restricted:
                job_filters.append(Job.restricted == False)  # noqa: E712
            if not show_nonpublic:
                job_filters.append(Job.department_id.in_(
                    select([Department.id]).where(
                        Department.solicits_volunteers == True)))  # noqa: E712

            jobs = session.jobs().filter(*job_filters)

        try:
            checklist = session.checklist_status('postcon_hours', department_id)
        except ValueError:
            checklist = {'conf': None, 'relevant': False, 'completed': None}

        return {
            'message': message,
            'department_id': 'All' if department_id is None else department_id,
            'show_past_shifts': show_past_shifts,
            'show_filled_shifts': cherrypy.session.get('signups_show_filled_shifts'),
            'show_restricted': show_restricted,
            'show_nonpublic': show_nonpublic,
            'attendees': session.staffers_for_dropdown(),
            'jobs': [job_dict(job) for job in jobs],
            'checklist': department_id and checklist
        }

    @department_id_adapter
    @requires_shifts_admin
    def unfilled_shifts(self, session, department_id=None, message='', toggle_filter=''):
        """
        This page is very similar to the signups view, but this is for STOPS to assign on-call
        volunteers to shifts onsite, so all the default values need to be the exact opposite.

        We also don't want the filters to interfere with the signups view so we store them separately.
        """
        if not toggle_filter:
            redirect_to_allowed_dept(session, department_id, 'unfilled_shifts')

        if department_id == 'None':
            department_id = ''
        elif department_id == 'All':
            department_id = None

        for filter in ['unfilled_show_past_shifts', 'unfilled_show_restricted', 'unfilled_show_nonpublic']:
            cherrypy.session.setdefault(filter, False)

        if toggle_filter:
            cherrypy.session[toggle_filter] = not cherrypy.session.get(toggle_filter)

        show_past_shifts = cherrypy.session.get('unfilled_show_past_shifts')
        show_restricted = cherrypy.session.get('unfilled_show_restricted')
        show_nonpublic = cherrypy.session.get('unfilled_show_nonpublic')

        jobs = []

        if department_id != '':
            job_filters = [Job.department_id == department_id] if department_id else []
            if not show_past_shifts:
                job_filters.append(Job.start_time > localized_now() - timedelta(hours=2))
            if not show_restricted:
                job_filters.append(Job.restricted == False)  # noqa: E712
            if not show_nonpublic:
                job_filters.append(Job.department_id.in_(
                    select([Department.id]).where(
                        Department.solicits_volunteers == True)))  # noqa: E712

            jobs = session.jobs().filter(*job_filters)

        return {
            'message': message,
            'department_id': 'All' if department_id is None else department_id,
            'show_past_shifts': show_past_shifts,
            'show_restricted': show_restricted,
            'show_nonpublic': show_nonpublic,
            'attendees': session.staffers_for_dropdown(),
            'jobs': [job_dict(job) for job in jobs],
        }

    @department_id_adapter
    @requires_shifts_admin
    def staffers(self, session, department_id=None, message=''):
        redirect_to_allowed_dept(session, department_id, 'staffers')

        if department_id == 'None':
            department_id = ''
        elif department_id == 'All':
            department_id = None

        attendees = []
        counts = defaultdict(int)
        requested_count = 0

        if department_id:
            department = session.query(Department).filter_by(id=department_id).first()
            if not department:
                department_id = ''

        if department_id != '':
            dept_filter = [] if department_id == None else [  # noqa: E711
                Attendee.dept_memberships.any(department_id=department_id)]
            attendees = session.staffers(pending=True).filter(*dept_filter).all()
            requested_count = None if not department_id else len(
                [a for a in department.unassigned_explicitly_requesting_attendees if a.is_valid])
            for attendee in attendees:
                if session.admin_has_staffer_access(attendee) or department_id:
                    attendee.is_dept_head_here = attendee.is_dept_head_of(department_id) if department_id \
                        else attendee.is_dept_head
                    attendee.trusted_here = attendee.trusted_in(department_id) if department_id \
                        else attendee.has_role_somewhere
                    attendee.hours_here = attendee.weighted_hours_in(department_id)
                else:
                    attendees.remove(attendee)

            for job in session.jobs(department_id):
                update_counts(job, counts)

        try:
            checklist = session.checklist_status('assigned_volunteers', department_id)
        except ValueError:
            checklist = {'conf': None, 'relevant': False, 'completed': None}

        return {
            'counts': counts,
            'department_id': 'All' if department_id is None else department_id,
            'attendees': attendees,
            'emails': ','.join(a.email for a in attendees),
            'emails_with_shifts': ','.join([a.email for a in attendees if department_id and a.hours_here]),
            'requested_count': requested_count,
            'checklist': checklist,
            'message': message,
        }

    def goto_volunteer_checklist(self, id):
        cherrypy.session['staffer_id'] = id
        raise HTTPRedirect('../staffing/index')

    @ajax
    def update_shifts_info(self, session, id, nonshift_hours, admin_notes, for_review=None):
        attendee = session.attendee(id, allow_invalid=True)
        attendee.nonshift_minutes = int(float(nonshift_hours or 0) * 60)
        attendee.admin_notes = admin_notes
        if for_review is not None:
            attendee.for_review = for_review
        session.commit()
        return {'success': True, 'message': 'Non-shift hours and admin notes updated'}

    @ajax
    def assign_shift(self, session, staffer_id, job_id):
        message = session.assign(staffer_id, job_id)
        if message:
            return {'success': False, 'message': message}
        else:
            session.commit()
            return {'success': True, 'message': 'Shift added'}

    @ajax
    def unassign_shift(self, session, shift_id):
        shift = session.shift(shift_id)
        session.delete(shift)
        session.commit()
        return {'success': True, 'message': 'Staffer unassigned from shift'}

    @requires_shifts_admin
    def form(self, session, message='', **params):
        defaults = {}
        if params.get('id') == 'None' and cherrypy.request.method != 'POST':
            defaults = cherrypy.session.get('job_defaults', defaultdict(dict))[params['department_id']]
            params.update(defaults)

        job = session.job(
            params,
            bools=['extra15'],
            allowed=['department_id', 'start_time', 'type'] + list(defaults.keys()))

        if cherrypy.request.method == 'POST':
            hours = params.get('duration_hours', 0)
            minutes = params.get('duration_minutes', 0)

            try:
                hours = int(hours)
            except ValueError:
                hours = 0

            try:
                minutes = int(minutes)
            except ValueError:
                minutes = 0

            job.duration = hours * 60 + minutes
            message = check(job)
            if not message:
                session.add(job)
                if params.get('id') == 'None':
                    defaults = cherrypy.session.get('job_defaults', defaultdict(dict))
                    defaults[params['department_id']] = {field: getattr(job, field) for field in c.JOB_DEFAULTS}
                    cherrypy.session['job_defaults'] = defaults
                tgt_start_time = job.start_time_local.strftime("%Y-%m-%dT%H:%M:%S%z")
                raise HTTPRedirect('index?department_id={}&time={}', job.department_id, tgt_start_time)

        if 'start_time' in params and 'type' not in params:
            local_start_time = c.EVENT_TIMEZONE.localize(datetime.strptime(params['start_time'], "%Y-%m-%d %H:%M:%S"))
            if c.EPOCH <= local_start_time < c.ESCHATON:
                job.type = c.REGULAR
            else:
                job.type = c.SETUP if local_start_time < c.EPOCH else c.TEARDOWN

        departments = session.admin_attendee().depts_where_can_admin
        can_admin_dept = any(job.department_id == d.id for d in departments)
        if not can_admin_dept and (job.department or job.department_id):
            job_department = job.department or session.query(Department).get(job.department_id)
            if job.is_new:
                departments = sorted(departments + [job_department], key=lambda d: d.name)
            else:
                departments = [job_department]

        dept_roles = defaultdict(list)
        for department in departments:
            for d in department.dept_roles:
                dept_roles[d.department_id].append((d.id, d.name, d.description))

        return {
            'job': job,
            'message': message,
            'dept_roles': dept_roles,
            'dept_opts': [(d.id, d.name) for d in departments],
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

        message = check_can_edit_dept(session, job.department, override_access='full_shifts_admin')
        if message:
            raise HTTPRedirect('index?department_id={}&time={}&message={}',
                               job.department_id, job.start_time_local.strftime("%Y-%m-%dT%H:%M:%S%z"),
                               message)

        for shift in job.shifts:
            session.delete(shift)
        session.delete(job)
        raise HTTPRedirect('index?department_id={}&time={}',
                           job.department_id,
                           job.start_time_local.strftime("%Y-%m-%dT%H:%M:%S%z"))

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
        except Exception:
            return {'error': 'Shift was already deleted'}
        else:
            return job_dict(session.job(shift.job_id))

    @ajax
    def set_worked(self, session, id, status):
        try:
            shift = session.shift(id)
            shift.worked = int(status)
            session.commit()
        except Exception:
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

        return {
            'departments': sorted(departments.items(), key=lambda d: d[1]['regular_signups'] - d[1]['regular_total'])}

    def all_shifts(self, session):
        departments = session.query(Department).options(
            subqueryload(Department.jobs)).order_by(Department.name)
        return {
            'depts': [(d.name, d.jobs) for d in departments]
        }
