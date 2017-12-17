from cherrypy import HTTPError
from dateutil import parser as dateparser
from uber.common import *
from uber.server import register_jsonrpc


__version__ = '0.1'


def docstring_format(*args, **kwargs):
    def _decorator(obj):
        obj.__doc__ = obj.__doc__.format(*args, **kwargs)
        return obj
    return _decorator


def _format_opts(opts):
    html = ['<table class="opts"><tbody>']
    for value, label in opts:
        html.append(
            '<tr class="opt">'
            '<td class="opt-value">{}</td>'
            '<td class="opt-label">{}</td>'
            '</tr>'.format(value, label))
    html.append('</tbody></table>')
    return ''.join(html)


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


def _parse_datetime(d):
    if isinstance(d, six.string_types) and d.strip().lower() == 'now':
        d = datetime.utcnow().replace(tzinfo=pytz.UTC)
    else:
        d = dateparser.parse(d)
    try:
        d = d.astimezone(pytz.UTC)  # aware object can be in any timezone
    except ValueError:
        d = c.EVENT_TIMEZONE.localize(d)  # naive assumed to be event timezone
    return d


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
        if getattr(inner_func, 'required_access', None):
            return func
        else:
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
            'worked': True,
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


@all_api_auth(c.API_UPDATE)
class JobLookup:
    fields = {
        'name': True,
        'description': True,
        'department_name': True,
        'start_time': True,
        'end_time': True,
        'duration': True,
        'shifts': {
            'worked': True,
            'worked_label': True,
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
    @api_auth(c.API_READ)
    def lookup(self, department_id, start_time=None, end_time=None):
        """
        Returns a list of all shifts for the given department.

        Takes the department id as the first parameter. For a list of all
        department ids call the "dept.list" method.

        Optionally, takes a "start_time" and "end_time" to constrain the
        results to a given date range. Dates may be given in any format
        supported by the
        <a href="http://dateutil.readthedocs.io/en/stable/parser.html">
        dateutil parser</a>, plus the string "now".

        Unless otherwise specified, "start_time" and "end_time" are assumed
        to be in the local timezone of the event.
        """
        with Session() as session:
            query = session.query(Job).filter_by(department_id=department_id)
            if start_time:
                start_time = _parse_datetime(start_time)
                query = query.filter(Job.start_time >= start_time)
            if end_time:
                end_time = _parse_datetime(end_time)
                query = query.filter(Job.start_time <= end_time)
            query = query.options(
                    subqueryload(Job.department),
                    subqueryload(Job.shifts).subqueryload(Shift.attendee))
            return [job.to_dict(self.fields) for job in query]

    def assign(self, job_id, attendee_id):
        """
        Assigns a shift for the given job to the given attendee.

        Takes the job id and attendee id as parameters.
        """
        with Session() as session:
            message = session.assign(attendee_id, job_id)
            if message:
                return {'error': message}
            else:
                session.commit()
                return session.job(job_id).to_dict(self.fields)

    def unassign(self, shift_id):
        """
        Unassigns whomever is working the given shift.

        Takes the shift id as the only parameter.
        """
        with Session() as session:
            try:
                shift = session.shift(shift_id)
                session.delete(shift)
                session.commit()
            except:
                return {'error': 'Shift was already deleted'}
            else:
                return session.job(shift.job_id).to_dict(self.fields)

    @docstring_format(
        _format_opts(c.WORKED_STATUS_OPTS),
        _format_opts(c.RATING_OPTS))
    def set_worked(self, shift_id, status=c.SHIFT_WORKED, rating=c.UNRATED, comment=''):
        """
        Returns a list of all shifts for the given department.

        Takes the shift id as the first parameter.

        Optionally takes the shift status, rating, and a comment required to
        explain either poor or excellent performance.

        <h6>Valid status values</h6>
        {}
        <h6>Valid rating values</h6>
        {}
        """
        try:
            status = int(status)
            _ = c.WORKED_STATUS[status]
        except:
            return {'error': 'Invalid status: {}'.format(status)}

        try:
            rating = int(rating)
            _ = c.RATINGS[rating]
        except:
            return {'error': 'Invalid rating: {}'.format(rating)}

        if rating in (c.RATED_BAD, c.RATED_GREAT) and not comment:
            return {'error': 'You must leave a comment explaining why the '
                    'staffer was rated as: {}'.format(c.RATINGS[rating])}

        with Session() as session:
            try:
                shift = session.shift(shift_id)
                shift.worked = status
                shift.rating = rating
                shift.comment = comment
                session.commit()
            except:
                return {'error': 'Unexpected error setting status'}
            else:
                return session.job(shift.job_id).to_dict(self.fields)


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
