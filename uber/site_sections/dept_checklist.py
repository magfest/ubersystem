from uber.common import *

@all_renderable(PEOPLE)
class Root:
    def index(self, session, message=''):
        attendee = session.admin_attendee()
        if not attendee.is_single_dept_head:
            raise HTTPRedirect('overview?message={}', 'The checklist is for department heads with exactly one department')

        return {
            'message': message,
            'attendee': attendee,
            'checklist': [(conf, conf.completed(attendee)) for conf in DeptChecklistConf.instances.values()]
        }

    def form(self, session, slug, csrf_token=None, comments=None):
        conf = DeptChecklistConf.instances[slug]
        attendee = session.admin_attendee()
        try:
            [item] = [item for item in attendee.dept_checklist_items if item.slug == slug]
        except:
            item = DeptChecklistItem(slug=slug, attendee=attendee)

        if comments is not None:
            check_csrf(csrf_token)  # since this form doesn't use our normal utility methods, we need to do this manuallu
            item.comments = comments
            session.add(item)
            raise HTTPRedirect('index?message={}', conf.name + ' checklist data uploaded')

        return {
            'item': item,
            'conf': conf
        }

    def overview(self, session, message=''):
        checklist = list(DeptChecklistConf.instances.values())
        overview = []
        for dept, dept_name in JOB_LOCATION_OPTS:
            dept_heads = []
            for attendee in session.query(Attendee) \
                                   .filter_by(ribbon=DEPT_HEAD_RIBBON, assigned_depts=str(dept)) \
                                   .order_by(Attendee.full_name).all():
                statuses = []
                for item in checklist:
                    if item.completed(attendee):
                        statuses.append({'done': True})
                    elif days_before(7, item.deadline):
                        statuses.append({'approaching': True})
                    elif item.deadline < datetime.now(UTC):
                        statuses.append({'missed': True})
                    else:
                        statuses.append({})
                    statuses[-1]['name'] = item.name
                dept_heads.append([attendee, statuses])
            overview.append([dept, dept_name, dept_heads])

        return {
            'message': message,
            'overview': overview,
            'checklist': checklist,
            'max_name_length': max(len(conf.name) for conf in checklist)
        }
