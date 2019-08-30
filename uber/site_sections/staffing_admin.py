import urllib
from datetime import datetime

import cherrypy
from dateutil import parser as dateparser
from pytz import UTC
from rpctools.jsonrpc import ServerProxy

from uber.config import c, _config
from uber.decorators import all_renderable, ajax_gettable, site_mappable
from uber.errors import HTTPRedirect
from uber.models import Department, DeptRole, Job


def _server_to_url(server):
    if not server:
        return ''
    host, _, path = urllib.parse.unquote(server).replace('http://', '').replace('https://', '').partition('/')
    if path.startswith('reggie'):
        return 'https://{}/reggie'.format(host)
    elif path.startswith('uber'):
        return 'https://{}/uber'.format(host)
    elif c.PATH == '/uber':
        return 'https://{}{}'.format(host, c.PATH)
    return 'https://{}'.format(host)


def _server_to_host(server):
    if not server:
        return ''
    return urllib.parse.unquote(server).replace('http://', '').replace('https://', '').split('/')[0]


def _format_import_params(target_server, api_token):
    target_url = _server_to_url(target_server)
    target_host = _server_to_host(target_server)
    remote_api_token = api_token.strip()
    if not remote_api_token:
        remote_api_tokens = _config.get('secret', {}).get('remote_api_tokens', {})
        remote_api_token = remote_api_tokens.get(target_host, remote_api_tokens.get('default', ''))
    return (target_url, target_host, remote_api_token.strip())


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


def _get_service(target_server, api_token):
    target_url, target_host, remote_api_token = _format_import_params(target_server, api_token)
    uri = '{}/jsonrpc/'.format(target_url)

    message = ''
    service = None
    if target_server or api_token:
        if not remote_api_token:
            message = 'No API token given and could not find a token for: {}'.format(target_host)
        elif not target_url:
            message = 'Unrecognized hostname: {}'.format(target_server)

        if not message:
            service = ServerProxy(uri=uri, extra_headers={'X-Auth-Token': remote_api_token})

    return service, message, uri


@all_renderable()
class Root:
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

        service, message, uri = _get_service(target_server, api_token)

        department = {}
        from_departments = []
        if not message and service:
            from_departments = [(id, name) for id, name in sorted(service.dept.list().items(), key=lambda d: d[1])]
            if cherrypy.request.method == 'POST':
                from_department = service.dept.jobs(department_id=from_department_id)
                if to_department_id == "None":
                    to_department = _create_copy_department(from_department)
                    session.add(to_department)
                else:
                    to_department = session.query(Department).get(to_department_id)

                dept_role_map = _copy_department_roles(to_department, from_department)

                shifts_text = ' shifts' if 'skip_shifts' in kwargs else ''
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
        target_url, target_host, remote_api_token = _format_import_params(target_server, api_token)
        uri = '{}/jsonrpc/'.format(target_url)

        if not remote_api_token:
            return {
                'error': 'No API token given and could not find a token for: ' + target_host,
                'target_url': uri,
            }

        try:
            service = ServerProxy(uri=uri, extra_headers={'X-Auth-Token': remote_api_token})
            return {
                'departments': [(id, name) for id, name in sorted(service.dept.list().items(), key=lambda d: d[1])],
                'target_url': uri,
            }
        except Exception as ex:
            return {
                'error': str(ex),
                'target_url': uri,
            }

    def bulk_dept_import(
            self,
            session,
            target_server='',
            api_token='',
            message='',
            **kwargs):

        service, message, uri = _get_service(target_server, api_token)

        if not message and service and cherrypy.request.method == 'POST':
            from_departments = [(id, name) for id, name in sorted(service.dept.list().items(), key=lambda d: d[1])]
            for id, name in from_departments:
                from_department = service.dept.jobs(department_id=id)
                to_department = session.query(Department).filter_by(name=from_department['name']).first()
                if not to_department:
                    to_department = _create_copy_department(from_department)
                    session.add(to_department)

                dept_role_map = _copy_department_roles(to_department, from_department)

                shifts_text = ' and shifts' if 'skip_shifts' in kwargs else ''
                if shifts_text:
                    _copy_department_shifts(service, to_department, from_department, dept_role_map)

                message = 'Bulk import of departments{} done!'.format(shifts_text)
                raise HTTPRedirect('import_shifts?target_server={}&api_token={}&message={}',
                                   target_server, api_token, message)
