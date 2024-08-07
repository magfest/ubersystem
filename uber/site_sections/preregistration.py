import json
from datetime import datetime, timedelta
from functools import wraps
from uber.models.admin import PasswordReset

import bcrypt
import cherrypy
from collections import defaultdict
from pockets import listify
from pockets.autolog import log
from sqlalchemy import func
from sqlalchemy.orm.exc import NoResultFound

from uber.config import c
from uber.custom_tags import email_only
from uber.decorators import ajax, all_renderable, credit_card, csrf_protected, id_required, log_pageview, \
    redirect_if_at_con_to_kiosk, render, requires_account
from uber.errors import HTTPRedirect
from uber.forms import load_forms
from uber.models import Attendee, AttendeeAccount, Attraction, Email, Group, PromoCode, PromoCodeGroup, \
                        ReceiptTransaction, Tracking
from uber.tasks.email import send_email
from uber.utils import add_opt, check, localized_now, normalize_email, normalize_email_legacy, genpasswd, valid_email, \
    valid_password, SignNowRequest, validate_model, create_new_hash
from uber.payments import PreregCart, TransactionRequest, ReceiptManager


def check_if_can_reg(is_dealer_reg=False):
    if c.DEV_BOX:
        pass  # Don't redirect to any of the pages below.
    elif is_dealer_reg and not c.DEALER_REG_OPEN:
        if c.AFTER_DEALER_REG_START:
            return render('static_views/dealer_reg_closed.html')
        else:
            return render('static_views/dealer_reg_not_open.html')
    elif not c.ATTENDEE_BADGE_AVAILABLE:
        return render('static_views/prereg_soldout.html')
    elif c.BEFORE_PREREG_OPEN and not is_dealer_reg:
        return render('static_views/prereg_not_yet_open.html')
    elif c.AFTER_PREREG_TAKEDOWN and not c.AT_THE_CON:
        return render('static_views/prereg_closed.html')


def check_post_con(klass):
    def wrapper(func):
        @wraps(func)
        def wrapped(self, *args, **kwargs):
            if c.POST_CON:
                return render('static_views/post_con.html')
            else:
                return func(self, *args, **kwargs)
        return wrapped

    for name in dir(klass):
        method = getattr(klass, name)
        if not name.startswith('_') and hasattr(method, '__call__'):
            setattr(klass, name, wrapper(method))
    return klass


def _add_promo_code(session, attendee, submitted_promo_code):
    if attendee.promo_code and submitted_promo_code != attendee.promo_code_code:
        attendee.promo_code = None
    if c.BADGE_PROMO_CODES_ENABLED and submitted_promo_code:
        if session.lookup_registration_code(submitted_promo_code, PromoCodeGroup):
            PreregCart.universal_promo_codes[attendee.id] = submitted_promo_code
        session.add_promo_code_to_attendee(attendee, submitted_promo_code)


def check_prereg_promo_code(session, attendee, codes_in_cart=defaultdict(int)):
    """
    Prevents double-use of promo codes if two people have the same promo code in their cart but only one use is
    remaining. If the attendee originally entered a 'universal' group code, which we track via
    PreregCart.universal_promo_codes, we instead try to find a different valid code and only throw an error if
    there are none left.
    """
    promo_code = session.query(PromoCode).filter(PromoCode.id == attendee.promo_code_id).with_for_update().one()

    if not promo_code.is_unlimited and (not promo_code.uses_remaining or
                                        promo_code.uses_remaining - codes_in_cart[promo_code.code] <= 0):
        universal_code = PreregCart.universal_promo_codes.get(attendee.id)
        if universal_code:
            message = session.add_promo_code_to_attendee(attendee, universal_code, codes_in_cart)
            session.commit()
            if message:
                return f"There are no more badges left in the group {attendee.full_name} " \
                    f"is trying to claim a badge in."
            return ""
        attendee.promo_code_id = None
        session.commit()
        return "The promo code you're using for {} has been used already.".format(attendee.full_name)


def update_prereg_cart(session):
    pending_preregs = PreregCart.pending_preregs.copy()
    for id in pending_preregs:
        existing_model = session.query(Attendee).filter_by(id=id).first()
        if not existing_model:
            existing_model = session.query(Group).filter_by(id=id).first()
        if existing_model:
            receipt = session.refresh_receipt_and_model(existing_model, is_prereg=True)
            if receipt and receipt.current_amount_owed:
                PreregCart.unpaid_preregs[id] = PreregCart.pending_preregs[id]
            elif receipt:
                PreregCart.paid_preregs.append(PreregCart.pending_preregs[id])
        PreregCart.pending_preregs.pop(id)


def check_account(session, email, password, confirm_password, skip_if_logged_in=True,
                  update_password=True, old_email=None):
    logged_in_account = session.current_attendee_account()
    if logged_in_account and skip_if_logged_in:
        return

    if email and valid_email(email):
        return valid_email(email)

    super_normalized_old_email = normalize_email_legacy(normalize_email(old_email)) if old_email else ''

    existing_account = session.query(AttendeeAccount).filter_by(normalized_email=normalize_email_legacy(email)).first()
    if existing_account and (old_email
                             and normalize_email_legacy(
                                 normalize_email(existing_account.email)) != super_normalized_old_email
                             or not old_email and not logged_in_account):
        return "There's already an account with that email address."
    elif existing_account and logged_in_account and \
            logged_in_account.normalized_email != existing_account.normalized_email:
        return "You cannot reset someone's password while logged in as someone else."

    if update_password:
        if password and password != confirm_password:
            return 'Password confirmation does not match.'

        return valid_password(password)


