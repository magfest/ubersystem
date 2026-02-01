import cherrypy
import os
import re

from collections import defaultdict, OrderedDict
from datetime import timedelta
from dateutil import parser as dateparser

from sqlalchemy import or_
from sqlalchemy.orm import subqueryload

from uber.config import c
from uber.decorators import all_renderable, csv_file, render
from uber.utils import department_id_adapter
from uber.models import Attendee, Department, Job


def volunteer_checklists(session):
    attendees = session.query(Attendee) \
        .filter(
            Attendee.staffing == True,  # noqa: E712
            Attendee.badge_status.in_([c.NEW_STATUS, c.COMPLETED_STATUS])) \
        .order_by(Attendee.full_name, Attendee.id).all()

    checklist_items = OrderedDict()
    for item_template in c.VOLUNTEER_CHECKLIST:
        item_name = os.path.splitext(os.path.basename(item_template))[0]
        if item_name.endswith('_item'):
            item_name = item_name[:-5]
        item_name = item_name.replace('_', ' ').title()
        checklist_items[item_name] = item_template

    re_checkbox = re.compile(r'<img src="\.\./static/images/checkbox_.*?/>')
    for attendee in attendees:
        attendee.checklist_items = OrderedDict()
        for item_name, item_template in checklist_items.items():
            html = render(item_template, {'attendee': attendee}, encoding=None)
            match = re_checkbox.search(html)
            is_complete = False
            is_applicable = False
            if match:
                is_applicable = True
                checkbox_html = match.group(0)
                if 'checkbox_checked' in checkbox_html:
                    is_complete = True
            attendee.checklist_items[item_name] = {
                'is_applicable': is_applicable,
                'is_complete': is_complete,
            }

    return {
        'checklist_items': checklist_items,
        'attendees': attendees,
    }


