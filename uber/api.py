from cherrypy import HTTPError
from uber.common import *
from uber.server import register_jsonrpc


__version__ = '0.1'


def _attendee_fields_and_query(full, query):
    if full:
        fields = AttendeeLookup.fields_full
        query = query.options(
            subqueryload(Attendee.dept_memberships),
            subqueryload(Attendee.assigned_depts),
            subqueryload(Attendee.food_restrictions),
            subqueryload(Attendee.shifts)
                .subqueryload(Shift.job))
    else:
        fields = AttendeeLookup.fields
        query = query.options(subqueryload(Attendee.dept_memberships))
    return (fields, query)


def auth_by_token(required_access):
    token = cherrypy.request.headers.get('X-Auth-Token', None)
    if not token:
        return (401, 'Missing X-Auth-Token header')

    try:
        token = uuid.UUID(token)
    except ValueError as ex:
        return (403, 'Invalid auth token, {}: {}'.format(ex, token))

    with Session() as session:
        api_token = session.query(ApiToken).filter_by(token=token).first()
        if not api_token:
            return (403, 'Auth token not recognized: {}'.format(token))
        if api_token.revoked_time:
            return (403, 'Revoked auth token: {}'.format(token))
        if not required_access.issubset(set(api_token.access_ints)):
            return (403, 'Insufficient access for auth token: {}'.format(token))
        cherrypy.session['account_id'] = api_token.admin_account_id
    return None


def auth_by_session(required_access):
    try:
        check_csrf()
    except CSRFException as ex:
        return (403, 'Your CSRF token is invalid. Please go back and try again.')
    admin_account_id = cherrypy.session.get('account_id', None)
    if not admin_account_id:
        return (403, 'Missing admin account in session')
    with Session() as session:
        admin_account = session.query(AdminAccount).filter_by(id=admin_account_id).first()
        if not admin_account:
            return (403, 'Invalid admin account in session')
        if not required_access.issubset(set(admin_account.access_ints)):
            return (403, 'Insufficient access for admin account')
    return None


def api_auth(*required_access):
    required_access = set(required_access)

    def _decorator(func):
        inner_func = get_innermost(func)
        if not getattr(inner_func, 'required_access', None):
            inner_func.required_access = required_access

        @wraps(func)
        def _with_api_auth(*args, **kwargs):
            error = None
            for auth in [auth_by_token, auth_by_session]:
                result = auth(required_access)
                error = error or result
                if not result:
                    return func(*args, **kwargs)
            raise HTTPError(*error)
        return _with_api_auth
    return _decorator


class all_api_auth:
    def __init__(self, *required_access):
        self.required_access = required_access

    def __call__(self, cls):
        for name, func in cls.__dict__.items():
            if hasattr(func, '__call__'):
                setattr(cls, name, api_auth(*self.required_access)(func))
        return cls


@all_api_auth(c.API_READ)
class AttendeeLookup:
    fields = {
        'full_name': True,
        'first_name': True,
        'last_name': True,
        'legal_name': True,
        'email': True,
        'zip_code': True,
        'cellphone': True,
        'ec_name': True,
        'ec_phone': True,
        'checked_in': True,
        'badge_num': True,
        'badge_printed_name': True,
        'badge_status_label': True,
        'badge_type_label': True,
        'staffing': True,
        'is_dept_head': True,
        'ribbon_labels': True,
    }

    fields_full = dict(fields, **{
        'assigned_depts_labels': True,
        'weighted_hours': True,
        'worked_hours': True,
        'food_restrictions': {
            'sandwich_pref_labels': True,
            'standard_labels': True,
            'freeform': True
        },
        'shifts': {
            'worked_label': True,
            'job': [
                'type_label', 'department_name', 'name', 'description',
                'start_time', 'end_time', 'extra15'
            ]
        }
    })

    def lookup(self, badge_num, full=False):
        """
        Returns a single attendee by badge number.

        Takes the badge number as the first parameter.

        Optionally, "full" may be passed as the second parameter to return the
        complete attendee record, including departments, shifts, and food
        restrictions.
        """
        with Session() as session:
            attendee_query = session.query(Attendee).filter_by(badge_num=badge_num)
            fields, attendee_query = _attendee_fields_and_query(full, attendee_query)
            attendee = attendee_query.first()
            if attendee:
                return attendee.to_dict(fields)
            else:
                return {'error': 'No attendee found with Badge #{}'.format(badge_num)}

    def search(self, query, full=False):
        """
        Searches for attendees using a freeform text query. Returns all
        matching attendees using the same search algorithm as the main
        attendee search box.

        Takes the search query as the first parameter.

        Optionally, "full" may be passed as the second parameter to return the
        complete attendee record, including departments, shifts, and food
        restrictions.
        """
        with Session() as session:
            attendee_query = session.search(query)
            fields, attendee_query = _attendee_fields_and_query(full, attendee_query)
            return [a.to_dict(fields) for a in attendee_query.limit(100)]


@all_api_auth(c.API_READ)
class JobLookup:
    fields = {
        'name': True,
        'description': True,
        'department_name': True,
        'start_time': True,
        'end_time': True,
        'duration': True,
        'shifts': {
            'attendee': {
                'badge_num': True,
                'full_name': True,
                'first_name': True,
                'last_name': True,
                'email': True,
                'cellphone': True,
                'badge_printed_name': True
            }
        }
    }

    @department_id_adapter
    def lookup(self, department_id):
        """
        Returns a list of all shifts for the given department. Takes the
        department id as a single parameter. For a list of all department
        ids call the "dept.list" method.
        """
        with Session() as session:
            query = session.query(Job).filter_by(department_id=department_id) \
                .options(
                    subqueryload(Job.department),
                    subqueryload(Job.shifts).subqueryload(Shift.attendee))
            return [job.to_dict(self.fields) for job in query]


@all_api_auth(c.API_READ)
class DepartmentLookup:
    def list(self):
        """
        Returns a list of department ids and names.
        """
        return c.DEPARTMENTS


@all_api_auth(c.API_READ)
class ConfigLookup:
    fields = [
        'EVENT_NAME',
        'ORGANIZATION_NAME',
        'YEAR',
        'EPOCH',
        'ESCHATON',
        'EVENT_VENUE',
        'EVENT_VENUE_ADDRESS',
        'AT_THE_CON',
        'POST_CON',
    ]

    def info(self):
        """
        Returns a list of all available configuration settings.
        """
        output = {field: getattr(c, field) for field in self.fields}
        output['API_VERSION'] = __version__
        return output

    def lookup(self, field):
        """
        Returns the given configuration setting. Takes the setting
        name as a single argument. For a list of available settings,
        call the "config.info" method.
        """
        if field.upper() in self.fields:
            return getattr(c, field.upper())


if c.API_ENABLED:
    register_jsonrpc(AttendeeLookup(), 'attendee')
    register_jsonrpc(JobLookup(), 'shifts')
    register_jsonrpc(DepartmentLookup(), 'dept')
    register_jsonrpc(ConfigLookup(), 'config')
