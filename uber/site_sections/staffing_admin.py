from datetime import datetime

import cherrypy
from dateutil import parser as dateparser
from pytz import UTC

from uber.config import c
from uber.decorators import all_renderable, ajax, ajax_gettable, site_mappable
from uber.errors import HTTPRedirect
from uber.models import Attendee, Attraction, Department, DeptRole, Job, JobTemplate
from uber.utils import get_api_service_from_server, slugify


def _create_copy_department(from_department):
    to_department = Department()
    for field in ['name', 'description', 'solicits_volunteers', 'max_consecutive_minutes']:
        if field in from_department:
            setattr(to_department, field, from_department[field])

        # Convert old years' max hours to minutes, this can eventually be removed
        if 'max_consecutive_hours' in from_department:
            setattr(to_department, 'max_consecutive_minutes', int(from_department['max_consecutive_hours']) * 60)
    return to_department


def _copy_department_roles(to_department, from_department):
    to_dept_roles_by_id = to_department.dept_roles_by_id
    to_dept_roles_by_name = to_department.dept_roles_by_name
    dept_role_map = {}
    for from_dept_role in from_department['dept_roles']:
        to_dept_role = to_dept_roles_by_id.get(from_dept_role['id'], [None])[0]
        if not to_dept_role:
            to_dept_role = to_dept_roles_by_name.get(from_dept_role['name'], [None])[0]
        if not to_dept_role:
            to_dept_role = DeptRole(
                name=from_dept_role['name'],
                description=from_dept_role['description'],
                department_id=to_department.id)
            to_department.dept_roles.append(to_dept_role)
        dept_role_map[from_dept_role['id']] = to_dept_role

    return dept_role_map


def _copy_department_templates(to_department, from_department):
    to_dept_templates_by_id = to_department.job_templates_by_id
    to_dept_templates_by_name = to_department.job_templates_by_name
    dept_template_map = {}
    for from_dept_template in from_department['job_templates']:
        to_dept_template = to_dept_templates_by_id.get(from_dept_template['id'], [None])[0]
        if not to_dept_template:
            to_dept_template = to_dept_templates_by_name.get(from_dept_template['template_name'], [None])[0]
        if not to_dept_template:
            to_dept_template = JobTemplate(department_id=to_department.id)
            for attr in ['template_name', 'type', 'name', 'description', 'duration', 'weight', 'extra15', 'visibility',
                         'all_roles_required', 'min_slots', 'days', 'open_time', 'close_time', 'interval']:
                setattr(to_dept_template, attr, from_dept_template.get(attr, None))
            to_department.job_templates.append(to_dept_template)
        dept_template_map[from_dept_template['id']] = to_dept_template

    return dept_template_map


def _copy_department_shifts(service, to_department, from_department, dept_role_map, dept_template_map):
    from_config = service.config.info()
    FROM_EPOCH = c.EVENT_TIMEZONE.localize(datetime.strptime(from_config['SHIFTS_EPOCH'], '%Y-%m-%d %H:%M:%S.%f'))
    EPOCH_DELTA = c.SHIFTS_EPOCH - FROM_EPOCH

    for from_job in from_department['jobs']:
        to_job = Job(
            name=from_job['name'],
            description=from_job['description'],
            duration=from_job['duration'],
            extra15=from_job['extra15'],
            slots=from_job['slots'],
            start_time=UTC.localize(dateparser.parse(from_job['start_time'])) + EPOCH_DELTA,
            visibility=from_job['visibility'],
            weight=from_job['weight'],
            department_id=to_department.id)
        for from_required_role in from_job['required_roles']:
            to_job.required_roles.append(dept_role_map[from_required_role['id']])
        if from_job['job_template_id']:
            to_job.template = dept_template_map[from_job['job_template_id']]
        to_department.jobs.append(to_job)


