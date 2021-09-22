import json
from datetime import timedelta
from functools import wraps
from uber.models.admin import PasswordReset
from uber.models.marketplace import MarketplaceApplication
from uber.models.art_show import ArtShowApplication

import bcrypt
import cherrypy
from pockets import listify
from pockets.autolog import log
from six import string_types
from sqlalchemy import func

from uber.config import c
from uber.decorators import ajax, all_renderable, check_if_can_reg, credit_card, csrf_protected, id_required, log_pageview, \
    redirect_if_at_con_to_kiosk, render, requires_account
from uber.errors import HTTPRedirect
from uber.models import Attendee, AttendeeAccount, Attraction, Email, Group, PromoCode, PromoCodeGroup, Tracking
from uber.tasks.email import send_email
from uber.utils import add_opt, check, check_pii_consent, localized_now, normalize_email, genpasswd, valid_email, \
    valid_password, Charge


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

def rollback_prereg_session(session):
    attendee_account_id = cherrypy.session.get('attendee_account_id')
    if Charge.stripe_intent_id:
        log.debug("Rolling back Stripe ID " + Charge.stripe_intent_id)
        session.delete_txn_by_stripe_id(Charge.stripe_intent_id)
    if attendee_account_id and cherrypy.session.get('new_account'):
        log.debug("Deleting attendee account ID " + attendee_account_id)
        account = session.query(AttendeeAccount).get(attendee_account_id)
        session.delete(account)
        cherrypy.session['new_account'] = False
        cherrypy.session['attendee_account_id'] = ''
    Charge.paid_preregs.clear()
    if Charge.pending_preregs:
        log.debug("Rolling back pending preregistrations")
        cherrypy.session['unpaid_preregs'] = Charge.pending_preregs.copy()
        Charge.pending_preregs.clear()
    session.commit()

def check_account(session, email, password, confirm_password, skip_if_logged_in=True, update_password=True, old_email=None):
    logged_in_account = session.current_attendee_account()
    if logged_in_account and skip_if_logged_in:
        return

    if valid_email(email):
        return valid_email(email)

    existing_account = session.query(AttendeeAccount).filter_by(normalized_email=normalize_email(email)).first()
    if existing_account and (old_email and existing_account.normalized_email != old_email 
            or logged_in_account and logged_in_account.normalized_email != existing_account.normalized_email
            or not old_email and not logged_in_account):
        return "There's already an account with that email address"
    
    if update_password:
        if password and password != confirm_password:
            return 'Password confirmation does not match.'

        return valid_password(password)

