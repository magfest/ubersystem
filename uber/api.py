import re
import uuid
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from functools import wraps

import cherrypy
import pytz
import json
import six
import traceback
import logging
from cherrypy import HTTPError
from dateutil import parser as dateparser
from time import mktime
from sqlalchemy import and_, func, or_, not_
from sqlalchemy.orm import subqueryload
from sqlalchemy.orm.exc import MultipleResultsFound, NoResultFound
from sqlalchemy.types import Boolean, Date, DateTime

from uber.barcode import get_badge_num_from_barcode
from uber.config import c
from uber.errors import CSRFException
from uber.models import (AdminAccount, ApiToken, Attendee, AttendeeAccount, Attraction, AttractionFeature, AttractionEvent,
                         BadgeInfo, Department, DeptMembership,
                         DeptRole, Event, IndieJudge, IndieStudio, Job, Session, Shift, Group,
                         GuestGroup, Room, HotelRequests, RoomAssignment)
from uber.models.badge_printing import PrintJob
from uber.serializer import serializer
from uber.utils import check, check_csrf, normalize_email_legacy, normalize_newlines, unwrap, department_id_adapter

log = logging.getLogger(__name__)

__version__ = '1.0'

ERR_INVALID_RPC = -32600
ERR_MISSING_FUNC = -32601
ERR_INVALID_PARAMS = -32602
ERR_FUNC_EXCEPTION = -32603
ERR_INVALID_JSON = -32700

def force_json_in():
    """A version of jsontools.json_in that forces all requests to be interpreted as JSON."""
    request = cherrypy.serving.request
    if not request.headers.get('Content-Length', ''):
        raise cherrypy.HTTPError(411)

    if cherrypy.request.method in ('POST', 'PUT'):
        body = request.body.fp.read()
        try:
            cherrypy.serving.request.json = json.loads(body.decode('utf-8'))
        except ValueError:
            raise cherrypy.HTTPError(400, 'Invalid JSON document')

cherrypy.tools.force_json_in = cherrypy.Tool('before_request_body', force_json_in, priority=30)

def json_handler(*args, **kwargs):
    value = cherrypy.serving.request._json_inner_handler(*args, **kwargs)
    return json.dumps(value, cls=serializer).encode('utf-8')

def _make_jsonrpc_handler(services, debug=c.DEV_BOX, precall=lambda body: None):

    @cherrypy.expose
    @cherrypy.tools.force_json_in()
    @cherrypy.tools.json_out(handler=json_handler)
    def _jsonrpc_handler(self=None):
        id = None

        def error(status, code, message):
            response = {'jsonrpc': '2.0', 'id': id, 'error': {'code': code, 'message': message}}
            log.debug('Returning error message: {}', repr(response).encode('utf-8'))
            cherrypy.response.status = status
            return response

        def success(result):
            response = {'jsonrpc': '2.0', 'id': id, 'result': result}
            log.debug('Returning success message: {}', {
                'jsonrpc': '2.0', 'id': id, 'result': len(result) if isinstance(result, Iterable) and not isinstance(result, str) else str(result).encode('utf-8')})
            cherrypy.response.status = 200
            return response

        request_body = cherrypy.request.json
        if not isinstance(request_body, dict):
            return error(400, ERR_INVALID_JSON, 'Invalid json input: {!r}'.format(request_body))

        log.debug('jsonrpc request body: {}', repr(request_body).encode('utf-8'))

        id, params = request_body.get('id'), request_body.get('params', [])
        if 'method' not in request_body:
            return error(400, ERR_INVALID_RPC, '"method" field required for jsonrpc request')

        method = request_body['method']
        if method.count('.') != 1:
            return error(404, ERR_MISSING_FUNC, 'Invalid method ' + method)

        module, function = method.split('.')
        if module not in services:
            return error(404, ERR_MISSING_FUNC, 'No module ' + module)

        service = services[module]
        if not hasattr(service, function):
            return error(404, ERR_MISSING_FUNC, 'No function ' + method)

        if not isinstance(params, (list, dict)):
            return error(400, ERR_INVALID_PARAMS, 'Invalid parameter list: {!r}'.format(params))

        args, kwargs = (params, {}) if isinstance(params, list) else ([], params)

        precall(request_body)
        try:
            return success(getattr(service, function)(*args, **kwargs))
        except HTTPError as http_error:
            return error(http_error.code, ERR_FUNC_EXCEPTION, http_error._message)
        except Exception as e:
            log.error('Unexpected error', exc_info=True)
            message = 'Unexpected error: {}'.format(e)
            if debug:
                message += '\n' + traceback.format_exc()
            return error(500, ERR_FUNC_EXCEPTION, message)

    return _jsonrpc_handler


jsonrpc_services = {}


def register_jsonrpc(service, name=None):
    name = name or service.__name__
    assert name not in jsonrpc_services, '{} has already been registered'.format(name)
    jsonrpc_services[name] = service


jsonrpc_app = _make_jsonrpc_handler(jsonrpc_services)
cherrypy.tree.mount(jsonrpc_app, c.CHERRYPY_MOUNT_PATH + '/jsonrpc', c.APPCONF)

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


def _attendee_fields_and_query(full, query, only_valid=True):
    if only_valid:
        query = query.filter(Attendee.is_valid == True)  # noqa: E712

    if full:
        fields = AttendeeLookup.fields_full
        query = query.options(
            subqueryload(Attendee.dept_memberships),
            subqueryload(Attendee.assigned_depts),
            subqueryload(Attendee.food_restrictions),
            subqueryload(Attendee.shifts).subqueryload(Shift.job))
    else:
        fields = AttendeeLookup.fields
        query = query.options(subqueryload(Attendee.dept_memberships))
    return (fields, query)


