import json
from datetime import datetime, timedelta
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
from sqlalchemy.orm.exc import NoResultFound

from uber import receipt_items
from uber.config import c
from uber.custom_tags import email_only
from uber.decorators import ajax, all_renderable, check_if_can_reg, credit_card, csrf_protected, id_required, log_pageview, \
    redirect_if_at_con_to_kiosk, render, requires_account
from uber.errors import HTTPRedirect
from uber.models import Attendee, AttendeeAccount, Attraction, Email, Group, ModelReceipt, PromoCode, PromoCodeGroup, \
                        ReceiptTransaction, SignedDocument, Tracking
from uber.tasks.email import send_email
from uber.utils import add_opt, check, check_pii_consent, localized_now, normalize_email, genpasswd, valid_email, \
    valid_password, Charge, SignNowDocument


def check_post_con(klass):
    def wrapper(func):
        @wraps(func)
        def wrapped(self, *args, **kwargs):
            if c.POST_CON:  # TODO: replace this with a template and make that suitably generic
                return """
                <html><head></head><body style='text-align:center'>
                    <h2 style='color:red'>We hope you enjoyed {event} {current_year}!</h2>
                    We look forward to seeing you in {next_year}! Watch our website (<a href="https://www.magfest.org">https://www.magfest.org</a>) and our Twitter (<a href="https://twitter.com/MAGFest">@MAGFest</a>) for announcements.
                </body></html>
                """.format(event=c.EVENT_NAME, current_year=c.EVENT_YEAR, next_year=(1 + int(c.EVENT_YEAR)) if c.EVENT_YEAR else '')
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

