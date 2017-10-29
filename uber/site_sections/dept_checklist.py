from uber.common import *


@all_renderable(c.PEOPLE)
class Root:
    def index(self, session, department_id=None, message=''):
        if not department_id:
            raise HTTPRedirect('overview')

        attendee = session.admin_attendee()
        if not attendee.is_dept_head:
            raise HTTPRedirect('overview?message={}', 'The checklist is for department heads only')

        department_id = Department.to_id(department_id)
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

    @csrf_protected
    def mark_item_complete(self, session, slug, department_id):
        attendee = session.admin_attendee()
        department_id = Department.to_id(department_id)
        department = session.query(Department).options(
            subqueryload(Department.dept_checklist_items)).get(department_id)
        conf = DeptChecklistConf.instances[slug]
        if not department.checklist_item_for_slug(slug):
            session.add(DeptChecklistItem(
                attendee=attendee, department=department, slug=slug))
        raise HTTPRedirect('index?message={}', 'Checklist item marked as complete')

    def form(self, session, slug, department_id, csrf_token=None, comments=None):
        attendee = session.admin_attendee()
        department_id = Department.to_id(department_id)
        department = session.query(Department).options(
            subqueryload(Department.dept_checklist_items)).get(department_id)
        conf = DeptChecklistConf.instances[slug]
        item = department.checklist_item_for_slug(slug)
        if not item:
            item = DeptChecklistItem(
                attendee=attendee, department=department, slug=slug)

        if comments is not None:
            check_csrf(csrf_token)  # since this form doesn't use our normal utility methods, we need to do this manually
            item.comments = comments
            session.add(item)
            raise HTTPRedirect('index?message={}', conf.name + ' checklist data uploaded')

        return {
            'item': item,
            'conf': conf,
            'department': department
        }

    def overview(self, session, message=''):
        checklist = list(DeptChecklistConf.instances.values())
        overview = []
        attendee = session.admin_attendee()
        departments = session.query(Department) \
            .options(
                subqueryload(Department.checklist_admins),
                subqueryload(Department.dept_checklist_items)) \
            .order_by(Department.name)
        for dept in departments:
            relevant = attendee.is_checklist_admin_for(dept)
            statuses = []
            for item in checklist:
                status = {'conf': item, 'name': item.name}
                if dept.checklist_item_for_slug(item.slug):
                    status['done'] = True
                elif days_before(7, item.deadline)():
                    status['approaching'] = True
                elif item.deadline < datetime.now(UTC):
                    status['missed'] = True
                statuses.append(status)
            overview.append([dept.id, dept.name, relevant, statuses, dept.checklist_admins])

        return {
            'message': message,
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
        return {
            'conf': conf,
            'overview': [(
                dept.id,
                dept.name,
                dept.checklist_item_for_slug(conf.slug),
                dept.checklist_admins)
                for dept in departments
            ]
        }