def _prepare_attendees_export(attendees, include_account_ids=False, include_apps=False,
                              include_depts=False, is_group_attendee=False):
    # If we add API classes for these models later, please move the field lists accordingly
    art_show_import_fields = [
        'artist_name',
        'artist_id',
        'banner_name',
        'description',
        'business_name',
        'zip_code',
        'address1',
        'address2',
        'city',
        'region',
        'country',
        'paypal_address',
        'website',
        'special_needs',
        'admin_notes',
    ]

    marketplace_import_fields = [
        'name',
        'display_name',
        'email_address',
        'website',
        'tax_number',
        'seating_requests',
        'accessibility_requests',
        'admin_notes',
    ]

    fields = AttendeeLookup.attendee_import_fields + Attendee.import_fields

    if include_depts or include_apps:
        fields.extend(['shirt'])

    if is_group_attendee:
        fields.extend(AttendeeLookup.group_attendee_import_fields)

    attendee_list = []
    for a in attendees:
        d = a.to_dict(fields)

        if include_account_ids and a.managers:
            d['attendee_account_ids'] = [m.id for m in a.managers]

        if include_apps:
            if a.art_show_applications:
                d['art_show_app'] = a.art_show_applications[0].to_dict(art_show_import_fields)
            if a.marketplace_application:
                d['marketplace_app'] = a.marketplace_application.to_dict(marketplace_import_fields)

        if include_depts:
            assigned_depts = {}
            checklist_admin_depts = {}
            dept_head_depts = {}
            poc_depts = {}
            roles_depts = defaultdict(list)

            if a.badge_status == c.DEFERRED_STATUS:
                active_dept_memberships = a.dept_memberships
            else:
                active_dept_memberships = [m for m in a.dept_memberships if m.has_inherent_role or 
                                           m.department in a.depts_where_working]

            for membership in active_dept_memberships:
                assigned_depts[membership.department_id] = membership.department.name
                for role in membership.dept_roles:
                    roles_depts[membership.department_id].append((role.id, role.name))
                if membership.is_checklist_admin:
                    checklist_admin_depts[membership.department_id] = membership.department.name
                if membership.is_dept_head:
                    dept_head_depts[membership.department_id] = membership.department.name
                if membership.is_poc:
                    poc_depts[membership.department_id] = membership.department.name

            d.update({
                'assigned_depts': assigned_depts,
                'checklist_admin_depts': checklist_admin_depts,
                'dept_head_depts': dept_head_depts,
                'poc_depts': poc_depts,
                'roles_depts': roles_depts,
            })

        attendee_list.append(d)
    return attendee_list


def _query_to_names_emails_ids(query, split_names=True):
    _re_name_email = re.compile(r'^\s*(.*?)\s*<\s*(.*?@.*?)\s*>\s*$')
    _re_sep = re.compile(r'[\n,]')
    _re_whitespace = re.compile(r'\s+')
    queries = [s.strip() for s in _re_sep.split(normalize_newlines(query)) if s.strip()]

    names = dict()
    emails = dict()
    names_and_emails = dict()
    ids = set()
    for q in queries:
        if '@' in q:
            match = _re_name_email.match(q)
            if match:
                name = match.group(1)
                email = normalize_email_legacy(match.group(2))
                if name:
                    first, last = (_re_whitespace.split(name.lower(), 1) + [''])[0:2]
                    names_and_emails[(first, last, email)] = q
                else:
                    emails[email] = q
            else:
                emails[normalize_email_legacy(q)] = q
        elif q:
            try:
                ids.add(str(uuid.UUID(q)))
            except Exception:
                if split_names:
                    first, last = (_re_whitespace.split(q.lower(), 1) + [''])[0:2]
                    names[(first, last)] = q
                else:
                    names[q] = q
    return names, emails, names_and_emails, ids


def _parse_datetime(d):
    if isinstance(d, six.string_types) and d.strip().lower() == 'now':
        d = datetime.now(pytz.UTC)
    else:
        d = dateparser.parse(d)
    try:
        d = d.astimezone(pytz.UTC)  # aware object can be in any timezone
    except ValueError:
        d = c.EVENT_TIMEZONE.localize(d)  # naive assumed to be event timezone
    return d


def _parse_if_datetime(key, val):
    # This should be in the DateTime and Date classes, but they're not defined in this app
    if hasattr(getattr(Attendee, key), 'type') and (
            isinstance(getattr(Attendee, key).type, DateTime) or isinstance(getattr(Attendee, key).type, sa.types.time) or isinstance(getattr(Attendee, key).type, Date)):
        return _parse_datetime(val)
    return val


def _parse_if_boolean(key, val):
    if hasattr(getattr(Attendee, key), 'type') and isinstance(getattr(Attendee, key).type, Boolean):
        if isinstance(val, six.string_types):
            return val.strip().lower() not in ('f', 'false', 'n', 'no', '0')
        else:
            return bool(val)
    return val


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
        for access_level in required_access:
            if not getattr(api_token, access_level, None):
                return (403, 'Insufficient access for auth token: {}'.format(token))
        cherrypy.session['account_id'] = api_token.admin_account_id
    return None


def auth_by_session(required_access):
    try:
        check_csrf()
    except CSRFException:
        return (403, 'Your CSRF token is invalid. Please go back and try again.')
    admin_account_id = cherrypy.session.get('account_id')
    if not admin_account_id:
        return (403, 'Missing admin account in session')
    with Session() as session:
        admin_account = session.query(AdminAccount).filter_by(id=admin_account_id).first()
        if not admin_account:
            return (403, 'Invalid admin account in session')
        for access_level in required_access:
            if not getattr(admin_account, access_level, None):
                return (403, 'Insufficient access for admin account')
    return None


def api_auth(*required_access):
    required_access = set(required_access)

    def _decorator(fn):
        inner_func = unwrap(fn)
        if getattr(inner_func, 'required_access', None) is not None:
            return fn
        else:
            inner_func.required_access = required_access

        @wraps(fn)
        def _with_api_auth(*args, **kwargs):
            error = None
            for auth in [auth_by_token, auth_by_session]:
                result = auth(required_access)
                error = error or result
                if not result:
                    return fn(*args, **kwargs)
            raise HTTPError(*error)
        return _with_api_auth
    return _decorator


class all_api_auth:
    def __init__(self, *required_access):
        self.required_access = required_access

    def __call__(self, cls):
        for name, fn in cls.__dict__.items():
            if hasattr(fn, '__call__'):
                setattr(cls, name, api_auth(*self.required_access)(fn))
        return cls


@all_api_auth('api_read')
class GuestLookup:
    fields = {
        'group_id': True,
        'group_type': True,
        'info': {
            'status': True,
            'poc_phone': True
        },
        'bio': {
            'status': True,
            'desc': True,
            'website': True,
            'facebook': True,
            'twitter': True,
            'instagram': True,
            'twitch': True,
            'bandcamp': True,
            'discord': True,
            'other_social_media': True,
            'teaser_song_url': True,
        },
        'interview': {
            'will_interview': True,
            'email': True,
            'direct_contact': True
        },
        'group': {
            'name': True,
            'website': True,
            'description': True
        }
    }

    def types(self):
        return c.GROUP_TYPE_VARS

    def list(self, type=None):
        """
        Returns a list of Guests.

        Optionally, 'type' may be passed to limit the results to a specific
        guest type.  For a full list of guest types, call the "guest.types"
        method.

        """
        with Session() as session:
            if type and type.upper() in c.GROUP_TYPE_VARS:
                query = session.query(GuestGroup).filter_by(group_type=getattr(c, type.upper()))
            else:
                query = session.query(GuestGroup)
            return [guest.to_dict(self.fields) for guest in query]


