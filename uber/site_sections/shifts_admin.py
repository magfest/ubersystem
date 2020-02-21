from collections import defaultdict
from datetime import datetime, timedelta

import cherrypy
import re
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import subqueryload

from uber.config import c
from uber.decorators import ajax, all_renderable, csrf_protected, department_id_adapter, \
    check_can_edit_dept, log_pageview, requires_shifts_admin
from uber.errors import HTTPRedirect
from uber.models import Attendee, Department, Email, Job, PageViewTracking, Shift, Tracking
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
            'jobs': jobs,
            'message': message,
        }

    @department_id_adapter
    @requires_shifts_admin
    def signups(self, session, department_id=None, message=''):
        redirect_to_allowed_dept(session, department_id, 'signups')
        department_id = None if department_id == 'All' else department_id
        cherrypy.session['prev_department_id'] = department_id

        return {
            'message': message,
            'department_id': department_id,
            'attendees': session.staffers_for_dropdown(),
            'jobs': [job_dict(job) for job in session.jobs(department_id)],
            'checklist': department_id and session.checklist_status('postcon_hours', department_id)
        }

    def everywhere(self, session, message='', show_restricted='', show_nonpublic=''):
        job_filters = [Job.start_time > localized_now() - timedelta(hours=2)]
        if not show_restricted:
            job_filters.append(Job.restricted == False)  # noqa: E712
        if not show_nonpublic:
            job_filters.append(Job.department_id.in_(
                select([Department.id]).where(
                    Department.solicits_volunteers == True)))  # noqa: E712

        jobs = session.jobs().filter(*job_filters)

        return {
            'message': message,
            'show_restricted': show_restricted,
            'show_nonpublic': show_nonpublic,
            'attendees': session.staffers_for_dropdown(),
            'jobs': [job_dict(job) for job in jobs]
        }

    @department_id_adapter
    @requires_shifts_admin
    def staffers(self, session, department_id=None, message=''):
        redirect_to_allowed_dept(session, department_id, 'staffers')

        department_id = None if department_id == 'All' else department_id

        if department_id:
            department = session.query(Department).filter_by(id=department_id).first()
            if not department:
                department_id = None

        dept_filter = [] if not department_id \
            else [Attendee.dept_memberships.any(department_id=department_id)]
        attendees = session.staffers(pending=True).filter(*dept_filter).all()
        for attendee in attendees:
            if session.admin_can_see_staffer(attendee) or department_id:
                attendee.is_dept_head_here = attendee.is_dept_head_of(department_id) if department_id \
                    else attendee.is_dept_head
                attendee.trusted_here = attendee.trusted_in(department_id) if department_id \
                    else attendee.has_role_somewhere
                attendee.hours_here = attendee.weighted_hours_in(department_id)
            else:
                attendees.remove(attendee)

        counts = defaultdict(int)
        for job in session.jobs(department_id):
            update_counts(job, counts)

        return {
            'counts': counts,
            'department_id': department_id,
            'attendees': attendees,
            'emails': ','.join(a.email for a in attendees),
            'emails_with_shifts': ','.join([a.email for a in attendees if department_id and a.hours_here]),
            'checklist': session.checklist_status('assigned_volunteers', department_id),
            'message': message,
        }

    def goto_volunteer_checklist(self, id):
        cherrypy.session['staffer_id'] = id
        raise HTTPRedirect('../staffing/index')

    @ajax
    def update_nonshift(self, session, id, nonshift_hours):
        attendee = session.attendee(id, allow_invalid=True)
        if not re.match('^[0-9]+$', nonshift_hours):
            return { 'success': False, 'message': 'Invalid integer' }
        else:
            attendee.nonshift_hours = int(nonshift_hours)
            session.commit()
            return { 'success': True, 'message': 'Non-shift hours updated' }

    @ajax
    def update_notes(self, session, id, admin_notes, for_review=None):
        attendee = session.attendee(id, allow_invalid=True)
        attendee.admin_notes = admin_notes
        if for_review is not None:
            attendee.for_review = for_review
        session.commit()
        return { 'success': True, 'message': 'Notes updated' }

    @ajax
    def assign_shift(self, session, staffer_id, job_id):
        message = session.assign(staffer_id, job_id)
        if message:
            return { 'success': False, 'message': message }
        else:
            session.commit()
            return { 'success': True, 'message': 'Shift added' }

    @ajax
    def unassign_shift(self, session, shift_id):
        shift = session.shift(shift_id)
        session.delete(shift)
        session.commit()
        return { 'success': True, 'message': 'Staffer unassigned from shift' }

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
            raise HTTPRedirect('index?department_id={}#{}&message={}', job.department_id, job.start_time, message)

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
