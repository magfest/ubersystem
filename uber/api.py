from uber.common import *
from uber.server import register_jsonrpc


__version__ = '0.1'


def token_auth(*required_access):
    def _decorator(func):
        if not getattr(func, 'required_access', None):
            func.required_access = set(required_access)

        @wraps(func)
        def _with_token_auth(*args, **kwargs):
            token = cherrypy.request.headers.get('X-Auth-Token', None)
            if not token:
                return {'error': 'Missing X-Auth-Token header'}
            with Session() as session:
                api_token = session.query(ApiToken).filter_by(id=token).first()
                if not api_token:
                    return {'error': 'Invalid auth token: {}'.format(token)}
                if api_token.revoked_time:
                    return {'error': 'Revoked auth token: {}'.format(token)}
                if not func.required_access.issubset(set(api_token.access_ints)):
                    return {'error': 'Insufficient access for auth token: {}'.format(token)}
                return func(*args, **kwargs)
        return _with_token_auth
    return _decorator


class all_token_auth:
    def __init__(self, *required_access):
        self.required_access = required_access

    def __call__(self, cls):
        for name, func in cls.__dict__.items():
            if hasattr(func, '__call__'):
                setattr(cls, name, token_auth(*self.required_access)(func))
        return cls


@all_token_auth(c.API_READ)
class AttendeeLookup:
    fields = {
        'full_name': True,
        'first_name': True,
        'last_name': True,
        'email': True,
        'zip_code': True,
        'cellphone': True,
        'ec_name': True,
        'ec_phone': True,
        'badge_status_label': True,
        'checked_in': True,
        'badge_type_label': True,
        'ribbon_labels': True,
        'staffing': True,
        'is_dept_head': True,
        'assigned_depts_labels': True,
        'weighted_hours': True,
        'worked_hours': True,
        'badge_num': True,
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
    }

    def lookup(self, badge_num):
        with Session() as session:
            attendee = session.query(Attendee).filter_by(badge_num=badge_num).first()
            if attendee:
                return attendee.to_dict(self.fields)
            else:
                return {'error': 'No attendee found with Badge #{}'.format(badge_num)}

    def search(self, query):
        with Session() as session:
            return [a.to_dict(self.fields) for a in session.search(query).all()]


@all_token_auth(c.API_READ)
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
        with Session() as session:
            query = session.query(Job).filter_by(department_id=department_id) \
                .options(
                    subqueryload(Job.department),
                    subqueryload(Job.shifts).subqueryload(Shift.attendee))
            return [job.to_dict(self.fields) for job in query]


@all_token_auth(c.API_READ)
class DepartmentLookup:
    def list(self):
        return c.DEPARTMENTS


@all_token_auth(c.API_READ)
class ConfigLookup:
    fields = [
        'EVENT_NAME',
        'ORGANIZATION_NAME',
        'YEAR',
        'EPOCH',
        'EVENT_VENUE',
        'EVENT_VENUE_ADDRESS',
        'AT_THE_CON',
        'POST_CON',
    ]

    def info(self):
        output = {field: getattr(c, field) for field in self.fields}
        output['API_VERSION'] = __version__
        return output

    def lookup(self, field):
        if field.upper() in self.fields:
            return getattr(c, field.upper())


if c.API_ENABLED:
    register_jsonrpc(AttendeeLookup(), 'attendee')
    register_jsonrpc(JobLookup(), 'shifts')
    register_jsonrpc(DepartmentLookup(), 'dept')
    register_jsonrpc(ConfigLookup(), 'config')