def check_account(session, email, password, confirm_password, skip_if_logged_in=True, update_password=True, old_email=None):
    logged_in_account = session.current_attendee_account()
    if logged_in_account and skip_if_logged_in:
        return

    if email and valid_email(email):
        return valid_email(email)

    existing_account = session.query(AttendeeAccount).filter_by(normalized_email=normalize_email(email)).first()
    if existing_account and (old_email and existing_account.normalized_email != normalize_email(old_email)
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

def set_up_new_account(session, attendee, email=None):
    email = email or attendee.email
    token = genpasswd(short=True)
    account = session.query(AttendeeAccount).filter_by(normalized_email=normalize_email(email)).first()
    if account:
        if account.password_reset:
            session.delete(account.password_reset)
            session.commit()
    else:
        account = session.create_attendee_account(email)
        session.add_attendee_to_account(attendee, account)
    session.add(PasswordReset(attendee_account=account, hashed=bcrypt.hashpw(token, bcrypt.gensalt())))

    body = render('emails/accounts/new_account.html', {
            'attendee': attendee, 'account_email': email, 'token': token}, encoding=None)
    send_email.delay(
        c.ADMIN_EMAIL,
        email,
        c.EVENT_NAME + ' Account Setup',
        body,
        format='html',
        model=account.to_dict('id'))

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
    def index(self, session, message='', account_email='', account_password='', removed_id=''):
        if removed_id:
            existing_model = session.query(Attendee).filter_by(id=removed_id).first()
            if not existing_model:
                existing_model = session.query(Group).filter_by(id=removed_id).first()
            if existing_model:
                existing_receipt = session.get_receipt_by_model(existing_model)
                existing_model.badge_status = c.INVALID_STATUS
                existing_receipt.closed = datetime.now()
                session.add(existing_receipt)
                session.add(existing_model)
                session.commit()

        if Charge.pending_preregs:
            # Getting here with pending preregs means the payment process was interrupted somehow
            # We can't handle this sensibly through code, an admin needs to sort it out
            attendees = []
            for id in Charge.pending_preregs:
                attendees.append(session.query(Attendee).filter_by(id=id).first())
            
            send_email.delay(c.REGDESK_EMAIL, c.REGDESK_EMAIL, "Prereg payment interrupted",
                            render('emails/interrupted_prereg.txt', {'attendees': attendees}, encoding=None),
                            model='n/a')
            message = message or "The payment process was interrupted. " \
                                 "If you don't receive a confirmation email soon, please contact us at {}" \
                                 .format(email_only(c.REGDESK_EMAIL))
            Charge.pending_preregs.clear()
        if not Charge.unpaid_preregs:
            raise HTTPRedirect('form?message={}', message) if message else HTTPRedirect('form')
        else:
            charge = Charge(listify(Charge.unpaid_preregs.values()))
            charge.set_total_cost()
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
    def dealer_registration(self, message='', invite_code=''):
        return self.form(badge_type=c.PSEUDO_DEALER_BADGE, message=message, invite_code=invite_code)

    @check_if_can_reg
    def reapply(self, session, id, **params):
        old_attendee = session.attendee(id)
        old_attendee_dict = old_attendee.to_dict(c.UNTRANSFERABLE_ATTRS)
        del old_attendee_dict['id']

        new_attendee = Attendee(**old_attendee_dict)
        
        new_attendee_dict = Charge.to_sessionized(new_attendee)
        new_attendee_dict['badge_type'] = c.PSEUDO_DEALER_BADGE

        cherrypy.session.setdefault('imported_attendee_ids', {})[new_attendee.id] = id

        Charge.unpaid_preregs[new_attendee.id] = new_attendee_dict
        Tracking.track(c.UNPAID_PREREG, new_attendee)
        raise HTTPRedirect("form?edit_id={}&repurchase=1&old_group_id={}", new_attendee.id, old_attendee.group.id)
        

    @check_if_can_reg
    def repurchase(self, session, id, skip_confirm=False, **params):
        if skip_confirm or 'csrf_token' in params:
            old_attendee = session.attendee(id)
            old_attendee_dict = old_attendee.to_dict(c.UNTRANSFERABLE_ATTRS)
            del old_attendee_dict['id']

            new_attendee = Attendee(**old_attendee_dict)

            cherrypy.session.setdefault('imported_attendee_ids', {})[new_attendee.id] = id

            Charge.unpaid_preregs[new_attendee.id] = Charge.to_sessionized(new_attendee)
            Tracking.track(c.UNPAID_PREREG, new_attendee)
            raise HTTPRedirect("form?edit_id={}&repurchase=1", new_attendee.id)
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
        badges = params.get('badges', 0)
        name = params.get('name', '')

        if edit_id is not None:
            attendee = self._get_unsaved(
                edit_id,
                if_not_found=HTTPRedirect('form?message={}', 'That preregistration has already been finalized'))
            badges = getattr(attendee, 'badges', 0)
            name = getattr(attendee, 'name', '')
        else:
            attendee = session.attendee(params, ignore_csrf=True, restricted=True)

        if attendee.badge_type == c.PSEUDO_DEALER_BADGE:
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
                    
            group_params['phone'] = params.get('group_phone', '')
            if params.get('copy_phone'):
                params['cellphone'] = group_params['phone']
                attendee.apply(params)
            
            group_params['email_address'] = params.get('group_email_address', '')
            if params.get('copy_email'):
                params['email'] = group_params['email_address']
                attendee.apply(params)

            if not params.get('old_group_id'):
                group = session.group(group_params, ignore_csrf=True, restricted=True)

        if edit_id is not None:
            attendee.apply(params, restricted=True)
            if not params.get('repurchase'):
                params.setdefault('pii_consent', True)
            if params.get('old_group_id'):
                old_group = session.group(params['old_group_id'])
                old_group_dict = session.group(params['old_group_id']).to_dict(c.GROUP_REAPPLY_ATTRS)
                group.apply(old_group_dict, ignore_csrf=True, restricted=True)
                name = old_group.name
                badges = old_group.badges_purchased
        else:
            attendee = session.attendee(params, ignore_csrf=True, restricted=True)

        if c.PAGE == 'post_dealer':
            attendee.badge_type = c.PSEUDO_DEALER_BADGE
        elif not attendee.badge_type:
            attendee.badge_type = c.ATTENDEE_BADGE

        if attendee.badge_type == c.PSEUDO_DEALER_BADGE:
            if not c.DEALER_REG_OPEN:
                return render('static_views/dealer_reg_closed.html') if c.AFTER_DEALER_REG_START \
                    else render('static_views/dealer_reg_not_open.html')
            
            if c.DEALER_INVITE_CODE:
                if not params.get('invite_code'):
                    raise HTTPRedirect("form?message={}s must have an invite code to register.".format(c.DEALER_TERM.capitalize()))
                elif params.get('invite_code') != c.DEALER_INVITE_CODE:
                    raise HTTPRedirect("form?message=Incorrect {} invite code.".format(c.DEALER_REG_TERM))

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
                'copy_email': params.get('copy_email'),
                'copy_phone': params.get('copy_phone'),
                'promo_code_code': params.get('promo_code', ''),
                'pii_consent': params.get('pii_consent'),
                'name': name,
                'badges': badges,
                'invite_code': params.get('invite_code', ''),
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
                    if c.ATTENDEE_ACCOUNTS_ENABLED:
                        message = add_to_new_or_existing_account(session, attendee, **params)

                    if not message:
                        if attendee.id in cherrypy.session.setdefault('imported_attendee_ids', {}):
                            old_attendee = session.attendee(cherrypy.session['imported_attendee_ids'][attendee.id])
                            old_attendee.current_attendee = attendee
                            session.add(old_attendee)
                            del cherrypy.session['imported_attendee_ids'][attendee.id]

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
            'account_password': params.get('account_password', ''),
            'confirm_password': params.get('confirm_password', ''),
            'badges': badges,
            'name': name,
            'group':      group,
            'promo_code_group': promo_code_group,
            'edit_id':    edit_id,
            'affiliates': session.affiliates(),
            'cart_not_empty': Charge.unpaid_preregs,
            'same_legal_name': params.get('same_legal_name'),
            'copy_address': params.get('copy_address'),
            'copy_email': params.get('copy_email'),
            'copy_phone': params.get('copy_phone'),
            'promo_code_code': params.get('promo_code', ''),
            'pii_consent': params.get('pii_consent'),
            'invite_code': params.get('invite_code', ''),
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
        
        if c.ATTENDEE_ACCOUNTS_ENABLED:
            message = check_account(session, account_email, account_password, params.get('confirm_password'))
            if message:
                return {'error': message}

            new_or_existing_account = session.current_attendee_account()
            if not new_or_existing_account:
                new_or_existing_account = session.create_attendee_account(account_email, account_password)
            cherrypy.session['attendee_account_id'] = new_or_existing_account.id
        
        charge = Charge(listify(Charge.unpaid_preregs.values()))
        charge.set_total_cost()
        if charge.total_cost <= 0:
            for attendee in charge.attendees:
                if attendee.id in cherrypy.session.setdefault('imported_attendee_ids', {}):
                    old_attendee = session.attendee(cherrypy.session['imported_attendee_ids'][attendee.id])
                    old_attendee.current_attendee = attendee
                    session.add(old_attendee)
                    del cherrypy.session['imported_attendee_ids'][attendee.id]

                if attendee.promo_code_id:
                    message = check_prereg_promo_code(session, attendee)
                
                if message:
                    session.rollback()
                    raise HTTPRedirect('index?message={}', message)
                elif c.ATTENDEE_ACCOUNTS_ENABLED:
                    session.add_attendee_to_account(attendee, new_or_existing_account)
                else:
                    session.add(attendee)

            for group in charge.groups:
                session.add(group)
        
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
        charge.set_total_cost()
        if not charge.total_cost:
            if not charge.models:
                HTTPRedirect('form?message={}', 'Your preregistration has already been finalized')
            message = 'Your total cost was $0. Your credit card has not been charged.'
        else:
            for attendee in charge.attendees:
                if not message and attendee.promo_code_id:
                    message = check_prereg_promo_code(session, attendee)
            
            if not message:
                if c.ATTENDEE_ACCOUNTS_ENABLED:
                    account_email, account_password = params.get('account_email'), params.get('account_password')
                    message = check_account(session, account_email, account_password, params.get('confirm_password'))
                    if message:
                        return {'error': message}

                    new_or_existing_account = session.current_attendee_account()
                    if not new_or_existing_account:
                        new_or_existing_account = session.create_attendee_account(account_email, account_password)
                    cherrypy.session['attendee_account_id'] = new_or_existing_account.id
                message = check(attendee, prereg=True)
            
            if not message:
                receipts = []
                for model in charge.models:
                    charge_receipt, charge_receipt_items = Charge.create_new_receipt(model, create_model=True)
                    existing_receipt = session.get_receipt_by_model(model)
                    if existing_receipt:
                        # If their registration costs changed, close their old receipt
                        compare_fields = ['amount', 'count', 'desc']
                        existing_items = [item.to_dict(compare_fields) for item in existing_receipt.receipt_items]
                        new_items = [item.to_dict(compare_fields) for item in charge_receipt_items]

                        for item in existing_items:
                            del item['id']
                        for item in new_items:
                            del item['id']

                        if existing_items != new_items:
                            existing_receipt.closed = datetime.now()
                            session.add(existing_receipt)
                        else:
                            receipts.append(existing_receipt)
                    
                    if not existing_receipt or existing_receipt.closed:
                        session.add(charge_receipt)
                        for item in charge_receipt_items:
                            session.add(item)
                        session.commit()
                        receipts.append(charge_receipt)

                if not message:
                    stripe_intent = charge.create_stripe_intent(sum([receipt.current_amount_owed for receipt in receipts]),
                                                                receipt_email=params.get('account_email'))
                    if isinstance(stripe_intent, string_types):
                        message = stripe_intent

        if message:
            return {'error': message}

        for receipt in receipts:
            receipt_txn = Charge.create_receipt_transaction(receipt, charge.description, stripe_intent.id)
            session.add(receipt_txn)

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
                elif pending_attendee.promo_code_groups:
                    pc_group = pending_attendee.promo_code_groups[0]
                    session.delete(pc_group)
                
                if c.ATTENDEE_ACCOUNTS_ENABLED:
                    session.add_attendee_to_account(pending_attendee, new_or_existing_account)
            else:
                if attendee.id in cherrypy.session.setdefault('imported_attendee_ids', {}):
                    old_attendee = session.attendee(cherrypy.session['imported_attendee_ids'][attendee.id])
                    old_attendee.current_attendee = attendee
                    session.add(old_attendee)
                    del cherrypy.session['imported_attendee_ids'][attendee.id]

                attendee.badge_status = c.PENDING_STATUS
                attendee.paid = c.PENDING
                session.add(attendee)
                if c.ATTENDEE_ACCOUNTS_ENABLED:
                    session.add_attendee_to_account(attendee, new_or_existing_account)
                
                if attendee.badges:
                    pc_group = session.create_promo_code_group(attendee, attendee.name, int(attendee.badges) - 1)
                    session.add(pc_group)

        cherrypy.session['pending_preregs'] = Charge.unpaid_preregs.copy()

        Charge.unpaid_preregs.clear()
        Charge.paid_preregs.extend(charge.targets)
        cherrypy.session['stripe_intent_id'] = stripe_intent.id
        session.commit()

        return {'stripe_intent': stripe_intent,
                'success_url': 'paid_preregistrations?total_cost={}&message={}'.format(
                    charge.dollar_amount, 'Payment accepted!'),
                'cancel_url': 'cancel_prereg_payment'}

    @ajax
    def cancel_prereg_payment(self, session, stripe_id):
        for txn in session.query(ReceiptTransaction).filter_by(intent_id=stripe_id).all():
            if not txn.charge_id:
                txn.cancelled = datetime.now()
                session.add(txn)

        account = session.current_attendee_account()
        if account and not any(attendee.badge_status != c.PENDING_STATUS for attendee in account.attendees) \
                   and len(account.attendees) == len(Charge.pending_preregs):
            session.delete(account)
            cherrypy.session['attendee_account_id'] = ''

        Charge.paid_preregs.clear()
        if Charge.pending_preregs:
            cherrypy.session['unpaid_preregs'] = Charge.pending_preregs.copy()
            Charge.pending_preregs.clear()
        session.commit()
        return {'message': 'Payment cancelled.'}
    
    @ajax
    def cancel_payment(self, session, stripe_id):
        for txn in session.query(ReceiptTransaction).filter_by(intent_id=stripe_id).all():
            if not txn.charge_id:
                txn.cancelled = datetime.now()
                session.add(txn)

        session.commit()

        return {'message': 'Payment cancelled.'}

    @ajax
    def cancel_promo_code_payment(self, session, stripe_id, **params):
        for txn in session.query(ReceiptTransaction).filter_by(intent_id=stripe_id).all():
            if not txn.charge_id:
                txn.cancelled = datetime.now()
                session.add(txn)
            
            owner_id = txn.receipt.owner_id

        attendee = session.query(Attendee).filter_by(id=owner_id).first()
        return {'redirect_url': 'group_promo_codes?id={}&message={}'.format(attendee.promo_code_groups[0].id, 'Payment cancelled.')}

    def paid_preregistrations(self, session, total_cost=None, message=''):
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
        raise HTTPRedirect('index?message={}&removed_id={}', message, id)

    @id_required(Group)
    def dealer_confirmation(self, session, id, document_id=''):
        group = session.group(id)
        if c.SIGNNOW_DEALER_TEMPLATE_ID:
            existing_doc = session.query(SignedDocument).filter_by(model="Group", fk_id=group.id).first()
            if document_id:
                if not existing_doc:
                    new_doc = SignedDocument(fk_id=group.id,
                                             model="Group",
                                             document_id=document_id,
                                             ident="terms_and_conditions",
                                             signed=localized_now())
                    session.add(new_doc)
                elif not existing_doc.signed:
                    existing_doc.signed = localized_now()
                    session.add(existing_doc)
            elif existing_doc and existing_doc.signed:
                pass
            else:
                document = existing_doc or SignedDocument(fk_id=group.id, model="Group", ident="terms_and_conditions")
                session.add(document)
                redirect_link = document.get_dealer_signing_link(group)
                if redirect_link:
                    raise HTTPRedirect(redirect_link)
            session.commit()
            if group.status != c.UNAPPROVED:
                # Dealers always hit this page after signing their terms and conditions
                # We want new dealers to see the confirmation page, and everyone else to go to their group page
                raise HTTPRedirect('group_members?id={}&message={}', group.id, "Thank you for signing the terms and conditions!")
        return {'group': group}

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
                    email_only(c.REGDESK_EMAIL))
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
        count = int(count)
        if count < group.min_badges_addable and not group.is_in_grace_period:
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
        from uber.models import ReceiptItem
        group = session.promo_code_group(id)
        receipt = session.get_receipt_by_model(group.buyer)
        count = int(count)
        session.add(ReceiptItem(receipt_id=receipt.id,
                                desc='Extra badge for {}'.format(group.name),
                                amount=c.get_group_price() * 100,
                                count=count,
                                who='non-admin',
                            ))
        charge_desc = '{} extra badge{} for {}'.format(count, 's' if count > 1 else '', group.name)
        charge = Charge(group, amount=c.get_group_price() * 100 * count,
                        description=charge_desc)
        if charge.dollar_amount % c.GROUP_PRICE:
            return {'error': 'Our preregistration price has gone up since you tried to add more codes; please try again'}
        
        stripe_intent = charge.create_stripe_intent()
        if isinstance(stripe_intent, string_types):
            session.rollback()
            return {'error': stripe_intent}

        receipt_txn = Charge.create_receipt_transaction(receipt, charge_desc, stripe_intent.id)
        if isinstance(receipt_txn, string_types):
            session.rollback()
            return {'error': receipt_txn}
            
        session.add(receipt_txn)
        session.commit()
            
        return {'stripe_intent': stripe_intent,
                'success_url': 'group_promo_codes?id={}&message={}'.format(
                    group.id,
                    'Your payment has been accepted and the codes have been added to your group'),
                'cancel_url': 'cancel_promo_code_payment'}

    @id_required(Group)
    @requires_account(Group)
    @log_pageview
    def group_members(self, session, id, message='', **params):
        group = session.group(id)

        signnow_document = None
        signnow_link = ''

        if group.is_dealer and c.SIGNNOW_DEALER_TEMPLATE_ID and group.is_valid:
            signnow_document = session.query(SignedDocument).filter_by(model="Group", fk_id=group.id).first()

            if not signnow_document:
                signnow_document = SignedDocument(fk_id=group.id,
                                                  model="Group",
                                                  ident="terms_and_conditions")
                session.add(signnow_document)
                session.commit()

            if signnow_document.signed:
                d = SignNowDocument()
                signnow_link = d.get_download_link(signnow_document.document_id)
                if d.error_message:
                    log.error(d.error_message)
            else:
                signed = signnow_document.get_doc_signed_timestamp()
                if signed:
                    signnow_document.signed = datetime.fromtimestamp(int(signed))
                    session.add(signnow_document)
                    session.commit()
                    d = SignNowDocument()
                    signnow_link = d.get_download_link(signnow_document.document_id)
                    if d.error_message:
                        log.error(d.error_message)
                else:
                    signnow_link = signnow_document.get_dealer_signing_link(group)

        if cherrypy.request.method == 'POST':
            # Both the Attendee class and Group class have identically named
            # address fields. In order to distinguish the two sets of address
            # fields in the params, the Group fields are prefixed with "group_"
            # when the form is submitted. To prevent instantiating the Group object
            # with the Attendee's address fields, we must clone the params and
            # rename all the "group_" fields.
            group_params = dict(params)
            for field_name in ['country', 'region', 'zip_code', 'address1', 'address2', 'city']:
                group_field_name = 'group_{}'.format(field_name)
                if group_field_name in params:
                    group_params[field_name] = params.get(group_field_name, '')

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
            'account': session.get_attendee_account_by_attendee(group.leader),
            'current_account': session.current_attendee_account(),
            'upgraded_badges': len([a for a in group.attendees if a.badge_type in c.BADGE_TYPE_PRICES]),
            'signnow_document': signnow_document if c.SIGNNOW_DEALER_TEMPLATE_ID else None,
            'signnow_link': signnow_link if c.SIGNNOW_DEALER_TEMPLATE_ID else None,
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

                if c.ATTENDEE_ACCOUNTS_ENABLED:
                    session.add_attendee_to_account(attendee, session.current_attendee_account())

                # Free group badges are considered 'registered' when they are actually claimed.
                if group.cost == 0:
                    attendee.registered = localized_now()

                if attendee.amount_unpaid:
                    raise HTTPRedirect(attendee.payment_page)
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
        receipt = session.get_receipt_by_model(group, create_if_none=True)
        charge_desc = "{}: {}".format(group.name, receipt.charge_description_list)
        charge = Charge(group, amount=receipt.current_amount_owed, description=charge_desc)

        stripe_intent = charge.create_stripe_intent()
        if isinstance(stripe_intent, string_types):
            return {'error': stripe_intent}

        receipt_txn = Charge.create_receipt_transaction(receipt, charge_desc, stripe_intent.id)
        session.add(receipt_txn)
        
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
            stripe_intent = charge.create_stripe_intent()
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
                    raise HTTPRedirect(attendee.payment_page)
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

    @id_required(Attendee)
    @requires_account(Attendee)
    @log_pageview
    def defer_badge(self, session, message='', **params):
        attendee = session.attendee(params)

        assert attendee.can_defer_badge, 'You cannot defer your badge at this time.'

        if cherrypy.request.method == 'POST':
            message = check(attendee)

            if not message:
                attendee.badge_status = c.DEFERRED_STATUS
                session.add(attendee)
                session.commit()

                if attendee.amount_unpaid:
                    raise HTTPRedirect(attendee.payment_page + '&payment_label=merch_shipping_fee')
                else:
                    raise HTTPRedirect(
                        'badge_updated?id={}&message={}', attendee.id, 'Your registration has been deferred')

        return {
            'attendee': attendee,
            'message':  message,
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
                .format(email_only(c.REGDESK_EMAIL))
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
                    .format(email_only(c.REGDESK_EMAIL))

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

        if 'email' in params or 'login_email' in params:
            email = params.get('login_email', params.get('email', ''))
            password = params.get('login_password', params.get('password', ''))
            account = session.query(AttendeeAccount).filter_by(normalized_email=normalize_email(email)).first()
            if not account:
                message = 'No account exists for that email address'
            elif not bcrypt.hashpw(password, account.hashed) == account.hashed:
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

        attendees_who_owe_money = {}
        for attendee in account.attendees:
            receipt = session.get_receipt_by_model(attendee)
            if receipt and receipt.current_amount_owed:
                attendees_who_owe_money[attendee.full_name] = receipt.current_amount_owed

        if not account:
            raise HTTPRedirect('../landing/index')

        return {
            'message': message,
            'account': account,
            'attendees_who_owe_money': attendees_who_owe_money,
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
            set_up_new_account(session, attendee)
        
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
                receipt = session.get_receipt_by_model(attendee)
                if not receipt:
                    new_receipt = session.get_receipt_by_model(attendee, create_if_none=True)
                    if new_receipt.current_amount_owed and not new_receipt.pending_total:
                        raise HTTPRedirect('new_badge_payment?id=' + attendee.id + '&return_to=' + return_to)
                raise HTTPRedirect(page + 'message=' + message)

        attendee.placeholder = placeholder
        if not message and attendee.placeholder:
            message = 'You are not yet registered!  You must fill out this form to complete your registration.'
        elif not message and not c.ATTENDEE_ACCOUNTS_ENABLED and attendee.badge_status == c.COMPLETED_STATUS:
            message = 'You are already registered but you may update your information with this form.'

        group_credit = receipt_items.credit_calculation.items['Attendee']['group_discount'](attendee)

        return {
            'undoing_extra': undoing_extra,
            'return_to':     return_to,
            'attendee':      attendee,
            'account':       session.get_attendee_account_by_attendee(attendee),
            'message':       message,
            'affiliates':    session.affiliates(),
            'attractions':   session.query(Attraction).filter_by(is_public=True).all(),
            'badge_cost':    attendee.badge_cost if attendee.paid != c.PAID_BY_GROUP else 0,
            'receipt':       session.get_receipt_by_model(attendee),
            'attendee_group_discount': (group_credit[1] / 100) if group_credit else 0,
        }
        
    @ajax
    def get_receipt_preview(self, session, id, **params):
        try:
            attendee = session.attendee(id)
        except Exception as ex:
            return {'error': "Can't get attendee: " + str(ex)}

        if not params.get('col_name'):
            return {'error': "Can't calculate cost change without the column name"}

        desc, change, count = Charge.process_receipt_upgrade_item(attendee, params['col_name'], new_val=params.get('val'))
        return {'desc': desc, 'change': change} # We don't need the count for this preview

    @ajax
    def purchase_upgrades(self, session, id, **params):
        attendee = session.attendee(id)
        try:
            receipt = session.model_receipt(params.get('receipt_id'))
        except Exception:
            return {'error': "Cannot find your receipt, please contact registration"}
        
        if receipt.open_receipt_items and receipt.current_amount_owed:
            return {'error': "You already have an outstanding balance, please pay for your current items or contact registration"}

        for param in params:
            if param in Attendee.cost_changes:
                receipt_item = Charge.process_receipt_upgrade_item(attendee, param, receipt=receipt, new_val=params[param])
                if receipt_item.amount != 0:
                    session.add(receipt_item)

        attendee.apply(params, ignore_csrf=True, restricted=False)
        message = check(attendee)
        
        if message:
            session.rollback()
            return {'error': message}
        session.commit()

        return {'success': True}

    @ajax
    @credit_card
    @requires_account(Attendee)
    def process_attendee_payment(self, session, id, receipt_id, message='', **params):
        receipt = session.model_receipt(receipt_id)
        attendee = session.attendee(id)
        charge_desc = "{}: {}".format(attendee.full_name, receipt.charge_description_list)
        charge = Charge(attendee, amount=receipt.current_amount_owed, description=charge_desc)

        stripe_intent = charge.create_stripe_intent()
        if isinstance(stripe_intent, string_types):
            return {'error': stripe_intent}

        receipt_txn = Charge.create_receipt_transaction(receipt, charge_desc, stripe_intent.id)
        session.add(receipt_txn)

        session.commit()

        return_to = params.get('return_to')

        success_url_base = 'confirm?id=' + id + '&' if not return_to or return_to == 'confirm' else return_to + '?'

        return {'stripe_intent': stripe_intent,
                'success_url': '{}message={}'.format(success_url_base, 'Payment accepted!'),
                'cancel_url': 'cancel_payment'}

    @id_required(Attendee)
    @requires_account(Attendee)
    def new_badge_payment(self, session, id, return_to, message=''):
        attendee = session.attendee(id)
        return {
            'attendee': attendee,
            'receipt': session.get_receipt_by_model(attendee, create_if_none=True),
            'return_to': return_to,
            'message': message,
        }

    @id_required(Attendee)
    @requires_account(Attendee)
    def reset_receipt(self, session, id, return_to):
        attendee = session.attendee(id)
        receipt = session.get_receipt_by_model(attendee)
        receipt.closed = datetime.now()
        session.add(receipt)
        session.commit()

        message = attendee.undo_extras()
        if not message:
            new_receipt = session.get_receipt_by_model(attendee, create_if_none=True)
            page = ('badge_updated?id=' + attendee.id + '&') if return_to == 'confirm' else (return_to + '?')
            if new_receipt.current_amount_owed:
                raise HTTPRedirect('new_badge_payment?id=' + attendee.id + '&return_to=' + return_to)
            raise HTTPRedirect(page + 'message=Your registration has been confirmed')
        log.error(message)
        raise HTTPRedirect('new_badge_payment?id=' + attendee.id + '&return_to=' + return_to + '&message=There was a problem resetting your receipt')

    @ajax
    @credit_card
    @requires_account(Attendee)
    def buy_own_group_badge(self, session, id):
        attendee = session.attendee(id)
        if attendee.paid != c.PAID_BY_GROUP:
            return {'error': 'You should already have an individual badge. Please refresh the page.'}
        
        attendee.paid = c.NOT_PAID
        session.add(attendee)
        session.commit()

        if session.get_receipt_by_model(attendee):
            return {'error': 'You have outstanding purchases. Please refresh the page to pay for them.'}
        
        receipt, receipt_items = Charge.create_new_receipt(attendee, create_model=True)
        session.add(receipt)
        for item in receipt_items:
            session.add(item)

        session.commit()

        charge_desc = "{}: {}".format(attendee.full_name, receipt.charge_description_list)
        charge = Charge(attendee, amount=receipt.current_amount_owed, description=charge_desc)

        stripe_intent = charge.create_stripe_intent()
        if isinstance(stripe_intent, string_types):
            return {'error': stripe_intent}

        receipt_txn = Charge.create_receipt_transaction(receipt, charge_desc, stripe_intent.id)
        session.add(receipt_txn)

        session.commit()

        return {'stripe_intent': stripe_intent,
                'success_url': 'confirm?id={}&message={}'.format(id, 'Payment accepted!'),
                'cancel_url': 'cancel_payment'}


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
            if 'admin_url' in params:
                success_url = "../{}message=Password reset email sent.".format(params['admin_url'])
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
