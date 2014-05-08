from uber.common import *

_checkboxes = ['staffing', 'can_spam', 'international', 'no_cellphone']

def check_prereg_reqs(attendee):
    if attendee.age_group == AGE_UNKNOWN:
        return 'You must select an age category'
    elif attendee.badge_type == PSEUDO_DEALER_BADGE and not attendee.phone:
        return 'Your phone number is required'
    elif attendee.amount_extra >= SHIRT_LEVEL and attendee.shirt == NO_SHIRT:
        return 'Your shirt size is required'

def check_dealer(group):
    if not group.address:
        return 'Dealers are required to provide an address for tax purposes'
    elif not group.wares:
        return 'You must provide a detail explanation of what you sell for us to evaluate your submission'
    elif not group.website:
        return "Please enter your business' website address"
    elif not group.description:
        return "Please provide a brief description of your business for our website's Confirmed Vendors page"

def send_banned_email(attendee):
    try:
        send_email(REGDESK_EMAIL, REGDESK_EMAIL, 'Banned attendee registration',
                   render('emails/banned_attendee.txt', {'attendee': attendee}), model='n/a')
    except:
        log.error('unable to send banned email about {}', attendee)

@all_renderable()
class Root:
    
    def stats(self):
        return json.dumps({
            'remaining badges': max(0,(MAX_BADGE_SALES - state.BADGES_SOLD)),
        })
        
    @property
    def preregs(self):
        return cherrypy.session.setdefault('preregs', OrderedDict())

    @property
    def paid_preregs(self):
        return cherrypy.session.setdefault('paid_preregs', [])

    def _get_unsaved(self, id, if_not_found = HTTPRedirect('index')):
        if id in self.preregs:
            return MagModel.from_sessionized(self.preregs[id]).get_unsaved()
        else:
            raise if_not_found

    @check_if_can_reg
    def index(self, message=''):
        if not self.preregs:
            raise HTTPRedirect('badge_choice?message={}', message) if message else HTTPRedirect('badge_choice')
        else:
            return {
                'message': message,
                'charge': Charge(list(self.preregs.values()))   # TODO: fix listify
            }
            
    @check_if_can_reg
    def badge_choice(self, message=''):
        return {'message': message}

    @check_if_can_reg
    def form(self, message='', edit_id=None, **params):
        if 'badge_type' not in params and edit_id is None:
            raise HTTPRedirect('badge_choice?message={}', 'You must select a badge type')

        params['id'] = 'None'   # security!
        if edit_id is not None:
            attendee, group = self._get_unsaved(edit_id, if_not_found = HTTPRedirect('badge_choice?message={}', 'That preregistration has already been finalized'))
            attendee.apply(params, bools=_checkboxes)
            group.apply(params)
            params.setdefault('badges', group.badges)
        else:
            attendee = Attendee.get(params, bools=_checkboxes, ignore_csrf=True, restricted=True)
            group = Group.get(params, ignore_csrf=True, restricted=True)

        if attendee.badge_type not in state.PREREG_BADGE_TYPES:
            raise HTTPRedirect('badge_choice?message={}', 'Dealer registration is not open' if attendee.is_dealer else 'Invalid badge type')

        if 'first_name' in params:
            message = check(attendee) or check_prereg_reqs(attendee)
            if not message and attendee.badge_type in [PSEUDO_DEALER_BADGE, PSEUDO_GROUP_BADGE]:
                message = check(group)
            elif not message and attendee.badge_type == PSEUDO_DEALER_BADGE:
                message = check_dealer(group)

            if not message:
                if attendee.badge_type in [PSEUDO_DEALER_BADGE, PSEUDO_GROUP_BADGE]:
                    attendee.paid = PAID_BY_GROUP
                    if attendee.badge_type == PSEUDO_GROUP_BADGE:
                        group.tables = 0
                        group.prepare_prereg_badges(attendee, params['badges'])
                    else:
                        group.status = WAITLISTED if state.AFTER_DEALER_REG_DEADLINE else UNAPPROVED

                if attendee.is_dealer:
                    group.save()
                    attendee.group = group
                    attendee.save()
                    group.assign_badges(params['badges'])
                    send_email(MARKETPLACE_EMAIL, MARKETPLACE_EMAIL, 'Dealer application received',
                               render('emails/dealer_reg_notification.txt', {'group': group}), model=group)
                    raise HTTPRedirect('dealer_confirmation?id={}', group.id)
                else:
                    target = group if group.badges else attendee
                    track_type = EDITED_PREREG if target.secret_id in self.preregs else UNPAID_PREREG
                    self.preregs[target.secret_id] = target.sessionize()
                    Tracking.track(track_type, attendee)
                    if group.badges:
                        Tracking.track(track_type, group)

                if Attendee.objects.filter(first_name=attendee.first_name, last_name=attendee.last_name, email=attendee.email):
                    raise HTTPRedirect('duplicate?id={}', group.secret_id if attendee.paid == PAID_BY_GROUP else attendee.secret_id)

                if attendee.full_name in BANNED_ATTENDEES:
                    raise HTTPRedirect('banned?id={}', group.secret_id if attendee.paid == PAID_BY_GROUP else attendee.secret_id)

                raise HTTPRedirect('index')
        else:
            attendee.can_spam = edit_id is None     # only defaults to true for these forms
            if attendee.badge_type == PSEUDO_DEALER_BADGE and state.AFTER_DEALER_REG_DEADLINE:
                message = 'Dealer registration is closed, but you can fill out this form to add yourself to our waitlist'

        return {
            'message':    message,
            'attendee':   attendee,
            'group':      group,
            'edit_id':    edit_id,
            'badges':     params.get('badges'),
            'affiliates': affiliates()
        }

    def duplicate(self, id):
        attendee, group = self._get_unsaved(id)
        orig = Attendee.objects.filter(first_name=attendee.first_name, last_name=attendee.last_name, email=attendee.email)
        if not orig:
            raise HTTPRedirect('index')

        return {
            'duplicate': attendee,
            'attendee': orig[0]
        }

    def banned(self, id):
        attendee, group = self._get_unsaved(id)
        return {'attendee': attendee}

    @credit_card
    def prereg_payment(self, payment_id, stripeToken):
        charge = Charge.get(payment_id)
        if not charge.total_cost:
            message = 'Your preregistration has already been paid for, so your credit card has not been charged'
        elif charge.amount != charge.total_cost:
            message = 'Our preregistration price has gone up; please fill out the payment form again at the higher price'
        else:
            message = charge.charge_cc(stripeToken)

        if message:
            raise HTTPRedirect('index?message={}', message)

        for attendee in charge.attendees:
            attendee.paid = HAS_PAID
            attendee.amount_paid = attendee.total_cost
            attendee.save()
            if attendee.full_name in BANNED_ATTENDEES:
                send_banned_email(attendee)

        for group in charge.groups:
            group.assign_prereg_badges()
            group.amount_paid = group.total_cost
            group.save()
            if group.leader.full_name in BANNED_ATTENDEES:
                send_banned_email(group.leader)

        self.preregs.clear()
        self.paid_preregs.extend(charge.targets)
        raise HTTPRedirect('paid_preregistrations')

    def paid_preregistrations(self):
        if not self.paid_preregs:
            raise HTTPRedirect('index')
        else:
            return {'preregs': [MagModel.from_sessionized(d) for d in self.paid_preregs]}

    def delete(self, id):
        self.preregs.pop(id, None)
        raise HTTPRedirect('index?message={}', 'Preregistration deleted')

    def dealer_confirmation(self, id):
        return {'group': Group.get(id)}

    def group_members(self, id, message=''):
        group = Group.get(id)
        return {
            'group':   group,
            'charge': Charge(group),
            'message': message
        }

    def register_group_member(self, message='', **params):
        attendee = Attendee.get(params, bools=_checkboxes, restricted=True)
        if 'first_name' in params:
            message = check(attendee) or check_prereg_reqs(attendee)
            if not message and not params['first_name']:
                message = 'First and Last Name are required fields'
            if not message:
                attendee.save()
                if attendee.full_name in BANNED_ATTENDEES:
                    send_banned_email(attendee)

                if attendee.amount_unpaid:
                    raise HTTPRedirect('group_extra_payment_form?id={}', attendee.secret_id)
                else:
                    raise HTTPRedirect('group_members?id={}&message={}', attendee.group.secret_id, 'Badge registered successfully')
        else:
            attendee.can_spam = True    # only defaults to true for these forms

        return {
            'attendee': attendee,
            'message':  message,
            'affiliates': affiliates()
        }

    def group_extra_payment_form(self, id):
        attendee = Attendee.get(id)
        return {
            'attendee': attendee,
            'charge': Charge(attendee, description = '{} kicking in extra'.format(attendee.full_name))
        }

    def group_undo_extra_payment(self, id):
        attendee = Attendee.get(id)
        attendee.amount_extra -= attendee.amount_unpaid
        attendee.save()
        raise HTTPRedirect('group_members?id={}&message={}', attendee.group.secret_id, 'Extra payment undone')

    @credit_card
    def process_group_payment(self, payment_id, stripeToken):
        charge = Charge.get(payment_id)
        [group] = charge.groups
        message = charge.charge_cc(stripeToken)
        if message:
            raise HTTPRedirect('group_members?id={}&message={}', group.secret_id, message)
        else:
            group.amount_paid += charge.dollar_amount
            group.save()
            raise HTTPRedirect('group_members?id={}&message={}', group.secret_id, 'Your payment has been accepted!')

    @credit_card
    def process_group_member_payment(self, payment_id, stripeToken):
        charge = Charge.get(payment_id)
        [attendee] = charge.attendees
        message = charge.charge_cc(stripeToken)
        if message:
            attendee.amount_extra -= attendee.amount_unpaid
            attendee.save()
            raise HTTPRedirect('group_members?id={}&message={}', attendee.group.secret_id, message)
        else:
            attendee.amount_paid += charge.dollar_amount
            attendee.save()
            raise HTTPRedirect('group_members?id={}&message={}', attendee.group.secret_id, 'Extra payment accepted')

    @csrf_protected
    def unset_group_member(self, id):
        attendee = Attendee.get(id)
        try:
            send_email(REGDESK_EMAIL, attendee.email, '{{ EVENT_NAME }} group registration dropped',
                       render('emails/group_member_dropped.txt', {'attendee': attendee}), model=attendee)
        except:
            log.error('unable to send group unset email', exc_info=True)

        for attr in ['first_name','last_name','email','zip_code','ec_phone','phone','interests','found_how','comments']:
            setattr(attendee, attr, '')
        attendee.age_group = AGE_UNKNOWN
        attendee.save()
        raise HTTPRedirect('group_members?id={}&message={}', attendee.group.secret_id, 'Attendee unset; you may now assign their badge to someone else')

    def add_group_members(self, id, count):
        group = Group.get(id)
        if int(count) < group.min_badges_addable:
            raise HTTPRedirect('group_members?id={}&message={}', group.secret_id, 'This group cannot add fewer than {} badges'.format(group.min_badges_addable))

        charge = Charge(group, amount = 100 * int(count) * state.GROUP_PRICE, description = '{} extra badges for {}'.format(count, group.name))
        charge.badges_to_add = int(count)
        return {
            'group': group,
            'charge': charge
        }

    @credit_card
    def pay_for_extra_members(self, payment_id, stripeToken):
        charge = Charge.get(payment_id)
        [group] = charge.groups
        if charge.dollar_amount != charge.badges_to_add * state.GROUP_PRICE:
            message = 'Our preregistration price has gone up since you tried to add the bagdes; please try again'
        else:
            message = charge.charge_cc(stripeToken)

        if message:
            raise HTTPRedirect('group_members?id={}&message={}', group.secret_id, message)
        else:
            group.assign_badges(group.badges + charge.badges_to_add)
            group.amount_paid += charge.dollar_amount
            group.save()
            raise HTTPRedirect('group_members?id={}&message={}', group.secret_id, 'You payment has been accepted and the badges have been added to your group')

    def transfer_badge(self, message = '', **params):
        old = Attendee.get(params['id'])
        assert old.is_transferrable, 'This badge is not transferrable'
        attendee = Attendee.get(params, bools=_checkboxes, restricted=True)

        if 'first_name' in params:
            message = check(attendee) or check_prereg_reqs(attendee)
            if not message and (not params['first_name'] and not params['last_name']):
                message = 'First and Last names are required.'
            if not message:
                attendee.save()
                subject, body = '{{ EVENT_NAME }} Registration Transferred', render('emails/transfer_badge.txt', {'new': attendee, 'old': old})
                try:
                    send_email(REGDESK_EMAIL, [old.email, attendee.email, REGDESK_EMAIL], subject, body, model = attendee)
                except:
                    log.error('unable to send badge change email', exc_info = True)

                if attendee.full_name in BANNED_ATTENDEES:
                    send_banned_email(attendee)

                raise HTTPRedirect('confirm?id={}&message={}', attendee.secret_id, 'Your registration has been transferred')
        else:
            for attr in ['first_name','last_name','email','zip_code','international','ec_phone','phone','interests','age_group','staffing','requested_depts']:
                setattr(attendee, attr, getattr(Attendee(), attr))

        return {
            'old':      old,
            'attendee': attendee,
            'message':  message
        }

    def confirm(self, message = '', return_to = 'confirm', **params):
        attendee = Attendee.get(params, bools=_checkboxes, restricted=True)

        placeholder = attendee.placeholder
        if 'email' in params:
            attendee.placeholder = False
            message = check(attendee) or check_prereg_reqs(attendee)
            if not message:
                attendee.save()
                if placeholder:
                    message = 'Your registration has been confirmed.'
                else:
                    message = 'Your information has been updated.'

                page = ('confirm?id=' + attendee.secret_id + '&') if return_to == 'confirm' else (return_to + '?')
                if attendee.amount_unpaid:
                    cherrypy.session['return_to'] = page
                    raise HTTPRedirect('attendee_donation_form?id={}', attendee.secret_id)
                else:
                    raise HTTPRedirect(page + 'message=' + message)

        elif attendee.amount_unpaid and attendee.zip_code:  # don't skip to payment until the form is filled out
            raise HTTPRedirect('attendee_donation_form?id={}&message={}', attendee.secret_id, message)

        attendee.placeholder = placeholder
        if not message and attendee.placeholder:
            message = 'You are not yet registered!  You must fill out this form to complete your registration.'
        elif not message:
            message = 'You are already registered but you may update your information with this form.'

        return {
            'return_to':  return_to,
            'attendee':   attendee,
            'message':    message,
            'affiliates': affiliates()
        }

    def guest_food(self, id):
        cherrypy.session['staffer_id'] = Attendee.get(id).id
        raise HTTPRedirect('../signups/food_restrictions')

    def attendee_donation_form(self, id, message=''):
        attendee = Attendee.get(id)
        return {
            'message': message,
            'attendee': attendee,
            'charge': Charge(attendee, description = '{}{}'.format(attendee.full_name, '' if attendee.overridden_price else ' kicking in extra'))
        }

    def undo_attendee_donation(self, id):
        attendee = Attendee.get(id)
        attendee.amount_extra = max(0, attendee.amount_extra - attendee.amount_unpaid)
        attendee.save()
        raise HTTPRedirect(cherrypy.session.pop('return_to', 'confirm?id=' + id))

    @credit_card
    def process_attendee_donation(self, payment_id, stripeToken):
        charge = Charge.get(payment_id)
        [attendee] = charge.attendees
        message = charge.charge_cc(stripeToken)
        return_to = cherrypy.session.pop('return_to', 'confirm?id=' + attendee.secret_id + '&') + 'message={}'
        if message:
            raise HTTPRedirect(return_to, message)
        else:
            attendee.amount_paid += charge.dollar_amount
            if attendee.paid == NOT_PAID and attendee.amount_paid == attendee.total_cost:
                attendee.paid = HAS_PAID
            attendee.save()
            raise HTTPRedirect(return_to, 'Your payment has been accepted, thanks so much!')

    def event(self, slug, *, id, register=None):
        attendee = Attendee.get(id)
        event = SEASON_EVENTS[slug]
        deadline_passed = datetime.now() > event['deadline']
        assert attendee.amount_extra >= SEASON_LEVEL
        if register and not deadline_passed:
            SeasonPassTicket.objects.get_or_create(attendee=attendee, slug=slug)
            raise HTTPRedirect(slug + '?id={}', id)

        return {
            'event': event,
            'attendee': attendee,
            'deadline_passed': deadline_passed,
            'registered': slug in [spt.slug for spt in attendee.seasonpassticket_set.all()]
        }

if POST_CON:
    @all_renderable()
    class Root:
        def default(self, *args, **kwargs):
            return """
                <html><head></head><body style='text-align:center'>
                    <h2 style='color:red'>Hope you had a great MAGFest!</h2>
                    Preregistration for MAGFest 13 will open in the summer.
                </body></html>
            """

        def shirt(self, message = '', **params):
            attendee = Attendee.get(params, restricted = True)
            assert attendee.owed_shirt, "There's no record of {} being owed a tshirt".format(attendee.full_name)
            if 'address' in params:
                if attendee.shirt in [NO_SHIRT, SIZE_UNKNOWN]:
                    message = 'Please select a shirt size.'
                elif not attendee.address:
                    message = 'Your address is required.'
                else:
                    attendee.save()
                    raise HTTPRedirect('shirt?id={}', attendee.secret_id)
            elif attendee.address:
                message = "We've recorded your shirt size and address, which you may update anytime before Jan 31st."

            return {
                'message': message,
                'attendee': attendee
            }
