from uber.common import *

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
        fr = attendee.food_restrictions or FoodRestrictions()
        if params:
            fr = session.food_restrictions(dict(params, attendee_id=attendee.id),
                                          bools = ['no_cheese'],
                                          checkgroups = ['standard'])
            if not fr.sandwich_pref:
                message = 'Please tell us your sandwich preference'
            else:
                session.add(fr)
                if attendee.badge_type == GUEST_BADGE:
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
            'opts': [('', 'Enter your shirt size')] + SHIRT_OPTS[1:]
        }

    @check_shutdown
    def hotel_requests(self, session, message='', decline=None, **params):
        if state.AFTER_ROOM_DEADLINE and STAFF_ROOMS not in AdminAccount.access_set():
            raise HTTPRedirect('index?message={}', 'The room deadline has passed')
        attendee = session.logged_in_volunteer()
        if attendee.badge_type != STAFF_BADGE:
            raise HTTPRedirect('index?message={}', 'Only Staffers can request hotel space')
        requests = session.hotel_requests(params, checkgroups=['nights'], restricted=True)
        if 'attendee_id' in params:
            session.add(requests)
            if decline or not requests.nights:
                requests.nights = ''
                raise HTTPRedirect('index?message={}', "We've recorded that you've declined hotel room space")
            else:
                if requests.setup_teardown:
                    days = ' / '.join(NIGHTS[day] for day in sorted(requests.nights_ints, key=NIGHT_DISPLAY_ORDER.index)
                                                   if day not in CORE_NIGHTS)
                    message = "Your hotel room request has been submitted.  We'll let you know whether your offer to help on {} is accepted, and who your roommates will be, a few weeks after the deadline.".format(days)
                else:
                    message = "You've accepted hotel room space for {}.  We'll let you know your roommates a few weeks after the deadline.".format(requests.nights_display)
                raise HTTPRedirect('index?message={}', message)
        else:
            requests = attendee.hotel_requests or requests
            if requests.is_new:
                requests.nights = ','.join(map(str, CORE_NIGHTS))

        nights = []
        day_before = (EPOCH - timedelta(days=1)).strftime('%A')
        last_day = ESCHATON.strftime('%A').upper()
        day_after = (ESCHATON + timedelta(days=1)).strftime('%A')
        nights.append([globals()[day_before.upper()], getattr(requests, day_before.upper()),
                       "I'd like to help set up on " + day_before])
        for night in CORE_NIGHTS:
            nights.append([night, night in requests.nights_ints, NIGHTS[night]])
        nights.append([globals()[last_day], getattr(requests, last_day),
                       "I'd like to help tear down on {} / {}".format(ESCHATON.strftime('%A'), day_after)])

        return {
            'nights':   nights,
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
    def shifts(self, session):
        return {
            'jobs': session.jobs_for_signups(),
            'name': session.logged_in_volunteer().full_name
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
    def login(self, session, message='', full_name='', email='', zip_code=''):
        if full_name or email or zip_code:
            try:
                attendee = session.lookup_attendee(full_name, email, zip_code)
                if not attendee.staffing:
                    message = SafeString('You are not signed up as a volunteer.  <a href="volunteer?id={}">Click Here</a> to sign up.'.format(attendee.id))
                elif not attendee.assigned_depts_ints:
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