@all_api_auth('api_read')
class MivsLookup:
    fields = {
        'name': True,
        'address': True,
        'website': True,
        'twitter': True,
        'facebook': True,
        'status_label': True,
        'staff_notes': True,
        'group': {
            'name': True,
        },
        'developers': {
            'full_name': True,
            'first_name': True,
            'last_name': True,
            'email': True,
            'cellphone': True,
        },
    }

    def statuses(self):
        return c.MIVS_STUDIO_STATUS_VARS

    def list(self, status=False):
        """
        Returns a list of MIVS studios and their developers.

        Optionally, 'status' may be passed to limit the results to MIVS
        studios with a specific status. Use 'confirmed' to get MIVS teams
        who are attending the event.

        For a full list of statuses, call the "mivs.statuses" method.

        """
        with Session() as session:
            if status and status.upper() in c.MIVS_STUDIO_STATUS_VARS:
                query = session.query(IndieStudio).filter_by(status=getattr(c, status.upper()))
            else:
                query = session.query(IndieStudio)
            return [mivs.to_dict(self.fields) for mivs in query]

    def export_judges(self):
        """
        Returns a set of tuples of MIVS judges and their corresponding attendees.
        Excludes judges that were disqualified or opted out of judging.

        Results are returned in the format expected by
        <a href="../showcase_admin/import_judges">the MIVS judge importer</a>.
        """
        judges_list = []
        with Session() as session:
            judges = session.query(IndieJudge).filter(not_(IndieJudge.status.in_([c.CANCELLED, c.DISQUALIFIED])))


            for judge in judges:
                fields = AttendeeLookup.attendee_import_fields + Attendee.import_fields
                judges_list.append((judge.to_dict(), judge.attendee.to_dict(fields)))

            return judges_list
    
    def lookup_judge(self, id):
        try:
            str(uuid.UUID(id))
        except Exception as e:
            raise HTTPError(400, f"Invalid ID: {str(e)}")

        with Session() as session:
            judge = session.query(IndieJudge).filter(IndieJudge.id == id).first()
            if judge:
                return judge.to_dict()
            else:
                raise HTTPError(404, f'No judge found with ID {id}.')


