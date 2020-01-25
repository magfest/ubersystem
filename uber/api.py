import re
import uuid
from datetime import datetime
from functools import wraps

import cherrypy
import pytz
import six
from cherrypy import HTTPError
from dateutil import parser as dateparser
from pockets import unwrap
from time import mktime
from residue import UTCDateTime
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import subqueryload
from sqlalchemy.orm.exc import MultipleResultsFound, NoResultFound
from sqlalchemy.types import Boolean, Date

from uber.barcode import get_badge_num_from_barcode
from uber.config import c
from uber.decorators import department_id_adapter
from uber.errors import CSRFException
from uber.models import AdminAccount, ApiToken, Attendee, Department, DeptMembership, DeptMembershipRequest, \
    Event, IndieStudio, Job, Session, Shift, GuestGroup, Room, HotelRequests, RoomAssignment
from uber.server import register_jsonrpc
from uber.utils import check, check_csrf, normalize_newlines


__version__ = '1.0'


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
            subqueryload(Attendee.shifts).subqueryload(Shift.job))
    else:
        fields = AttendeeLookup.fields
        query = query.options(subqueryload(Attendee.dept_memberships))
    return (fields, query)


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
    # This should be in the UTCDateTime and Date classes, but they're not defined in this app
    if hasattr(getattr(Attendee, key), 'type') and (
            isinstance(getattr(Attendee, key).type, UTCDateTime) or isinstance(getattr(Attendee, key).type, Date)):
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
            'other_social_media': True,
            'teaser_song_url': True,
            'pic_url': True
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