def add_to_new_or_existing_account(session, attendee, **params):
    current_account = session.current_attendee_account()
    if current_account:
        session.add_attendee_to_account(attendee, current_account)
        return
    
    account_email, account_password = params.get('account_email'), params.get('account_password')
    message = check_account(session, account_email, account_password, params.get('confirm_password'))
    if not message:
        new_account = session.create_attendee_account(account_email, account_password)
        session.add_attendee_to_account(attendee, new_account)
        cherrypy.session['attendee_account_id'] = new_account.id
    return message


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
                        attendee.email_to_address,
                        subject,
                        render('emails/reg_workflow/prereg_check.txt', {'attendee': attendee}, encoding=None),
                        model=attendee.to_dict('id'))

        return {'message': message}

    @check_if_can_reg
    def index(self, session, message='', account_email='', account_password=''):
        if Charge.pending_preregs:
            rollback_prereg_session(session)
            raise HTTPRedirect('index')

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
                'logged_in_account': session.current_attendee_account(),
                'message': message,
                'charge': charge,
                'account_email': account_email or charge.attendees[0].email,
                'account_password': account_password,
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
            if not message and attendee.promo_code and params.get('promo_code') != attendee.promo_code_code:
                attendee.promo_code = None
            if not message and c.BADGE_PROMO_CODES_ENABLED and params.get('promo_code'):
                if session.lookup_promo_or_group_code(params.get('promo_code'), PromoCodeGroup):
                    Charge.universal_promo_codes[attendee.id] = params.get('promo_code')
                message = session.add_promo_code_to_attendee(attendee, params.get('promo_code'))

        if message:
            return {
                'logged_in_account': session.current_attendee_account(),
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
                    message = add_to_new_or_existing_account(session, attendee, **params)

                    if not message:
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
                                attendee.email_to_address,
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

                if not message:
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
            'logged_in_account': session.current_attendee_account(),
            'message':    message,
            'attendee':   attendee,
            'account_email': params.get('account_email', ''),
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

    def process_free_prereg(self, session, message='', **params):
        account_email, account_password = params.get('account_email'), params.get('account_password')
        message = check_account(session, account_email, account_password, params.get('confirm_password'))
        if message:
            return {'error': message}

        new_or_existing_account = session.current_attendee_account()
        if not new_or_existing_account:
            new_or_existing_account = session.create_attendee_account(account_email, account_password)
        cherrypy.session['attendee_account_id'] = new_or_existing_account.id
        
        charge = Charge(listify(Charge.unpaid_preregs.values()))
        if charge.total_cost <= 0:
            for attendee in charge.attendees:
                if attendee.promo_code_id:
                    message = check_prereg_promo_code(session, attendee)
                
                if message:
                    session.rollback()
                    raise HTTPRedirect('index?message={}', message)
                else:
                    session.add_attendee_to_account(attendee, new_or_existing_account)

            for group in charge.groups:
                session.add(group)
                
            else:
                Charge.unpaid_preregs.clear()
                Charge.paid_preregs.extend(charge.targets)
                raise HTTPRedirect('paid_preregistrations?total_cost={}', charge.dollar_amount)
        else:
            message = "These badges aren't free! Please pay for them."
            raise HTTPRedirect('index?message={}', message)

    @ajax
    @credit_card
    def prereg_payment(self, session, message='', **params):
        charge = Charge(listify(Charge.unpaid_preregs.values()))
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
                stripe_intent = charge.create_stripe_intent(session)
                message = stripe_intent if isinstance(stripe_intent, string_types) else ''

        if message:
            return {'error': message}

        account_email, account_password = params.get('account_email'), params.get('account_password')
        message = check_account(session, account_email, account_password, params.get('confirm_password'))
        if message:
            return {'error': message}

        new_or_existing_account = session.current_attendee_account()
        if not new_or_existing_account:
            new_or_existing_account = session.create_attendee_account(account_email, account_password)
        cherrypy.session['attendee_account_id'] = new_or_existing_account.id

        for attendee in charge.attendees:
            pending_attendee = session.query(Attendee).filter_by(id=attendee.id).first()
            if pending_attendee:
                pending_attendee.apply(attendee.to_dict(), restricted=True)
                if attendee.badges:
                    pc_group = pending_attendee.promo_code_groups[0]
                    pc_group.name = attendee.name

                    pc_codes = int(attendee.badges) - 1
                    pending_codes = len(pc_group.promo_codes)
                    if pc_codes > pending_codes:
                        session.add_codes_to_pc_group(pc_group, pc_codes - pending_codes)
                    elif pc_codes < pending_codes:
                        session.remove_codes_from_pc_group(pc_group, pending_codes - pc_codes)

                for receipt_item in pending_attendee.receipt_items:
                    session.delete(receipt_item)
                
                pending_attendee.amount_paid_override = pending_attendee.total_cost
                session.add_attendee_to_account(pending_attendee, new_or_existing_account)
            else:
                attendee.badge_status = c.PENDING_STATUS
                attendee.paid = c.PENDING
                session.add(attendee)
                session.add_attendee_to_account(attendee, new_or_existing_account)
                
                if attendee.badges:
                    pc_group = session.create_promo_code_group(attendee, attendee.name, int(attendee.badges) - 1)
                    session.add(pc_group)

                attendee.amount_paid_override = attendee.total_cost

        cherrypy.session['pending_preregs'] = Charge.unpaid_preregs.copy()

        session.commit() # save PromoCodeGroup to the database to generate receipt items correctly
        for attendee in charge.attendees:
            session.add(session.create_receipt_item(attendee, attendee.total_cost * 100,
                                                    "Prereg payment", charge.stripe_transaction))

        Charge.unpaid_preregs.clear()
        Charge.paid_preregs.extend(charge.targets)
        cherrypy.session['stripe_intent_id'] = stripe_intent.id
        session.commit()

        return {'stripe_intent': stripe_intent,
                'success_url': 'paid_preregistrations?total_cost={}&message={}'.format(
                    charge.dollar_amount, 'Payment accepted!'),
                'cancel_url': 'cancel_prereg_payment'}

    @ajax
    def cancel_prereg_payment(self, session, stripe_id=None, account_id=None):
        rollback_prereg_session(session)
        return {'message': 'Payment cancelled.'}
    
    @ajax
    def cancel_payment(self, session, stripe_id, model_id=None, cancel_amt=0):
        session.delete_txn_by_stripe_id(stripe_id)
        if model_id and cancel_amt:
            for model in [ArtShowApplication, MarketplaceApplication]:
                app = session.query(model).filter_by(id=model_id).first()
                if app:
                    app.amount_paid -= int(cancel_amt)
                    session.add(app)
        session.commit()
        
        return {'message': 'Payment cancelled.'}

    def paid_preregistrations(self, session, total_cost=None, stripe_intent_id=None, message=''):
        if not Charge.paid_preregs:
            raise HTTPRedirect('index')
        else:
            Charge.pending_preregs.clear()
            preregs = [session.merge(Charge.from_sessionized(d)) for d in Charge.paid_preregs]
            for prereg in preregs:
                try:
                    session.refresh(prereg)
                except Exception:
                    pass  # this badge must have subsequently been transferred or deleted
            return {
                'preregs': preregs,
                'total_cost': total_cost,
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
            else:
                message = valid_email(params.get('email'))

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

        return {
            'count': count,
            'group': group,
        }

    @ajax
    @credit_card
    def pay_for_extra_codes(self, session, id, count):
        group = session.promo_code_group(id)
        charge = Charge(
            group.buyer,
            amount=100 * int(count) * c.get_group_price(),
            description='{} extra badge{} for {}'.format(count, 's' if int(count) > 1 else '', group.name))
        badges_to_add = charge.dollar_amount // c.GROUP_PRICE
        if charge.dollar_amount % c.GROUP_PRICE:
            message = 'Our preregistration price has gone up since you tried to add more codes; please try again'
        else:
            stripe_intent = charge.create_stripe_intent(session)
            message = stripe_intent if isinstance(stripe_intent, string_types) else ''

        if message:
            return {'error': message}
        else:
            session.add(session.create_receipt_item(
                group.buyer, charge.amount,
                "Adding {} badge{} to promo code group {} (${} each)".format(
                    badges_to_add,
                    "s" if badges_to_add > 1 else "",
                    group.name, c.GROUP_PRICE), charge.stripe_transaction),
            )

            session.add_codes_to_pc_group(group, badges_to_add)
            session.commit()
            
            return {'stripe_intent': stripe_intent,
                    'success_url': 'group_promo_codes?id={}&message={}'.format(
                        group.id,
                        'You payment has been accepted and the codes have been added to your group')}

    @id_required(Group)
    @requires_account(Group)
    @log_pageview
    def group_members(self, session, id, message='', **params):
        group = session.group(id)
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
            'account': session.one_badge_attendee_account(group.leader),
            'current_account': session.current_attendee_account(),
            'upgraded_badges': len([a for a in group.attendees if a.badge_type in c.BADGE_TYPE_PRICES]),
            'message': message
        }

    @requires_account(Group)
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

                session.add_attendee_to_account(attendee, session.current_attendee_account())

                # Free group badges are considered 'registered' when they are actually claimed.
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

    @ajax
    @credit_card
    def process_group_payment(self, session, id):
        group = session.group(id)
        charge = Charge(group, amount=group.amount_unpaid * 100)
        stripe_intent = charge.create_stripe_intent(session)
        message = stripe_intent if isinstance(stripe_intent, string_types) else ''
        if message:
            return {'error': message}
        else:
            session.add(session.create_receipt_item(group, charge.amount, "Group page payment", charge.stripe_transaction))

            session.merge(group)
            session.commit()
                    
            return {'stripe_intent': stripe_intent,
                    'success_url': 'group_members?id={}&message={}'.format(group.id, 'Your payment has been accepted')}

    @requires_account(Attendee)
    @csrf_protected
    def unset_group_member(self, session, id):
        attendee = session.attendee(id)
        try:
            send_email.delay(
                c.REGDESK_EMAIL,
                attendee.email_to_address,
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

    @requires_account(Group)
    def add_group_members(self, session, id, count):
        group = session.group(id)
        if int(count) < group.min_badges_addable and not group.is_in_grace_period:
            raise HTTPRedirect(
                'group_members?id={}&message={}',
                group.id,
                'This group cannot add fewer than {} badges'.format(group.min_badges_addable))

        return {
            'count': count,
            'group': group,
        }

    @ajax
    @credit_card
    def pay_for_extra_members(self, session, id, count):
        group = session.group(id)
        charge = Charge(
            group,
            amount=100 * int(count) * group.new_badge_cost,
            description='{} extra badge{} for {}'.format(count, "s" if int(count) > 1 else "", group.name))
        badges_to_add = charge.dollar_amount // group.new_badge_cost
        if charge.dollar_amount % group.new_badge_cost:
            message = 'Our preregistration price has gone up since you tried to add the badges; please try again'
        else:
            stripe_intent = charge.create_stripe_intent(session)
            message = stripe_intent if isinstance(stripe_intent, string_types) else ''

        if message:
            return {'error': message}
        else:
            session.assign_badges(group, group.badges + badges_to_add)
            
            session.add(session.create_receipt_item(
                group, charge.amount,
                "Adding {} badge{} to group {} (${} each)".format(
                    badges_to_add,
                    "s" if badges_to_add > 1 else "",
                    group.name, group.new_badge_cost), charge.stripe_transaction),
            )
            session.merge(group)
            session.commit()
            
            return {'stripe_intent': stripe_intent,
                    'success_url': 'group_members?id={}&message={}'.format(
                        group.id, 'Your payment has been accepted and the badges have been added to your group')}

    @id_required(Attendee)
    @requires_account(Attendee)
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
                        [old.email_to_address, attendee.email_to_address, c.REGDESK_EMAIL],
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

    @requires_account(Attendee)
    def abandon_badge(self, session, id):
        from uber.custom_tags import format_currency
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
            total_refunded = 0
            for stripe_log in attendee.stripe_txn_share_logs:
                error, response, stripe_transaction = session.process_refund(stripe_log, attendee)
                if error:
                    raise HTTPRedirect('confirm?id={}&message={}', id,
                                       failure_message)
                elif response:
                    session.add(session.create_receipt_item(attendee, 
                        response.amount, 
                        "Self-service refund", 
                        stripe_transaction,
                        c.REFUND))
                    total_refunded += response.amount

            success_message = "Your refund of {} should appear on your credit card in a few days."\
                .format(format_currency(total_refunded / 100))
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

    def badge_updated(self, id, message=''):
        return {'id': id, 'message': message}

    def login(self, session, message='', original_location=None, **params):
        from uber.utils import create_valid_user_supplied_redirect_url, ensure_csrf_token_exists
        original_location = create_valid_user_supplied_redirect_url(original_location, default_url='homepage')

        if 'email' in params:
            account = session.query(AttendeeAccount).filter_by(normalized_email=normalize_email(params.get('email', ''))).first()
            if not account:
                message = 'No account exists for that email address'
            elif not bcrypt.hashpw(params.get('password', ''), account.hashed) == account.hashed:
                message = 'Incorrect password'

            if not message:
                cherrypy.session['attendee_account_id'] = account.id
                ensure_csrf_token_exists()
                raise HTTPRedirect(original_location)

        raise HTTPRedirect('../landing/index?message={}&original_location={}&email={}', message, original_location, params.get('email', ''))

    @requires_account()
    def homepage(self, session, message=''):
        if not cherrypy.session.get('attendee_account_id'):
            raise HTTPRedirect('../landing/')

        account = session.query(AttendeeAccount).get(cherrypy.session.get('attendee_account_id'))

        if not account:
            raise HTTPRedirect('../landing/index')

        if account.has_only_one_badge and account.attendees[0].badge_status != c.INVALID_STATUS:
            if account.attendees[0].is_group_leader:
                raise HTTPRedirect('group_members?id={}&message={}', account.attendees[0].group.id, message)
            else:
                raise HTTPRedirect('confirm?id={}&message={}', account.attendees[0].id, message)
        return {
            'message': message,
            'account': account,
        }

    @requires_account()
    @csrf_protected
    def grant_account(self, session, id, message=''):
        attendee = session.attendee(id)
        if not attendee:
            message = "Something went wrong. Please try again."
        if not attendee.email:
            message = "This attendee needs an email address to set up a new account."
        if normalize_email(attendee.email) == session.current_attendee_account().normalized_email:
            message = "You cannot grant an account to someone with the same email address as your account."
        if not message:
            token = genpasswd(short=True)
            account = session.query(AttendeeAccount).filter_by(normalized_email=normalize_email(attendee.email)).first()
            if account:
                if account.password_reset:
                    session.delete(account.password_reset)
                    session.commit()
            else:
                account = session.create_attendee_account(attendee.email)
                session.add_attendee_to_account(attendee, account)
            session.add(PasswordReset(attendee_account=account, hashed=bcrypt.hashpw(token, bcrypt.gensalt())))

            body = render('emails/accounts/new_account.html', {
                    'attendee': attendee, 'token': token}, encoding=None)
            send_email.delay(
                c.ADMIN_EMAIL,
                account.email_to_address,
                c.EVENT_NAME + ' Account Setup',
                body,
                format='html',
                model=account.to_dict('id'))
        
        raise HTTPRedirect('homepage?message={}', message or 
                'An email has been sent to {} to set up their account.'.format(attendee.email))
    
    def logout(self, return_to=''):
        cherrypy.session.pop('attendee_account_id')
        return_to = return_to or '/preregistration/login'
        raise HTTPRedirect('..{}?message={}', return_to, 'You have been logged out.')

    @id_required(Attendee)
    @requires_account(Attendee)
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
        elif not message and not c.ATTENDEE_ACCOUNTS_ENABLED:
            message = 'You are already registered but you may update your information with this form.'

        return {
            'undoing_extra': undoing_extra,
            'return_to':     return_to,
            'attendee':      attendee,
            'account':       session.one_badge_attendee_account(attendee),
            'message':       message,
            'affiliates':    session.affiliates(),
            'attractions':   session.query(Attraction).filter_by(is_public=True).all(),
            'badge_cost':    attendee.badge_cost if attendee.paid != c.PAID_BY_GROUP else 0,
        }

    @requires_account()
    def update_account(self, session, id, **params):
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('homepage')
        
        message = ''
        account = session.attendee_account(id)
        password = params.get('current_password')

        if not password:
            message = 'Please enter your current password to make changes to your account.'
        elif not bcrypt.hashpw(password, account.hashed) == account.hashed:
            message = 'Incorrect password'

        if not message:
            if params.get('new_password') == '':
                new_password = None
                confirm_password = None
            else:
                new_password = params.get('new_password')
                confirm_password = params.get('confirm_new_password')
            message = check_account(session, params.get('account_email'), new_password, confirm_password, 
                                    False, new_password, account.normalized_email)

        if not message:
            if new_password:
                account.hashed = bcrypt.hashpw(new_password, bcrypt.gensalt())
            account.email = params.get('account_email')
            message = 'Account information updated successfully.'
        raise HTTPRedirect('homepage?message={}', message)

    def reset_password(self, session, **params):
        if 'account_email' in params:
            account_email = params['account_email']
            account = session.query(AttendeeAccount).filter_by(normalized_email=normalize_email(account_email)).first()
            if 'is_admin' in params:
                success_url = "../reg_admin/attendee_accounts?message=Password reset email sent."
            else:
                success_url = "../landing/index?message=Check your email for a password reset link."
            if not account:
                # Avoid letting attendees de facto search for other attendees by email
                raise HTTPRedirect(success_url)
            if account.password_reset:
                session.delete(account.password_reset)
                session.commit()

            token = genpasswd(short=True)
            session.add(PasswordReset(attendee_account=account, hashed=bcrypt.hashpw(token, bcrypt.gensalt())))

            body = render('emails/accounts/password_reset.html', {
                    'account': account, 'token': token}, encoding=None)
            send_email.delay(
                c.ADMIN_EMAIL,
                account.email_to_address,
                c.EVENT_NAME + ' Account Password Reset',
                body,
                format='html',
                model=account.to_dict('id'))
            
            raise HTTPRedirect(success_url)
        return {}

    def new_password_setup(self, session, account_email, token, message='', **params):
        if 'id' in params:
            account = session.attendee_account(params['id'])
        else:
            account = session.query(AttendeeAccount).filter_by(normalized_email=normalize_email(account_email)).first()
        if not account or not account.password_reset:
            message = 'Invalid link. This link may have already been used or replaced.'
        elif account.password_reset.is_expired:
            message = 'This link has expired. Please use the "forgot password" option to get a new link.'
        elif bcrypt.hashpw(token, account.password_reset.hashed) != account.password_reset.hashed:
            message = 'Invalid token. Did you copy the URL correctly?'
        
        if message:
            raise HTTPRedirect('../landing/index?message={}', message)
        
        if cherrypy.request.method == 'POST':
            account_password = params.get('account_password')
            message = check_account(session, account_email, account_password, 
                                    params.get('confirm_password'), False, True, account.normalized_email)

            if not message:
                account.email = account_email
                account.hashed = bcrypt.hashpw(account_password, bcrypt.gensalt())
                session.delete(account.password_reset)
                for attendee in account.attendees:
                    # Make sure only this account manages the attendee if c.ONE_MANAGER_PER_BADGE is set
                    # This lets us keep attendees under the prior account until their new account is confirmed
                    session.add_attendee_to_account(attendee, account)
                cherrypy.session['attendee_account_id'] = account.id
                raise HTTPRedirect('../preregistration/homepage?message={}', "Success!")

        return {
            'is_new': account.hashed == '',
            'message': message,
            'token': token,
            'id': account.id,
            'account_email': account_email,
        }

    @id_required(Attendee)
    @requires_account(Attendee)
    def guest_food(self, session, id):
        attendee = session.attendee(id)
        assert attendee.badge_type == c.GUEST_BADGE, 'This form is for guests only'
        cherrypy.session['staffer_id'] = attendee.id
        raise HTTPRedirect('../staffing/food_restrictions')

    @id_required(Attendee)
    @requires_account(Attendee)
    def attendee_donation_form(self, session, id, message=''):
        attendee = session.attendee(id)
        if attendee.amount_unpaid <= 0:
            raise HTTPRedirect('confirm?id={}', id)
        if 'attendee_donation_form' not in attendee.payment_page:
            raise HTTPRedirect(attendee.payment_page)

        return {
            'message': message,
            'attendee': attendee,
        }

    @requires_account(Attendee)
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

    @ajax
    @credit_card
    @requires_account(Attendee)
    def process_attendee_donation(self, session, id):
        attendee = session.attendee(id)
        charge = Charge(
                attendee,
                amount=attendee.amount_unpaid * 100,
                description='{}'.format('Badge' if attendee.overridden_price else 'Registration extras')
            )
        stripe_intent = charge.create_stripe_intent(session)
        message = stripe_intent if isinstance(stripe_intent, string_types) else ''
        
        if message:
            return {'error': message}
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
                
            session.add(session.create_receipt_item(attendee, charge.amount, 
                                                    "Extra payment via confirmation page", 
                                                    charge.stripe_transaction))
            session.commit()
            
            return {'stripe_intent': stripe_intent,
                    'success_url': 'badge_updated?id={}&message={}'.format(attendee.id, 'Your payment has been accepted')}

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