@all_api_auth('api_read')
class AttendeeLookup:
    fields = {
        'full_name': True,
        'first_name': True,
        'last_name': True,
        'legal_name': True,
        'email': True,
        'zip_code': True,
        'address1': True,
        'address2': True,
        'city': True,
        'region': True,
        'country': True,
        'cellphone': True,
        'ec_name': True,
        'ec_phone': True,
        'checked_in': True,
        'badge_num': True,
        'badge_printed_name': True,
        'badge_status_label': True,
        'badge_type_label': True,
        'amount_unpaid': True,
        'donation_tier': True,
        'donation_tier_label': True,
        'staffing': True,
        'is_dept_head': True,
        'ribbon_labels': True,
        'public_id': True,
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
                'start_time', 'end_time', 'extra15', 'weight'
            ]
        },
        'group': {
            'name': True,
        },
    })

    attendee_import_fields = [
        'first_name',
        'last_name',
        'legal_name',
        'birthdate',
        'email',
        'zip_code',
        'address1',
        'address2',
        'city',
        'region',
        'country',
        'birthdate',
        'international',
        'ec_name',
        'ec_phone',
        'cellphone',
        'badge_printed_name',
        'badge_num',
        'found_how',
        'comments',
        'admin_notes',
        'all_years',
        'badge_status',
        'badge_status_label',
    ]

    group_attendee_import_fields = [
        'placeholder',
        'paid',
        'badge_type',
        'ribbon',
    ]

    def lookup(self, badge_num, full=False):
        """
        Returns a single attendee by badge number.

        Takes the badge number as the first parameter.

        Optionally, "full" may be passed as the second parameter to return the
        complete attendee record, including departments, shifts, and food
        restrictions.
        """
        with Session() as session:
            attendee_query = session.query(Attendee).join(BadgeInfo).filter(BadgeInfo.ident == badge_num)
            fields, attendee_query = _attendee_fields_and_query(full, attendee_query)
            attendee = attendee_query.first()
            if attendee:
                return attendee.to_dict(fields)
            else:
                raise HTTPError(404, 'No attendee found with badge #{}'.format(badge_num))

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
            attendee_query, error = session.search(query)
            if error:
                raise HTTPError(400, error)
            fields, attendee_query = _attendee_fields_and_query(full, attendee_query)
            return [a.to_dict(fields) for a in attendee_query.limit(100)]

    def login(self, first_name, last_name, email, zip_code):
        """
        Does a lookup similar to the volunteer checklist pages login screen.
        """
        # this code largely copied from above with different fields
        with Session() as session:
            attendee_query = session.query(Attendee).filter(Attendee.first_name.ilike(first_name),
                                                            Attendee.last_name.ilike(last_name),
                                                            Attendee.email.ilike(email),
                                                            Attendee.zip_code.ilike(zip_code))
            fields, attendee_query = _attendee_fields_and_query(False, attendee_query)
            try:
                attendee = attendee_query.one()
            except MultipleResultsFound:
                raise HTTPError(404, 'found more than one attendee with matching information?')
            except NoResultFound:
                raise HTTPError(404, 'No attendee found with matching information')

            return attendee.to_dict(fields)

    def export(self, query, full=False):
        """
        Searches for attendees by either email, "first last" name, or
        "first last &lt;email&gt;" combinations.

        `query` should be a comma or newline separated list of email/name
        queries.

        Example:
        <pre>Merrium Webster, only.email@example.com, John Doe &lt;jdoe@example.com&gt;</pre>

        Results are returned in the format expected by
        <a href="../reg_admin/import_attendees">the attendee importer</a>.
        """
        names, emails, names_and_emails, ids = _query_to_names_emails_ids(query)

        with Session() as session:
            if full:
                options = [
                    subqueryload(Attendee.dept_memberships).subqueryload(DeptMembership.department),
                    subqueryload(Attendee.dept_roles).subqueryload(DeptRole.department)]
            else:
                options = []

            email_attendees = []
            if emails:
                email_attendees = session.query(Attendee).filter(Attendee.normalized_email.in_(list(emails.keys()))) \
                    .options(*options).order_by(Attendee.email, Attendee.id).all()

            known_emails = set(a.normalized_email for a in email_attendees)
            unknown_emails = sorted([raw for normalized, raw in emails.items() if normalized not in known_emails])

            name_attendees = []
            if names:
                filters = [
                    and_(func.lower(Attendee.first_name) == first, func.lower(Attendee.last_name) == last)
                    for first, last in names.keys()]
                name_attendees = session.query(Attendee).filter(or_(*filters)) \
                    .options(*options).order_by(Attendee.email, Attendee.id).all()

            known_names = set((a.first_name.lower(), a.last_name.lower()) for a in name_attendees)
            unknown_names = sorted([raw for normalized, raw in names.items() if normalized not in known_names])

            name_and_email_attendees = []
            if names_and_emails:
                filters = [
                    and_(
                        func.lower(Attendee.first_name) == first,
                        func.lower(Attendee.last_name) == last,
                        Attendee.normalized_email == email)
                    for first, last, email in names_and_emails.keys()]
                name_and_email_attendees = session.query(Attendee).filter(or_(*filters)) \
                    .options(*options).order_by(Attendee.email, Attendee.id).all()

            known_names_and_emails = set(
                (a.first_name.lower(), a.last_name.lower(), a.normalized_email) for a in name_and_email_attendees)
            unknown_names_and_emails = sorted([
                raw for normalized, raw in names_and_emails.items() if normalized not in known_names_and_emails])

            id_attendees = []
            if ids:
                id_attendees = session.query(Attendee).filter(Attendee.id.in_(ids)) \
                    .options(*options).order_by(Attendee.email, Attendee.id).all()

            known_ids = set(str(a.id) for a in id_attendees)
            unknown_ids = sorted([i for i in ids if i not in known_ids])

            seen = set()
            all_attendees = [
                a for a in (id_attendees + email_attendees + name_attendees + name_and_email_attendees)
                if a.id not in seen and not seen.add(a.id)]

            fields = AttendeeLookup.attendee_import_fields + Attendee.import_fields
            if full:
                fields.extend(['shirt'])

            attendees = _prepare_attendees_export(all_attendees, include_depts=full, include_account_ids=full)

            return {
                'unknown_ids': unknown_ids,
                'unknown_emails': unknown_emails,
                'unknown_names': unknown_names,
                'unknown_names_and_emails': unknown_names_and_emails,
                'attendees': attendees,
            }

    @api_auth('api_create')
    def create(self, first_name, last_name, email, params):
        """
        Create an attendee with at least a first name, last name, and email. Prevents duplicate attendees.

        `params` should be a dictionary with column name: value to set other values, or a falsey value.
        Use labels for Choice and MultiChoice columns, and a string like "no" or "yes" for Boolean columns.
        Date and DateTime columns should be parsed correctly as long as they follow a standard format.

        Example `params` dictionary for setting extra parameters:
        <pre>{"placeholder": "yes", "legal_name": "First Last", "cellphone": "5555555555"}</pre>
        """
        with Session() as session:
            attendee_query = session.query(Attendee).filter(Attendee.first_name.ilike(first_name),
                                                            Attendee.last_name.ilike(last_name),
                                                            Attendee.email.ilike(email))

            if attendee_query.first():
                raise HTTPError(400, 'An attendee with this name and email address already exists')

            attendee = Attendee(first_name=first_name, last_name=last_name, email=email)

            if params:
                for key, val in params.items():
                    if val != "":
                        params[key] = _parse_if_datetime(key, val)
                        params[key] = _parse_if_boolean(key, val)

            attendee.apply(params, restricted=False)
            session.add(attendee)

            # Staff (not volunteers) also almost never need to pay by default
            if (attendee.staffing and c.VOLUNTEER_RIBBON not in attendee.ribbon_ints) and 'paid' not in params:
                attendee.paid = c.NEED_NOT_PAY

            message = check(attendee)
            if message:
                session.rollback()
                raise HTTPError(400, message)

            return attendee.id

    @api_auth('api_update')
    def update(self, id, params):
        """
        Update an attendee using their unique ID, returned by our lookup functions.

        `params` should be a dictionary with column name: value to update values.
        Use labels for Choice and MultiChoice columns, and a string like "no" or "yes" for Boolean columns.
        Date and DateTime columns should be parsed correctly as long as they follow a standard format.

        Example:
        <pre>{"first_name": "First", "paid": "doesn't need to", "ribbon": "Volunteer, Panelist"}</pre>
        """
        with Session() as session:
            attendee = session.attendee(id, allow_invalid=True)

            if not attendee:
                raise HTTPError(404, 'No attendee found with this ID')

            if not params:
                raise HTTPError(400, 'Please provide parameters to update')

            for key, val in params.items():
                params[key] = _parse_if_datetime(key, val)
                params[key] = _parse_if_boolean(key, val)

            for key, val in params.items():
                if not hasattr(Attendee, key):
                    return HTTPError(400, 'Attendee has no field {}'.format(key))
                setattr(attendee, key, val)

            message = check(attendee)
            if message:
                session.rollback()
                raise HTTPError(400, message)

            # Staff (not volunteers) also almost never need to pay by default
            if attendee.staffing and not attendee.orig_value_of('staffing') \
                    and c.VOLUNTEER_RIBBON not in attendee.ribbon_ints and 'paid' not in params:
                attendee.paid = c.NEED_NOT_PAY

            return attendee.id


@all_api_auth('api_read')
class AttendeeAccountLookup:
    def export_attendees(self, id, full=False, include_group=False):
        """
        Exports attendees by their attendee account ID.

        `id` is the UUID of the account.

        `full` includes the attendee's individual applications, such as art show.

        `include_group` exports attendees in groups. This should be done rarely, as
        you should be importing groups with their attendees before importing accounts.

        Results are returned in the format expected by
        <a href="../reg_admin/import_attendees">the attendee importer</a>.
        """

        with Session() as session:
            account = session.query(AttendeeAccount).filter(AttendeeAccount.id == id).first()

            if not account:
                raise HTTPError(404, 'No attendee account found with this ID')

            attendees_to_export = account.valid_attendees if include_group \
                else [a for a in account.valid_attendees if not a.group]

            attendees = _prepare_attendees_export(attendees_to_export, include_apps=full)
            return {
                'attendees': attendees,
            }

    def export(self, query, all=False):
        """
        Searches for attendee accounts by either email or id.

        `query` should be a comma or newline separated list of email/id
        queries.

        `all` ignores the query and returns all attendee accounts.

        Example:
        <pre>account.email@example.com, e3a670c4-8f7e-4d62-841d-49f73f58d8b1</pre>
        """
        names, emails, names_and_emails, ids = _query_to_names_emails_ids(query)
        unknown_emails = []
        unknown_ids = []

        with Session() as session:
            if all:
                all_accounts = session.query(AttendeeAccount).all()
            else:
                email_accounts = []
                if emails:
                    email_accounts = session.query(AttendeeAccount).filter(
                        AttendeeAccount.email.in_(list(emails.keys()))
                        ).options(subqueryload(AttendeeAccount.attendees)
                                  ).order_by(AttendeeAccount.email, AttendeeAccount.id).all()

                known_emails = set(a.normalized_email for a in email_accounts)
                unknown_emails = sorted([raw for normalized, raw in emails.items() if normalized not in known_emails])

                id_accounts = []
                if ids:
                    id_accounts = session.query(AttendeeAccount).filter(
                        AttendeeAccount.id.in_(ids)).options(subqueryload(AttendeeAccount.attendees)
                                                             ).order_by(AttendeeAccount.email,
                                                                        AttendeeAccount.id).all()

                known_ids = set(str(a.id) for a in id_accounts)
                unknown_ids = sorted([i for i in ids if i not in known_ids])

                seen = set()
                all_accounts = [
                    a for a in (id_accounts + email_accounts)
                    if a.id not in seen and not seen.add(a.id)]

            accounts = []
            for a in all_accounts:
                d = a.to_dict(['id', 'email', 'hashed'])

                attendees = {}
                for attendee in a.attendees:
                    attendees[attendee.id] = attendee.full_name + " <{}>".format(attendee.email)

                d.update({
                    'attendees': attendees,
                })
                accounts.append(d)

            return {
                'unknown_ids': unknown_ids,
                'unknown_emails': unknown_emails,
                'accounts': accounts,
            }