@all_api_auth('api_read')
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
        'amount_unpaid': True,
        'donation_tier': True,
        'donation_tier_label': True,
        'donation_tier_paid': True,
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
            attendee_query = session.search(query)
            fields, attendee_query = _attendee_fields_and_query(full, attendee_query)
            return [a.to_dict(fields) for a in attendee_query.limit(100)]
        
    @api_auth('api_update')
    def update(self, **kwargs):
        """
        Updates an existing attendee record. "id" parameter is required and
        sets the attendee to be updated. All other fields are taken as changes
        to the attendee.
        
        Returns the updated attendee.
        """
        if not 'id' in kwargs:
            return HTTPError(400, 'You must provide the id of the attendee.')
        with Session() as session:
            attendee = session.query(Attendee).filter(Attendee.id == kwargs['id']).one()
            if not attendee:
                return HTTPError(404, 'Attendee {} not found.'.format(kwargs['id']))
            for key, val in kwargs.items():
                if not hasattr(Attendee, key):
                    return HTTPError(400, 'Attendee has no field {}'.format(key))
                setattr(attendee, key, val)
            session.add(attendee)
            session.commit()
            return attendee.to_dict(self.fields)

    def login(self, first_name, last_name, email, zip_code):
        """
        Does a lookup similar to the volunteer checklist pages login screen.
        """
        #this code largely copied from above with different fields
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
        <a href="../import/staff">the staff importer</a>.
        """
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
                    email = Attendee.normalize_email(match.group(2))
                    if name:
                        first, last = (_re_whitespace.split(name.lower(), 1) + [''])[0:2]
                        names_and_emails[(first, last, email)] = q
                    else:
                        emails[email] = q
                else:
                    emails[Attendee.normalize_email(q)] = q
            elif q:
                try:
                    ids.add(str(uuid.UUID(q)))
                except Exception:
                    first, last = (_re_whitespace.split(q.lower(), 1) + [''])[0:2]
                    names[(first, last)] = q

        with Session() as session:
            if full:
                options = [
                    subqueryload(Attendee.dept_memberships).subqueryload(DeptMembership.department),
                    subqueryload(Attendee.dept_membership_requests).subqueryload(DeptMembershipRequest.department)]
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

            fields = [
                'first_name',
                'last_name',
                'birthdate',
                'email',
                'zip_code',
                'birthdate',
                'international',
                'ec_name',
                'ec_phone',
                'cellphone',
                'badge_printed_name',
                'found_how',
                'comments',
                'admin_notes',
                'all_years',
                'badge_status',
                'badge_status_label',
            ]
            if full:
                fields.extend(['shirt'])

            attendees = []
            for a in all_attendees:
                d = a.to_dict(fields)
                if full:
                    assigned_depts = {}
                    checklist_admin_depts = {}
                    dept_head_depts = {}
                    poc_depts = {}
                    for membership in a.dept_memberships:
                        assigned_depts[membership.department_id] = membership.department.name
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
                        'requested_depts': {
                            (m.department_id if m.department_id else 'All'):
                            (m.department.name if m.department_id else 'Anywhere')
                            for m in a.dept_membership_requests},
                    })
                attendees.append(d)

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
            attendee_query = session.query(Attendee).filter(Attendee.first_name.ilike("first_name"),
                                                            Attendee.last_name.ilike("last_name"),
                                                            Attendee.email.ilike("email@example.com"))

            if attendee_query.first():
                raise HTTPError(400, 'An attendee with this name and email address already exists')

            attendee = Attendee(first_name=first_name, last_name=last_name, email=email)

            if params:
                for key, val in params.items():
                    params[key] = _parse_if_datetime(key, val)
                    params[key] = _parse_if_boolean(key, val)

            attendee.apply(params, restricted=False)
            session.add(attendee)

            message = check(attendee)
            if message:
                session.rollback()
                raise HTTPError(400, message)

            # Duplicates functionality on the admin form that makes placeholder badges need not pay
            # Staff (not volunteers) also almost never need to pay by default
            if (attendee.placeholder or
                    attendee.staffing and c.VOLUNTEER_RIBBON not in attendee.ribbon_ints) and 'paid' not in params:
                attendee.paid = c.NEED_NOT_PAY

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

            attendee.apply(params, restricted=False)
            message = check(attendee)
            if message:
                session.rollback()
                raise HTTPError(400, message)

            # Staff (not volunteers) also almost never need to pay by default
            if attendee.staffing and not attendee.orig_value_of('staffing') \
                    and c.VOLUNTEER_RIBBON not in attendee.ribbon_ints and 'paid' not in params:
                attendee.paid = c.NEED_NOT_PAY

            return attendee.id


@all_api_auth('api_update')
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
class DepartmentLookup:
    def list(self):
        """
        Returns a list of department ids and names.
        """
        return c.DEPARTMENTS

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
                'is_setup_approval_exempt': True,
                'is_teardown_approval_exempt': True,
                'max_consecutive_hours': True,
                'jobs': {
                    'id': True,
                    'type': True,
                    'name': True,
                    'description': True,
                    'start_time': True,
                    'duration': True,
                    'weight': True,
                    'slots': True,
                    'extra15': True,
                    'visibility': True,
                    'required_roles': {'id': True},
                },
                'dept_roles': {
                    'id': True,
                    'name': True,
                    'description': True,
                },
            })


@all_api_auth('api_read')
class ConfigLookup:
    fields = [
        'EVENT_NAME',
        'ORGANIZATION_NAME',
        'EVENT_YEAR',
        'EPOCH',
        'ESCHATON',
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
            attendees = session.query(Attendee.id).filter(Attendee.hotel_eligible == True).all()
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
            for attr in ['attendee_id', 'nights', 'wanted_roommates', 'unwanted_roommates', 'special_needs', 'approved']:
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
                    'location': event.location_label,
                    'start': event.start_time_local.strftime('%I%p %a').lstrip('0'),
                    'end': event.end_time_local.strftime('%I%p %a').lstrip('0'),
                    'start_unix': int(mktime(event.start_time.utctimetuple())),
                    'end_unix': int(mktime(event.end_time.utctimetuple())),
                    'duration': event.minutes,
                    'description': event.description,
                    'panelists': [panelist.attendee.full_name for panelist in event.assigned_panelists]
                }
                for event in sorted(session.query(Event).all(), key=lambda e: [e.start_time, e.location_label])
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
            query = session.query(Attendee).filter_by(badge_num=badge_num)
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


if c.API_ENABLED:
    register_jsonrpc(AttendeeLookup(), 'attendee')
    register_jsonrpc(JobLookup(), 'shifts')
    register_jsonrpc(DepartmentLookup(), 'dept')
    register_jsonrpc(ConfigLookup(), 'config')
    register_jsonrpc(BarcodeLookup(), 'barcode')
    register_jsonrpc(GuestLookup(), 'guest')
    register_jsonrpc(MivsLookup(), 'mivs')
    register_jsonrpc(HotelLookup(), 'hotel')
    register_jsonrpc(ScheduleLookup(), 'schedule')
