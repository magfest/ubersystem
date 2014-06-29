from uber.common import *

# TODO: it seems like half the time we're using the json and the other half we're re-loading; this seems confusing and wasteful
# TODO: maybe move this to SessionMixin?
# TODO: confirm that this uses to_dict properly
def dump_jobs(session):
    return json.dumps([job.to_dict() for job in session.logged_in_volunteer().possible_and_current])

@all_renderable(SIGNUPS)
class Root:
    def index(self, session, message=''):
        if UBER_SHUT_DOWN:
            return render('signups/printable.html', {'attendee': session.logged_in_volunteer()})
        else:
            return {
                'message': message,
                'attendee': session.logged_in_volunteer()
            }

    @check_shutdown
    def fire_safety(self, session, message='', fire_safety_cert=None, csrf_token=None):
        attendee = session.logged_in_volunteer()
        if fire_safety_cert is not None:
            check_csrf(csrf_token)
            if not re.match(r'^\d{5}\.\d{5,11}$', fire_safety_cert):
                message = 'That is not a valid certification number'
            else:
                attendee.fire_safety_cert = fire_safety_cert
                raise HTTPRedirect('index?message={}', 'Your fire safety certification has been received')

        return {
            'message': message,
            'attendee': attendee,
            'fire_safety_cert': fire_safety_cert or ''
        }

    @check_shutdown
    def food_restrictions(self, session, message='', **params):
        attendee = session.logged_in_volunteer()
        if params:
            session.add(
                session.food_restrictions(dict(params, attendee_id=attendee.id),
                                          allowed     = ['attendee_id', 'freeform'],
                                          checkgroups = ['standard']))
            if attendee.badge_type == GUEST_BADGE:
                raise HTTPRedirect('food_restrictions?message={}', 'Your info has been recorded, thanks a bunch!')
            else:
                raise HTTPRedirect('index?message={}', 'Your dietary restrictions have been recorded')
        else:
            return {
                'message': message,
                'attendee': attendee,
                'fr': attendee.food_restrictions or FoodRestrictions()
            }

    # TODO: make nights configurable, which is needed both for 8.5 and MAGFest of this year
    @check_shutdown
    def hotel_requests(self, session, message='', decline=None, **params):
        attendee = session.logged_in_volunteer()
        requests = session.hotel_requests(params, checkgroups=['nights'], restricted=True)
        if 'attendee_id' in params:
            session.add(requests)
            if decline or not requests.nights:
                requests.nights = ''
                raise HTTPRedirect('index?message={}', "We've recorded that you've declined hotel room space")
            else:
                nondefault = set(map(int, requests.nights.split(','))) - {THURSDAY, FRIDAY, SATURDAY}
                if nondefault:
                    days = ' / '.join(dict(NIGHTS_OPTS)[day] for day in sorted(nondefault))
                    message = "Your hotel room request has been submitted.  We'll let you know whether your offer to help on {} is accepted, and who your roommates will be, in the first week of December.".format(days)
                else:
                    message = "You've accepted hotel room space for Thursday / Friday / Saturday.  We'll let you know your roommates in the first week of December."
                raise HTTPRedirect('index?message={}', message)
        else:
            requests = attendee.hotel_requests or requests

        return {
            'message':  message,
            'requests': requests,
            'attendee': attendee
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
    @ng_renderable
    def shifts(self, session):
        return {
            'jobs': dump_jobs(session),
            'name': session.logged_in_volunteer().full_name
        }

    @check_shutdown
    def jobs(self, session):
        return json.dumps({'jobs': json.loads(dump_jobs(session))})

    @check_shutdown
    @ajax
    def sign_up(self, session, job_id):
        return {
            'error': session.assign(self.staffer.id, job_id),
            'jobs': json.loads(dump_jobs(session))
        }

    @check_shutdown
    @ajax
    def drop(self, session, job_id):
        try:
            session.delete(session.shift(job_id=job_id, attendee_id=self.logged_in_volunteer().id))
            session.commit()
        except:
            pass
        finally:
            return {'jobs': json.loads(dump_jobs(session))}

    @check_shutdown
    def templates(self, template):
        return ng_render(os.path.join('signups', template))

    @unrestricted
    def login(self, session, message='', full_name='', email='', zip_code=''):
        if full_name or email or zip_code:
            try:
                attendee = session.lookup_attendee(full_name, email, zip_code)
                if not attendee.staffing:
                    message = SafeString('You are not signed up as a volunteer.  <a href="volunteer?id={}">Click Here</a> to sign up.'.format(attendee.id))
                elif not attendee.assigned:
                    message = 'You have not been assigned to any departmemts; an admin must assign you to a department before you can log in'
            except:
                message = 'No attendee matches that name and email address and zip code'

            if not message:
                cherrypy.session['csrf_token'] = uuid4().hex
                cherrypy.session['staffer_id'] = attendee.id
                raise HTTPRedirect('index')

        return {
            'message':   message,
            'full_name': full_name,
            'email':     email,
            'zip_code':  zip_code
        }