@all_api_auth('api_read')
class AttractionLookup:
    def list(self):
        """
        Returns a list of all attractions
        """
        with Session() as session:
            return [(id, name) for id, name in session.query(Attraction.id, Attraction.name).order_by(Attraction.name).all()]

    @department_id_adapter
    @api_auth('api_read')
    def features_events(self, attraction_id):
        """
        Returns a list of all features and events for the given attraction.

        Takes the attraction id as the first parameter. For a list of all
        attraction ids call the "attraction.list" method.
        """
        with Session() as session:
            attraction = session.query(Attraction).filter_by(id=attraction_id).first()
            if not attraction:
                raise HTTPError(404, 'Attraction id not found: {}'.format(attraction_id))
            return attraction.to_dict({
                'id': True,
                'name': True,
                'description': True,
                'full_description': True,
                'checkin_reminder': True,
                'advance_checkin': True,
                'restriction': True,
                'badge_num_required': True,
                'populate_schedule': True,
                'no_notifications': True,
                'waitlist_available': True,
                'waitlist_slots': True,
                'signups_open_relative': True,
                'signups_open_time': True,
                'slots': True,
                'department': {
                    'id': True,
                    'name': True,
                },
                'features': {
                    'id': True,
                    'name': True,
                    'description': True,
                    'badge_num_required': True,
                    'populate_schedule': True,
                    'no_notifications': True,
                    'waitlist_available': True,
                    'waitlist_slots': True,
                    'signups_open_relative': True,
                    'signups_open_time': True,
                    'slots': True,
                    'events': {
                        'id': True,
                        'start_time': True,
                        'duration': True,
                        'populate_schedule': True,
                        'no_notifications': True,
                        'waitlist_available': True,
                        'waitlist_slots': True,
                        'signups_open_relative': True,
                        'signups_open_time': True,
                        'slots': True,
                        'location': {
                            'id': True,
                            'name': True,
                            'room': True,
                        }
                    }
                }
            })


