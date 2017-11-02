from uber.common import *


@all_renderable(c.PEOPLE)
class Root:

    def index(self, session, message=''):
        departments = session.query(Department).order_by(Department.name).all()
        return {
            'message': message,
            'departments': departments
        }

    @requires_dept_admin
    def form(self, session, message='', **params):
        department_id = params.get('id')
        if not department_id or department_id == 'None':
            raise HTTPRedirect('index')

        if cherrypy.request.method == 'POST':
            department = session.department(
                params,
                bools=Department.all_bools,
                checkgroups=Department.all_checkgroups)
            message = check(department)
            if not message:
                session.add(department)
                raise HTTPRedirect('form?id={}', department.id)
        else:
            department = session.query(Department).options(
                subqueryload(Department.dept_roles)
                    .subqueryload(DeptRole.dept_memberships),
                subqueryload(Department.members)
                    .subqueryload(Attendee.shifts)
                        .subqueryload(Shift.job),
                subqueryload(Department.unassigend_requesting_attendees),
                subqueryload(Department.dept_heads)
                    .subqueryload(Attendee.dept_memberships),
                subqueryload(Department.pocs)
                    .subqueryload(Attendee.dept_memberships),
                subqueryload(Department.checklist_admins)
                    .subqueryload(Attendee.dept_memberships)
                ).get(department_id)

        return {
            'admin': session.admin_attendee(),
            'message': message,
            'department': department
        }

    @requires_dept_admin
    @csrf_protected
    def delete(self, session, id, message=''):
        if cherrypy.request.method == 'POST':
            department = session.query(Department).get(id)
            attendee = session.admin_attendee()
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

        department = session.department(
            params,
            bools=Department.all_bools,
            checkgroups=Department.all_checkgroups)

        if cherrypy.request.method == 'POST':
            message = check(department)
            if not message:
                attendee = session.admin_attendee()
                has_email = bool(attendee.email)
                department.memberships = [DeptMembership(
                    attendee=attendee,
                    is_dept_head=True,
                    is_poc=has_email,
                    is_checklist_admin=has_email)]
                session.add(department)
                raise HTTPRedirect('form?id={}', department.id)
            session.rollback()

        return {
            'department': department,
            'message': message
        }

    @requires_dept_admin
    @ajax
    def set_implicit_role(self, session, department_id, attendee_id, role, value=None):
        assert role in ('dept_head', 'poc', 'checklist_admin'), \
            'Unknown role: "{}"'.format(role)

        try:
            value = str(value).lower() not in ('false', 'none', '', '0')
            dept_membership = session.query(DeptMembership).filter_by(
                department_id=department_id, attendee_id=attendee_id).one()
            setattr(dept_membership, 'is_' + role, value)
            session.commit()
        except:
            return {'error': 'Unexpected error setting role'}
        else:
            return {
                'dept_membership_id': dept_membership.id,
                'department_id': department_id,
                'attendee_id': attendee_id,
                'role': role,
                'value': value
            }

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
        department = session.query(Department).options(
            subqueryload(Department.memberships)
                .subqueryload(DeptMembership.attendee)
                    .subqueryload(Attendee.dept_roles)).get(department_id)

        if cherrypy.request.method == 'POST':
            is_new = role.is_new
            if is_new:
                role.department = department

            ids = params.get('dept_memberships_ids', [])
            session.set_relation_ids(role, DeptMembership, 'dept_memberships', ids)
            message = check(role)
            if not message:
                session.add(role)

                raise HTTPRedirect(
                    'form?id={}&message={}',
                    department_id,
                    'The {} role was successfully {}'.format(
                        role.name, 'created' if is_new else 'updated'))
            session.rollback()

        return {
            'department': department,
            'role': role,
            'message': message
        }

    @csrf_protected
    def delete_role(self, session, id, message=''):
        dept_role = session.query(DeptRole).get(id)
        department_id = dept_role.department_id
        if cherrypy.request.method == 'POST':
            session.delete(dept_role)
            raise HTTPRedirect(
                'form?id={}&message={}',
                department_id,
                'The {} role was deleted'.format(dept_role.name))

        raise HTTPRedirect('form?id={}', department_id)

    @requires_dept_admin
    @csrf_protected
    def unassign_member(self, session, department_id, attendee_id, message=''):
        if cherrypy.request.method == 'POST':
            membership = session.query(DeptMembership) \
                .filter_by(
                    department_id=department_id, attendee_id=attendee_id) \
                .options(subqueryload(DeptMembership.attendee)).first()

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
                .options(subqueryload(DeptMembership.attendee)).first()

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