def set_up_new_account(session, attendee, email=None):
    email = email or attendee.email
    token = genpasswd(short=True)
    account = session.query(AttendeeAccount).filter_by(normalized_email=normalize_email_legacy(email)).first()
    if account:
        if account.password_reset:
            session.delete(account.password_reset)
            session.commit()
    else:
        account = session.create_attendee_account(email)
        session.add_attendee_to_account(attendee, account)

    if not account.is_sso_account:
        session.add(PasswordReset(attendee_account=account, hashed=create_new_hash(token)))

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
    def _get_unsaved(self, id, cart=None, if_not_found=None):
        """
        if_not_found:  pass in an HTTPRedirect() class to raise if the unsaved attendee is not found.
                       by default we will redirect to the index page
        """
        if not cart:
            cart = PreregCart.unpaid_preregs
        if id in cart:
            return PreregCart.from_sessionized(cart[id])
        else:
            if cart == PreregCart.unpaid_preregs:
                raise HTTPRedirect('form?message={}', 'That preregistration expired or has already been finalized.')
            elif cart == PreregCart.pending_dealers:
                raise HTTPRedirect('dealer_registration?message={}',
                                   'That application expired or has already been finalized.')
            raise HTTPRedirect('index') if if_not_found is None else if_not_found

    def _get_attendee_or_group(self, params):
        if 'attendee_id' in params:
            return self._get_unsaved(params['attendee_id']), None
        elif 'group_id' in params:
            group = self._get_unsaved(params['group_id'], PreregCart.pending_dealers)
            if not group.attendees:
                raise HTTPRedirect('form?dealer_id={}&message={}', group.id,
                                   "We couldn't find your personal information, please enter it below.")
            return group.attendees[0], group
        else:
            raise HTTPRedirect('index')

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

    def index(self, session, message='', account_email='', account_password='', **params):
        errors = check_if_can_reg()
        if errors:
            return errors

        update_prereg_cart(session)

        if not PreregCart.unpaid_preregs:
            raise HTTPRedirect('form?message={}', message) if message else HTTPRedirect('form')
        else:
            cart = PreregCart(listify(PreregCart.unpaid_preregs.values()))
            cart.set_total_cost()
            for attendee in cart.attendees:
                if attendee.promo_code:
                    real_code = session.query(PromoCode).filter_by(code=attendee.promo_code.code).first()
                    if real_code and real_code.group:
                        attendee.promo_group_name = real_code.group.name
            return {
                'logged_in_account': session.current_attendee_account(),
                'is_prereg_dealer': False,
                'message': message,
                'cart': cart,
                'account_email': account_email or cart.attendees[0].email,
                'account_password': account_password,
            }

    def reapply(self, session, id, **params):
        errors = check_if_can_reg(is_dealer_reg=True)
        if errors:
            return errors

        old_attendee = session.attendee(id)
        old_attendee_dict = old_attendee.to_dict(c.UNTRANSFERABLE_ATTRS)
        del old_attendee_dict['id']
        new_attendee = Attendee(**old_attendee_dict)
        new_attendee.badge_type = c.PSEUDO_DEALER_BADGE

        old_group = session.group(old_attendee.group.id)
        old_group_dict = old_group.to_dict(c.GROUP_REAPPLY_ATTRS)
        del old_group_dict['id']
        new_group = Group(**old_group_dict)

        new_attendee.group_id = new_group.id
        new_group.attendees = [new_attendee]

        cherrypy.session.setdefault('imported_attendee_ids', {})[new_attendee.id] = id

        PreregCart.pending_dealers[new_group.id] = PreregCart.to_sessionized(new_group,
                                                                             badge_count=old_group.badges_purchased)
        raise HTTPRedirect("dealer_registration?edit_id={}", new_group.id)

    def repurchase(self, session, id, skip_confirm=False, **params):
        errors = check_if_can_reg()
        if errors:
            return errors
        if skip_confirm or 'csrf_token' in params:
            old_attendee = session.attendee(id)
            old_attendee_dict = old_attendee.to_dict(c.UNTRANSFERABLE_ATTRS)
            del old_attendee_dict['id']

            new_attendee = Attendee(**old_attendee_dict)

            cherrypy.session.setdefault('imported_attendee_ids', {})[new_attendee.id] = id

            PreregCart.unpaid_preregs[new_attendee.id] = PreregCart.to_sessionized(new_attendee)
            Tracking.track(c.UNPAID_PREREG, new_attendee)
            raise HTTPRedirect("form?edit_id={}&repurchase=1", new_attendee.id)
        return {
            'id': id
        }

    def resume_pending(self, session, id=None, account_id=None, **params):
        if account_id:
            pending_badges = session.attendee_account(account_id).pending_attendees
        else:
            pending_badges = [session.attendee(id)]

        for badge in pending_badges:
            PreregCart.pending_preregs[badge.id] = PreregCart.to_sessionized(badge)

        update_prereg_cart(session)
        if not PreregCart.unpaid_preregs:
            message = "Successful payments found for all badges!"
        elif len(PreregCart.unpaid_preregs) < len(pending_badges):
            message = "Some badges have been marked as completed as we found successful payments for them."
        else:
            message = f"{len(pending_badges)} incomplete badges found." if c.ATTENDEE_ACCOUNTS_ENABLED \
                        else "Please complete your registration below."

        raise HTTPRedirect(f"index?message={message}")

    @cherrypy.expose('post_dealer')
    @requires_account()
    def dealer_registration(self, session, message='', edit_id=None, **params):
        errors = check_if_can_reg(is_dealer_reg=True)
        if errors:
            return errors

        if c.DEALER_INVITE_CODE and not edit_id:
            if not params.get('invite_code'):
                raise HTTPRedirect("dealer_registration?message={}s must have an invite code to register."
                                   .format(c.DEALER_TERM.capitalize()))
            elif params.get('invite_code') != c.DEALER_INVITE_CODE:
                raise HTTPRedirect("dealer_registration?message=Incorrect {} invite code.".format(c.DEALER_REG_TERM))

        params['id'] = 'None'   # security!
        group = Group(is_dealer=True)

        if edit_id is not None:
            group = self._get_unsaved(edit_id, PreregCart.pending_dealers)
            params['badges'] = params.get('badges', getattr(group, 'badge_count', 0))

        badges = params.get('badges', 0)
        attendee = group.attendees[0] if group.attendees else None

        forms = load_forms(params, group, ['ContactInfo', 'TableInfo'])
        for form in forms.values():
            form.populate_obj(group)

        if cherrypy.request.method == 'POST':
            message = check(group, prereg=True)
            if not message:
                track_type = c.UNPAID_PREREG

                if attendee:
                    group.attendees = [attendee]
                PreregCart.pending_dealers[group.id] = PreregCart.to_sessionized(group,
                                                                                 badge_count=badges)
                Tracking.track(track_type, group)
                if 'go_to_cart' in params:
                    raise HTTPRedirect('additional_info?group_id={}{}'
                                       .format(group.id, "&editing={}".format(edit_id) if edit_id else ""))
                raise HTTPRedirect("form?dealer_id={}", group.id)
        else:
            if c.DEALER_REG_SOFT_CLOSED:
                message = '{} is closed, but you can ' \
                    'fill out this form to add yourself to our waitlist'.format(c.DEALER_REG_TERM.title())

        return {
                'logged_in_account': session.current_attendee_account(),
                'is_prereg_dealer': True,
                'forms': forms,
                'message':    message,
                'group':      group,
                'attendee':   Attendee(),
                'edit_id':    edit_id,
                'badges': badges,
                'invite_code': params.get('invite_code', ''),
            }

    def finish_dealer_reg(self, session, id, **params):
        errors = check_if_can_reg(is_dealer_reg=True)
        if errors:
            return errors

        group = self._get_unsaved(id, PreregCart.pending_dealers)
        group.is_dealer = True
        attendee = group.attendees[0]

        if c.ATTENDEE_ACCOUNTS_ENABLED:
            attendee_account = session.current_attendee_account()
            session.add_attendee_to_account(attendee, attendee_account)

        if attendee.id in cherrypy.session.setdefault('imported_attendee_ids', {}):
            old_attendee = session.attendee(cherrypy.session['imported_attendee_ids'][attendee.id])
            old_attendee.current_attendee = attendee
            session.add(old_attendee)
            del cherrypy.session['imported_attendee_ids'][attendee.id]

        attendee.paid = c.PAID_BY_GROUP
        group.attendees = [attendee]
        session.assign_badges(group, group.badge_count)
        group.status = c.WAITLISTED if c.DEALER_REG_SOFT_CLOSED else c.UNAPPROVED
        attendee.ribbon = add_opt(attendee.ribbon_ints, c.DEALER_RIBBON)
        attendee.badge_type = c.ATTENDEE_BADGE

        session.add_all([attendee, group])
        session.commit()
        try:
            if c.NOTIFY_DEALER_APPLIED:
                send_email.delay(
                    c.MARKETPLACE_EMAIL,
                    c.MARKETPLACE_NOTIFICATIONS_EMAIL,
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

    def claim_badge(self, session, message='', **params):
        if params.get('id') in [None, '', 'None']:
            attendee = Attendee()
        else:
            attendee = session.attendee(params.get('id'), ignore_csrf=True)

        form_list = ['PersonalInfo', 'BadgeExtras', 'BadgeFlags', 'OtherInfo', 'StaffingInfo', 'Consents']
        forms = load_forms(params, attendee, form_list)

        if cherrypy.request.method == 'POST':
            message = session.add_promo_code_to_attendee(attendee, params.get('promo_code_code', '').strip())

            if not message:
                for form in forms.values():
                    if hasattr(form, 'same_legal_name') and params.get('same_legal_name'):
                        form['legal_name'].data = ''
                    form.populate_obj(attendee)
                receipt, receipt_items = ReceiptManager.create_new_receipt(attendee, create_model=True)
                session.add(receipt)
                session.add_all(receipt_items)

                attendee.badge_status = c.COMPLETED_STATUS
                attendee.badge_cost = attendee.calculate_badge_cost()
                if not attendee.badge_cost:
                    attendee.paid = c.NEED_NOT_PAY

                if c.ATTENDEE_ACCOUNTS_ENABLED:
                    session.add_attendee_to_account(attendee, session.current_attendee_account())
                else:
                    session.add(attendee)

                raise HTTPRedirect("confirm?id={}&message={}", attendee.id,
                                   f"You have successfully claimed a badge in the group "
                                   f"{attendee.promo_code.group.name}!")
        return {
            'message': message,
            'attendee': attendee,
            'forms': forms,
            'logged_in_account': session.get_attendee_account_by_attendee(attendee),
        }

    @ajax
    def validate_badge_claim(self, session, form_list=[], is_prereg=True, **params):
        group_code = params.get('promo_code_code', '').strip()
        all_errors = defaultdict(list)
        if not group_code:
            all_errors['promo_code_code'].append("You must enter a group code to claim a badge in a group.")
        else:
            code = session.lookup_promo_code(group_code)
            if not code:
                all_errors['promo_code_code'].append(f"The promo code you entered ({group_code}) is invalid.")
            elif not code.group:
                all_errors['promo_code_code'].append(f"There is no group for code {group_code}.")

        normal_validations = json.loads(self.validate_attendee(form_list=form_list, **params))

        if 'error' in normal_validations:
            for key, val in normal_validations['error'].items():
                all_errors[key] = val

        if bool(all_errors):
            return {"error": all_errors}

        return {"success": True}

    @cherrypy.expose('post_form')
    @redirect_if_at_con_to_kiosk
    @requires_account()
    def form(self, session, message='', edit_id=None, **params):
        # Help prevent data leaking between people registering on the same computer
        cherrypy.session.pop('paid_preregs')

        dealer_id = params.get('dealer_id', params.get('group_id', None))
        errors = check_if_can_reg(bool(dealer_id))
        if errors:
            return errors
        """
        Our production NGINX config caches the page at /preregistration/form.
        Since it's cached, we CAN'T return a session cookie with the page. We
        must POST to a different URL in order to bypass the cache and get a
        valid session cookie. Thus, this page is also exposed as "post_form".
        """
        params['id'] = 'None'   # security!
        attendee = Attendee()
        group = Group()
        badges = params.get('badges', 0)
        name = params.get('name', '')
        loaded_from_group = False

        if cherrypy.request.method == 'POST' and not params.get('badge_type'):
            params['badge_type'] = c.ATTENDEE_BADGE

        if dealer_id:
            group = self._get_unsaved(dealer_id, PreregCart.pending_dealers)
            if group.attendees:
                attendee = group.attendees[0]
                loaded_from_group = True
            else:
                attendee.badge_type = c.PSEUDO_DEALER_BADGE
            attendee.group_id = dealer_id

        if edit_id is not None:
            attendee = self._get_unsaved(edit_id)
            badges = getattr(attendee, 'badges', 0)
            name = getattr(attendee, 'name', '')

        forms_list = ['PersonalInfo', 'BadgeExtras', 'Consents']
        if c.GROUPS_ENABLED:
            forms_list.append('GroupInfo')
        forms = load_forms(params, attendee, forms_list)
        if edit_id or loaded_from_group:
            forms['consents'].pii_consent.data = True

        for form in forms.values():
            if hasattr(form, 'same_legal_name') and params.get('same_legal_name'):
                form['legal_name'].data = ''
            form.populate_obj(attendee)

        if (cherrypy.request.method == 'POST' or edit_id is not None) and c.PRE_CON:
            if not message and attendee.badge_type not in c.PREREG_BADGE_TYPES:
                message = 'Invalid badge type!'

        if message:
            return {
                'logged_in_account': session.current_attendee_account(),
                'loaded_from_group': loaded_from_group,
                'forms': forms,
                'message':    message,
                'attendee':   attendee,
                'group':      group,
                'edit_id':    edit_id,
                'cart_not_empty': PreregCart.unpaid_preregs,
                'name': name,
                'badges': badges,
                'invite_code': params.get('invite_code', ''),
                'is_prereg_dealer': bool(dealer_id),
            }

        if cherrypy.request.method == 'POST':
            if not attendee.promo_code_code:
                _add_promo_code(session, attendee, params.get('promo_code_code'))

            if attendee.badge_type == c.PSEUDO_GROUP_BADGE:
                message = "Please enter a group name" if not params.get('name') else message
            else:
                params['badges'] = 0
                params['name'] = ''

            if not message:
                track_type = c.UNPAID_PREREG

                if 'group_id' in params and attendee.badge_type == c.PSEUDO_DEALER_BADGE:
                    attendee.group_id = params['group_id']

                    if params.get('copy_email'):
                        attendee.email = group.email_address
                    if params.get('copy_phone'):
                        attendee.cellphone = group.phone
                    if params.get('copy_address'):
                        attendee.address1 = group.address1
                        attendee.address2 = group.address2
                        attendee.country = group.country
                        attendee.region = group.region
                        attendee.city = group.city
                        attendee.zip_code = group.zip_code

                    group.attendees = [attendee]
                    PreregCart.pending_dealers[group.id] = PreregCart.to_sessionized(group,
                                                                                     badge_count=group.badge_count)
                    Tracking.track(track_type, group)
                    url_string = "group_id={}".format(group.id)
                else:
                    if attendee.id in PreregCart.unpaid_preregs:
                        track_type = c.EDITED_PREREG
                        # Clear out any previously cached targets, in case the unpaid badge
                        # has been edited and changed from a single to a group or vice versa.
                        del PreregCart.unpaid_preregs[attendee.id]

                    PreregCart.unpaid_preregs[attendee.id] = PreregCart.to_sessionized(attendee,
                                                                                       name=params.get('name'),
                                                                                       badges=params.get('badges'))
                    Tracking.track(track_type, attendee)
                    url_string = "attendee_id={}".format(attendee.id)

                if not message:
                    if session.attendees_with_badges().filter_by(
                            first_name=attendee.first_name, last_name=attendee.last_name, email=attendee.email).count():

                        raise HTTPRedirect('duplicate?{}'.format(url_string))

                    if attendee.banned:
                        raise HTTPRedirect('banned?{}'.format(url_string))

                    if edit_id and params.get('go_to_cart'):
                        raise HTTPRedirect('index')
                    raise HTTPRedirect('additional_info?{}{}'.format(url_string,
                                                                     "&editing={}".format(edit_id) if edit_id else ""))

        promo_code_group = None
        if attendee.promo_code:
            promo_code_group = session.query(PromoCode).filter_by(code=attendee.promo_code.code).first().group

        return {
            'logged_in_account': session.current_attendee_account(),
            'loaded_from_group': loaded_from_group,
            'is_prereg_dealer': bool(dealer_id),
            'message':    message,
            'attendee':   attendee,
            'forms': forms,
            'badges': badges,
            'name': name,
            'group':      group,
            'promo_code_group': promo_code_group,
            'edit_id':    edit_id,
            'cart_not_empty': PreregCart.unpaid_preregs,
            'promo_code_code': params.get('promo_code', ''),
            'invite_code': params.get('invite_code', ''),
        }

    def additional_info(self, session, message='', editing=None, **params):
        is_dealer_reg = 'group_id' in params
        errors = check_if_can_reg(is_dealer_reg)
        if errors:
            return errors

        attendee, group = self._get_attendee_or_group(params)

        forms = load_forms(params, attendee, ['PreregOtherInfo'], truncate_prefix="prereg")

        for form in forms.values():
            form.populate_obj(attendee)

        if cherrypy.request.method == "POST":
            _add_promo_code(session, attendee, params.get('promo_code_code'))

            if attendee.badge_type == c.PSEUDO_DEALER_BADGE:
                group.attendees = [attendee]
                PreregCart.pending_dealers[group.id] = PreregCart.to_sessionized(group, badge_count=group.badge_count)
                raise HTTPRedirect('finish_dealer_reg?id={}', attendee.group_id)
            PreregCart.unpaid_preregs[attendee.id] = PreregCart.to_sessionized(attendee,
                                                                               name=attendee.name,
                                                                               badges=attendee.badges)
            Tracking.track(c.EDITED_PREREG, attendee)

            raise HTTPRedirect('index')
        return {
            'logged_in_account': session.current_attendee_account(),
            'is_prereg_dealer': is_dealer_reg,
            'message':    message,
            'attendee':   attendee,
            'editing': editing,
            'forms': forms,
        }

    def duplicate(self, session, **params):
        errors = check_if_can_reg(is_dealer_reg='group_id' in params)
        if errors:
            return errors

        attendee, group = self._get_attendee_or_group(params)
        orig = session.query(Attendee).filter_by(
            first_name=attendee.first_name, last_name=attendee.last_name, email=attendee.email).first()

        if not orig:
            raise HTTPRedirect('index')

        return {
            'duplicate': attendee,
            'attendee': orig,
            'id': id
        }

    def banned(self, **params):
        errors = check_if_can_reg(is_dealer_reg='group_id' in params)
        if errors:
            return errors

        attendee, group = self._get_attendee_or_group(params)
        return {
            'attendee': attendee,
            'id': id
        }

    def at_door_confirmation(self, session, message='', qr_code_id='', **params):
        # Currently the cart feature relies on attendee accounts and "At Door Pending Status"
        # We will want real "carts" later so we can support group check-in for prereg attendees

        cart = PreregCart(listify(PreregCart.unpaid_preregs.values()))
        used_codes = defaultdict(int)
        registrations_list = []
        account = None

        if not listify(PreregCart.unpaid_preregs.values()):
            if c.ATTENDEE_ACCOUNTS_ENABLED and qr_code_id:
                account = session.query(AttendeeAccount).filter_by(public_id=qr_code_id).first()
                for attendee in account.at_door_attendees:
                    registrations_list.append(attendee.full_name)
            elif c.ATTENDEE_ACCOUNTS_ENABLED:
                account = session.current_attendee_account()
                qr_code_id = qr_code_id or (account.public_id if account else '')

            if not qr_code_id:
                raise HTTPRedirect('form')

        for attendee in cart.attendees:
            registrations_list.append(attendee.full_name)
            if c.ATTENDEE_ACCOUNTS_ENABLED:
                attendee.badge_status = c.AT_DOOR_PENDING_STATUS
            # Setting this makes the badge count against our badge cap (does not work if at-door pending status is used)
            attendee.paid = c.PENDING

            if attendee.id in cherrypy.session.setdefault('imported_attendee_ids', {}):
                old_attendee = session.attendee(cherrypy.session['imported_attendee_ids'][attendee.id])
                old_attendee.current_attendee = attendee
                session.add(old_attendee)
                del cherrypy.session['imported_attendee_ids'][attendee.id]

            if attendee.promo_code_code:
                message = check_prereg_promo_code(session, attendee, used_codes)
                if not message:
                    used_codes[attendee.promo_code_code] += 1

            if message:
                session.rollback()
                raise HTTPRedirect('index?message={}', message)
            elif account:
                session.add_attendee_to_account(attendee, account)
            else:
                session.add(attendee)
            receipt, receipt_items = ReceiptManager.create_new_receipt(attendee, create_model=True)
            session.add(receipt)
            session.add_all(receipt_items)
            total_cost = sum([(item.amount * item.count) for item in receipt_items])
            if total_cost == 0:
                attendee.paid = c.NEED_NOT_PAY
        for group in cart.groups:
            session.add(group)

        PreregCart.unpaid_preregs.clear()
        session.commit()

        return {
            'account': account,
            'qr_code_id': qr_code_id,
            'completed_registrations': registrations_list,
            'logged_in_account': session.current_attendee_account(),
        }

    def process_free_prereg(self, session, message='', **params):
        cart = PreregCart(listify(PreregCart.unpaid_preregs.values()))
        cart.set_total_cost()
        if cart.total_cost <= 0:
            used_codes = defaultdict(int)
            for attendee in cart.attendees:
                receipt, receipt_items = ReceiptManager.create_new_receipt(attendee, create_model=True)
                session.add(receipt)
                session.add_all(receipt_items)

                attendee.badge_status = c.COMPLETED_STATUS
                attendee.badge_cost = attendee.calculate_badge_cost()
                attendee.paid = c.NEED_NOT_PAY

                if attendee.id in cherrypy.session.setdefault('imported_attendee_ids', {}):
                    old_attendee = session.attendee(cherrypy.session['imported_attendee_ids'][attendee.id])
                    old_attendee.current_attendee = attendee
                    session.add(old_attendee)
                    del cherrypy.session['imported_attendee_ids'][attendee.id]

                if attendee.promo_code_code:
                    message = check_prereg_promo_code(session, attendee, used_codes)
                    if not message:
                        used_codes[attendee.promo_code_code] += 1

                if message:
                    session.rollback()
                    raise HTTPRedirect('index?message={}', message)
                elif c.ATTENDEE_ACCOUNTS_ENABLED:
                    session.add_attendee_to_account(attendee, session.current_attendee_account())
                else:
                    session.add(attendee)

            for group in cart.groups:
                session.add(group)

            PreregCart.unpaid_preregs.clear()
            PreregCart.paid_preregs.extend(cart.targets)
            raise HTTPRedirect('paid_preregistrations?total_cost={}', cart.dollar_amount)
        else:
            message = "These badges aren't free! Please pay for them."
            raise HTTPRedirect('index?message={}', message)

    @ajax
    @credit_card
    def prereg_payment(self, session, message='', **params):
        errors = check_if_can_reg()
        if errors:
            return errors
        update_prereg_cart(session)
        cart = PreregCart(listify(PreregCart.unpaid_preregs.values()))
        cart.set_total_cost()
        if not cart.total_cost:
            if not cart.models:
                HTTPRedirect('form?message={}', 'Your preregistration has already been finalized')
            message = 'Your total cost was $0. Your credit card has not been charged.'
        else:
            used_codes = defaultdict(int)
            for attendee in cart.attendees:
                if not message and attendee.promo_code_code:
                    message = check_prereg_promo_code(session, attendee, used_codes)
                if not message:
                    used_codes[attendee.promo_code_code] += 1
                    form_list = ['PersonalInfo', 'BadgeExtras', 'PreregOtherInfo', 'Consents']
                    # Populate checkboxes based on the model (I need a better solution for this)
                    params = {}
                    if not attendee.legal_name:
                        params['same_legal_name'] = True
                    params['pii_consent'] = True

                    forms = load_forms(params, attendee, form_list, checkboxes_present=False)

                    all_errors = validate_model(forms, attendee)
                    if all_errors:
                        pass
                        # Flatten the errors as we don't have fields on this page
                        # message = ' '.join([item for sublist in all_errors.values() for item in sublist])
                if message:
                    message += f" Please click 'Edit' next to {attendee.full_name}'s registration to fix any issues."
                    break

            if not message:
                receipts = []
                for model in cart.models:
                    charge_receipt, charge_receipt_items = ReceiptManager.create_new_receipt(model, create_model=True)
                    existing_receipt = session.refresh_receipt_and_model(model, is_prereg=True)
                    if existing_receipt:
                        # Multiple attendees can have the same transaction during pre-reg,
                        # so we always cancel any incomplete transactions
                        incomplete_txn = existing_receipt.get_last_incomplete_txn()
                        if incomplete_txn:
                            incomplete_txn.cancelled = datetime.now()
                            session.add(incomplete_txn)

                        # If their registration costs changed, close their old receipt
                        compare_fields = ['amount', 'count', 'desc']
                        existing_items = [item.to_dict(compare_fields) for item in existing_receipt.receipt_items]
                        new_items = [item.to_dict(compare_fields) for item in charge_receipt_items]

                        for item in existing_items:
                            del item['id']
                        for item in new_items:
                            del item['id']

                        diff_list = [x for x in existing_items + new_items
                                     if x not in existing_items or x not in new_items]

                        if diff_list:
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
                    receipt_email = session.current_attendee_account().email \
                        if c.ATTENDEE_ACCOUNTS_ENABLED else cart.receipt_email
                    charge = TransactionRequest(receipt_email=receipt_email,
                                                description=cart.description,
                                                amount=sum([receipt.current_amount_owed for receipt in receipts]))
                    message = charge.create_stripe_intent()

        if message:
            return {'error': message}

        for receipt in receipts:
            receipt_manager = ReceiptManager(receipt)
            if receipt.current_amount_owed != 0:
                receipt_manager.create_payment_transaction(charge.description, charge.intent,
                                                           receipt.current_amount_owed)
                session.add_all(receipt_manager.items_to_add)

        for attendee in cart.attendees:
            pending_attendee = session.query(Attendee).filter_by(id=attendee.id).first()
            if pending_attendee:
                pending_attendee.apply(PreregCart.to_sessionized(attendee), restricted=True)
                if attendee.badges and pending_attendee.promo_code_groups:
                    pc_group = pending_attendee.promo_code_groups[0]
                    pc_group.name = attendee.name

                    pc_codes = int(attendee.badges) - 1
                    pending_codes = len(pc_group.promo_codes)
                    if pc_codes > pending_codes:
                        session.add_codes_to_pc_group(pc_group, pc_codes - pending_codes)
                    elif pc_codes < pending_codes:
                        session.remove_codes_from_pc_group(pc_group, pending_codes - pc_codes)
                elif attendee.badges:
                    pc_group = session.create_promo_code_group(pending_attendee, attendee.name,
                                                               int(attendee.badges) - 1)
                    session.add(pc_group)
                elif pending_attendee.promo_code_groups:
                    pc_group = pending_attendee.promo_code_groups[0]
                    session.delete(pc_group)

                if c.ATTENDEE_ACCOUNTS_ENABLED:
                    session.add_attendee_to_account(pending_attendee, session.current_attendee_account())
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
                    session.add_attendee_to_account(attendee, session.current_attendee_account())

                if attendee.badges:
                    pc_group = session.create_promo_code_group(attendee, attendee.name, int(attendee.badges) - 1)
                    session.add(pc_group)

        cherrypy.session['pending_preregs'] = PreregCart.unpaid_preregs.copy()

        PreregCart.unpaid_preregs.clear()
        PreregCart.paid_preregs.extend(cart.targets)
        cherrypy.session['payment_intent_id'] = charge.intent.id
        session.commit()

        return {'stripe_intent': charge.intent,
                'success_url': 'paid_preregistrations?total_cost={}&message={}'.format(
                    cart.dollar_amount, 'Payment accepted!'),
                'cancel_url': 'cancel_prereg_payment'}

    @ajax
    def submit_authnet_charge(self, session, ref_id, amount, email, desc, customer_id, token_desc, token_val, **params):
        charge = TransactionRequest(receipt_email=email, description=desc, amount=amount, customer_id=customer_id)
        error = charge.send_authorizenet_txn(token_desc=token_desc, token_val=token_val, intent_id=ref_id,
                                             first_name=params.get('first_name', ''),
                                             last_name=params.get('last_name', ''))
        if error:
            return {'error': error}
        else:
            return {'success': True}

    @ajax
    def cancel_prereg_payment(self, session, stripe_id):
        for txn in session.query(ReceiptTransaction).filter_by(intent_id=stripe_id).all():
            if not txn.charge_id:
                txn.cancelled = datetime.now()
                session.add(txn)

        PreregCart.paid_preregs.clear()
        if PreregCart.pending_preregs:
            cherrypy.session['unpaid_preregs'] = PreregCart.pending_preregs.copy()
            PreregCart.pending_preregs.clear()
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
    def cancel_payment_and_revert(self, session, stripe_id):
        last_receipt = None
        model = None
        for txn in session.query(ReceiptTransaction).filter_by(intent_id=stripe_id).all():
            receipt = txn.receipt
            if receipt != last_receipt:
                model = session.get_model_by_receipt(receipt)

            if model and not txn.charge_id:
                new_model = model.__class__(**model.to_dict())
                for item in txn.receipt_items:
                    for col_name in item.revert_change:
                        setattr(new_model, col_name, item.revert_change[col_name])
                for item in txn.receipt_items:
                    for col_name in item.revert_change:
                        receipt_items = ReceiptManager.process_receipt_change(
                            model, col_name, receipt=receipt, new_model=new_model)
                        session.add_all(receipt_items)
                        model.apply(item.revert_change, restricted=False)
            if not txn.charge_id:
                txn.cancelled = datetime.now()
                session.add(txn)

            last_receipt = receipt

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
        return {'redirect_url': 'group_promo_codes?id={}&message={}'.format(attendee.promo_code_groups[0].id,
                                                                            'Payment cancelled.')}

    def paid_preregistrations(self, session, total_cost=None, message=''):
        if not PreregCart.paid_preregs:
            raise HTTPRedirect('index')
        else:
            for key in [key for key in PreregCart.session_keys if key != 'paid_preregs']:
                cherrypy.session.pop(key)

            # We do NOT want to merge the old data into the new attendee
            preregs = []
            for prereg in PreregCart.paid_preregs:
                model = session.query(Attendee).filter_by(id=prereg['id']).first()
                if not model:
                    model = session.query(Group).filter_by(id=prereg['id']).first()

                if model:
                    preregs.append(model)

            for prereg in preregs:
                receipt = session.get_receipt_by_model(prereg)
                if isinstance(prereg, Attendee):
                    session.refresh_receipt_and_model(prereg, is_prereg=True)
                    session.update_paid_from_receipt(prereg, receipt)

            session.commit()
            return {
                'logged_in_account': session.current_attendee_account(),
                'preregs': preregs,
                'is_prereg_dealer': False,
                'total_cost': total_cost,
                'message': message
            }

    def delete(self, session, message='Preregistration deleted.', **params):
        if 'id' or 'attendee_id' in params:
            id = params.get("id", params.get("attendee_id"))
            existing_model = session.query(Attendee).filter_by(id=id).first()
        elif 'group_id' in params:
            id = params.get("group_id")
            existing_model = session.query(Group).filter_by(id=id).first()

        PreregCart.unpaid_preregs.pop(id, None)

        if existing_model:
            existing_receipt = session.get_receipt_by_model(existing_model)
            existing_model.badge_status = c.INVALID_STATUS
            session.add(existing_model)
            if existing_receipt:
                existing_receipt.closed = datetime.now()
                session.add(existing_receipt)
            session.commit()

        raise HTTPRedirect('index?message={}', message)

    @id_required(Group)
    def dealer_confirmation(self, session, id):
        group = session.group(id)

        return {
            'logged_in_account': session.current_attendee_account(),
            'group': group,
            'is_prereg_dealer': True
            }

    @id_required(PromoCodeGroup)
    def group_promo_codes(self, session, id, message='', **params):
        group = session.promo_code_group(id)
        if not group.buyer:
            raise HTTPRedirect('../landing/index?message={}', "This group does not have an owner.")
        receipt = session.refresh_receipt_and_model(group.buyer)
        session.commit()

        sent_code_emails = session.query(Email.ident, Email.to, func.max(Email.when)).filter(
            Email.ident.contains("pc_group_invite_")).order_by(func.max(Email.when)).group_by(Email.ident,
                                                                                              Email.to).all()

        emailed_codes = defaultdict(str)

        for code in group.sorted_promo_codes:
            all_recipients = sorted([(email_to, sent) for (ident, email_to, sent) in sent_code_emails
                                     if ident == f"pc_group_invite_{code.code}"], key=lambda x: x[1], reverse=True)
            if all_recipients:
                emailed_codes[code.code] = all_recipients[0][0]

        return {
            'group': group,
            'receipt': receipt,
            'message': message,
            'emailed_codes': emailed_codes,
        }

    def email_promo_code(self, session, group_id, message='', **params):
        if cherrypy.request.method == 'POST':
            code = session.lookup_registration_code(params.get('code'))
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
                    model=code.to_dict('id'),
                    ident="pc_group_invite_" + code.code)
                raise HTTPRedirect('group_promo_codes?id={}&message={}'.format(
                    group_id, f"Email sent to {params.get('email', '')}!"))
            else:
                raise HTTPRedirect('group_promo_codes?id={}&message={}'.format(group_id, message))

    def add_promo_codes(self, session, id, count, estimated_cost):
        errors = check_if_can_reg()
        if errors:
            return errors
        group = session.promo_code_group(id)
        count = int(count)
        
        if int(estimated_cost) != count * c.GROUP_PRICE:
            raise HTTPRedirect(
                'group_members?id={}&message={}',
                group.id,
                'Our preregistration price has gone up since you tried to add badges; please try again.')

        if count < group.min_badges_addable and not group.is_in_grace_period:
            raise HTTPRedirect(
                'group_promo_codes?id={}&message={}',
                group.id,
                'You must add at least {} codes.'.format(group.min_badges_addable))

        receipt = session.get_receipt_by_model(group.buyer)
        if receipt:
            session.add(ReceiptManager().create_receipt_item(receipt,
                                                             c.REG_RECEIPT_ITEM,
                                                             c.GROUP_BADGE,
                                                             f'{count} extra badge{"s" if count > 1 else ""} '
                                                             f'for {group.name}',
                                                             count * c.GROUP_PRICE * 100))
        
        session.add_codes_to_pc_group(group, count)
        session.commit()

        raise HTTPRedirect('group_promo_codes?id={}&count={}&message={}', group.id, count,
                            f"{count} codes have been added to your group! Please pay for them below.")

    @id_required(Group)
    @requires_account(Group)
    @log_pageview
    def group_members(self, session, id, message='', **params):
        group = session.group(id)

        if group.is_dealer:
            form_list = ['TableInfo', 'ContactInfo']
        else:
            form_list = ['GroupInfo']

        forms = load_forms(params, group, form_list)
        for form in forms.values():
            form.populate_obj(group)

        signnow_document = None
        signnow_link = ''

        if group.is_dealer and c.SIGNNOW_DEALER_TEMPLATE_ID and group.is_valid and group.status == c.APPROVED:
            signnow_request = SignNowRequest(session=session, group=group, ident="terms_and_conditions",
                                             create_if_none=True)

            if signnow_request.error_message:
                log.error(signnow_request.error_message)
            else:
                signnow_document = signnow_request.document
                session.add(signnow_document)

                signnow_link = signnow_document.link

                if not signnow_document.signed:
                    signed = signnow_request.get_doc_signed_timestamp()
                    if signed:
                        signnow_document.signed = datetime.fromtimestamp(int(signed))
                        signnow_link = ''
                        signnow_document.link = signnow_link
                    elif not signnow_link:
                        signnow_link = signnow_request.create_dealer_signing_link()
                        if signnow_request.error_message:
                            log.error(signnow_request.error_message)
                        else:
                            signnow_document.link = signnow_link

                session.commit()

        if cherrypy.request.method == 'POST':
            session.commit()
            if group.is_dealer:
                send_email.delay(
                    c.MARKETPLACE_EMAIL,
                    c.MARKETPLACE_NOTIFICATIONS_EMAIL,
                    '{} Changed'.format(c.DEALER_APP_TERM.title()),
                    render('emails/dealers/appchange_notification.html', {'group': group}, encoding=None),
                    'html',
                    model=group.to_dict('id'))

            message = 'Thank you! Your application has been updated.'

            raise HTTPRedirect('group_members?id={}&message={}', group.id, message)

        receipt = session.refresh_receipt_and_model(group)
        session.commit()
        if receipt and receipt.current_amount_owed and not group.is_dealer:
            raise HTTPRedirect('group_payment?id={}', group.id)

        return {
            'group':   group,
            'forms': forms,
            'locked_fields': [item for sublist in [form.get_non_admin_locked_fields(group) for form in forms.values()]
                              for item in sublist],
            'homepage_account': session.get_attendee_account_by_attendee(group.leader),
            'logged_in_account': session.current_attendee_account(),
            'signnow_document': signnow_document,
            'signnow_link': signnow_link,
            'receipt': receipt,
            'incomplete_txn': receipt.get_last_incomplete_txn() if receipt else None,
            'message': message
        }

    def download_signnow_document(self, session, id, return_to='../preregistration/group_members'):
        group = session.group(id)
        signnow_request = SignNowRequest(session=session, group=group)
        if signnow_request.error_message:
            log.error(signnow_request.error_message)
            raise HTTPRedirect(return_to + "?id={}&message={}", id,
                               "We're having an issue fetching this document link. Please try again later!")
        elif signnow_request.document:
            if signnow_request.document.signed:
                download_link = signnow_request.get_download_link()
                if signnow_request.error_message:
                    log.error(signnow_request.error_message)
                else:
                    raise HTTPRedirect(download_link)
            raise HTTPRedirect(return_to + "?id={}&message={}", id,
                               "We don't have a record of this document being signed.")
        raise HTTPRedirect(return_to + "?id={}&message={}", id, "We don't have a record of a document for this group.")

    def register_group_member(self, session, group_id, message='', **params):
        group = session.group(group_id, ignore_csrf=True)
        if params.get('id') in [None, '', 'None']:
            attendee = group.unassigned[0] if group.unassigned else None
        else:
            attendee = session.attendee(params.get('id'), ignore_csrf=True)

        if not group.unassigned:
            redirect_link = '..landing/index'
            if c.ATTENDEE_ACCOUNTS_ENABLED and session.current_attendee_account():
                redirect_link = '../preregistration/homepage'

            redirect_link += '?message={}'

            raise HTTPRedirect(
                redirect_link,
                'No more unassigned badges exist in this group')
        elif attendee.first_name:
            # Someone claimed this badge while we had the form open
            # Grab the next one instead
            attendee.id = group.unassigned[0].id
            if cherrypy.request.method != 'POST':
                attrs_to_preserve_from_unassigned_group_member = [
                    'id',
                    'group_id',
                    'badge_type',
                    'badge_num',
                    'badge_cost',
                    'staffing',
                    'ribbon',
                    'paid',
                    'overridden_price'
                    ]

                attr_attendee = group.unassigned[0]
                for attr in attrs_to_preserve_from_unassigned_group_member:
                    setattr(attendee, attr, getattr(attr_attendee, attr))

            if group.unassigned[0].staffing:
                params['staffing'] = True

        receipt = session.get_receipt_by_model(attendee)
        form_list = ['BadgeFlags', 'PersonalInfo', 'BadgeExtras', 'OtherInfo', 'Consents']
        forms = load_forms(params, attendee, form_list)

        for form in forms.values():
            form.populate_obj(attendee)

        if cherrypy.request.method == 'POST':
            # TODO: I don't think this works, but it probably should just be removed
            if attendee and receipt:
                receipt_items = ReceiptManager.auto_update_receipt(attendee, receipt, params.copy())
                session.add_all(receipt_items)

            if attendee.placeholder:
                raise HTTPRedirect('group_members?id={}&message={}', group.id,
                                   f"Thanks! We'll email {attendee.full_name} to finish filling out their badge!")

            # Free group badges are considered 'registered' when they are actually claimed.
            if group.cost == 0:
                attendee.registered = localized_now()

            if c.ATTENDEE_ACCOUNTS_ENABLED and session.current_attendee_account():
                session.add_attendee_to_account(attendee, session.current_attendee_account())

            if not receipt:
                new_receipt = session.get_receipt_by_model(attendee, create_if_none="DEFAULT")
                if new_receipt.current_amount_owed and not new_receipt.pending_total:
                    raise HTTPRedirect('new_badge_payment?id=' + attendee.id + '&return_to=confirm')
            raise HTTPRedirect('badge_updated?id={}&message={}', attendee.id, 'Badge registered successfully')

        return {
            'logged_in_account': session.current_attendee_account(),
            'message':  message,
            'group': group,
            'attendee': attendee,
            'forms': forms,
            'locked_fields': [item for sublist in
                              [form.get_non_admin_locked_fields(attendee) for form in forms.values()
                               ] for item in sublist]
        }

    @ajax
    @credit_card
    def process_group_payment(self, session, id):
        group = session.group(id)
        receipt = session.get_receipt_by_model(group, create_if_none="DEFAULT")
        charge_desc = "{}: {}".format(group.name, receipt.charge_description_list)
        charge = TransactionRequest(receipt, group.email, charge_desc)

        message = charge.prepare_payment()
        if message:
            return {'error': message}

        session.add_all(charge.get_receipt_items_to_add())
        session.commit()

        return {'stripe_intent': charge.intent,
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
    def add_group_members(self, session, id, count, estimated_cost):
        errors = check_if_can_reg()
        if errors:
            return errors
        group = session.group(id)
        count = int(count)
        if int(estimated_cost) != count * group.new_badge_cost:
            raise HTTPRedirect(
                'group_members?id={}&message={}',
                group.id,
                'Our {} price has gone up since you tried to add badges; please try again.'.format(
                    "dealer badge" if group.is_dealer else "preregistration"
                ))

        if count < group.min_badges_addable and not group.is_in_grace_period:
            raise HTTPRedirect(
                'group_members?id={}&message={}',
                group.id,
                'You cannot add fewer than {} badges to this group.'.format(group.min_badges_addable))
        
        if group.is_dealer and count > group.dealer_badges_remaining:
            raise HTTPRedirect(
                'group_members?id={}&message={}',
                group.id,
                'You cannot add more than {} badges'.format(group.dealer_badges_remaining))
            
        receipt = session.get_receipt_by_model(group)
        if receipt:
            receipt_items = ReceiptManager.auto_update_receipt(group, receipt,
                                                               {'badges': count + group.badges,
                                                                'auto_recalc': group.auto_recalc})
            session.add_all(receipt_items)
        
        session.assign_badges(group, group.badges + count)
        session.commit()
        if group.auto_recalc:
            group.cost = group.calc_default_cost()
            session.add(group)

        if group.is_dealer and not receipt:
            raise HTTPRedirect(
                'group_members?id={}&message={}',
                group.id,
                f'{count} {c.DEALER_HELPER_TERM}s added!')
        else:
            raise HTTPRedirect('group_payment?id={}&count={}&message={}', group.id, count,
                               f"{count} badges have been added to your group! Please pay for them below.")
    
    @id_required(Group)
    @requires_account(Group)
    def group_payment(self, session, id, count=0, message=''):
        group = session.group(id)
        return {
            'count': count,
            'group': group,
            'receipt': session.get_receipt_by_model(group, create_if_none="DEFAULT"),
            'message': message,
        }

    def cancel_dealer(self, session, id):
        from uber.site_sections.dealer_admin import decline_and_convert_dealer_group
        group = session.group(id)
        has_assistants = group.badges_purchased - len(group.floating) > 1
        decline_and_convert_dealer_group(session,
                                         group,
                                         c.CANCELLED,
                                         f'Converted badge from {c.DEALER_REG_TERM} "{group.name}"\
                                         cancelling their application.',
                                         email_leader=False)

        message = "Dealer application cancelled.{} You may purchase your own badge using the form below.".format(
                    " Assistants have been emailed a link to purchase their badges." if has_assistants else "")

        raise HTTPRedirect('../preregistration/new_badge_payment?id={}&message={}&return_to=confirm',
                           group.leader.id, message)

    def purchase_dealer_badge(self, session, id):
        from uber.site_sections.dealer_admin import convert_dealer_badge
        from uber.custom_tags import datetime_local_filter
        attendee = session.attendee(id)
        convert_dealer_badge(session, attendee, f"Self-purchased dealer badge {datetime_local_filter(datetime.now())}.")
        session.add(attendee)
        session.commit()

        raise HTTPRedirect(f'new_badge_payment?id={attendee.id}&return_to=confirm')

    def dealer_signed_document(self, session, id):
        message = 'Thanks for signing!'
        group = session.group(id)
        if group.amount_unpaid:
            message += ' Please pay your application fee below.'
        raise HTTPRedirect(f'group_members?id={id}&message={message}')

    @id_required(Attendee)
    @requires_account(Attendee)
    @log_pageview
    def transfer_badge(self, session, message='', **params):
        old = session.attendee(params['id'])

        if not old.is_transferable:
            raise HTTPRedirect('../landing/index?message={}', 'This badge is not transferable.')
        if not old.is_valid:
            raise HTTPRedirect('../landing/index?message={}',
                               'This badge is no longer valid. It may have already been transferred.')

        old_attendee_dict = old.to_dict()
        del old_attendee_dict['id']

        attendee = Attendee(**old_attendee_dict)
        receipt = session.get_receipt_by_model(old)
        for attr in c.UNTRANSFERABLE_ATTRS:
            setattr(attendee, attr, getattr(Attendee(), attr))

        form_list = ['PersonalInfo', 'OtherInfo', 'StaffingInfo', 'Consents']
        forms = load_forms(params, attendee, form_list)

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                if hasattr(form, 'same_legal_name') and params.get('same_legal_name'):
                    form['legal_name'].data = ''
                form.populate_obj(attendee)

            if (old.first_name == attendee.first_name and old.last_name == attendee.last_name) \
                    and (not old.legal_name or old.legal_name == attendee.legal_name):
                message = 'You cannot transfer your badge to yourself.'

            if attendee.banned and not params.get('ban_bypass', None):
                return {
                    'forms': forms,
                    'old': old,
                    'attendee': attendee,
                    'message':  message,
                    'receipt': receipt,
                    'ban_bypass': True,
                }
            
            if not params.get('duplicate_bypass', None):
                duplicate = session.attendees_with_badges().filter_by(first_name=attendee.first_name,
                                                                      last_name=attendee.last_name,
                                                                      email=attendee.email).first()
                if duplicate:
                    return {
                        'forms': forms,
                        'old': old,
                        'attendee': attendee,
                        'duplicate': duplicate,
                        'message':  message,
                        'receipt': receipt,
                        'ban_bypass': params.get('ban_bypass', None),
                        'duplicate_bypass': True,
                    }

            if not message:
                old.badge_status = c.INVALID_STATUS
                old.append_admin_note(f"Automatic transfer to attendee {attendee.id}")
                attendee.badge_status = c.NEW_STATUS
                attendee.admin_notes = f"Automatic transfer from attendee {old.id}"

                subject = c.EVENT_NAME + ' Registration Transferred'
                new_body = render('emails/reg_workflow/badge_transfer.txt',
                                  {'new': attendee, 'old': old, 'include_link': True}, encoding=None)
                old_body = render('emails/reg_workflow/badge_transfer.txt',
                                  {'new': attendee, 'old': old, 'include_link': False}, encoding=None)

                try:
                    send_email.delay(
                        c.REGDESK_EMAIL,
                        [attendee.email_to_address, c.REGDESK_EMAIL],
                        subject,
                        new_body,
                        model=attendee.to_dict('id'))
                    send_email.delay(
                        c.REGDESK_EMAIL,
                        [old.email_to_address],
                        subject,
                        old_body,
                        model=old.to_dict('id'))
                except Exception:
                    log.error('Unable to send badge change email', exc_info=True)

                session.add(attendee)
                session.commit()
                if receipt:
                    session.add(receipt)
                    receipt.owner_id = attendee.id
                    amount_unpaid = receipt.current_amount_owed
                    session.commit()
                else:
                    amount_unpaid = attendee.amount_unpaid
                session.refresh_receipt_and_model(attendee)
                if amount_unpaid:
                    raise HTTPRedirect('new_badge_payment?id={}&return_to=confirm', attendee.id)
                else:
                    raise HTTPRedirect(
                        'badge_updated?id={}&message={}', attendee.id, 'Your registration has been transferred')

        return {
            'forms': forms,
            'old': old,
            'attendee': attendee,
            'message':  message,
            'receipt': receipt,
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
                # TODO: Add a receipt item manually for this, if we ever want to use this page again
                # Use attendee.calculate_shipping_fee_cost()
                session.add(attendee)
                session.commit()

                if attendee.amount_unpaid:
                    raise HTTPRedirect('new_badge_payment?id={}&return_to=confirm', attendee.id)
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

    @csrf_protected
    @requires_account(Attendee)
    def abandon_badge(self, session, id):
        from uber.custom_tags import format_currency
        attendee = session.attendee(id)
        page_redirect = ''
        if attendee.amount_paid and not attendee.is_group_leader:
            failure_message = "Something went wrong with your refund. Please contact us at {}."\
                .format(email_only(c.REGDESK_EMAIL))
            new_status = c.REFUNDED_STATUS
            page_redirect = 'repurchase'
        else:
            success_message = "Sorry you can't make it! We hope to see you next year!"
            new_status = c.INVALID_STATUS
            page_redirect = '../landing/index'
            if attendee.is_group_leader:
                failure_message = "You cannot abandon your badge because you are the leader of a group."
            else:
                failure_message = "You cannot abandon your badge for some reason. Please contact us at {}."\
                    .format(email_only(c.REGDESK_EMAIL))
        page_redirect = 'homepage' if c.ATTENDEE_ACCOUNTS_ENABLED else page_redirect

        if (not attendee.amount_paid and attendee.cannot_abandon_badge_reason)\
                or (attendee.amount_paid and attendee.cannot_self_service_refund_reason):
            raise HTTPRedirect('confirm?id={}&message={}', id, failure_message)

        if attendee.amount_paid:
            receipt = session.get_receipt_by_model(attendee)
            total_refunded = 0
            for txn in receipt.receipt_txns:
                refund = TransactionRequest(receipt, amount=txn.amount_left)
                error = refund.refund_or_skip(txn)
                if error:
                    raise HTTPRedirect('confirm?id={}&message={}', id, error)
                session.add_all(refund.get_receipt_items_to_add())
                total_refunded += refund.amount

            receipt.closed = datetime.now()
            session.add(receipt)

            success_message = "Your refund of {} should appear on your credit card in a few days."\
                .format(format_currency(total_refunded / 100))
            if attendee.paid == c.HAS_PAID:
                attendee.paid = c.REFUNDED

        # if attendee is part of a group, we must delete attendee and remove them from the group
        if attendee.group and attendee.group.is_valid:
            session.assign_badges(
                attendee.group,
                attendee.group.badges + 1,
                new_badge_type=attendee.badge_type,
                new_ribbon_type=attendee.ribbon,
                registered=attendee.registered,
                paid=attendee.paid)

            session.delete_from_group(attendee, attendee.group)
            raise HTTPRedirect('{}?id={}&message={}', page_redirect, attendee.id, success_message)
        # otherwise, we will mark attendee as invalid and remove them from shifts if necessary
        else:
            attendee.badge_status = new_status
            for shift in attendee.shifts:
                session.delete(shift)
            raise HTTPRedirect('{}?id={}&message={}',
                               page_redirect,
                               attendee.id, success_message)

    def badge_updated(self, session, id, message=''):
        return {
            'attendee': session.attendee(id),
            'message': message,
            'homepage_account': session.current_attendee_account(),
            }

    @ajax
    def validate_account_email(self, account_email, **params):
        error = valid_email(account_email)
        if error:
            return {'success': False, 'message': error}
        if c.SSO_EMAIL_DOMAINS:
            local, domain = normalize_email(account_email, split_address=True)
            if domain in c.SSO_EMAIL_DOMAINS:
                return {'success': False, 'sso_email': True}
        return {'success': True}

    @ajax
    def login(self, session, **params):
        email = params.get('account_email')  # This email has already been validated
        password = params.get('account_password')
        account = session.query(AttendeeAccount).filter(
            AttendeeAccount.normalized_email == normalize_email_legacy(email)).first()
        if account and not account.hashed:
            return {'success': False,
                    'message': "We had an issue logging you into your account. Please contact an administrator."}
        elif not account or not bcrypt.hashpw(password.encode('utf-8'),
                                              account.hashed.encode('utf-8')) == account.hashed.encode('utf-8'):
            return {'success': False, 'message': "Incorrect email/password combination."}

        cherrypy.session['attendee_account_id'] = account.id
        return {'success': True}

    @ajax
    def create_account(self, session, **params):
        email = params.get('account_email')  # This email has already been validated
        account = session.query(AttendeeAccount).filter_by(normalized_email=normalize_email_legacy(email)).first()
        if account:
            return {'success': False,
                    'message': "You already have an account. Please use the 'forgot your password' link. \
                    Keep in mind your account may be from a prior year."}
        password = params.get('new_password')
        confirm_password = params.get('confirm_password')
        message = check_account(session, email, password, confirm_password)
        if message:
            return {'success': False, 'message': message}

        new_account = session.create_attendee_account(email, password=password)
        session.commit()

        cherrypy.session['attendee_account_id'] = new_account.id
        return {'success': True}

    @requires_account()
    def homepage(self, session, message='', **params):
        account = session.query(AttendeeAccount).get(cherrypy.session.get('attendee_account_id'))

        attendees_who_owe_money = {}
        for attendee in account.attendees:
            receipt = session.get_receipt_by_model(attendee)
            if receipt and receipt.current_amount_owed and attendee.is_valid:
                attendees_who_owe_money[attendee.full_name] = receipt.current_amount_owed

        account_attendee = None
        account_attendees = session.valid_attendees().filter(~Attendee.badge_status.in_([c.REFUNDED_STATUS,
                                                                                         c.NOT_ATTENDING]))\
            .filter(Attendee.normalized_email == normalize_email_legacy(account.email))
        if account_attendees.count() == 1:
            account_attendee = account_attendees.first()
            if account_attendee not in account.attendees:
                account_attendee = None

        if not account:
            raise HTTPRedirect('../landing/index')

        return {
            'message': message,
            'homepage_account': account,
            'account_attendee': account_attendee,
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
        if session.current_attendee_account() and \
                normalize_email_legacy(attendee.email) == session.current_attendee_account().normalized_email:
            message = "You cannot grant an account to someone with the same email address as your account."
        if not message:
            set_up_new_account(session, attendee)

        raise HTTPRedirect('homepage?message={}', message or
                           'An email has been sent to {} to set up their account.'.format(attendee.email))

    def logout(self, return_to=''):
        cherrypy.session.pop('attendee_account_id')
        for key in PreregCart.session_keys:
            cherrypy.session.pop(key)
        return_to = return_to or '/landing/index'
        raise HTTPRedirect('..{}?message={}', return_to, 'You have been logged out.')

    @id_required(Attendee)
    @requires_account(Attendee)
    @log_pageview
    def confirm(self, session, message='', return_to='confirm', undoing_extra='', **params):
        if params.get('id') not in [None, '', 'None']:
            attendee = session.attendee(params.get('id'))
            receipt = session.get_receipt_by_model(attendee)
            if cherrypy.request.method == 'POST':
                receipt_items = ReceiptManager.auto_update_receipt(attendee, receipt, params.copy())
                session.add_all(receipt_items)
        else:
            receipt = None

        if attendee.badge_status == c.REFUNDED_STATUS:
            raise HTTPRedirect('repurchase?id={}', attendee.id)

        placeholder = attendee.placeholder

        form_list = ['PersonalInfo', 'BadgeExtras', 'BadgeFlags', 'OtherInfo', 'StaffingInfo', 'Consents']
        forms = load_forms(params, attendee, form_list)
        if not attendee.is_new and not attendee.placeholder:
            forms['consents'].pii_consent.data = True

        for form in forms.values():
            if hasattr(form, 'same_legal_name') and params.get('same_legal_name'):
                form['legal_name'].data = ''
            form.populate_obj(attendee)

        if cherrypy.request.method == 'POST' and not message:
            session.add(attendee)
            session.commit()

            if placeholder:
                attendee.confirmed = localized_now()
                message = 'Your registration has been confirmed'
            else:
                message = 'Your information has been updated'

            page = ('badge_updated?id=' + attendee.id + '&') if return_to == 'confirm' else (return_to + '?')
            if not receipt:
                receipt = session.get_receipt_by_model(attendee, create_if_none="DEFAULT")
            if not receipt.current_amount_owed or receipt.pending_total:
                raise HTTPRedirect(page + 'message=' + message)
            elif receipt.current_amount_owed and not receipt.pending_total:
                # TODO: could use some cleanup, needed because of how we handle the placeholder attr
                raise HTTPRedirect('new_badge_payment?id={}&message={}&return_to={}', attendee.id, message, return_to)

        session.refresh_receipt_and_model(attendee)
        session.commit()

        attendee.placeholder = placeholder
        if not message and attendee.placeholder:
            message = 'You are not yet registered!  You must fill out this form to complete your registration.'
        elif not message and not c.ATTENDEE_ACCOUNTS_ENABLED and attendee.badge_status == c.COMPLETED_STATUS:
            message = 'You are already registered but you may update your information with this form.'

        if receipt and receipt.current_amount_owed and not receipt.pending_total and not attendee.placeholder:
            raise HTTPRedirect('new_badge_payment?id={}&message={}&return_to={}', attendee.id, message, return_to)

        return {
            'undoing_extra': undoing_extra,
            'return_to':     return_to,
            'attendee':      attendee,
            'homepage_account': session.get_attendee_account_by_attendee(attendee),
            'message':       message,
            'attractions':   session.query(Attraction).filter_by(is_public=True).all(),
            'badge_cost':    attendee.badge_cost if attendee.paid != c.PAID_BY_GROUP else 0,
            'receipt':       session.get_receipt_by_model(attendee) if attendee.is_valid else None,
            'incomplete_txn':  receipt.get_last_incomplete_txn() if receipt else None,
            'forms': forms,
            'locked_fields': [item for sublist in
                              [form.get_non_admin_locked_fields(attendee) for form in forms.values()
                               ] for item in sublist]
        }

    @ajax
    def validate_dealer(self, session, form_list=[], is_prereg=False, **params):
        id = params.get('id', params.get('edit_id'))
        if id in [None, '', 'None']:
            group = Group(tables=1)
        else:
            try:
                group = session.group(id)
            except NoResultFound:
                if is_prereg:
                    group = self._get_unsaved(
                        id,
                        PreregCart.pending_dealers,
                        if_not_found=HTTPRedirect('dealer_registration?message={}',
                                                  'That application expired or has already been finalized.'))
                else:
                    return {"error": {'': ["We could not find the group you're trying to update."]}}

        if not form_list:
            form_list = ['ContactInfo', 'TableInfo']
        elif isinstance(form_list, str):
            form_list = [form_list]
        forms = load_forms(params, group, form_list, get_optional=False)

        all_errors = validate_model(forms, group, Group(**group.to_dict()))
        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    @ajax
    def validate_attendee(self, session, form_list=[], is_prereg=False, **params):
        id = params.get('id', params.get('edit_id', params.get('attendee_id')))
        if id in [None, '', 'None']:
            attendee = Attendee()
        else:
            try:
                attendee = session.attendee(id)
            except NoResultFound:
                if is_prereg:
                    attendee = self._get_unsaved(
                        id,
                        if_not_found=HTTPRedirect('form?message={}',
                                                  'That preregistration expired or has already been finalized.'))
                else:
                    return {"error": {'': ["We could not find the badge you're trying to update."]}}

        if not form_list:
            form_list = ['PersonalInfo', 'BadgeExtras', 'BadgeFlags', 'OtherInfo', 'Consents']
        elif isinstance(form_list, str):
            form_list = [form_list]

        forms = load_forms(params, attendee, form_list, get_optional=False)

        all_errors = validate_model(forms, attendee, Attendee(**attendee.to_dict()))
        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    @ajax
    def get_receipt_preview(self, session, id, **params):
        try:
            attendee = session.attendee(id)
        except Exception as ex:
            return {'error': "Can't get attendee: " + str(ex)}

        if not params.get('col_name'):
            return {'error': "Can't calculate cost change without the column name"}

        preview_attendee = Attendee(**attendee.to_dict())
        new_val = params.get('val')

        column = preview_attendee.__table__.columns.get(params['col_name'])
        if column is not None:
            new_val = preview_attendee.coerce_column_data(column, new_val)
        setattr(preview_attendee, params['col_name'], new_val)
        
        changes_list = ReceiptManager.process_receipt_change(attendee, params['col_name'],
                                                                    new_model=preview_attendee)
        only_change = changes_list[0] if changes_list else ("", 0, 0)
        desc, change, count = only_change
        return {'desc': desc, 'change': change}  # We don't need the count for this preview

    @ajax
    def purchase_upgrades(self, session, id, **params):
        message = ''
        attendee = session.attendee(id)
        try:
            receipt = session.model_receipt(params.get('receipt_id'))
        except Exception:
            return {'error': "Cannot find your receipt, please contact registration"}

        if receipt.open_receipt_items and receipt.current_amount_owed:
            return {'error': "You already have an outstanding balance, please refresh the page to pay \
                    for your current items or contact {}".format(email_only(c.REGDESK_EMAIL))}

        receipt_items = ReceiptManager.auto_update_receipt(attendee,
                                                           session.get_receipt_by_model(attendee), params.copy())
        if not receipt_items:
            return {'error': "There was an issue with adding your upgrade. Please contact the system administrator."}
        session.add_all(receipt_items)

        # Get around locked field restrictions by applying the parameters directly
        attendee.apply(params, restricted=False, ignore_csrf=True)

        forms = load_forms(params, attendee, ['BadgeExtras'])

        all_errors = validate_model(forms, attendee)
        if all_errors:
            # TODO: Make this work with the fields on the upgrade modal instead of flattening it all
            message = ' '.join([item for sublist in all_errors.values() for item in sublist])

        if message:
            session.rollback()
            return {'error': message}

        session.commit()

        return {'success': True}

    @ajax
    @credit_card
    @requires_account(Attendee)
    def finish_pending_payment(self, session, id, txn_id, **params):
        attendee = session.attendee(id)
        txn = session.receipt_transaction(txn_id)

        error = txn.check_stripe_id()
        if error:
            return {'error': "Something went wrong with this payment. Please refresh the page and try again."}

        if c.AUTHORIZENET_LOGIN_ID:
            # Authorize.net doesn't actually have a concept of pending transactions,
            # so there's no transaction to resume. Create a new one.
            new_txn_requent = TransactionRequest(txn.receipt, attendee.email, txn.desc, txn.amount)
            stripe_intent = new_txn_requent.stripe_or_mock_intent()
            txn.intent_id = stripe_intent.id
            session.commit()
        else:
            stripe_intent = txn.get_stripe_intent()

        if not stripe_intent:
            return {'error': "Something went wrong. Please contact us at {}.".format(email_only(c.REGDESK_EMAIL))}

        if not c.AUTHORIZENET_LOGIN_ID and stripe_intent.status == "succeeded":
            return {'error': "This payment has already been finalized!"}

        return {'stripe_intent': stripe_intent,
                'success_url': 'confirm?id={}&message={}'.format(
                    attendee.id,
                    'Your payment has been accepted!'),
                'cancel_url': 'cancel_payment'}

    @ajax
    @credit_card
    @requires_account(Group)
    def finish_pending_group_payment(self, session, id, txn_id, **params):
        group = session.group(id)
        txn = session.receipt_transaction(txn_id)

        error = txn.check_stripe_id()
        if error:
            return {'error': "Something went wrong with this payment. Please refresh the page and try again."}

        if c.AUTHORIZENET_LOGIN_ID:
            # Authorize.net doesn't actually have a concept of pending transactions,
            # so there's no transaction to resume. Create a new one.
            receipt_email = ""
            if group.email:
                receipt_email = group.email
            elif group.leader:
                receipt_email = group.leader.email
            elif group.attendees:
                receipt_email = group.attendees[0].email
            new_txn_requent = TransactionRequest(txn.receipt, receipt_email, txn.desc, txn.amount)
            stripe_intent = new_txn_requent.stripe_or_mock_intent()
            txn.intent_id = stripe_intent.id
            session.commit()
        else:
            stripe_intent = txn.get_stripe_intent()

        if not stripe_intent:
            return {'error': "Something went wrong. Please contact us at {}.".format(c.REGDESK_EMAIL)}

        if not c.AUTHORIZENET_LOGIN_ID and stripe_intent.status == "succeeded":
            return {'error': "This payment has already been finalized!"}

        return {'stripe_intent': stripe_intent,
                'success_url': 'group_members?id={}&message={}'.format(
                    group.id,
                    'Your payment has been accepted!'),
                'cancel_url': 'cancel_payment'}

    @ajax
    @credit_card
    @requires_account(Attendee)
    def process_attendee_payment(self, session, id, receipt_id, message='', **params):
        receipt = session.model_receipt(receipt_id)
        attendee = session.attendee(id)
        charge_desc = "{}: {}".format(attendee.full_name, receipt.charge_description_list)
        charge = TransactionRequest(receipt, attendee.email, charge_desc)

        message = charge.prepare_payment()
        if message:
            return {'error': message}

        session.add_all(charge.get_receipt_items_to_add())
        session.commit()

        return_to = params.get('return_to')

        success_url_base = 'confirm?id=' + id + '&' if not return_to or return_to == 'confirm' else return_to + (
            '?' if '?' not in return_to else '&')

        return {'stripe_intent': charge.intent,
                'success_url': '{}message={}'.format(success_url_base, 'Payment accepted!'),
                'cancel_url': params.get('cancel_url', 'cancel_payment')}

    @id_required(Attendee)
    @requires_account(Attendee)
    def new_badge_payment(self, session, id, return_to, message=''):
        attendee = session.attendee(id)
        return {
            'attendee': attendee,
            'receipt': session.get_receipt_by_model(attendee, create_if_none="DEFAULT"),
            'return_to': return_to,
            'message': message,
        }

    @id_required(Attendee)
    @requires_account(Attendee)
    @csrf_protected
    def reset_receipt(self, session, id, return_to):
        attendee = session.attendee(id)
        message = attendee.undo_extras()

        if not message:
            receipt = session.get_receipt_by_model(attendee)
            receipt.closed = datetime.now()
            session.add(receipt)

            new_receipt = session.get_receipt_by_model(attendee, create_if_none="DEFAULT")
            page = ('badge_updated?id=' + attendee.id + '&') if return_to == 'confirm' else (return_to + '?')
            if new_receipt.current_amount_owed:
                raise HTTPRedirect('new_badge_payment?id=' + attendee.id + '&return_to=' + return_to)
            raise HTTPRedirect(page + 'message=Your registration has been confirmed')
        log.error(message)
        raise HTTPRedirect('new_badge_payment?id=' + attendee.id + '&return_to=' +
                           return_to + '&message=There was a problem resetting your receipt')

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

        receipt, receipt_items = ReceiptManager.create_new_receipt(attendee, create_model=True)
        session.add(receipt)
        session.add_all(receipt_items)

        session.commit()

        charge_desc = "{}: {}".format(attendee.full_name, receipt.charge_description_list)
        charge = TransactionRequest(receipt, attendee.email, charge_desc)

        message = charge.prepare_payment()
        if message:
            return {'error': message}

        session.add_all(charge.get_receipt_items_to_add())
        session.commit()

        return {'stripe_intent': charge.intent,
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
        elif not bcrypt.hashpw(password.encode('utf-8'),
                               account.hashed.encode('utf-8')) == account.hashed.encode('utf-8'):
            message = 'Incorrect password'

        if not message:
            if params.get('new_password') == '':
                new_password = None
                confirm_password = None
            else:
                new_password = params.get('new_password')
                confirm_password = params.get('confirm_password')
            message = check_account(session, params.get('account_email'), new_password, confirm_password,
                                    False, new_password, account.email)

        if not message:
            if new_password:
                account.hashed = create_new_hash(new_password)
            account.email = params.get('account_email')
            message = 'Account information updated successfully.'
        raise HTTPRedirect('homepage?message={}', message)

    def reset_password(self, session, **params):
        if 'account_email' in params:
            account_email = params['account_email']
            account = session.query(AttendeeAccount).filter_by(
                normalized_email=normalize_email_legacy(account_email)).first()
            if 'admin_url' in params:
                success_url = "../{}message=Password reset email sent.".format(params['admin_url'])
                sso_url = "../{}message=SSO accounts do not have passwords.".format(params['admin_url'])
            else:
                success_url = "../landing/index?message=Check your email for a password reset link."
                sso_url = "../landing/index?message=Please log in via the staff login link!"
            if not account:
                # Avoid letting attendees de facto search for other attendees by email
                if c.SSO_EMAIL_DOMAINS:
                    local, domain = normalize_email(account_email, split_address=True)
                    if domain in c.SSO_EMAIL_DOMAINS:
                        raise HTTPRedirect(sso_url)
                raise HTTPRedirect(success_url)

            if account.password_reset:
                session.delete(account.password_reset)
                session.commit()

            if account.is_sso_account:
                raise HTTPRedirect(sso_url)

            token = genpasswd(short=True)
            session.add(PasswordReset(attendee_account=account, hashed=create_new_hash(token)))

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
            account = session.query(AttendeeAccount).filter_by(
                normalized_email=normalize_email_legacy(account_email)).first()
        if not account or not account.password_reset:
            message = 'Invalid link. This link may have already been used or replaced.'
        elif account.password_reset.is_expired:
            message = 'This link has expired. Please use the "forgot password" option to get a new link.'
        elif bcrypt.hashpw(token.encode('utf-8'),
                           account.password_reset.hashed.encode('utf-8')) != account.password_reset.hashed.encode('utf-8'):
            message = 'Invalid token. Did you copy the URL correctly?'

        if message:
            raise HTTPRedirect('../landing/index?message={}', message)

        if cherrypy.request.method == 'POST':
            account_password = params.get('account_password')
            message = check_account(session, account_email, account_password,
                                    params.get('confirm_password'), False, True, account.email)

            if not message:
                account.email = normalize_email(account_email)
                account.hashed = create_new_hash(account_password)
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
