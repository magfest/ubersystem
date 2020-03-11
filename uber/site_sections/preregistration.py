import json
from datetime import timedelta
from functools import wraps

import cherrypy
from email_validator import validate_email, EmailNotValidError
from pockets import listify
from pockets.autolog import log
from sqlalchemy import func

from uber.config import c
from uber.decorators import all_renderable, check_if_can_reg, credit_card, csrf_protected, id_required, log_pageview, \
    redirect_if_at_con_to_kiosk, render
from uber.errors import HTTPRedirect
from uber.models import Attendee, Attraction, Email, Group, PromoCode, PromoCodeGroup, ReceiptItem, Tracking
from uber.tasks.email import send_email
from uber.utils import add_opt, check, check_pii_consent, localized_now, Charge


def check_post_con(klass):
    def wrapper(func):
        @wraps(func)
        def wrapped(self, *args, **kwargs):
            if c.POST_CON:  # TODO: replace this with a template and make that suitably generic
                return """
                <html><head></head><body style='text-align:center'>
                    <h2 style='color:red'>Hope you had a great {event}!</h2>
                    Preregistration for {event} {year} will open in a few months.
                </body></html>
                """.format(event=c.EVENT_NAME, year=(1 + int(c.EVENT_YEAR)) if c.EVENT_YEAR else '')
            else:
                return func(self, *args, **kwargs)
        return wrapped

    for name in dir(klass):
        method = getattr(klass, name)
        if not name.startswith('_') and hasattr(method, '__call__'):
            setattr(klass, name, wrapper(method))
    return klass

def check_prereg_promo_code(session, attendee):
    """
    Prevents double-use of promo codes if two people have the same promo code in their cart but only one use is remaining.
    If the attendee originally entered a 'universal' group code, which we track via Charge.universal_promo_codes,
    we instead try to find a different valid code and only throw an error if there are none left.
    """
    promo_code = session.query(PromoCode).filter(PromoCode.id==attendee.promo_code_id).with_for_update().one()
    
    if not promo_code.is_unlimited and not promo_code.uses_remaining:
        universal_code = Charge.universal_promo_codes.get(attendee.id)
        if universal_code:
            message = session.add_promo_code_to_attendee(attendee, universal_code)
            if message:
                return "There are no more badges left in the group {} is trying to claim a badge in.".format(attendee.full_name)
            return ""
        attendee.promo_code_id = None
        session.commit()
        return "The promo code you're using for {} has been used too many times.".format(attendee.full_name)


