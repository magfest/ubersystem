import cherrypy
from datetime import datetime, timedelta
import logging
import ics
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.orm.exc import NoResultFound

from uber.config import c
from uber.custom_tags import safe_string
from uber.decorators import ajax, ajax_gettable, all_renderable, check_shutdown, csrf_protected, render, requires_account
from uber.errors import HTTPRedirect
from uber.forms import load_forms
from uber.models import Attendee, Job, FoodRestrictions
from uber.utils import check_csrf, create_valid_user_supplied_redirect_url, ensure_csrf_token_exists, localized_now, extract_urls, validate_model

log = logging.getLogger(__name__)


def _convert_urls(desc):
    urls = extract_urls(desc)
    if not urls:
        return desc

    for url in urls:
        new_url = url
        if not url.startswith('http'):
            new_url = 'https://' + url
        desc = desc.replace(url, f'<a href="{new_url}" target="_blank">{url}</a>')
    return desc


@all_renderable(public=True)
class Root:
    @requires_account()
    def index(self, session, id, message=''):
        attendee = session.volunteer_from_id(id)
        if c.UBER_SHUT_DOWN:
            return render('staffing/printable.html', {'attendee': attendee})
        else:
            if not c.VOLUNTEER_CHECKLIST_OPEN or attendee.shift_prereqs_complete:
                raise HTTPRedirect('shifts?id={}&message={}', attendee.id, message)
            raise HTTPRedirect('checklist?id={}&message={}', attendee.id, message)

    @requires_account()
    def checklist(self, session, id, message=''):
        attendee = session.volunteer_from_id(id)
        if c.UBER_SHUT_DOWN:
            return render('staffing/printable.html', {'attendee': attendee})
        elif not c.VOLUNTEER_CHECKLIST_OPEN:
            raise HTTPRedirect('shifts?id={}&message={}', attendee.id, message)
        else:
            return {
                'message': message,
                'attendee': attendee
            }

    @requires_account()
    def printable(self, id, session):
        return {'attendee': session.volunteer_from_id(id)}

    @requires_account()
    def food_restrictions(self, session, id, message='', **params):
        attendee = session.volunteer_from_id(params.get('attendee_id', id))
        restrictions = attendee.food_restrictions or FoodRestrictions(attendee_id=attendee.id)
        forms = load_forms(params, restrictions, ["DietaryRestrictions"])

        if cherrypy.request.method == "POST":
            for form in forms.values():
                form.populate_obj(restrictions)
            session.add(restrictions)
            session.commit()
            if attendee.badge_type == c.GUEST_BADGE:
                raise HTTPRedirect('food_restrictions?id={}&message={}', attendee.id,
                                   'Your info has been recorded, thanks a bunch!')
            else:
                raise HTTPRedirect('checklist?id={}&message={}', attendee.id,
                                   'Your dietary restrictions have been recorded.')

        return {
            'restrictions': restrictions,
            'forms': forms,
            'message': message,
            'attendee': attendee
        }

    @requires_account()
    @ajax
    def validate_food_restrictions(self, session, form_list=[], **params):
        all_errors = {}

        attendee = session.volunteer_from_id(params.get('attendee_id'))
        restrictions = attendee.food_restrictions or FoodRestrictions(attendee_id=attendee.id)

        if not form_list:
            form_list = ['DietaryRestrictions']
        elif isinstance(form_list, str):
            form_list = [form_list]

        forms = load_forms(params, restrictions, form_list)
        all_errors = validate_model(session, forms, restrictions)

        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    @requires_account()
    @check_shutdown
    def shirt_size(self, session, id, message='', **params):
        attendee = session.volunteer_from_id(id)
        if cherrypy.request.method == "POST":
            check_csrf(params.get('csrf_token'))
            test_attendee = Attendee(**attendee.to_dict())
            test_attendee.apply(params)

            if c.STAFF_EVENT_SHIRT_OPTS and test_attendee.gets_staff_shirt and test_attendee.num_event_shirts == -1:
                message = "Please indicate your preference for shirt type."
            elif not test_attendee.shirt_size_marked:
                message = "Please select a shirt size."

            if not message:
                for attr in ['shirt', 'staff_shirt', 'num_event_shirts', 'shirt_opt_out']:
                    if params.get(attr):
                        setattr(attendee, attr, int(params.get(attr)))
                raise HTTPRedirect('checklist?id={}&message={}', id, 'Shirt info uploaded.')

        return {
            'message': message,
            'attendee': attendee,
            'opts': [('', 'Enter your shirt size')] + c.SHIRT_OPTS[1:]
        }

    @requires_account()
    @check_shutdown
    def volunteer_agreement(self, session, id, message='', agreed_to_terms=None, agreed_to_terms_1=None,
                            agreed_to_terms_2=None, csrf_token=None):
        attendee = session.volunteer_from_id(id)
        if csrf_token is not None:
            check_csrf(csrf_token)
            if agreed_to_terms or (agreed_to_terms_1 and agreed_to_terms_2):
                attendee.agreed_to_volunteer_agreement = True
                raise HTTPRedirect('checklist?id={}&message={}', id, 'Agreement received')
            elif agreed_to_terms_1 or agreed_to_terms_2:
                message = "You must agree to both the terms of the agreement and "\
                    "the volunteering policies and guidelines"
            else:
                message = "You must agree to the terms of the agreement"

        return {
            'message': message,
            'attendee': attendee,
            'agreed_to_terms_1': agreed_to_terms_1,
            'agreed_to_terms_2': agreed_to_terms_2,
            'agreement_end_date': c.ESCHATON.date() + timedelta(days=31),
        }

    @requires_account()
    @check_shutdown
    def emergency_procedures(self, session, id, message='', reviewed_procedures=None, csrf_token=None):
        attendee = session.volunteer_from_id(id)
        if csrf_token is not None:
            check_csrf(csrf_token)
            if reviewed_procedures:
                attendee.reviewed_emergency_procedures = True
                raise HTTPRedirect('checklist?id={}&message={}', id,
                                   'Thanks for reviewing our safety and security information!')

            message = "You must acknowledge that you reviewed our safety and security information."

        return {
            'message': message,
            'attendee': attendee,
        }

    @requires_account()
    @check_shutdown
    def cash_handling(self, session, id, message='', reviewed_cash_handling=None, csrf_token=None):
        attendee = session.volunteer_from_id(id)
        if csrf_token is not None:
            check_csrf(csrf_token)
            if reviewed_cash_handling:
                attendee.reviewed_cash_handling = datetime.now()
                raise HTTPRedirect('checklist?id={}&message={}', id,
                                   'Thanks for reviewing our payment handling guidelines!')

            message = "You must acknowledge that you reviewed our payment handling guidelines."

        return {
            'message': message,
            'attendee': attendee,
        }

    @requires_account()
    @check_shutdown
    def credits(self, session, id, message='', name_in_credits='', csrf_token=None):
        attendee = session.volunteer_from_id(id)
        if csrf_token is not None:
            check_csrf(csrf_token)
            attendee.name_in_credits = name_in_credits
            message = "Thank you for providing a name for the credits roll!" if name_in_credits \
                else "You have opted out of having your name in the credits roll."
            raise HTTPRedirect('checklist?id={}&message={}', id, message)

        return {
            'message': message,
            'attendee': attendee,
        }

    @requires_account()
    @check_shutdown
    def shifts(self, session, id, **params):
        volunteer = session.volunteer_from_id(id)

        total_duration = 0
        event_dates = []
        day = c.SHIFTS_EPOCH
        while day <= c.SHIFTS_ESCHATON:
            total_duration += 1
            if c.EPOCH <= day and day <= c.ESCHATON:
                event_dates.append(day.strftime('%Y-%m-%d'))
            day += timedelta(days=1)

        default_filters = [{'id': 'public_assigned', 'title': "Assigned Shifts (Public)"}]
        for department in volunteer.assigned_depts:
            default_filters.append({
                'id': department.id,
                'title': department.name,
            })
        other_filters = [
            {'id': 'public', 'title': "Public Shifts",},
            ]
        
        requested_hotel_nights = []

        return {
            'attendee': volunteer,
            'has_public_jobs': session.query(Job).filter(Job.is_public == True).first(),
            'depts_with_roles': [membership.department.name for membership in volunteer.dept_memberships_with_role],
            'assigned_depts_list': [(dept.id, dept.name) for dept in volunteer.assigned_depts],
            'hours': volunteer.weighted_hours,
            'assigned_depts_labels': volunteer.assigned_depts_labels,
            'default_filters': default_filters,
            'all_filters': default_filters + other_filters,
            'start': c.SHIFTS_EPOCH.date(),
            'total_duration': total_duration,
            'highlighted_dates': event_dates,
            'setup_duration': (c.EPOCH - c.SHIFTS_EPOCH).days,
            'teardown_duration': (c.SHIFTS_ESCHATON - c.ESCHATON).days,
            'requested_setup_nights': [c.NIGHTS[night] for night in requested_hotel_nights if night in c.SETUP_NIGHTS],
            'requested_teardown_nights': [c.NIGHTS[night] for night in requested_hotel_nights if night in c.TEARDOWN_NIGHTS],
        }

    @requires_account()
    @ajax_gettable
    def get_available_jobs(self, session, id, all=False, highlight=False, **params):
        joblist = session.jobs_for_signups(id=id, all=all)

        volunteer = session.volunteer_from_id(id)
        assigned_dept_ids = set(volunteer.assigned_depts_ids)
        event_list = []

        for job in joblist:
            resource_id = job.department_id
            bg_color = "#0d6efd"
            if job.is_public and job.department_id not in assigned_dept_ids:
                resource_id = "public"
                bg_color = "#0dcaf0"
            if highlight and len(job.shifts) == 0:
                bg_color = "#dc3545"
            event_list.append({
                'id': job.id,
                'resourceIds': [resource_id],
                'allDay': False,
                'start': job.start_time_local.isoformat(),
                'end': job.end_time_local.isoformat(),
                'title': f"{job.name}",
                'backgroundColor': bg_color,
                'extendedProps': {
                    'department_name': job.department_name,
                    'desc': _convert_urls(job.description),
                    'desc_text': job.description,
                    'weight': job.weight,
                    'slots': f"{job.slots_taken}/{job.slots}" if job.slots else "",
                    'can_drop': job.slots and (not c.DROP_SHIFTS_DEADLINE or c.BEFORE_DROP_SHIFTS_DEADLINE),
                    'is_public': job.is_public,
                    'assigned': False,
                    }
            })
        session.close()
        return event_list

    @requires_account()
    @ajax_gettable
    def get_assigned_jobs(self, session, id, **params):
        volunteer = session.volunteer_from_id(id)
        event_list = []
        jobs = session.query(Job).filter(Job.shifts.any(attendee_id=volunteer.id)).options(joinedload(Job.shifts))

        for job in jobs:
            if job.is_public and job.department_id not in set(volunteer.assigned_depts_ids):
                resource_id = "public_assigned"
            else:
                resource_id = job.department_id
            event_list.append({
                'id': job.id,
                'resourceIds': [resource_id],
                'allDay': False,
                'start': job.start_time_local.isoformat(),
                'end': job.end_time_local.isoformat(),
                'title': f"{job.name}",
                'backgroundColor': '#198754',
                'extendedProps': {
                    'department_name': job.department_name,
                    'desc': _convert_urls(job.description),
                    'desc_text': job.description,
                    'weight': job.weight,
                    'slots': f"{job.slots_taken}/{job.slots}" if job.slots else "",
                    'can_drop': job.slots and (not c.DROP_SHIFTS_DEADLINE or c.BEFORE_DROP_SHIFTS_DEADLINE),
                    'is_public': job.is_public,
                    'is_setup': job.is_setup,
                    'is_teardown': job.is_teardown,
                    'assigned': True,
                    }
            })
        session.close()
        return event_list

    @requires_account()
    def shifts_ical(self, session, id, **params):
        attendee = session.volunteer_from_id(id)
        icalendar = ics.Calendar()

        calname = "".join(filter(str.isalnum, attendee.full_name)) + "_Shifts"

        for shift in attendee.shifts:
            icalendar.events.add(ics.Event(
                name=shift.job.name,
                location=shift.job.department_name,
                begin=shift.job.start_time,
                end=(shift.job.start_time + timedelta(minutes=shift.job.duration)),
                description=shift.job.description))

        cherrypy.response.headers['Content-Type'] = \
            'text/calendar; charset=utf-8'
        cherrypy.response.headers['Content-Disposition'] = \
            'attachment; filename="{}.ics"'.format(calname)

        return icalendar

    @check_shutdown
    @ajax_gettable
    def jobs(self, id, session, all=False):
        return {'jobs': session.jobs_for_signups(id=id, all=all)}

    @requires_account()
    @check_shutdown
    @ajax
    def sign_up(self, session, id, job_id, **params):
        volunteer = session.volunteer_from_id(id)
        message = session.assign(volunteer.id, job_id)
        if message:
            return {'success': False, 'message': message}
        return {'success': True, 'message': "Signup complete!", 'hours': volunteer.weighted_hours}

    @requires_account()
    @check_shutdown
    @ajax
    def drop(self, session, id, job_id, all=False):
        if c.AFTER_DROP_SHIFTS_DEADLINE:
            return {
                'success': False,
                'message': "You can no longer drop shifts."
            }
        try:
            volunteer = session.volunteer_from_id(id)
            shift = session.shift(job_id=job_id, attendee_id=volunteer.id)
            session.delete(shift)
            session.commit()
        except NoResultFound:
            return {
                'success': True,
                'message': "You've already dropped or have been unassigned from this shift.",
                'hours': volunteer.weighted_hours
            }
        finally:
            return {'success': True, 'message': "Shift dropped.", 'hours': volunteer.weighted_hours}

    @requires_account()
    def onsite_jobs(self, session, id, message=''):
        attendee = session.volunteer_from_id(id)
        return {
            'message': message,
            'attendee': attendee,
            'jobs': [job for job in attendee.possible_and_current
                     if getattr(job, 'taken', False) or job.start_time > localized_now()]
        }

    @requires_account()
    @csrf_protected
    def onsite_sign_up(self, session, id, job_id):
        message = session.assign(id, job_id)
        raise HTTPRedirect('onsite_jobs?id={}&message={}', id, message or 'It worked')
