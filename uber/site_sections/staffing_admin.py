from datetime import datetime

import cherrypy
from dateutil import parser as dateparser
from pytz import UTC

from uber.config import c
from uber.decorators import all_renderable, ajax, ajax_gettable, site_mappable
from uber.errors import HTTPRedirect
from uber.models import Attendee, Department, DeptRole, Job
from uber.utils import get_api_service_from_server


def _create_copy_department(from_department):
    to_department = Department()
    for field in ['name', 'description', 'solicits_volunteers', 'is_shiftless',
                  'is_setup_approval_exempt', 'is_teardown_approval_exempt', 'max_consecutive_hours']:
        if field in from_department:
            setattr(to_department, field, from_department[field])
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


def _copy_department_shifts(service, to_department, from_department, dept_role_map):
    from_config = service.config.info()
    FROM_EPOCH = c.EVENT_TIMEZONE.localize(datetime.strptime(from_config['EPOCH'], '%Y-%m-%d %H:%M:%S.%f'))
    EPOCH_DELTA = c.EPOCH - FROM_EPOCH

    for from_job in from_department['jobs']:
        to_job = Job(
            name=from_job['name'],
            description=from_job['description'],
            duration=from_job['duration'],
            type=from_job['type'],
            extra15=from_job['extra15'],
            slots=from_job['slots'],
            start_time=UTC.localize(dateparser.parse(from_job['start_time'])) + EPOCH_DELTA,
            visibility=from_job['visibility'],
            weight=from_job['weight'],
            department_id=to_department.id)
        for from_required_role in from_job['required_roles']:
            to_job.required_roles.append(dept_role_map[from_required_role['id']])
        to_department.jobs.append(to_job)


@all_renderable()
class Root:
    def pending_badges(self, session, message=''):
        return {
            'pending_badges': session.query(Attendee).filter_by(badge_status=c.PENDING_STATUS).filter_by(staffing=True),
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

                if shifts_text:
                    _copy_department_shifts(service, to_department, from_department, dept_role_map)

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

            message = 'Successfully imported all departments and roles from {}'.format(uri)
            raise HTTPRedirect('import_shifts?target_server={}&api_token={}&message={}',
                               target_server, api_token, message)