@all_renderable()
class Root:
    def index(self, session):
        attendees = session.staffers().options(subqueryload(Attendee.dept_memberships)).all()
        attendees_by_dept = defaultdict(list)
        for attendee in attendees:
            for dept_membership in attendee.dept_memberships:
                attendees_by_dept[dept_membership.department_id].append(attendee)

        jobs = session.jobs().all()
        jobs_by_dept = defaultdict(list)
        for job in jobs:
            jobs_by_dept[job.department_id].append(job)

        departments = session.query(Department).order_by(Department.name)

        return {
            'hour_total': sum(j.weighted_hours * j.slots for j in jobs),
            'shift_total': sum(j.weighted_hours * len(j.shifts) for j in jobs),
            'volunteers': len(attendees),
            'departments': [{
                'department': dept,
                'assigned': len(attendees_by_dept[dept.id]),
                'total_hours': sum(j.weighted_hours * j.slots for j in jobs_by_dept[dept.id]),
                'taken_hours': sum(j.weighted_hours * len(j.shifts) for j in jobs_by_dept[dept.id])
            } for dept in departments]
        }

    def all_schedules(self, session):
        return {'staffers': [a for a in session.staffers() if a.shifts]}

    def departments(self, session):
        everything = []
        departments = session.query(Department).options(
            subqueryload(Department.members).subqueryload(Attendee.dept_memberships),
            subqueryload(Department.unassigned_explicitly_requesting_attendees)).order_by(Department.name)
        for department in departments:
            assigned = department.members
            unassigned = department.unassigned_explicitly_requesting_attendees
            everything.append([department, assigned, unassigned])
        return {'everything': everything}

    def ratings(self, session):
        return {
            'prev_years': [a for a in session.staffers() if 'poorly' in a.past_years],
            'current': [a for a in session.staffers() if any(shift.rating == c.RATED_BAD for shift in a.shifts)]
        }

    def volunteer_hours_overview(self, session, message=''):
        attendees = session.staffers()
        return {
            'volunteers': attendees,
            'message': message,
        }
    
    @department_id_adapter
    def volunteer_food(self, session, message='', department_id=None, start_time=None, end_time=None):
        staffers = set()
        start = dateparser.parse(start_time) if start_time else None
        end = dateparser.parse(end_time) if end_time else None

        if cherrypy.request.method == 'POST' or department_id or start_time or end_time:
            if department_id == 'All':
                department_id = None

            if not start or not end:
                potential = session.query(Attendee).filter(Attendee.badge_type != c.CONTRACTOR_BADGE, Attendee.shifts)
                for attendee in potential:
                    if attendee.badge_type == c.STAFF_BADGE or attendee.weighted_hours >= c.HOURS_FOR_FOOD:
                        staffers.add(attendee)
            else:
                if end < start:
                    message = 'Start must come before end: {} {}'.format(start, end)
                else:
                    filters = [Job.start_time < end, Job.end_time > start]
                    if department_id:
                        filters.append(Job.department_id == department_id)
                    minutes = set()
                    minute = start
                    while minute < end:
                        minutes.add(minute)
                        minute += timedelta(minutes=1)
                    for job in session.query(Job).filter(*filters):
                        if minutes.intersection(job.minutes):
                            for shift in job.shifts:
                                if shift.attendee.badge_type != c.CONTRACTOR_BADGE and (
                                        shift.attendee.badge_type == c.STAFF_BADGE or shift.attendee.weighted_hours >= c.HOURS_FOR_FOOD):
                                    staffers.add(shift.attendee)

        return {
            'message': message,
            'start_time': start.isoformat() if start else '',
            'end_time': end.isoformat() if end else '',
            'department_id': department_id,
            'staffers': sorted(staffers, key=lambda a: a.full_name)
        }

    @csv_file
    def dept_head_contact_info(self, out, session):
        out.writerow(["Full Name", "Email", "Phone", "Department(s)"])
        for a in session.query(Attendee).filter(Attendee.dept_memberships_as_dept_head.any()).order_by('last_name'):
            for label in a.assigned_depts_labels:
                out.writerow([a.full_name, a.email, a.cellphone, label])

    @csv_file
    def volunteers_with_worked_hours(self, out, session):
        out.writerow(['Badge #', 'Full Name', 'Email Address', 'Weighted Hours Scheduled', 'Weighted Hours Worked'])
        for a in session.staffers():
            if a.worked_hours > 0:
                out.writerow([a.badge_num, a.full_name, a.email, a.weighted_hours, a.worked_hours])

    def restricted_untaken(self, session):
        untaken = defaultdict(lambda: defaultdict(list))
        for job in session.jobs():
            if job.restricted and job.slots_taken < job.slots:
                for minute in job.minutes:
                    untaken[job.department_id][minute].append(job)
        flagged = []
        for attendee in session.staffers():
            if not attendee.is_dept_head:
                overlapping = defaultdict(set)
                for shift in attendee.shifts:
                    if not shift.job.restricted:
                        for dept in attendee.assigned_depts:
                            for minute in shift.job.minutes:
                                if attendee.trusted_in(dept) and minute in untaken[dept]:
                                    overlapping[shift.job].update(untaken[dept][minute])
                if overlapping:
                    flagged.append([attendee, sorted(overlapping.items(), key=lambda tup: tup[0].start_time)])
        return {'flagged': flagged}

    def consecutive_threshold(self, session):
        def exceeds_threshold(start_time, attendee):
            time_slice = (start_time, start_time + timedelta(hours=18))
            return len([h for h in attendee.shift_minutes if time_slice[0] < h < time_slice[1]]) >= 13 * 60
        flagged = []
        for attendee in session.staffers():
            if attendee.staffing and attendee.unweighted_hours >= 12:
                for start_time, desc in c.START_TIME_OPTS[::6]:
                    if exceeds_threshold(start_time, attendee):
                        flagged.append(attendee)
                        break
        return {'flagged': flagged}

    def setup_teardown_neglect(self, session):
        jobs = session.jobs().all()
        return {
            'unfilled': [
                ('Setup', [job for job in jobs if job.is_setup and job.slots_untaken]),
                ('Teardown', [job for job in jobs if job.is_teardown and job.slots_untaken])
            ]
        }

    def volunteers_owed_refunds(self, session):
        attendees = session.all_attendees(only_staffing=True).all()
        owed = [a for a in attendees if a.paid_for_badge and not a.has_been_refunded
                and a.worked_hours >= c.HOURS_FOR_REFUND]
        refunded = [a for a in attendees if a.has_been_refunded]
        maybe = [a for a in attendees if a.paid_for_badge and not a.has_been_refunded
                 and a.worked_hours < c.HOURS_FOR_REFUND and a.weighted_hours >= c.HOURS_FOR_REFUND]

        return {
            'attendees': [(
                'Volunteers Owed Refunds',
                owed,
                sum([a.badge_cost for a in owed])
            ), (
                'Volunteers Already Refunded',
                refunded,
                sum([a.badge_cost for a in refunded])
            ), (
                'Volunteers Who Can Be Refunded Once Their Shifts Are Marked',
                maybe,
                sum([a.badge_cost for a in maybe])
            )]
        }

    @csv_file
    def volunteers_owed_refunds_csv(self, out, session):
        attendees = session.all_attendees(only_staffing=True).all()
        out.writerow(['Volunteer', 'Departments', 'Hours Worked', 'Hours Taken',
                      'Badge Cost', 'Owed/Refunded/Maybe'])
        for attendee in attendees:
            if attendee.weighted_hours >= c.HOURS_FOR_REFUND and (attendee.has_been_refunded or attendee.paid_for_badge):
                if attendee.has_been_refunded:
                    owed = "Refunded"
                elif attendee.worked_hours >= c.HOURS_FOR_REFUND:
                    owed = "Owed Refund"
                else:
                    owed = "Once Shifts Marked"
                out.writerow([attendee.full_name, ' / '.join(attendee.assigned_depts_labels),
                            attendee.worked_hours, attendee.weighted_hours,
                            attendee.badge_cost, owed])

    @csv_file
    def volunteer_checklist_csv(self, out, session):
        checklists = volunteer_checklists(session)
        out.writerow(['First Name', 'Last Name', 'Email', 'Cellphone', 'Assigned Depts']
                     + [s for s in checklists['checklist_items'].keys()])
        for attendee in checklists['attendees']:
            checklist_items = []
            for item in attendee.checklist_items.values():
                checklist_items.append('Yes' if item['is_complete'] else 'No' if item['is_applicable'] else 'N/A')
            out.writerow([attendee.first_name,
                          attendee.last_name,
                          attendee.email,
                          attendee.cellphone,
                          ', '.join(attendee.assigned_depts_labels)
                          ] + checklist_items)

    def volunteer_checklists(self, session):
        return volunteer_checklists(session)

    @csv_file
    def name_in_credits(self, out, session):
        out.writerow(["Name submitted for credits"])
        for attendee in session.all_attendees():
            if attendee.name_in_credits:
                out.writerow([attendee.name_in_credits])
