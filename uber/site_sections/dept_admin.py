import cherrypy
from sqlalchemy.orm import subqueryload
from datetime import timedelta

from uber.config import c
from uber.custom_tags import pluralize, yesno, readable_join
from uber.decorators import all_renderable, ajax, check_dept_admin, csrf_protected, csv_file, department_id_adapter, \
    requires_dept_admin, site_mappable
from uber.errors import HTTPRedirect
from uber.forms import load_forms
from uber.models import AdminAccount, Attendee, Department, DeptMembership, DeptRole, Shift
from uber.utils import check, validate_model


@all_renderable()
class Root:
    @site_mappable
    def index(self, session, filtered=False, message='', **params):
        if filtered:
            admin_account_id = cherrypy.session.get('account_id')
            admin_account = session.query(AdminAccount).get(admin_account_id)
            dept_filter = [Department.memberships.any(
                DeptMembership.attendee_id == admin_account.attendee_id)]
        else:
            dept_filter = []

        forms = load_forms({}, Department(), ['DepartmentInfo'])

        departments = session.query(Department).filter(*dept_filter) \
            .order_by(Department.name).all()
        return {
            'filtered': filtered,
            'message': message,
            'departments': departments,
            'forms': forms,
        }

    @requires_dept_admin
    def form(self, session, message='', **params):
        department_id = params.get('id')
        if not department_id or department_id == 'None':
            raise HTTPRedirect('index')
        
        department = session.department(department_id)
        forms = load_forms(params, department, ['DepartmentInfo'])

        if cherrypy.request.method == 'POST':
            message = check_dept_admin(session)
            if not message:
                for form in forms.values():
                    form.populate_obj(department)
                session.add(department)

                raise HTTPRedirect(
                    'form?id={}&message={}',
                    department.id,
                    'Department updated successfully.')
        else:
            department = session.query(Department) \
                .filter_by(id=department_id) \
                .order_by(Department.id) \
                .options(
                    subqueryload(Department.dept_roles).subqueryload(DeptRole.dept_memberships),
                    subqueryload(Department.members).subqueryload(Attendee.shifts).subqueryload(Shift.job),
                    subqueryload(Department.members).subqueryload(Attendee.admin_account),
                    subqueryload(Department.dept_heads).subqueryload(Attendee.dept_memberships),
                    subqueryload(Department.pocs).subqueryload(Attendee.dept_memberships),
                    subqueryload(Department.checklist_admins).subqueryload(Attendee.dept_memberships)) \
                .one()

        return {
            'admin': session.admin_attendee(),
            'forms': forms,
            'message': message,
            'department': department
        }

    @requires_dept_admin('dept_head')
    @csrf_protected
    def delete(self, session, id, message=''):
        if cherrypy.request.method == 'POST':
            department = session.query(Department).get(id)
            if department.member_count > 1:
                raise HTTPRedirect(
                    'form?id={}&message={}',
                    id,
                    'You cannot delete a department with more than one member')

            session.delete(department)
            raise HTTPRedirect(
                'index?message={}',
                'The {} department was deleted'.format(department.name))

        raise HTTPRedirect('form?id={}', id)

    def new(self, session, message='', **params):
        if params.get('id'):
            raise HTTPRedirect('form?id={}', params['id'])

        department = Department()

        forms = load_forms(params, department, ['DepartmentInfo'])

        if cherrypy.request.method == 'POST':
            message = check_dept_admin(session)
            if not message:
                for form in forms.values():
                    form.populate_obj(department)
                session.add(department)

                attendee = session.admin_attendee()
                has_email = bool(attendee.email)
                department.memberships = [DeptMembership(
                    attendee=attendee,
                    is_dept_head=True,
                    is_poc=has_email,
                    is_checklist_admin=has_email)]
                session.add(department)
                raise HTTPRedirect('form?id={}', department.id)

        return {
            'department': department,
            'forms': forms,
            'message': message
        }
    
    @ajax
    def validate_department(self, session, form_list=[], **params):
        if params.get('id') in [None, '', 'None']:
            dept = Department()
        else:
            dept = session.department(params.get('id'))

        if not form_list:
            form_list = ['DepartmentInfo']
        elif isinstance(form_list, str):
            form_list = [form_list]

        forms = load_forms(params, dept, form_list)
        all_errors = validate_model(forms, dept, is_admin=True)

        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    @ajax
    def set_inherent_role(
            self, session, department_id, attendee_id, role, value=None):

        assert role in ('dept_head', 'poc', 'checklist_admin'), \
            'Unknown role: "{}"'.format(role)

        admin_role = 'dept_head' if role == 'dept_head' else None
        message = check_dept_admin(session, department_id, admin_role)
        if message:
            return {'error': message}

        try:
            value = str(value).lower() not in ('false', 'none', '', '0')
            dept_membership = session.query(DeptMembership).filter_by(
                department_id=department_id, attendee_id=attendee_id).one()
            setattr(dept_membership, 'is_' + role, value)
            session.commit()
        except Exception:
            return {'error': 'Unexpected error setting role'}
        else:
            return {
                'dept_membership_id': dept_membership.id,
                'department_id': department_id,
                'attendee_id': attendee_id,
                'role': role,
                'value': value
            }

    @department_id_adapter
    def requests(self, session, department_id=None, requested_any=False, message='', **params):
        if not department_id:
            raise HTTPRedirect('index')

        department = session.query(Department).get(department_id)
        if cherrypy.request.method == 'POST':
            attendee_ids = [s for s in params.get('attendee_ids', []) if s]
            if attendee_ids:
                attendee_count = len(attendee_ids)
                for attendee_id in attendee_ids:
                    session.add(DeptMembership(
                        department_id=department_id, attendee_id=attendee_id))
                raise HTTPRedirect(
                    'form?id={}&message={}',
                    department_id,
                    '{} volunteer{}!'.format(attendee_count, pluralize(
                        attendee_count,
                        ' added as a new member',
                        's added as new members')))

            raise HTTPRedirect('form?id={}', department_id)

        return {
            'department': department,
            'message': message,
            'requested_any': requested_any
        }

    @department_id_adapter
    @csv_file
    def dept_requests_export(self, out, session, department_id, requested_any=False, message='', **params):
        department = session.query(Department).get(department_id)

        requesting_attendees = department.unassigned_requesting_attendees \
            if requested_any else department.unassigned_explicitly_requesting_attendees

        headers = ['Name', 'Email', 'Badge', 'Placeholder']
        if requested_any:
            headers.append('Explicitly Requested {}'.format(department.name))

        out.writerow(headers)
        for attendee in requesting_attendees:
            if attendee.is_valid:
                row = [attendee.full_name, attendee.email, attendee.badge, yesno(attendee.placeholder, 'Yes,No')]
                if requested_any:
                    row.append(yesno(attendee in department.unassigned_explicitly_requesting_attendees, 'Yes,No'))

                out.writerow(row)

    @department_id_adapter
    @csv_file
    def dept_members_export(self, out, session, department_id, message='', **params):
        department = session.query(Department).get(department_id)
        headers = ['Name', 'Legal Name', 'Email', 'Phone Number', 'Emergency Contact',
                   'Weighted Hours', 'Badge Status', 'Placeholder', 'Has Shifts', 'Roles']

        out.writerow(headers)
        for attendee in department.members:
            row = [attendee.full_name, attendee.legal_name, attendee.email, attendee.cellphone,
                   attendee.ec_name + ": " + attendee.ec_phone,
                   attendee.weighted_hours_in(department),
                   attendee.badge_status_label,
                   yesno(attendee.placeholder, 'Yes,No'),
                   yesno(attendee.weighted_hours_in(department) > 0, 'Yes,No'),
                   readable_join([role.name for role in attendee.dept_roles])]

            out.writerow(row)

    @csv_file
    def overworked_attendees(self, out, session):
        def single_sequence(attendee, start_minute, minute_map):
            all_depts_limit = 1000
            minutes_worked = 0
            current_minute = start_minute
            while current_minute in minute_map:
                dept_limit = minute_map[current_minute].max_consecutive_minutes
                if dept_limit > 0:
                    all_depts_limit = min(all_depts_limit, dept_limit)
                minutes_worked += 1
                current_minute = current_minute + timedelta(minutes=1)

            if minutes_worked > all_depts_limit:
                # reiterate over to gather department names
                current_minute = start_minute
                departments_overworked = set()
                while current_minute in minute_map:
                    dept_limit = minute_map[current_minute].max_consecutive_minutes
                    if dept_limit > 0 and minutes_worked > dept_limit:
                        departments_overworked.add(minute_map[current_minute].department_name)
                    current_minute = current_minute + timedelta(minutes=1)
                out.writerow([attendee.full_name,
                              start_minute.astimezone(c.EVENT_TIMEZONE),
                              minutes_worked] +
                             list(departments_overworked))

        out.writerow(["Attendee name", "Start of overworked shift sequence",
                      "Length of shift sequence", "Departments overworked in"])
        for attendee in session.query(Attendee).filter(Attendee.staffing == True).all():  # noqa: E712
            minute_map = attendee.shift_minute_map
            for start_minute in minute_map:
                # only look at start-of-sequence minutes
                if start_minute - timedelta(minutes=1) not in minute_map:
                    single_sequence(attendee, start_minute, minute_map)

    @department_id_adapter
    def role(self, session, department_id=None, message='', **params):
        if not department_id or department_id == 'None':
            department_id = None

        if not department_id \
                and (not params.get('id') or params.get('id') == 'None'):
            raise HTTPRedirect('index')

        role = session.dept_role(
            params,
            bools=DeptRole.all_bools,
            checkgroups=DeptRole.all_checkgroups)

        department_id = role.department_id or department_id
        department = session.query(Department).filter_by(id=department_id).order_by(Department.id) \
            .options(
                subqueryload(Department.memberships)
                .subqueryload(DeptMembership.attendee)
                .subqueryload(Attendee.dept_roles)) \
            .one()

        if cherrypy.request.method == 'POST':
            message = check_dept_admin(session)
            if not message:
                if role.is_new:
                    role.department = department
                message = check(role)

            if not message:
                session.add(role)

                raise HTTPRedirect(
                    'form?id={}&message={}',
                    department_id,
                    'The {} role was successfully {}'.format(
                        role.name, 'created' if role.is_new else 'updated'))
            session.rollback()

        return {
            'department': department,
            'role': role,
            'message': message
        }

    @csrf_protected
    def delete_role(self, session, id):
        dept_role = session.query(DeptRole).get(id)
        department_id = dept_role.department_id
        message = ''
        if cherrypy.request.method == 'POST':
            message = check_dept_admin(session, department_id)
            if not message:
                session.delete(dept_role)
                raise HTTPRedirect(
                    'form?id={}&message={}',
                    department_id,
                    'The {} role was deleted'.format(dept_role.name))

        if not message:
            raise HTTPRedirect('form?id={}', department_id)
        else:
            raise HTTPRedirect('form?id={}&message={}', department_id, message)

    @requires_dept_admin
    @csrf_protected
    def unassign_member(self, session, department_id, attendee_id, message=''):
        if cherrypy.request.method == 'POST':
            membership = session.query(DeptMembership) \
                .filter_by(
                    department_id=department_id, attendee_id=attendee_id) \
                .order_by(DeptMembership.id) \
                .options(subqueryload(DeptMembership.attendee)) \
                .first()

            if membership:
                session.delete(membership)
                message = '{} successfully unassigned from this ' \
                    'department'.format(membership.attendee.full_name)
            else:
                message = 'That attendee is not a member of this department'

            raise HTTPRedirect('form?id={}&message={}', department_id, message)

        raise HTTPRedirect('form?id={}', department_id)

    @requires_dept_admin
    @csrf_protected
    def assign_member(self, session, department_id, attendee_id, message=''):
        if cherrypy.request.method == 'POST':
            membership = session.query(DeptMembership) \
                .filter_by(
                    department_id=department_id, attendee_id=attendee_id) \
                .order_by(DeptMembership.id) \
                .options(subqueryload(DeptMembership.attendee)) \
                .first()

            if membership:
                message = '{} is already a member of this ' \
                    'department'.format(membership.attendee.full_name)
            else:
                session.add(DeptMembership(
                    department_id=department_id, attendee_id=attendee_id))
                attendee = session.query(Attendee).get(attendee_id)
                message = '{} successfully added as a member of this ' \
                    'department'.format(attendee.full_name)

            raise HTTPRedirect('form?id={}&message={}', department_id, message)

        raise HTTPRedirect('form?id={}', department_id)
