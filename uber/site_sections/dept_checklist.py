from uber.common import *


def _submit_checklist_item(session, department_id, submitted, csrf_token, slug):
    if not department_id:
        raise HTTPRedirect('../dept_checklist/index')
    attendee = session.admin_attendee()
    department = session.query(Department).options(
        subqueryload(Department.dept_checklist_items)).get(department_id)
    if submitted:
        item = department.checklist_item_for_slug(slug)
        if not item:
            item = DeptChecklistItem(
                attendee=attendee, department=department, slug=slug)
        check_csrf(csrf_token)  # since this form doesn't use our normal utility methods, we need to do this manually
        session.add(item)
        raise HTTPRedirect(
            '../dept_checklist/index?department_id={}&message={}',
            department_id,
            'Thanks for completing the {} form!'.format(slug.replace('_', ' ')))

    return {'department': department}


@all_renderable(c.PEOPLE)
class Root:

    @department_id_adapter
    def index(self, session, department_id=None, message=''):
        attendee = session.admin_attendee()
        if not department_id and len(attendee.can_admin_checklist_depts) != 1:
            if message:
                raise HTTPRedirect('overview?filtered=1&message={}', message)
            else:
                raise HTTPRedirect('overview?filtered=1')

        if not department_id and len(attendee.can_admin_checklist_depts) == 1:
            department_id = attendee.can_admin_checklist_depts[0].id

        department = session.query(Department).options(
            subqueryload(Department.dept_checklist_items)).get(department_id)
        return {
            'message': message,
            'attendee': attendee,
            'department': department,
            'checklist': [
                (conf, department.checklist_item_for_slug(slug))
                for slug, conf in DeptChecklistConf.instances.items()]
        }

    @department_id_adapter
    @csrf_protected
    def mark_item_complete(self, session, slug, department_id):
        attendee = session.admin_attendee()
        department = session.query(Department).options(
            subqueryload(Department.dept_checklist_items)).get(department_id)
        conf = DeptChecklistConf.instances[slug]
        if department.checklist_item_for_slug(slug):
            message = 'Checklist item already marked as complete'
        else:
            item = DeptChecklistItem(
                attendee=attendee, department=department, slug=slug)
            message = check(item)
            if not message:
                session.add(item)
                message = 'Checklist item marked as complete'
        raise HTTPRedirect(
            'index?department_id={}&message={}', department_id, message)

    @department_id_adapter
    def form(self, session, slug, department_id, csrf_token=None, comments=None):
        attendee = session.admin_attendee()
        department = session.query(Department).options(
            subqueryload(Department.dept_checklist_items)).get(department_id)

        conf = DeptChecklistConf.instances[slug]
        item = department.checklist_item_for_slug(slug)
        if not item:
            item = DeptChecklistItem(
                attendee=attendee, department=department, slug=slug)

        if comments is not None:
            # since this form doesn't use our normal utility methods, we need
            # to check the csrf_token manually
            check_csrf(csrf_token)
            item.comments = comments
            message = check(item)
            if not message:
                session.add(item)
                message = conf.name + ' checklist data uploaded'
            raise HTTPRedirect(
                'index?department_id={}&message={}', department_id, message)

        return {
            'item': item,
            'conf': conf,
            'department': department
        }

    def overview(self, session, filtered=False, message=''):
        checklist = list(DeptChecklistConf.instances.values())
        attendee = session.admin_attendee()

        dept_filter = [Department.members_who_can_admin_checklist.any(
            Attendee.id == attendee.id)] if filtered else []

        departments = session.query(Department).filter(*dept_filter) \
            .options(
                subqueryload(Department.members_who_can_admin_checklist),
                subqueryload(Department.dept_checklist_items)) \
            .order_by(Department.name)

        overview = []
        for dept in departments:
            is_checklist_admin = attendee.is_checklist_admin_of(dept)
            can_admin_checklist = attendee.can_admin_checklist_for(dept)
            statuses = []
            for item in checklist:
                status = {'conf': item, 'name': item.name}
                checklist_item = dept.checklist_item_for_slug(item.slug)
                if checklist_item:
                    status['done'] = True
                    status['completed_by'] = checklist_item.attendee.full_name
                elif days_before(7, item.deadline)():
                    status['approaching'] = True
                elif item.deadline < datetime.now(UTC):
                    status['missed'] = True
                statuses.append(status)
            if not filtered or can_admin_checklist:
                overview.append([
                    dept,
                    is_checklist_admin,
                    can_admin_checklist,
                    statuses,
                    dept.members_who_can_admin_checklist])

        return {
            'message': message,
            'filtered': filtered,
            'overview': overview,
            'checklist': checklist
        }

    def item(self, session, slug):
        conf = DeptChecklistConf.instances[slug]
        departments = session.query(Department) \
            .options(
                subqueryload(Department.checklist_admins),
                subqueryload(Department.dept_checklist_items)) \
            .order_by(Department.name)

        emails = []
        for dept in departments:
            if not dept.checklist_item_for_slug(conf.slug):
                emails.extend([dh.email for dh in dept.dept_heads if dh.email])

        return {
            'conf': conf,
            'delinquent_emails': sorted(set(emails)),
            'overview': [(
                dept,
                dept.checklist_item_for_slug(conf.slug),
                dept.checklist_admins)
                for dept in departments
            ]
        }

    @department_id_adapter
    def hotel_setup(self, session, department_id=None, submitted=None, csrf_token=None):
        return _submit_checklist_item(session, department_id, submitted, csrf_token, 'hotel_setup')

    @department_id_adapter
    def logistics(self, session, department_id=None, submitted=None, csrf_token=None):
        return _submit_checklist_item(session, department_id, submitted, csrf_token, 'logistics')