@all_api_auth('api_update')
class JobLookup:
    fields = {
        'name': True,
        'description': True,
        'department_name': True,
        'start_time': True,
        'end_time': True,
        'duration': True,
        'slots': True,
        'slots_taken': True,
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
    @api_auth('api_read')
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
                raise HTTPError(400, message)
            else:
                session.commit()
                return session.job(job_id).to_dict(self.fields)

    def unassign(self, shift_id):
        """
        Unassigns whomever is working the given shift.

        Takes the shift id as the only parameter.
        """
        with Session() as session:
            shift = session.query(Shift).filter_by(id=shift_id).first()
            if not shift:
                raise HTTPError(404, 'Shift id not found:{}'.format(shift_id))

            session.delete(shift)
            session.commit()
            return session.job(shift.job_id).to_dict(self.fields)

    @docstring_format(
        _format_opts(c.WORKED_STATUS_OPTS),
        _format_opts(c.RATING_OPTS))
    def set_worked(self, shift_id, status=c.SHIFT_WORKED, rating=c.UNRATED, comment=''):
        """
        Sets the given shift status as worked or not worked.

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
            assert c.WORKED_STATUS[status] is not None
        except Exception:
            raise HTTPError(400, 'Invalid status: {}'.format(status))

        try:
            rating = int(rating)
            assert c.RATINGS[rating] is not None
        except Exception:
            raise HTTPError(400, 'Invalid rating: {}'.format(rating))

        if rating in (c.RATED_BAD, c.RATED_GREAT) and not comment:
            raise HTTPError(400, 'You must leave a comment explaining why the staffer was rated as: {}'.format(
                c.RATINGS[rating]))

        with Session() as session:
            shift = session.query(Shift).filter_by(id=shift_id).first()
            if not shift:
                raise HTTPError(404, 'Shift id not found:{}'.format(shift_id))

            shift.worked = status
            shift.rating = rating
            shift.comment = comment
            session.commit()
            return session.job(shift.job_id).to_dict(self.fields)


@all_api_auth('api_read')
class GroupLookup:
    fields = {
        'name': True,
        'badges': True,
        'admin_notes': True,
        'can_add': True,
    }

    dealer_fields = dict(fields, **{
        'tables': True,
        'wares': True,
        'description': True,
        'zip_code': True,
        'address1': True,
        'address2': True,
        'city': True,
        'region': True,
        'country': True,
        'website': True,
        'special_needs': True,
        'categories': True,
        'categories_text': True,
    })

    group_import_fields = [
        'name',
        'admin_notes',
        'badges',
        'can_add',
    ]

    dealer_import_fields = [
        'tables',
        'wares',
        'description',
        'zip_code',
        'address1',
        'address2',
        'city',
        'region',
        'country',
        'website',
        'special_needs',
        'categories',
        'categories_text',
    ]

    def dealers(self, status=None):
        """
        Returns a list of Groups that are also dealers.

        Optionally, `status` may be passed to limit the results to dealers with a specific
        status.

        """
        with Session() as session:
            filters = [Group.is_dealer == True]  # noqa: E712
            if status and status.upper() in c.DEALER_STATUS_VARS:
                filters += [Group.status == getattr(c, status.upper())]
            query = session.query(Group).filter(*filters)
            groups = []

            for g in query.all():
                d = g.to_dict(['id'] + GroupLookup.group_import_fields + Group.import_fields
                              + GroupLookup.dealer_import_fields)

                attendees = {}
                for attendee in g.attendees:
                    if not attendee.is_unassigned:
                        attendees[attendee.id] = attendee.full_name + " <{}>".format(attendee.email)

                d.update({
                    'assigned_attendees': attendees,
                })
                groups.append(d)

            return {'groups': groups}

    def export_attendees(self, id, full=False):
        """
        Exports attendees by their group ID. Excludes unassigned attendees.

        `id` is the UUID of the group.

        `full` includes the attendee's individual applications, such as art show.

        Results are returned in the format expected by
        <a href="../reg_admin/import_attendees">the attendee importer</a>.

        Attendee account IDs are also included so that group members can be imported
        with their accounts.
        """

        with Session() as session:
            group = session.query(Group).filter(Group.id == id).first()

            if not group:
                raise HTTPError(404, 'No group found with this ID')

            attendees_to_export = [a for a in group.attendees if not a.is_unassigned and a.is_valid]
            attendees = _prepare_attendees_export(attendees_to_export, include_account_ids=True,
                                                  include_apps=full, is_group_attendee=True)

            if group.unassigned:
                unassigned_badge_type = group.unassigned[0].badge_type
                unassigned_ribbon = group.unassigned[0].ribbon
            else:
                unassigned_badge_type, unassigned_ribbon = c.ATTENDEE_BADGE, None

            return {
                'attendees': attendees,
                'group_leader_id': group.leader.id,
                'unassigned_badge_type': unassigned_badge_type,
                'unassigned_ribbon': unassigned_ribbon,
            }

    def export(self, query, full=False):
        """
        Searches for groups by group name or ID.

        `query` should be a comma or newline separated list of ID/name
        queries.

        Example:
        <pre>Group Name, 962f1d9d-0799-4a4a-a346-7ab9e737f0a4</pre>

        Results are returned in the format expected by
        <a href="../reg_admin/import_groups">the group importer</a>.
        """
        names, emails, names_and_emails, ids = _query_to_names_emails_ids(query, split_names=False)

        with Session() as session:
            name_groups = []
            if names:
                name_groups = session.query(Group).filter(Group.name.in_(names)) \
                    .order_by(Group.name).all()

            known_names = set(str(a.name) for a in name_groups)
            unknown_names = sorted([n for n in names if n not in known_names])

            id_groups = []
            if ids:
                id_groups = session.query(Group).filter(Group.id.in_(ids)) \
                    .order_by(Group.name).all()

            known_ids = set(str(a.id) for a in id_groups)
            unknown_ids = sorted([i for i in ids if i not in known_ids])

            seen = set()
            all_groups = [
                a for a in (id_groups + name_groups)
                if a.id not in seen and not seen.add(a.id)]

            fields = GroupLookup.group_import_fields + Group.import_fields

            groups = []
            for g in all_groups:
                if full and g.is_dealer:
                    d = g.to_dict(fields + GroupLookup.dealer_import_fields)
                else:
                    d = g.to_dict(fields)

                attendees = {}
                for attendee in g.attendees:
                    if not attendee.is_unassigned:
                        attendees[attendee.id] = attendee.full_name + " <{}>".format(attendee.email)

                d.update({
                    'assigned_attendees': attendees,
                })

                groups.append(d)

            return {
                'unknown_ids': unknown_ids,
                'unknown_names': unknown_names,
                'groups': groups,
            }


@all_api_auth('api_read')
class DepartmentLookup:
    def list(self):
        """
        Returns a list of department ids and names.
        """
        return c.DEPARTMENTS

    @department_id_adapter
    @api_auth('api_read')
    def members(self, department_id, full=False):
        """
        Returns an object with all members of this department broken down by their roles.

        Takes the department id and 'full' to return attendees' full list of fields.
        """
        with Session() as session:
            department = session.query(Department).filter_by(id=department_id).first()
            if not department:
                raise HTTPError(404, 'Department id not found: {}'.format(department_id))
            if full:
                attendee_fields = AttendeeLookup.fields_full
            else:
                attendee_fields = AttendeeLookup.fields
            return department.to_dict({
                'id': True,
                'name': True,
                'description': True,
                'dept_roles': True,
                'dept_heads': attendee_fields,
                'checklist_admins': attendee_fields,
                'members_with_inherent_role': attendee_fields,
                'members_who_can_admin_checklist': attendee_fields,
                'pocs': attendee_fields,
                'members': attendee_fields
            })

    @department_id_adapter
    @api_auth('api_read')
    def jobs(self, department_id):
        """
        Returns a list of all roles and jobs for the given department.

        Takes the department id as the first parameter. For a list of all
        department ids call the "dept.list" method.
        """
        with Session() as session:
            department = session.query(Department).filter_by(id=department_id).first()
            if not department:
                raise HTTPError(404, 'Department id not found: {}'.format(department_id))
            return department.to_dict({
                'id': True,
                'name': True,
                'description': True,
                'solicits_volunteers': True,
                'is_shiftless': True,
                'max_consecutive_minutes': True,
                'from_email': True,
                'manages_panels': True,
                'handles_cash': True,
                'panels_desc': True,
                'jobs': {
                    'id': True,
                    'name': True,
                    'description': True,
                    'start_time': True,
                    'duration': True,
                    'weight': True,
                    'slots': True,
                    'extra15': True,
                    'visibility': True,
                    'all_roles_required': True,
                    'required_roles': {'id': True},
                    'job_template_id': True,
                },
                'dept_roles': {
                    'id': True,
                    'name': True,
                    'description': True,
                },
                'job_templates': {
                    'id': True,
                    'template_name': True,
                    'type': True,
                    'name': True,
                    'description': True,
                    'duration': True,
                    'weight': True,
                    'extra15': True,
                    'visibility': True,
                    'all_roles_required': True,
                    'min_slots': True,
                    'days': True,
                    'open_time': True,
                    'close_time': True,
                    'interval': True,
                    'required_roles': {'id': True},
                },
                'attractions': {
                    'id': True,
                    'name': True,
                    'description': True,
                    'full_description': True,
                    'checkin_reminder': True,
                    'advance_checkin': True,
                    'restriction': True,
                    'badge_num_required': True,
                    'populate_schedule': True,
                    'no_notifications': True,
                    'waitlist_available': True,
                    'waitlist_slots': True,
                    'signups_open_relative': True,
                    'signups_open_time': True,
                    'slots': True,
                }
            })


@all_api_auth('api_read')
class ConfigLookup:
    fields = [
        'EVENT_NAME',
        'ORGANIZATION_NAME',
        'EVENT_YEAR',
        'EPOCH',
        'ESCHATON',
        'SHIFTS_EPOCH',
        'SHIFTS_ESCHATON',
        'PANELS_EPOCH',
        'PANELS_ESCHATON',
        'EVENT_VENUE',
        'EVENT_VENUE_ADDRESS',
        'EVENT_TIMEZONE',
        'AT_THE_CON',
        'POST_CON',
        'URL_BASE',
        'URL_ROOT',
        'PATH',
        'BADGE_PRICE',
        'BADGES_SOLD',
        'REMAINING_BADGES',
    ]

    def info(self):
        """
        Returns a list of all available configuration settings.
        """
        output = {field: getattr(c, field) for field in self.fields}

        # This is to allow backward compatibility with pre 1.0 code
        output['YEAR'] = c.EVENT_YEAR
        output['API_VERSION'] = __version__
        output['EVENT_TIMEZONE'] = str(output['EVENT_TIMEZONE'])
        return output

    def lookup(self, field):
        """
        Returns the given configuration setting. Takes the setting
        name as a single argument. For a list of available settings,
        call the "config.info" method.
        """
        if field.upper() in self.fields:
            return getattr(c, field.upper())
        else:
            raise HTTPError(404, 'Config field not found: {}'.format(field))


@all_api_auth('api_read')
class HotelLookup:
    def eligible_attendees(self):
        """
        Returns a list of hotel eligible attendees
        """
        with Session() as session:
            attendees = session.query(Attendee.id).filter(Attendee.hotel_eligible == True).all()  # noqa: E712
            return [x.id for x in attendees]

    @api_auth('api_update')
    def update_room(self, id=None, **kwargs):
        """
        Create or update a hotel room. If the id of an existing room is
        supplied then it will attempt to update an existing room.
        Possible attributes are notes, message, locked_in, nights, and created.

        Returns the created room, with its id.
        """
        with Session() as session:
            if id:
                room = session.query(Room).filter(Room.id == id).one_or_none()
                if not room:
                    return HTTPError(404, "Could not locate room {}".format(id))
            else:
                room = Room()
            for attr in ['notes', 'message', 'locked_in', 'nights', 'created']:
                if attr in kwargs:
                    setattr(room, attr, kwargs[attr])
            session.add(room)
            session.commit()
            return room.to_dict()

    @api_auth('api_update')
    def update_request(self, id=None, **kwargs):
        """
        Create or update a hotel request. If the id is supplied then it will
        attempt to update the given request.
        Possible attributes are attendee_id, nights, wanted_roommates, unwanted_roommates, special_needs, and approved.

        Returns the created or updated request.
        """
        with Session() as session:
            if id:
                hotel_request = session.query(HotelRequests).filter(HotelRequests.id == id).one_or_none()
                if not hotel_request:
                    return HTTPError(404, "Could not locate request {}".format(id))
            else:
                hotel_request = HotelRequests()
            for attr in ['attendee_id', 'nights', 'wanted_roommates', 'unwanted_roommates',
                         'special_needs', 'approved']:
                if attr in kwargs:
                    setattr(hotel_request, attr, kwargs[attr])
            session.add(hotel_request)
            session.commit()
            return hotel_request.to_dict()

    @api_auth('api_update')
    def update_assignment(self, id=None, **kwargs):
        """
        Create or update a hotel room assignment. If the id is supplied then it will
        attempt to update the given request. Otherwise a new one is created.
        Possible attributes are room_id, and attendee_id.

        Returns the created or updated assignment.
        """
        with Session() as session:
            if id:
                assignment = session.query(RoomAssignment).filter(RoomAssignment.id == id).one_or_none()
                if not assignment:
                    return HTTPError(404, "Could not locate room assignment {}".format(id))
            else:
                assignment = RoomAssignment()
            for attr in ['room_id', 'attendee_id']:
                if attr in kwargs:
                    setattr(assignment, attr, kwargs[attr])
            session.add(assignment)
            session.commit()
            return assignment.to_dict()

    def nights(self):
        """
        Returns the available room nights.
        """
        return {
            "core_nights": c.CORE_NIGHTS,
            "setup_nights": c.SETUP_NIGHTS,
            "teardown_nights": c.TEARDOWN_NIGHTS,
            "dates": c.NIGHT_DATES,
            "order": c.NIGHT_DISPLAY_ORDER,
            "names": c.NIGHT_NAMES
        }


@all_api_auth('api_read')
class ScheduleLookup:
    def schedule(self):
        """
        Returns the entire schedule in machine parseable format.
        """
        with Session() as session:
            return [
                {
                    'name': event.name,
                    'location': event.location_name,
                    'start': event.start_time_local.strftime('%I%p %a').lstrip('0'),
                    'end': event.end_time_local.strftime('%I%p %a').lstrip('0'),
                    'start_unix': int(mktime(event.start_time.utctimetuple())),
                    'end_unix': int(mktime(event.end_time.utctimetuple())),
                    'duration': event.duration,
                    'description': event.public_description or event.description,
                    'panelists': [panelist.attendee.full_name for panelist in event.assigned_panelists]
                }
                for event in sorted(session.query(Event).all(), key=lambda e: [e.start_time, e.location_name])
            ]


@all_api_auth('api_read')
class BarcodeLookup:
    def lookup_attendee_from_barcode(self, barcode_value, full=False):
        """
        Returns a single attendee using the barcode value from their badge.

        Takes the (possibly encrypted) barcode value as the first parameter.

        Optionally, "full" may be passed as the second parameter to return the
        complete attendee record, including departments, shifts, and food
        restrictions.
        """
        badge_num = -1
        try:
            result = get_badge_num_from_barcode(barcode_value)
            badge_num = result['badge_num']
        except Exception as e:
            raise HTTPError(500, "Couldn't look up barcode value: " + str(e))

        # Note: A decrypted barcode can yield a valid badge num,
        # but that badge num may not be assigned to an attendee.
        with Session() as session:
            query = session.query(Attendee).join(BadgeInfo).filter(BadgeInfo.ident == badge_num)
            fields, query = _attendee_fields_and_query(full, query)
            attendee = query.first()
            if attendee:
                return attendee.to_dict(fields)
            else:
                raise HTTPError(404, 'Valid barcode, but no attendee found with Badge #{}'.format(badge_num))

    def lookup_badge_number_from_barcode(self, barcode_value):
        """
        Returns a badge number using the barcode value from the given badge.

        Takes the (possibly encrypted) barcode value as a single parameter.
        """
        try:
            result = get_badge_num_from_barcode(barcode_value)
            return {'badge_num': result['badge_num']}
        except Exception as e:
            raise HTTPError(500, "Couldn't look up barcode value: " + str(e))


class PrintJobLookup:
    def _build_job_json_data(self, job):
        result_json = job.json_data
        result_json['admin_name'] = job.admin_name
        result_json['printer_id'] = job.printer_id
        result_json['reg_station'] = job.reg_station
        result_json['is_minor'] = job.is_minor

        return result_json

    @api_auth('api_read')
    def get_pending(self, printer_ids='', restart=False, dry_run=False):
        """
        Returns pending print jobs' `json_data`.

        Takes either a single printer ID or a comma-separated list of printer IDs as the first parameter.
        If this is set, only the print jobs whose printer_id match one of those in the list are returned.

        Takes the boolean `restart` as the second parameter.
        If true, pulls any print job that's not marked as printed or invalid.
        Otherwise, only print jobs not marked as sent to printer are returned.

        Takes the boolean `dry_run` as the third parameter.
        If true, pulls print jobs without marking them as sent to printer.

        Returns a dictionary of pending jobs' `json_data` plus job metadata, keyed by job ID.
        """

        with Session() as session:
            filters = [PrintJob.printed == None, PrintJob.ready == True, PrintJob.errors == '']  # noqa: E711
            if printer_ids:
                printer_ids = [id.strip() for id in printer_ids.split(',')]
                filters += [PrintJob.printer_id.in_(printer_ids)]
            if not restart:
                filters += [PrintJob.queued == None]  # noqa: E711
            print_jobs = session.query(PrintJob).filter(*filters).all()

            results = {}
            for job in print_jobs:
                if restart:
                    errors = session.update_badge_print_job(job.id)
                    if errors:
                        if job.errors:
                            job.errors += "; "
                        job.errors += "; ".join(errors)
                if not restart or not errors:
                    results[job.id] = self._build_job_json_data(job)
                    if not dry_run:
                        job.queued = datetime.utcnow()
                        session.add(job)
                        session.commit()

        return results

    @api_auth('api_create')
    def create(self, attendee_id, printer_id, reg_station, print_fee=None):
        """
        Create a new print job for a specified badge.

        Takes the attendee ID as the first parameter, the printer ID as the second parameter,
        and the reg station number as the third parameter.

        Takes a print_fee as an optional fourth parameter. If this is not specified, an error
        is returned unless this is the first time this attendee's badge is being printed.

        Returns a dictionary of the new job's `json_data` plus job metadata, keyed by job ID.
        """
        with Session() as session:
            try:
                reg_station = int(reg_station)
            except ValueError:
                raise HTTPError(400, "Reg station must be an integer.")

            attendee = session.query(Attendee).filter_by(id=attendee_id).first()
            if not attendee:
                raise HTTPError(404, "Attendee not found.")

            print_id, errors = session.add_to_print_queue(attendee, printer_id, reg_station, print_fee)
            if errors:
                raise HTTPError(424, "Attendee not ready to print. Error(s): {}".format("; ".join(errors)))

            return {print_id: self._build_job_json_data(session.print_job(print_id))}

    @api_auth('api_update')
    def add_error(self, job_ids, error):
        """
        Adds an error message to a print job, effectively marking it invalid.

        Takes either a single job ID or a comma-seperated list of job IDs as the first parameter.

        Takes the error message as the second parameter.

        Returns a dictionary of changed jobs' `json_data` plus job metadata, keyed by job ID.
        """
        with Session() as session:
            if not job_ids:
                raise HTTPError(400, "You must provide at least one job ID.")

            job_ids = [id.strip() for id in job_ids.split(',')]
            jobs = session.query(PrintJob).filter(PrintJob.id.in_(job_ids)).all()

            if not jobs:
                raise HTTPError(404, '"No jobs found with those IDs."')

            results = {}

            for job in jobs:
                results[job.id] = self._build_job_json_data(job)
                if job.errors:
                    job.errors += "; " + error
                else:
                    job.errors = error
                session.add(job)
                session.commit()

            return results

    @api_auth('api_update')
    def mark_complete(self, job_ids=''):
        """
        Marks print jobs as printed.

        Takes either a single job ID or a comma-separated list of job IDs as the first parameter.

        Returns a dictionary of changed jobs' `json_data` plus job metadata, keyed by job ID.
        """
        with Session() as session:
            base_query = session.query(PrintJob).filter_by(printed=None)

            if not job_ids:
                raise HTTPError(400, "You must provide at least one job ID.")

            job_ids = [id.strip() for id in job_ids.split(',')]
            jobs = base_query.filter(PrintJob.id.in_(job_ids)).all()

            if not jobs:
                raise HTTPError(404, '"No jobs found with those IDs."')

            results = {}

            for job in jobs:
                results[job.id] = self._build_job_json_data(job)
                job.printed = datetime.utcnow()
                session.add(job)
                session.commit()

            return results

    @api_auth('api_update')
    def clear_jobs(self, printer_ids='', all=False, invalidate=False, error=''):
        """
        Marks all pending print jobs as either printed or invalid, effectively clearing them from the queue.

        Takes either a single printer ID, comma-separated list of printer IDs, or empty string as the first parameter.
        If this is set, only the print jobs whose printer_id match one of those in the list are cleared.

        Takes the boolean `all` as the second parameter.
        If true, all jobs are cleared. Otherwise, at least one printer_id is required.

        Takes the boolean `invalidate` as the third parameter.
        If true, cleared jobs are marked invalid instead of printed (the default), marked with the parameter `error`.

        Returns a dictionary of changed jobs' `json_data` plus job metadata, keyed by job ID.
        """
        with Session() as session:
            filters = [PrintJob.printed == None, PrintJob.ready == True, PrintJob.errors == '']  # noqa: E711

            if printer_ids:
                printer_ids = [id.strip() for id in printer_ids.split(',')]
                filters += [PrintJob.printer_id.in_(printer_ids)]
            elif not all:
                raise HTTPError(400, "You must provide at least one printer ID or set all to true.")

            jobs = session.query(PrintJob).filter(*filters).all()

            if invalidate and not error:
                raise HTTPError(400, "You must provide an error message to invalidate jobs.")

            results = {}

            for job in jobs:
                results[job.id] = self._build_job_json_data(job)
                if invalidate:
                    if job.errors:
                        job.errors += "; " + error
                    else:
                        job.errors = error
                else:
                    job.printed = datetime.utcnow()
                session.add(job)
                session.commit()

            return results


if c.API_ENABLED:
    register_jsonrpc(AttendeeLookup(), 'attendee')
    register_jsonrpc(AttendeeAccountLookup(), 'attendee_account')
    register_jsonrpc(AttractionLookup(), 'attraction')
    register_jsonrpc(GroupLookup(), 'group')
    register_jsonrpc(JobLookup(), 'shifts')
    register_jsonrpc(DepartmentLookup(), 'dept')
    register_jsonrpc(ConfigLookup(), 'config')
    register_jsonrpc(BarcodeLookup(), 'barcode')
    register_jsonrpc(GuestLookup(), 'guest')
    register_jsonrpc(MivsLookup(), 'mivs')
    register_jsonrpc(HotelLookup(), 'hotel')
    register_jsonrpc(ScheduleLookup(), 'schedule')
    register_jsonrpc(PrintJobLookup(), 'print_job')
