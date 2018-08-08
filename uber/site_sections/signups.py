import cherrypy
from datetime import timedelta

from uber.config import c
from uber.custom_tags import safe_string
from uber.decorators import ajax, ajax_gettable, all_renderable, check_shutdown, csrf_protected, render, unrestricted
from uber.errors import HTTPRedirect
from uber.utils import check_csrf, create_valid_user_supplied_redirect_url, ensure_csrf_token_exists, localized_now


@all_renderable(c.SIGNUPS)
class Root:

    def index(self, session, message=''):
        if c.UBER_SHUT_DOWN or c.AT_THE_CON:
            return render('signups/printable.html', {'attendee': session.logged_in_volunteer()})
        else:
            return {
                'message': message,
                'attendee': session.logged_in_volunteer()
            }

    def printable(self, session):
        return {'attendee': session.logged_in_volunteer()}

    @check_shutdown
    def food_restrictions(self, session, message='', **params):
        from uber.models.attendee import FoodRestrictions
        attendee = session.logged_in_volunteer()
        fr = attendee.food_restrictions or FoodRestrictions()
        if params:
            fr = session.food_restrictions(dict(params, attendee_id=attendee.id), checkgroups=['standard'])
            session.add(fr)
            if attendee.badge_type == c.GUEST_BADGE:
                raise HTTPRedirect('food_restrictions?message={}', 'Your info has been recorded, thanks a bunch!')
            else:
                raise HTTPRedirect('index?message={}', 'Your dietary restrictions have been recorded')

        return {
            'fr': fr,
            'message': message,
            'attendee': attendee
        }

    @check_shutdown
    def shirt_size(self, session, message='', shirt=None, second_shirt=None, csrf_token=None):
        attendee = session.logged_in_volunteer()
        if shirt is not None:
            check_csrf(csrf_token)
            if not shirt:
                message = 'You must select a shirt size'
            else:
                attendee.shirt = int(shirt)
                if attendee.gets_staff_shirt and c.SHIRTS_PER_STAFFER > 1 and c.BEFORE_SHIRT_DEADLINE:
                    attendee.second_shirt = int(second_shirt)
                raise HTTPRedirect('index?message={}', 'Shirt info uploaded')

        return {
            'message': message,
            'attendee': attendee,
            'opts': [('', 'Enter your shirt size')] + c.SHIRT_OPTS[1:]
        }

    @check_shutdown
    def volunteer_agreement(self, session, message='', agreed_to_terms=None, csrf_token=None):
        attendee = session.logged_in_volunteer()
        if csrf_token is not None:
            check_csrf(csrf_token)
            if agreed_to_terms:
                attendee.agreed_to_volunteer_agreement = True
                raise HTTPRedirect('index?message={}', 'Agreement received')

            message = "You must agree to the terms of the agreement"

        return {
            'message': message,
            'attendee': attendee,
            'agreement_end_date': c.ESCHATON.date() + timedelta(days=31),
        }

    @check_shutdown
    @unrestricted
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
    def shifts(self, session, view='', start=''):
        joblist = session.jobs_for_signups()
        con_days = -(-c.CON_LENGTH // 24)  # Equivalent to ceil(c.CON_LENGTH / 24)

        volunteer = session.logged_in_volunteer()
        assigned_dept_ids = set(volunteer.assigned_depts_ids)
        has_public_jobs = False
        for job in joblist:
            job['is_public_to_volunteer'] = job['is_public'] and job['department_id'] not in assigned_dept_ids
            if job['is_public_to_volunteer']:
                has_public_jobs = True

        has_setup = volunteer.can_work_setup or any(d.is_setup_approval_exempt for d in volunteer.assigned_depts)
        has_teardown = volunteer.can_work_teardown or any(
            d.is_teardown_approval_exempt for d in volunteer.assigned_depts)

        if has_setup and has_teardown:
            cal_length = c.CON_TOTAL_LENGTH
        elif has_setup:
            cal_length = con_days + c.SETUP_SHIFT_DAYS
        elif has_teardown:
            cal_length = con_days + 2  # There's no specific config for # of shift signup days
        else:
            cal_length = con_days

        return {
            'jobs': joblist,
            'has_public_jobs': has_public_jobs,
            'name': session.logged_in_volunteer().full_name,
            'hours': session.logged_in_volunteer().weighted_hours,
            'assigned_depts_labels': volunteer.assigned_depts_labels,
            'view': view,
            'start': start,
            'start_day': c.SHIFTS_START_DAY if has_setup else c.EPOCH,
            'cal_length': cal_length
        }

    @check_shutdown
    @ajax_gettable
    def jobs(self, session):
        return {'jobs': session.jobs_for_signups()}

    @check_shutdown
    @ajax
    def sign_up(self, session, job_id):
        return {
            'error': session.assign(session.logged_in_volunteer().id, job_id),
            'jobs': session.jobs_for_signups()
        }

    @check_shutdown
    @ajax
    def drop(self, session, job_id):
        try:
            shift = session.shift(job_id=job_id, attendee_id=session.logged_in_volunteer().id)
            session.delete(shift)
            session.commit()
        except Exception:
            pass
        finally:
            return {'jobs': session.jobs_for_signups()}

    @unrestricted
    def login(self, session, message='',  first_name='', last_name='', email='', zip_code='', original_location=None):
        original_location = create_valid_user_supplied_redirect_url(original_location, default_url='index')

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
            except Exception as ex:
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