@all_renderable(public=True)
@check_post_con
class Root:
    def _get_unsaved(self, id, if_not_found=None):
        """
        if_not_found:  pass in an HTTPRedirect() class to raise if the unsaved attendee is not found.
                       by default we will redirect to the index page
        """
        if id in Charge.unpaid_preregs:
            return Charge.from_sessionized(Charge.unpaid_preregs[id])
        else:
            raise HTTPRedirect('index') if if_not_found is None else if_not_found

    def kiosk(self):
        """
        Landing page for kiosk laptops, this should redirect to whichever page we want at-the-door laptop kiosks
        to land on.  The reason this is a redirect is that at-the-door laptops might be imaged and hard to change
        their default landing page.  If sysadmins want to change the landing page, they can do it here.
        """
        raise HTTPRedirect(c.KIOSK_REDIRECT_URL)

    def check_prereg(self):
        return json.dumps({
            'force_refresh': not c.AT_THE_CON and (c.AFTER_PREREG_TAKEDOWN or not c.ATTENDEE_BADGE_AVAILABLE)})

    def check_if_preregistered(self, session, message='', **params):
        if 'email' in params:
            attendee = session.query(Attendee).filter(func.lower(Attendee.email) == func.lower(params['email'])).first()
            message = 'Thank you! You will receive a confirmation email if ' \
                'you are registered for {}.'.format(c.EVENT_NAME_AND_YEAR)

            subject = c.EVENT_NAME_AND_YEAR + ' Registration Confirmation'

            if attendee:
                last_email = (session.query(Email)
                                     .filter_by(to=attendee.email, subject=subject)
                                     .order_by(Email.when.desc()).first())
                if not last_email or last_email.when < (localized_now() - timedelta(days=7)):
                    send_email.delay(
                        c.REGDESK_EMAIL,
                        attendee.email,
                        subject,
                        render('emails/reg_workflow/prereg_check.txt', {'attendee': attendee}, encoding=None),
                        model=attendee.to_dict('id'))

        return {'message': message}

    @check_if_can_reg
    def index(self, session, message=''):
        if not Charge.unpaid_preregs:
            raise HTTPRedirect('form?message={}', message) if message else HTTPRedirect('form')
        else:
            charge = Charge(listify(Charge.unpaid_preregs.values()))
            for attendee in charge.attendees:
                if attendee.promo_code:
                    real_code = session.query(PromoCode).filter_by(code=attendee.promo_code.code).first()
                    if real_code and real_code.group:
                        attendee.promo_group_name = real_code.group.name
            return {
                'message': message,
                'charge': charge
            }

    @check_if_can_reg
    def dealer_registration(self, message=''):
        return self.form(badge_type=c.PSEUDO_DEALER_BADGE, message=message)

    @check_if_can_reg
    def repurchase(self, session, id, **params):
        if 'csrf_token' in params:
            old_attendee = session.attendee(id).to_dict(c.UNTRANSFERABLE_ATTRS)
            del old_attendee['id']
            new_attendee = Attendee(**old_attendee)
            Charge.unpaid_preregs[new_attendee.id] = Charge.to_sessionized(new_attendee)
            Tracking.track(c.UNPAID_PREREG, new_attendee)
            raise HTTPRedirect("form?edit_id={}", new_attendee.id)
        return {
            'id': id
        }

    @cherrypy.expose(['post_form', 'post_dealer'])
    @redirect_if_at_con_to_kiosk
    @check_if_can_reg
    def form(self, session, message='', edit_id=None, **params):
        """
        Our production NGINX config caches the page at /preregistration/form.
        Since it's cached, we CAN'T return a session cookie with the page. We
        must POST to a different URL in order to bypass the cache and get a
        valid session cookie. Thus, this page is also exposed as "post_form".
        """
        params['id'] = 'None'   # security!
        group = Group()

        if edit_id is not None:
            attendee = self._get_unsaved(
                edit_id,
                if_not_found=HTTPRedirect('form?message={}', 'That preregistration has already been finalized'))
            attendee.apply(params, restricted=True)
            params.setdefault('pii_consent', True)
        else:
            attendee = session.attendee(params, ignore_csrf=True, restricted=True)

            if attendee.badge_type == c.PSEUDO_DEALER_BADGE:
                if not c.DEALER_REG_OPEN:
                    return render('static_views/dealer_reg_closed.html') if c.AFTER_DEALER_REG_START \
                        else render('static_views/dealer_reg_not_open.html')

                # Both the Attendee class and Group class have identically named
                # address fields. In order to distinguish the two sets of address
                # fields in the params, the Group fields are prefixed with "group_"
                # when the form is submitted. To prevent instantiating the Group object
                # with the Attendee's address fields, we must clone the params and
                # rename all the "group_" fields.
                group_params = dict(params)
                for field_name in ['country', 'region', 'zip_code', 'address1', 'address2', 'city']:
                    group_params[field_name] = params.get('group_{}'.format(field_name), '')
                    if params.get('copy_address'):
                        params[field_name] = group_params[field_name]
                        attendee.apply(params)

                group = session.group(group_params, ignore_csrf=True, restricted=True)

        if c.PAGE == 'post_dealer':
            attendee.badge_type = c.PSEUDO_DEALER_BADGE
        elif not attendee.badge_type:
            attendee.badge_type = c.ATTENDEE_BADGE

        if cherrypy.request.method == 'POST' or edit_id is not None:
            message = check_pii_consent(params, attendee) or message
            if not message and attendee.badge_type not in c.PREREG_BADGE_TYPES:
                message = 'Invalid badge type!'
            if not message and c.BADGE_PROMO_CODES_ENABLED and params.get('promo_code'):
                if session.lookup_promo_or_group_code(params.get('promo_code'), PromoCodeGroup):
                    Charge.universal_promo_codes[attendee.id] = params.get('promo_code')
                message = session.add_promo_code_to_attendee(attendee, params.get('promo_code'))

        if message:
            return {
                'message':    message,
                'attendee':   attendee,
                'group':      group,
                'edit_id':    edit_id,
                'affiliates': session.affiliates(),
                'cart_not_empty': Charge.unpaid_preregs,
                'copy_address': params.get('copy_address'),
                'promo_code_code': params.get('promo_code', ''),
                'pii_consent': params.get('pii_consent'),
                'name': params.get('name', ''),
                'badges': params.get('badges', 0),
            }

        if 'first_name' in params:
            if attendee.badge_type == c.PSEUDO_DEALER_BADGE:
                message = check(group, prereg=True)

            message = message or check(attendee, prereg=True)

            if attendee.badge_type in [c.PSEUDO_GROUP_BADGE, c.PSEUDO_DEALER_BADGE]:
                message = "Please enter a group name" if not params.get('name') else message
            else:
                params['badges'] = 0
                params['name'] = ''

            if not message:
                if attendee.badge_type == c.PSEUDO_DEALER_BADGE:
                    attendee.paid = c.PAID_BY_GROUP
                    group.attendees = [attendee]
                    session.assign_badges(group, params['badges'])
                    group.status = c.WAITLISTED if c.DEALER_REG_SOFT_CLOSED else c.UNAPPROVED
                    attendee.ribbon = add_opt(attendee.ribbon_ints, c.DEALER_RIBBON)
                    attendee.badge_type = c.ATTENDEE_BADGE

                    session.add_all([attendee, group])
                    session.commit()
                    try:
                        send_email.delay(
                            c.MARKETPLACE_EMAIL,
                            c.MARKETPLACE_EMAIL,
                            '{} Received'.format(c.DEALER_APP_TERM.title()),
                            render('emails/dealers/reg_notification.txt', {'group': group}, encoding=None),
                            model=group.to_dict('id'))
                        send_email.delay(
                            c.MARKETPLACE_EMAIL,
                            attendee.email,
                            '{} Received'.format(c.DEALER_APP_TERM.title()),
                            render('emails/dealers/application.html', {'group': group}, encoding=None),
                            'html',
                            model=group.to_dict('id'))
                    except Exception:
                        log.error('unable to send marketplace application confirmation email', exc_info=True)
                    raise HTTPRedirect('dealer_confirmation?id={}', group.id)
                else:
                    track_type = c.UNPAID_PREREG
                    if attendee.id in Charge.unpaid_preregs:
                        track_type = c.EDITED_PREREG
                        # Clear out any previously cached targets, in case the unpaid badge
                        # has been edited and changed from a single to a group or vice versa.
                        del Charge.unpaid_preregs[attendee.id]

                    Charge.unpaid_preregs[attendee.id] = Charge.to_sessionized(attendee,
                                                                               params.get('name'),
                                                                               params.get('badges'))
                    Tracking.track(track_type, attendee)

                if session.attendees_with_badges().filter_by(
                        first_name=attendee.first_name, last_name=attendee.last_name, email=attendee.email).count():

                    raise HTTPRedirect('duplicate?id={}', group.id if attendee.paid == c.PAID_BY_GROUP else attendee.id)

                if attendee.banned:
                    raise HTTPRedirect('banned?id={}', group.id if attendee.paid == c.PAID_BY_GROUP else attendee.id)

                if c.PREREG_REQUEST_HOTEL_INFO_OPEN:
                    hotel_page = 'hotel?edit_id={}' if edit_id else 'hotel?id={}'
                    raise HTTPRedirect(hotel_page, group.id if attendee.paid == c.PAID_BY_GROUP else attendee.id)
                else:
                    raise HTTPRedirect('index')

        else:
            if edit_id is None:
                if attendee.badge_type == c.PSEUDO_DEALER_BADGE:
                    # All new dealer signups should default to receiving the
                    # hotel info email, even if the deadline has passed.
                    # There's a good chance some dealers will apply for a table
                    # AFTER the hotel booking deadline, but BEFORE the hotel
                    # booking is sent out. This ensures they'll still receive
                    # the email, as requested by the Marketplace Department.
                    attendee.requested_hotel_info = True

            if attendee.badge_type == c.PSEUDO_DEALER_BADGE and c.DEALER_REG_SOFT_CLOSED:
                message = '{} is closed, but you can ' \
                    'fill out this form to add yourself to our waitlist'.format(c.DEALER_REG_TERM.title())

        promo_code_group = None
        if attendee.promo_code:
            promo_code_group = session.query(PromoCode).filter_by(code=attendee.promo_code.code).first().group

        return {
            'message':    message,
            'attendee':   attendee,
            'badges': params.get('badges', 0),
            'name': params.get('name', ''),
            'group':      group,
            'promo_code_group': promo_code_group,
            'edit_id':    edit_id,
            'affiliates': session.affiliates(),
            'cart_not_empty': Charge.unpaid_preregs,
            'copy_address': params.get('copy_address'),
            'promo_code_code': params.get('promo_code', ''),
            'pii_consent': params.get('pii_consent'),
        }

    @redirect_if_at_con_to_kiosk
    @check_if_can_reg
    def hotel(self, session, message='', id=None, edit_id=None, requested_hotel_info=False):
        id = edit_id or id
        if not id:
            raise HTTPRedirect('form')

        if not c.PREREG_REQUEST_HOTEL_INFO_OPEN:
            if cherrypy.request.method == 'POST':
                raise HTTPRedirect('index?message={}', 'Requests for hotel booking info have already been closed')
            else:
                raise HTTPRedirect('form?edit_id={}', id)

        attendee = self._get_unsaved(
            id, if_not_found=HTTPRedirect('form?message={}', 'Could not find the given preregistration'))

        is_group_leader = not attendee.is_unassigned and attendee.promo_code_groups > 0

        if cherrypy.request.method == 'POST':
            attendee.requested_hotel_info = requested_hotel_info
            target = attendee
            track_type = c.EDITED_PREREG if target.id in Charge.unpaid_preregs else c.UNPAID_PREREG
            Charge.unpaid_preregs[target.id] = Charge.to_sessionized(attendee)
            Tracking.track(track_type, attendee)
            raise HTTPRedirect('index')
        return {
            'message': message,
            'id': id,
            'edit_id': edit_id,
            'is_group_leader': is_group_leader,
            'requested_hotel_info': attendee.requested_hotel_info if edit_id else True
        }

    def duplicate(self, session, id):
        attendee = self._get_unsaved(id)
        orig = session.query(Attendee).filter_by(
            first_name=attendee.first_name, last_name=attendee.last_name, email=attendee.email).first()

        if not orig:
            raise HTTPRedirect('index')

        return {
            'duplicate': attendee,
            'attendee': orig,
            'id': id
        }

    def banned(self, id):
        attendee = self._get_unsaved(id)
        return {
            'attendee': attendee,
            'id': id
        }

    def process_free_prereg(self, session, message=''):
        charge = Charge(listify(Charge.unpaid_preregs.values()))
        if charge.total_cost <= 0:
            for attendee in charge.attendees:
                if attendee.promo_code_id:
                    message = check_prereg_promo_code(session, attendee)
                
                if message:
                    session.rollback()
                    raise HTTPRedirect('index?message={}', message)
                else:
                    session.add(attendee)

            for group in charge.groups:
                session.add(group)
                
            else:
                Charge.unpaid_preregs.clear()
                Charge.paid_preregs.extend(charge.targets)
                raise HTTPRedirect('paid_preregistrations?payment_received={}', charge.dollar_amount)
        else:
            message = "These badges aren't free! Please pay for them."
            raise HTTPRedirect('index?message={}', message)

    @credit_card
    def prereg_payment(self, session, payment_id=None, stripeToken=None, message=''):
        if not payment_id or not stripeToken or c.HTTP_METHOD != 'POST':
            message = 'The payment was interrupted. Please check below to ensure you received your badge.'
            raise HTTPRedirect('paid_preregistrations?message={}', message)

        charge = Charge.get(payment_id)
        if not charge.total_cost:
            message = 'Your total cost was $0. Your credit card has not been charged.'
        elif charge.amount != charge.total_cost:
            message = 'Our preregistration price has gone up; ' \
                'please fill out the payment form again at the higher price'
        else:
            for attendee in charge.attendees:
                if not message and attendee.promo_code_id:
                    message = check_prereg_promo_code(session, attendee)
            
            if not message:
                message = charge.charge_cc(session, stripeToken)

        if message:
            raise HTTPRedirect('index?message={}', message)

        # from this point on, the credit card has actually been charged but we haven't marked anything as charged yet.
        # be ultra-careful until the attendees/groups are marked paid and written to the DB or we could end up in a
        # situation where we took the payment, but didn't mark the cards charged
        for attendee in charge.attendees:
            attendee.paid = c.HAS_PAID
            attendee.amount_paid_override = attendee.total_cost
            attendee_name = 'PLACEHOLDER' if attendee.is_unassigned else attendee.full_name
            log.info("PAYMENT: marked attendee id={} ({}) as paid", attendee.id, attendee_name)
            session.add(attendee)

            if attendee.badges:
                pc_group = session.create_promo_code_group(attendee, attendee.name, int(attendee.badges) - 1)
                session.add(pc_group)

        session.commit() # save PromoCodeGroup to the database to generate receipt items correctly
        for attendee in charge.attendees:
            session.add(session.create_receipt_item(attendee, attendee.total_cost * 100,
                                                    "Prereg payment", charge.stripe_transaction))

        Charge.unpaid_preregs.clear()
        Charge.paid_preregs.extend(charge.targets)

        log.debug('PAYMENT: prereg payment actual charging process FINISHED for stripeToken={}', stripeToken)
        raise HTTPRedirect('paid_preregistrations?payment_received={}', charge.dollar_amount)

    def paid_preregistrations(self, session, payment_received=None, message=''):
        if not Charge.paid_preregs:
            raise HTTPRedirect('index')
        else:
            preregs = [session.merge(Charge.from_sessionized(d)) for d in Charge.paid_preregs]
            for prereg in preregs:
                try:
                    session.refresh(prereg)
                except Exception:
                    pass  # this badge must have subsequently been transferred or deleted
            return {
                'preregs': preregs,
                'total_cost': payment_received,
                'message': message
            }

    def delete(self, id, message='Preregistration deleted'):
        Charge.unpaid_preregs.pop(id, None)
        raise HTTPRedirect('index?message={}', message)

    @id_required(Group)
    def dealer_confirmation(self, session, id):
        return {'group': session.group(id)}

    @id_required(PromoCodeGroup)
    def group_promo_codes(self, session, id, message='', **params):
        group = session.promo_code_group(id)

        sent_code_emails = session.query(Email).filter_by(subject='Claim a "{}" group badge for {}'.format(
            group.name, c.EVENT_NAME)).order_by(Email.when)

        emailed_codes = {}

        for code in group.sorted_promo_codes:
            emailed_codes.update({code.code: email.to for email in sent_code_emails if code.code in email.body})

        return {
            'group': group,
            'message': message,
            'emailed_codes': emailed_codes,
        }

    def email_promo_code(self, session, group_id, message='', **params):
        if cherrypy.request.method == 'POST':
            code = session.lookup_promo_or_group_code(params.get('code'))
            if not code:
                message = "This code is invalid. If it has not been claimed, please contact us at {}".format(
                    c.REGDESK_EMAIL)
            elif not params.get('email'):
                message = "Please enter an email address"
            else:
                try:
                    validate_email(params.get('email'))
                except EmailNotValidError as e:
                    message = str(e)
                    message = 'Enter a valid email address. ' + message

            if not message:
                send_email.delay(
                    c.REGDESK_EMAIL,
                    params.get('email'),
                    'Claim a {} badge in "{}"'.format(c.EVENT_NAME, code.group.name),
                    render('emails/reg_workflow/promo_code_invite.txt', {'code': code}, encoding=None),
                    model=code.to_dict('id'))
                raise HTTPRedirect('group_promo_codes?id={}&message={}'.format(group_id, "Email sent!"))
            else:
                raise HTTPRedirect('group_promo_codes?id={}&message={}'.format(group_id, message))

    def add_promo_codes(self, session, id, count):
        group = session.promo_code_group(id)
        if int(count) < group.min_badges_addable and not group.is_in_grace_period:
            raise HTTPRedirect(
                'group_promo_codes?id={}&message={}',
                group.id,
                'You must add at least {} codes'.format(group.min_badges_addable))

        charge = Charge(
            group.buyer,
            amount=100 * int(count) * c.get_group_price(),
            description='{} extra badge{} for {}'.format(count, 's' if int(count) > 1 else '', group.name))

        return {
            'count': count,
            'group': group,
            'charge': charge
        }

    @credit_card
    def pay_for_extra_codes(self, session, payment_id, stripeToken):
        charge = Charge.get(payment_id)
        [attendee] = charge.attendees
        attendee = session.attendee(attendee.id)
        group = attendee.promo_code_groups[0]
        badges_to_add = charge.dollar_amount // c.GROUP_PRICE
        if charge.dollar_amount % c.GROUP_PRICE:
            message = 'Our preregistration price has gone up since you tried to add more codes; please try again'
        else:
            message = charge.charge_cc(session, stripeToken)

        if message:
            raise HTTPRedirect('group_promo_codes?id={}&message={}', group.id, message)
        else:
            session.add(session.create_receipt_item(
                attendee, charge.amount,
                "Adding {} badge{} to promo code group {} (${} each)".format(
                    badges_to_add,
                    "s" if badges_to_add > 1 else "",
                    group.name, c.GROUP_PRICE), charge.stripe_transaction),
            )

            session.add_codes_to_pc_group(group, badges_to_add)
            attendee.amount_paid_override += charge.dollar_amount

            raise HTTPRedirect(
                'group_promo_codes?id={}&message={}',
                group.id,
                'You payment has been accepted and the codes have been added to your group')

    @id_required(Group)
    @log_pageview
    def group_members(self, session, id, message='', **params):
        group = session.group(id)
        charge = Charge(group)
        if cherrypy.request.method == 'POST':
            # Both the Attendee class and Group class have identically named
            # address fields. In order to distinguish the two sets of address
            # fields in the params, the Group fields are prefixed with "group_"
            # when the form is submitted. To prevent instantiating the Group object
            # with the Attendee's address fields, we must clone the params and
            # rename all the "group_" fields.
            group_params = dict(params)
            for field_name in ['country', 'region', 'zip_code', 'address1', 'address2', 'city']:
                group_params[field_name] = params.get('group_{}'.format(field_name), '')

            group.apply(group_params, restricted=True)
            message = check(group, prereg=True)
            if message:
                session.rollback()
            else:
                session.commit()
                if group.is_dealer:
                    send_email.delay(
                        c.MARKETPLACE_EMAIL,
                        c.MARKETPLACE_EMAIL,
                        '{} Changed'.format(c.DEALER_APP_TERM.title()),
                        render('emails/dealers/appchange_notification.html', {'group': group}, encoding=None),
                        'html',
                        model=group.to_dict('id'))

                message = 'Thank you! Your application has been updated.'

            raise HTTPRedirect('group_members?id={}&message={}', group.id, message)
        return {
            'group':   group,
            'upgraded_badges': len([a for a in group.attendees if a.badge_type in c.BADGE_TYPE_PRICES]),
            'charge':  charge,
            'message': message
        }

    def register_group_member(self, session, group_id, message='', **params):
        # Safe to ignore csrf tokens here, because an attacker would need to know the group id a priori
        group = session.group(group_id, ignore_csrf=True)
        attendee = session.attendee(params, restricted=True, ignore_csrf=True)
        must_be_staffing = False
        
        if group.unassigned[0].staffing:
            must_be_staffing = True
            attendee.staffing = True
            params['staffing'] = True

        message = check_pii_consent(params, attendee) or message
        if not message and 'first_name' in params:
            message = check(attendee, prereg=True)
            if not message and not params['first_name']:
                message = 'First and Last Name are required fields'
            if not message:
                if not group.unassigned:
                    raise HTTPRedirect(
                        'register_group_member?group_id={}&message={}',
                        group_id,
                        'No more unassigned badges exist in this group')

                attrs_to_preserve_from_unassigned_group_member = [
                    'id',
                    'group_id',
                    'badge_type',
                    'badge_num',
                    'base_badge_price',
                    'ribbon',
                    'paid',
                    'overridden_price',
                    'requested_hotel_info']

                attendee = group.unassigned[0]
                for attr in attrs_to_preserve_from_unassigned_group_member:
                    if attr in params:
                        del params[attr]

                attendee.apply(params, restricted=True)

                # Free group badges are considered registered' when they are actually claimed.
                if group.cost == 0:
                    attendee.registered = localized_now()

                if attendee.amount_unpaid:
                    raise HTTPRedirect('attendee_donation_form?id={}', attendee.id)
                else:
                    raise HTTPRedirect('badge_updated?id={}&message={}', attendee.id, 'Badge registered successfully')

        return {
            'message':  message,
            'group_id': group_id,
            'group': group,
            'attendee': attendee,
            'affiliates': session.affiliates(),
            'badge_cost': 0,
            'must_be_staffing': must_be_staffing,
        }

    @credit_card
    def process_group_payment(self, session, payment_id, stripeToken):
        charge = Charge.get(payment_id)
        [group] = charge.groups
        message = charge.charge_cc(session, stripeToken)
        if message:
            raise HTTPRedirect('group_members?id={}&message={}', group.id, message)
        else:
            session.add(session.create_receipt_item(group, group.cost * 100, "Group page payment", charge.stripe_transaction))

            group.amount_paid_override += charge.dollar_amount

            session.merge(group)
            if group.is_dealer:
                try:
                    send_email.delay(
                        c.MARKETPLACE_EMAIL,
                        c.MARKETPLACE_EMAIL,
                        '{} Payment Completed'.format(c.DEALER_TERM.title()),
                        render('emails/dealers/payment_notification.txt', {'group': group}, encoding=None),
                        model=group.to_dict('id'))
                except Exception:
                    log.error('unable to send {} payment confirmation email'.format(c.DEALER_TERM), exc_info=True)
            raise HTTPRedirect('group_members?id={}&message={}', group.id, 'Your payment has been accepted!')

    @csrf_protected
    def unset_group_member(self, session, id):
        attendee = session.attendee(id)
        try:
            send_email.delay(
                c.REGDESK_EMAIL,
                attendee.email,
                '{} group registration dropped'.format(c.EVENT_NAME),
                render('emails/reg_workflow/group_member_dropped.txt', {'attendee': attendee}, encoding=None),
                model=attendee.to_dict('id'))
        except Exception:
            log.error('unable to send group unset email', exc_info=True)

        session.assign_badges(
            attendee.group,
            attendee.group.badges + 1,
            new_badge_type=attendee.badge_type,
            new_ribbon_type=attendee.ribbon,
            registered=attendee.registered,
            paid=attendee.paid)

        session.delete_from_group(attendee, attendee.group)
        raise HTTPRedirect(
            'group_members?id={}&message={}',
            attendee.group_id,
            'Attendee unset; you may now assign their badge to someone else')

    def add_group_members(self, session, id, count):
        group = session.group(id)
        if int(count) < group.min_badges_addable and not group.is_in_grace_period:
            raise HTTPRedirect(
                'group_members?id={}&message={}',
                group.id,
                'This group cannot add fewer than {} badges'.format(group.min_badges_addable))

        charge = Charge(
            group,
            amount=100 * int(count) * group.new_badge_cost,
            description='{} extra badges for {}'.format(count, group.name))

        return {
            'count': count,
            'group': group,
            'charge': charge
        }

    @credit_card
    def pay_for_extra_members(self, session, payment_id, stripeToken):
        charge = Charge.get(payment_id)
        [group] = charge.groups
        group_badge_price = c.DEALER_BADGE_PRICE if group.tables else c.GROUP_PRICE
        badges_to_add = charge.dollar_amount // group_badge_price
        if charge.dollar_amount % group_badge_price:
            message = 'Our preregistration price has gone up since you tried to add the badges; please try again'
        else:
            message = charge.charge_cc(session, stripeToken)

        if message:
            raise HTTPRedirect('group_members?id={}&message={}', group.id, message)
        else:
            session.assign_badges(group, group.badges + badges_to_add)
            group.amount_paid_override += charge.dollar_amount
            session.add(session.create_receipt_item(
                group, charge.amount,
                "Adding {} badge{} to group {} (${} each)".format(
                    badges_to_add,
                    "s" if badges_to_add > 1 else "",
                    group.name, group.new_badge_cost), charge.stripe_transaction),
            )
            session.merge(group)
            if group.is_dealer:
                send_email.delay(
                    c.MARKETPLACE_EMAIL,
                    c.MARKETPLACE_EMAIL,
                    '{} Paid for Extra Members'.format(c.DEALER_TERM.title()),
                    render('emails/dealers/payment_notification.txt', {'group': group}, encoding=None),
                    model=group.to_dict('id'))
            raise HTTPRedirect(
                'group_members?id={}&message={}',
                group.id,
                'You payment has been accepted and the badges have been added to your group')

    @id_required(Attendee)
    @log_pageview
    def transfer_badge(self, session, message='', **params):
        old = session.attendee(params['id'])

        assert old.is_transferable, 'This badge is not transferable.'
        session.expunge(old)
        attendee = session.attendee(params, restricted=True)

        if 'first_name' in params:
            message = check(attendee, prereg=True)
            if (old.first_name == attendee.first_name and old.last_name == attendee.last_name) \
                    or (old.legal_name and old.legal_name == attendee.legal_name):
                message = 'You cannot transfer your badge to yourself.'
            elif not message and (not params['first_name'] and not params['last_name']):
                message = check(attendee, prereg=True)
            if not message and (not params['first_name'] and not params['last_name']):
                message = 'First and Last names are required.'

            if not message:
                subject = c.EVENT_NAME + ' Registration Transferred'
                body = render('emails/reg_workflow/badge_transfer.txt', {'new': attendee, 'old': old}, encoding=None)

                try:
                    send_email.delay(
                        c.REGDESK_EMAIL,
                        [old.email, attendee.email, c.REGDESK_EMAIL],
                        subject,
                        body,
                        model=attendee.to_dict('id'))
                except Exception:
                    log.error('unable to send badge change email', exc_info=True)

                if attendee.amount_unpaid:
                    raise HTTPRedirect('attendee_donation_form?id={}', attendee.id)
                else:
                    raise HTTPRedirect(
                        'badge_updated?id={}&message={}', attendee.id, 'Your registration has been transferred')
        else:
            for attr in c.UNTRANSFERABLE_ATTRS:
                setattr(attendee, attr, getattr(Attendee(), attr))

        return {
            'old':      old,
            'attendee': attendee,
            'message':  message,
            'affiliates': session.affiliates()
        }

    def invalid_badge(self, session, id, message=''):
        return {'attendee': session.attendee(id, allow_invalid=True), 'message': message}

    def not_found(self, id, message=''):
        return {'id': id, 'message': message}

    def abandon_badge(self, session, id):
        attendee = session.attendee(id)
        if attendee.amount_paid and not attendee.is_group_leader:
            failure_message = "Something went wrong with your refund. Please contact us at {}."\
                .format(c.REGDESK_EMAIL)
            new_status = c.REFUNDED_STATUS
            page_redirect = 'repurchase'
        else:
            success_message = "Sorry you can't make it! We hope to see you next year!"
            new_status = c.INVALID_STATUS
            page_redirect = 'invalid_badge'
            if attendee.is_group_leader:
                failure_message = "You cannot abandon your badge because you are the leader of a group."
            else:
                failure_message = "You cannot abandon your badge for some reason. Please contact us at {}."\
                    .format(c.REGDESK_EMAIL)

        if (not attendee.amount_paid and not attendee.can_abandon_badge)\
                or (attendee.amount_paid and not attendee.can_self_service_refund_badge):
            raise HTTPRedirect('confirm?id={}&message={}', id, failure_message)

        if attendee.amount_paid:
            if not all(stripe_log.stripe_transaction.stripe_id
                       and stripe_log.stripe_transaction.type == c.PAYMENT
                       for stripe_log in attendee.stripe_txn_share_logs):
                raise HTTPRedirect('confirm?id={}&message={}', id,
                                   failure_message)
            for stripe_log in attendee.stripe_txn_share_logs:
                error, response, stripe_transaction = session.process_refund(stripe_log, attendee)
                if error:
                    raise HTTPRedirect('confirm?id={}&message={}', id,
                                       failure_message)
                elif response:
                    session.add(session.create_receipt_item(attendee, response.amount, "Self-service refund", stripe_transaction))

            success_message = "Your refund of ${:,.2f} should appear on your credit card in a few days."\
                .format(amount_refunded / 100)
            if attendee.paid == c.HAS_PAID:
                attendee.paid = c.REFUNDED

        if attendee.in_promo_code_group:
            attendee.promo_code = None

        # if attendee is part of a group, we must delete attendee and remove them from the group
        if attendee.group:
            session.assign_badges(
                attendee.group,
                attendee.group.badges + 1,
                new_badge_type=attendee.badge_type,
                new_ribbon_type=attendee.ribbon,
                registered=attendee.registered,
                paid=attendee.paid)

            session.delete_from_group(attendee, attendee.group)
            raise HTTPRedirect('not_found?id={}&message={}', attendee.id, success_message)
        # otherwise, we will mark attendee as invalid and remove them from shifts if necessary
        else:
            attendee.badge_status = new_status
            for shift in attendee.shifts:
                session.delete(shift)
            raise HTTPRedirect('{}?id={}&message={}', page_redirect, attendee.id, success_message)

    def badge_updated(self, session, id, message=''):
        return {'id': id, 'message': message}

    @id_required(Attendee)
    @log_pageview
    def confirm(self, session, message='', return_to='confirm', undoing_extra='', **params):
        # Safe to ignore csrf tokens here, because an attacker would need to know the attendee id a priori
        attendee = session.attendee(params, restricted=True, ignore_csrf=True)

        if attendee.badge_status == c.REFUNDED_STATUS:
            raise HTTPRedirect('repurchase?id={}', attendee.id)

        placeholder = attendee.placeholder
        if 'email' in params and not message:
            attendee.placeholder = False
            message = check(attendee, prereg=True)
            if not message:
                if placeholder:
                    attendee.confirmed = localized_now()
                    message = 'Your registration has been confirmed'
                else:
                    message = 'Your information has been updated'

                page = ('badge_updated?id=' + attendee.id + '&') if return_to == 'confirm' else (return_to + '?')
                if attendee.amount_unpaid:
                    raise HTTPRedirect('attendee_donation_form?id={}', attendee.id)
                else:
                    raise HTTPRedirect(page + 'message=' + message)

        elif attendee.amount_unpaid and attendee.zip_code and not undoing_extra and cherrypy.request.method == 'POST':
            # Don't skip to payment until the form is filled out
            raise HTTPRedirect('attendee_donation_form?id={}&message={}', attendee.id, message)

        attendee.placeholder = placeholder
        if not message and attendee.placeholder:
            message = 'You are not yet registered!  You must fill out this form to complete your registration.'
        elif not message:
            message = 'You are already registered but you may update your information with this form.'

        return {
            'undoing_extra': undoing_extra,
            'return_to':     return_to,
            'attendee':      attendee,
            'message':       message,
            'affiliates':    session.affiliates(),
            'attractions':   session.query(Attraction).filter_by(is_public=True).all(),
            'badge_cost':    attendee.badge_cost if attendee.paid != c.PAID_BY_GROUP else 0,
        }

    @id_required(Attendee)
    def guest_food(self, session, id):
        attendee = session.attendee(id)
        assert attendee.badge_type == c.GUEST_BADGE, 'This form is for guests only'
        cherrypy.session['staffer_id'] = attendee.id
        raise HTTPRedirect('../staffing/food_restrictions')

    @id_required(Attendee)
    def attendee_donation_form(self, session, id, message=''):
        attendee = session.attendee(id)
        if attendee.amount_unpaid <= 0:
            raise HTTPRedirect('confirm?id={}', id)
        if 'attendee_donation_form' not in attendee.payment_page:
            raise HTTPRedirect(attendee.payment_page)

        return {
            'message': message,
            'attendee': attendee,
            'charge': Charge(
                attendee,
                description='{}{}'.format(attendee.full_name, '' if attendee.overridden_price else ' paying for extras')
            )
        }

    def undo_attendee_donation(self, session, id):
        attendee = session.attendee(id)
        if len(attendee.cost_property_names) > 1:  # core Uber only has one cost property
            raise HTTPRedirect(
                'confirm?id={}&undoing_extra=true&message={}',
                attendee.id,
                'Please revert your registration to the extras you wish to pay for, if any')
        else:
            attendee.amount_extra = max(0, attendee.amount_extra - attendee.amount_unpaid)
            raise HTTPRedirect('confirm?id=' + id)

    @credit_card
    def process_attendee_donation(self, session, payment_id, stripeToken):
        charge = Charge.get(payment_id)
        [attendee] = charge.attendees
        message = charge.charge_cc(session, stripeToken)
        if message:
            raise HTTPRedirect('attendee_donation_form?id=' + attendee.id + '&message={}', message)
        else:
            # It's safe to assume the attendee exists in the database already.
            # The only path to reach this method requires the attendee to have
            # already paid for their registration, thus the attendee has been
            # saved to the database.
            attendee = session.query(Attendee).get(attendee.id)
            
            attendee_payment = charge.dollar_amount
            if attendee.marketplace_cost:
                for app in attendee.marketplace_applications:
                    attendee_payment -= app.amount_unpaid
                    app.amount_paid += app.amount_unpaid
                
            session.add(session.create_receipt_item(attendee, charge.amount, "Extra donation", charge.stripe_transaction))
            
            if attendee.paid == c.NOT_PAID and attendee.amount_paid == attendee.total_cost:
                attendee.paid = c.HAS_PAID
            raise HTTPRedirect('badge_updated?id={}&message={}', attendee.id, 'Your payment has been accepted')

    def credit_card_retry(self):
        return {}

    # TODO: figure out if this is the best way to handle the issue of people not getting shirts
    # TODO: this may be all now-dead one-time code (attendee.owed_shirt doesn't exist anymore)
    def shirt_reorder(self, session, message='', **params):
        attendee = session.attendee(params, restricted=True)
        assert attendee.owed_shirt, "There's no record of {} being owed a tshirt".format(attendee.full_name)
        if 'address' in params:
            if attendee.shirt in [c.NO_SHIRT, c.SIZE_UNKNOWN]:
                message = 'Please select a shirt size.'
            elif not attendee.address:
                message = 'Your address is required.'
            else:
                raise HTTPRedirect('shirt?id={}', attendee.id)
        elif attendee.address:
            message = "We've recorded your shirt size and address, which you may update anytime before Jan 31st."

        return {
            'message': message,
            'attendee': attendee
        }
