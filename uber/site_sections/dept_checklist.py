from datetime import datetime

from pytz import UTC
from sqlalchemy.orm import joinedload, subqueryload

from uber.config import c
from uber.decorators import ajax, all_renderable, csrf_protected, department_id_adapter, render, xlsx_file
from uber.errors import HTTPRedirect
from uber.models import Attendee, Department, DeptChecklistItem, HotelRequests, RoomAssignment, Shift
from uber.utils import check, check_csrf, days_before, DeptChecklistConf, redirect_to_allowed_dept


def _submit_checklist_item(session, department_id, submitted, csrf_token, slug, custom_message=''):
    if not department_id:
        raise HTTPRedirect('../dept_checklist/index')
    attendee = session.admin_attendee()
    department = session.query(Department).options(
        subqueryload(Department.dept_checklist_items)).get(department_id)
    if submitted:
        item = department.checklist_item_for_slug(slug)
        if not item:
            item = DeptChecklistItem(attendee=attendee, department=department, slug=slug)

        # since this form doesn't use our normal utility methods, we need to do this manually
        check_csrf(csrf_token)
        session.add(item)
        raise HTTPRedirect(
            '../dept_checklist/index?department_id={}&message={}',
            department_id,
            custom_message or 'Thanks for completing the {} form!'.format(slug.replace('_', ' ')))

    return {'department': department}