@all_renderable()
class Root:
    def pending_badges(self, session, message=''):
        return {
            'pending_badges': session.query(Attendee).filter_by(
                badge_status=c.PENDING_STATUS).filter_by(staffing=True).filter(Attendee.paid != c.PENDING),
            'message': message,
        }

    @ajax
    def approve_badge(self, session, id):
        attendee = session.attendee(id)
        attendee.badge_status = c.NEW_STATUS
        session.add(attendee)
        session.commit()

        return {'added': id}

    @site_mappable
    def import_shifts(
            self,
            session,
            target_server='',
            api_token='',
            to_department_id='',
            from_department_id='',
            message='',
            **kwargs):

        if message:
            service, uri = None, ''
        else:
            service, message, target_url = get_api_service_from_server(target_server, api_token)
            uri = '{}/jsonrpc/'.format(target_url)

        department = {}
        from_departments = []
        if not message and service:
            from_departments = [(id, name) for id, name in sorted(service.dept.list().items(), key=lambda d: d[1])]
            if cherrypy.request.method == 'POST':
                from_department = service.dept.jobs(department_id=from_department_id)
                shifts_text = ' shifts' if 'skip_shifts' not in kwargs else ''

                if to_department_id == "None":
                    existing_department = session.query(Department).filter_by(name=from_department['name']).first()
                    if existing_department:
                        raise HTTPRedirect('import_shifts?target_server={}&api_token={}&message={}',
                                           target_server,
                                           api_token,
                                           "Cannot create a department with the same name as an existing department")
                    to_department = _create_copy_department(from_department)
                    session.add(to_department)
                else:
                    to_department = session.query(Department).get(to_department_id)

                dept_role_map = _copy_department_roles(to_department, from_department)
                dept_template_map = _copy_department_templates(to_department, from_department)

                if shifts_text:
                    _copy_department_shifts(service, to_department, from_department, dept_role_map, dept_template_map)

                message = '{}{}successfully imported from {}'.format(to_department.name, shifts_text, uri)
                raise HTTPRedirect('import_shifts?target_server={}&api_token={}&message={}',
                                   target_server, api_token, message)

        return {
            'target_server': target_server,
            'target_url': uri,
            'api_token': api_token,
            'department': department,
            'to_departments': c.DEPARTMENT_OPTS,
            'from_departments': from_departments,
            'message': message,
        }

    @ajax_gettable
    def lookup_departments(self, session, target_server='', api_token='', **kwargs):
        service, message, target_url = get_api_service_from_server(target_server, api_token)
        uri = '{}/jsonrpc/'.format(target_url)

        if not message:
            try:
                results = [(id, name) for id, name in sorted(service.dept.list().items(), key=lambda d: d[1])]
            except Exception as ex:
                message = str(ex)

        if message:
            return {
                'error': message,
                'target_url': uri,
            }

        return {
            'departments': results,
            'target_url': uri,
        }

    def bulk_dept_import(
            self,
            session,
            target_server='',
            api_token='',
            message='',
            **kwargs):

        service, message, target_url = get_api_service_from_server(target_server, api_token)
        uri = '{}/jsonrpc/'.format(target_url)

        if not message and service and cherrypy.request.method == 'POST':
            from_departments = [(id, name) for id, name in sorted(service.dept.list().items(), key=lambda d: d[1])]

            for id, name in from_departments:
                from_department = service.dept.jobs(department_id=id)
                to_department = session.query(Department).filter_by(name=from_department['name']).first()
                if not to_department:
                    to_department = _create_copy_department(from_department)
                    session.add(to_department)

                _copy_department_roles(to_department, from_department)
                _copy_department_templates(to_department, from_department)

                to_dept_attractions = {attraction.slug: attraction for attraction in to_department.attractions}
                for from_dept_attraction in from_department['attractions']:
                    from_slug = slugify(from_dept_attraction['name'])
                    to_dept_attraction = to_dept_attractions.get(from_slug, None)

                    if not to_dept_attraction:
                        existing_attraction = session.query(Attraction).filter(Attraction.slug == from_slug).first()

                        if existing_attraction:
                            if not existing_attraction.department:
                                to_department.attractions.append(existing_attraction)
                        else:
                            to_dept_attraction = Attraction(department_id=to_department.id)
                            for attr in ['name', 'description', 'full_description', 'checkin_reminder',
                                        'advance_checkin', 'restriction', 'badge_num_required',
                                        'populate_schedule', 'no_notifications', 'waitlist_available', 'waitlist_slots',
                                        'signups_open_relative', 'slots']:
                                setattr(to_dept_attraction, attr, from_dept_attraction.get(attr, None))
                            old_signups_open_time = from_dept_attraction.get('signups_open_time', None)
                            if old_signups_open_time:
                                signups_open_time = UTC.localize(dateparser.parse(old_signups_open_time))
                                to_dept_attraction.signups_open_time = signups_open_time.replace(year=signups_open_time.year + 1)
                            to_department.attractions.append(to_dept_attraction)

            message = 'Successfully imported all departments, roles, job templates, and department attractions from {}'.format(uri)
            raise HTTPRedirect('import_shifts?target_server={}&api_token={}&message={}',
                               target_server, api_token, message)
