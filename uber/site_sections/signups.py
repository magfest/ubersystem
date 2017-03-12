from uber.common import *


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
    def shirt_size(self, session, message='', shirt=None, csrf_token=None):
        attendee = session.logged_in_volunteer()
        if shirt is not None:
            check_csrf(csrf_token)
            if not shirt:
                message = 'You must select a shirt size'
            else:
                attendee.shirt = int(shirt)
                raise HTTPRedirect('index?message={}', 'Shirt size uploaded')

        return {
            'message': message,
            'attendee': attendee,
            'opts': [('', 'Enter your shirt size')] + c.SHIRT_OPTS[1:]
        }

    @check_shutdown
    @unrestricted
    def volunteer(self, session, id, csrf_token=None, requested_depts='', message='Select which departments interest you as a volunteer.'):
        attendee = session.attendee(id)
        if requested_depts:
            check_csrf(csrf_token)
            attendee.staffing = True
            attendee.requested_depts = ','.join(listify(requested_depts))
            raise HTTPRedirect('login?message={}', "Thanks for signing up as a volunteer; you'll be emailed as soon as you are assigned to one or more departments.")

        return {
            'message': message,
            'attendee': attendee,
            'requested_depts': requested_depts
        }

    @check_shutdown
    def shifts(self, session, tgt_date='', state=''):
        joblist = session.jobs_for_signups()
        return {
            'jobs': joblist,
            'name': session.logged_in_volunteer().full_name,
            'hours': session.logged_in_volunteer().weighted_hours
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
        except:
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
                    message = SafeString('You are not signed up as a volunteer.  <a href="volunteer?id={}">Click Here</a> to sign up.'.format(attendee.id))
                elif not attendee.assigned_depts_ints and not c.AT_THE_CON:
                    message = 'You have not been assigned to any departmemts; an admin must assign you to a department before you can log in'
            except:
                message = 'No attendee matches that name and email address and zip code'

            if not message:
                cherrypy.session['csrf_token'] = uuid4().hex
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