@all_renderable()
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

        if department.checklist_item_for_slug(slug):
            message = 'Checklist item already marked as complete'
        else:
            item = DeptChecklistItem(attendee=attendee, department=department, slug=slug)
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
            # since this form doesn't use our normal utility methods, we need to check the csrf_token manually
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

    @xlsx_file
    def overview_xlsx(self, out, session):
        checklist = list(DeptChecklistConf.instances.values())
        departments = session.query(Department).options(
            subqueryload(Department.members_who_can_admin_checklist),
            subqueryload(Department.dept_checklist_items)) \
            .order_by(Department.name)

        header_row = ['Department']
        header_row.extend(item.name for item in checklist)
        header_row.extend(['Emails'])
        out.writerow(header_row)

        for dept in departments:
            out.writecell(dept.name)
            for item in checklist:
                checklist_item = dept.checklist_item_for_slug(item.slug)
                if checklist_item:
                    out.writecell('', {'bg_color': 'green'})
                elif days_before(7, item.deadline)():
                    out.writecell('', {'bg_color': 'orange'})
                elif item.deadline < datetime.now(UTC):
                    out.writecell('', {'bg_color': 'red'})
                else:
                    out.writecell('')

            out.writecell(', '.join([admin.email for admin in dept.checklist_admins]), last_cell=True)

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
    def placeholders(self, session, department_id=None):
        redirect_to_allowed_dept(session, department_id, 'placeholders')

        if department_id == 'All':
            department_id = None

        dept_filter = [] if not department_id else [Attendee.dept_memberships.any(department_id=department_id)]
        placeholders = session.query(Attendee).filter(
            Attendee.placeholder == True,
            Attendee.staffing == True,
            Attendee.badge_status.in_([c.NEW_STATUS, c.COMPLETED_STATUS]),
            *dept_filter).order_by(Attendee.full_name).all()  # noqa: E712

        try:
            checklist = session.checklist_status('placeholders', department_id)
        except ValueError:
            checklist = {'conf': None, 'relevant': False, 'completed': None}

        return {
            'department_id': department_id,
            'dept_name': session.query(Department).get(department_id).name if department_id else 'All',
            'checklist': checklist,
            'placeholders': placeholders
        }

    @department_id_adapter
    def hotel_setup(self, session, department_id=None, submitted=None, csrf_token=None):
        return _submit_checklist_item(session, department_id, submitted, csrf_token, 'hotel_setup')

    @department_id_adapter
    def logistics(self, session, department_id=None, submitted=None, csrf_token=None):
        return _submit_checklist_item(session, department_id, submitted, csrf_token, 'logistics')
    
    @department_id_adapter
    def printed_signs(self, session, department_id=None, submitted=None, csrf_token=None):
        # We actually submit from this page to `form`, this just lets us render a custom page
        return _submit_checklist_item(session, department_id, submitted, csrf_token, 'printed_signs')

    @department_id_adapter
    def treasury(self, session, department_id=None, submitted=None, csrf_token=None):
        return _submit_checklist_item(session, department_id, submitted, csrf_token, 'treasury',
                                      'Thanks for completing the MPoints form!')

    @department_id_adapter
    def allotments(self, session, department_id=None, submitted=None, csrf_token=None, **params):
        return _submit_checklist_item(session, department_id, submitted, csrf_token, 'allotments',
                                      'Treasury checklist data uploaded')

    @department_id_adapter
    def tech_requirements(self, session, department_id=None, submitted=None, csrf_token=None):
        return _submit_checklist_item(session, department_id, submitted, csrf_token, 'tech_requirements')
    
    @department_id_adapter
    def guidebook_schedule(self, session, department_id=None, submitted=None, csrf_token=None):
        return _submit_checklist_item(session, department_id, submitted, csrf_token, 'guidebook_schedule',
                                      'Thanks for confirming your schedule is ready for Guidebook!')

    @department_id_adapter
    def hotel_eligible(self, session, department_id=None):
        redirect_to_allowed_dept(session, department_id, 'hotel_eligible')

        if department_id == 'All':
            department_id = None

        return {
            'department_id': department_id,
            'department_name': c.DEPARTMENTS.get(department_id, 'All'),
            'checklist': session.checklist_status('hotel_eligible', department_id),
            'attendees': session.query(Attendee).filter(
                Attendee.hotel_eligible == True,
                Attendee.badge_status.in_([c.NEW_STATUS, c.COMPLETED_STATUS]),
                Attendee.dept_memberships.any(department_id=department_id)
            ).order_by(Attendee.full_name).all()
        }  # noqa: E712

    @department_id_adapter
    def hotel_requests(self, session, department_id=None):
        redirect_to_allowed_dept(session, department_id, 'index')

        if department_id == 'All':
            department_id = None

        dept_filter = [] if not department_id \
            else [Attendee.dept_memberships.any(department_id=department_id)]

        requests = session.query(HotelRequests) \
            .join(HotelRequests.attendee) \
            .options(joinedload(HotelRequests.attendee)) \
            .filter(
            Attendee.badge_status.in_([c.NEW_STATUS, c.COMPLETED_STATUS]),
            *dept_filter) \
            .order_by(Attendee.full_name).all()
        
        attendee = session.admin_attendee()

        return {
            'admin_has_room_access': c.HAS_HOTEL_ADMIN_ACCESS,
            'attendee': attendee,
            'requests': requests,
            'department_id': department_id,
            'department_name': c.DEPARTMENTS.get(department_id, 'All'),
            'declined_count': len([r for r in requests if r.nights == '']),
            'checklist': session.checklist_status(
                'approve_setup_teardown', department_id),
            'staffer_count': session.query(Attendee).filter(
                Attendee.hotel_eligible == True, *dept_filter).count()  # noqa: E712
        }

    def hours(self, session):
        staffers = session.query(Attendee) \
            .filter(Attendee.hotel_eligible == True, Attendee.badge_status.in_([c.NEW_STATUS, c.COMPLETED_STATUS])) \
            .options(joinedload(Attendee.hotel_requests), subqueryload(Attendee.shifts).subqueryload(Shift.job)) \
            .order_by(Attendee.full_name).all()  # noqa: E712

        return {'staffers': [s for s in staffers if s.hotel_shifts_required and s.weighted_hours < c.HOURS_FOR_HOTEL_SPACE]}

    def no_shows(self, session):
        room_assignments = session.query(RoomAssignment).options(
            joinedload(RoomAssignment.attendee).joinedload(Attendee.hotel_requests),
            joinedload(RoomAssignment.attendee).subqueryload(Attendee.room_assignments))
        staffers = [ra.attendee for ra in room_assignments if not ra.attendee.checked_in]
        return {'staffers': sorted(staffers, key=lambda a: a.full_name)}

    @ajax
    def approve(self, session, id, approved):
        hr = session.hotel_requests(id)
        if approved == 'approved':
            hr.approved = True
        else:
            hr.decline()
        session.commit()
        return {'nights': hr.nights_display}
