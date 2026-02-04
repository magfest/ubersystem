import cherrypy
from datetime import datetime, timedelta
import logging
import ics
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import NoResultFound

from uber.config import c
from uber.custom_tags import safe_string
from uber.decorators import ajax, ajax_gettable, all_renderable, check_shutdown, csrf_protected, render, public
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


@all_renderable()
class Root:
    def index(self, session, message=''):
        if c.UBER_SHUT_DOWN:
            return render('staffing/printable.html', {'attendee': session.logged_in_volunteer()})
        else:
            return {
                'message': message,
                'attendee': session.logged_in_volunteer()
            }

    def printable(self, session):
        return {'attendee': session.logged_in_volunteer()}

    def food_restrictions(self, session, message='', **params):
        attendee = session.logged_in_volunteer()
        restrictions = attendee.food_restrictions or FoodRestrictions(attendee_id=attendee.id)
        forms = load_forms(params, restrictions, ["DietaryRestrictions"])

        if cherrypy.request.method == "POST":
            for form in forms.values():
                form.populate_obj(restrictions)
            session.add(restrictions)
            session.commit()
            if attendee.badge_type == c.GUEST_BADGE:
                raise HTTPRedirect('food_restrictions?message={}', 'Your info has been recorded, thanks a bunch!')
            else:
                raise HTTPRedirect('index?message={}', 'Your dietary restrictions have been recorded.')

        return {
            'restrictions': restrictions,
            'forms': forms,
            'message': message,
            'attendee': attendee
        }

    @ajax
    def validate_food_restrictions(self, session, form_list=[], **params):
        all_errors = {}

        attendee = session.logged_in_volunteer()
        restrictions = attendee.food_restrictions or FoodRestrictions()

        if not form_list:
            form_list = ['DietaryRestrictions']
        elif isinstance(form_list, str):
            form_list = [form_list]

        forms = load_forms(params, restrictions, form_list)
        all_errors = validate_model(forms, restrictions)

        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    @check_shutdown
    def shirt_size(self, session, message='', **params):
        attendee = session.logged_in_volunteer()
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
                raise HTTPRedirect('index?message={}', 'Shirt info uploaded.')

        return {
            'message': message,
            'attendee': attendee,
            'opts': [('', 'Enter your shirt size')] + c.SHIRT_OPTS[1:]
        }

    @check_shutdown
    def volunteer_agreement(self, session, message='', agreed_to_terms=None, agreed_to_terms_1=None,
                            agreed_to_terms_2=None, csrf_token=None):
        attendee = session.logged_in_volunteer()
        if csrf_token is not None:
            check_csrf(csrf_token)
            if agreed_to_terms or (agreed_to_terms_1 and agreed_to_terms_2):
                attendee.agreed_to_volunteer_agreement = True
                raise HTTPRedirect('index?message={}', 'Agreement received')
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

    @check_shutdown
    def emergency_procedures(self, session, message='', reviewed_procedures=None, csrf_token=None):
        attendee = session.logged_in_volunteer()
        if csrf_token is not None:
            check_csrf(csrf_token)
            if reviewed_procedures:
                attendee.reviewed_emergency_procedures = True
                raise HTTPRedirect('index?message={}', 'Thanks for reviewing our safety and security information!')

            message = "You must acknowledge that you reviewed our safety and security information."

        return {
            'message': message,
            'attendee': attendee,
        }
    
    @check_shutdown
    def cash_handling(self, session, message='', reviewed_cash_handling=None, csrf_token=None):
        attendee = session.logged_in_volunteer()
        if csrf_token is not None:
            check_csrf(csrf_token)
            if reviewed_cash_handling:
                attendee.reviewed_cash_handling = datetime.now()
                raise HTTPRedirect('index?message={}', 'Thanks for reviewing our payment handling guidelines!')

            message = "You must acknowledge that you reviewed our payment handling guidelines."

        return {
            'message': message,
            'attendee': attendee,
        }

    @check_shutdown
    def credits(self, session, message='', name_in_credits='', csrf_token=None):
        attendee = session.logged_in_volunteer()
        if csrf_token is not None:
            check_csrf(csrf_token)
            attendee.name_in_credits = name_in_credits
            message = "Thank you for providing a name for the credits roll!" if name_in_credits \
                else "You have opted out of having your name in the credits roll."
            raise HTTPRedirect('index?message={}', message)

        return {
            'message': message,
            'attendee': attendee,
        }

    @check_shutdown
    @public
    def volunteer(self, session, id, csrf_token=None, requested_depts_ids=None, message=''):
        attendee = session.attendee(id)
        if requested_depts_ids:
            check_csrf(csrf_token)
            attendee.staffing = True
            attendee.requested_depts_ids = requested_depts_ids
            raise HTTPRedirect(
                'login?message={}',
                "Thanks for signing up as a volunteer; you'll be emailed as "
                "soon as you are assigned to one or more departments.")

        return {
            'message': message,
            'attendee': attendee,
            'requested_depts_ids': requested_depts_ids
        }

    @check_shutdown
    def hotel(self, session, message='', decline=None, **params):
        if c.AFTER_ROOM_DEADLINE and not c.HAS_STAFFING_ADMIN_ACCESS:
            raise HTTPRedirect('../staffing/index?message={}', 'The room deadline has passed')
        attendee = session.logged_in_volunteer()
        if not attendee.hotel_eligible:
            raise HTTPRedirect('../staffing/index?message={}', 'You have not been marked as eligible for hotel space')
        requests = session.hotel_requests(params, checkgroups=['nights'], restricted=True)
        if 'attendee_id' in params:
            requests.attendee = attendee  # foreign keys are automatically admin-only
            session.add(requests)
            if decline or not requests.nights:
                requests.nights = ''
                raise HTTPRedirect(
                    '../staffing/index?message={}', "We've recorded that you've declined hotel room space")
            else:
                if requests.setup_teardown:
                    days = ' / '.join(
                        c.NIGHTS[day] for day in sorted(requests.nights_ints, key=c.NIGHT_DISPLAY_ORDER.index)
                        if day not in c.CORE_NIGHTS)

                    message = "Your hotel room request has been submitted. " \
                        "We'll let you know whether your offer to help on {} is accepted, " \
                        "and who your roommates will be, a few weeks after the deadline.".format(days)

                else:
                    message = "You've accepted hotel room space for {}. " \
                        "We'll let you know your roommates a few weeks after the " \
                        "deadline.".format(requests.nights_display)

                raise HTTPRedirect('../staffing/index?message={}', message)
        else:
            requests = attendee.hotel_requests or requests
            if requests.is_new:
                requests.nights = ','.join(map(str, c.CORE_NIGHTS))

        nights = []
        two_day_before = (c.EPOCH - timedelta(days=2)).strftime('%A')
        day_before = (c.EPOCH - timedelta(days=1)).strftime('%A')
        last_day = c.ESCHATON.strftime('%A').upper()
        day_after = (c.ESCHATON + timedelta(days=1)).strftime('%A')
        nights.append([getattr(c, two_day_before.upper()), getattr(requests, two_day_before.upper()),
                       "I'd like to help set up on " + two_day_before])
        nights.append([getattr(c, day_before.upper()), getattr(requests, day_before.upper()),
                       "I'd like to help set up on " + day_before])
        for night in c.CORE_NIGHTS:
            nights.append([night, night in requests.nights_ints, c.NIGHTS[night]])
        nights.append([getattr(c, last_day), getattr(requests, last_day),
                       "I'd like to help tear down on {} / {}".format(c.ESCHATON.strftime('%A'), day_after)])

        return {
            'nights':   nights,
            'message':  message,
            'requests': requests,
            'attendee': attendee
        }

    @check_shutdown
    def shifts(self, session, **params):
        volunteer = session.logged_in_volunteer()

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
        
        requested_hotel_nights = volunteer.hotel_requests.nights_ints if volunteer.hotel_requests else []

        return {
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
    
    @ajax_gettable
    def get_available_jobs(self, session, all=False, highlight=False, **params):
        joblist = session.jobs_for_signups(all=all)

        volunteer = session.logged_in_volunteer()
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
    
    @ajax_gettable
    def get_assigned_jobs(self, session, **params):
        volunteer = session.logged_in_volunteer()
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

    def shifts_ical(self, session, **params):
        attendee = session.logged_in_volunteer()
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
    def jobs(self, session, all=False):
        return {'jobs': session.jobs_for_signups(all=all)}

    @check_shutdown
    @ajax
    def sign_up(self, session, job_id, **params):
        volunteer = session.logged_in_volunteer()
        message = session.assign(volunteer.id, job_id)
        if message:
            return {'success': False, 'message': message}
        return {'success': True, 'message': "Signup complete!", 'hours': volunteer.weighted_hours}

    @check_shutdown
    @ajax
    def drop(self, session, job_id, all=False):
        if c.AFTER_DROP_SHIFTS_DEADLINE:
            return {
                'success': False,
                'message': "You can no longer drop shifts."
            }
        try:
            volunteer = session.logged_in_volunteer()
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

    @public
    def login(self, session, message='', first_name='', last_name='', email='', zip_code='', original_location=None):
        original_location = create_valid_user_supplied_redirect_url(original_location, default_url='/staffing/index')

        if first_name or last_name or email or zip_code:
            try:
                attendee = session.lookup_attendee(first_name.strip(), last_name.strip(), email, zip_code)
                if not attendee.staffing:
                    message = safe_string(
                        'You are not signed up as a volunteer. '
                        '<a href="volunteer?id={}">Click Here</a> to sign up.'.format(attendee.id))
                elif not attendee.dept_memberships and not c.AT_THE_CON:
                    message = 'You have not been assigned to any departments; ' \
                        'an admin must assign you to a department before you can log in'
            except Exception:
                message = 'No attendee matches that name and email address and zip code'

            if not message:
                ensure_csrf_token_exists()
                cherrypy.session['staffer_id'] = attendee.id
                raise HTTPRedirect(original_location)

        return {
            'message':   message,
            'first_name': first_name,
            'last_name': last_name,
            'email': email,
            'zip_code':  zip_code,
            'original_location': original_location
        }

    def onsite_jobs(self, session, message=''):
        attendee = session.logged_in_volunteer()
        return {
            'message': message,
            'attendee': attendee,
            'jobs': [job for job in attendee.possible_and_current
                     if getattr(job, 'taken', False) or job.start_time > localized_now()]
        }

    @csrf_protected
    def onsite_sign_up(self, session, job_id):
        message = session.assign(session.logged_in_volunteer().id, job_id)
        raise HTTPRedirect('onsite_jobs?message={}', message or 'It worked')
