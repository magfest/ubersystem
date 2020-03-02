import json
import math
import re
from datetime import datetime, timedelta
from functools import wraps
from io import BytesIO

import cherrypy
import treepoem
from pytz import UTC
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import joinedload

from uber.config import c
from uber.decorators import ajax, all_renderable, attendee_view, check_for_encrypted_badge_num, check_if_can_reg, credit_card, \
    csrf_protected, department_id_adapter, log_pageview, render, site_mappable, public
from uber.errors import HTTPRedirect
from uber.models import Attendee, Department, Email, Group, Job, PageViewTracking, PromoCode, PromoCodeGroup, Sale, \
    Session, Shift, Tracking, WatchList
from uber.utils import add_opt, check, check_csrf, check_pii_consent, Charge, get_page, hour_day_format, \
    localized_now, Order


def pre_checkin_check(attendee, group):
    if c.NUMBERED_BADGES:
        min_badge, max_badge = c.BADGE_RANGES[attendee.badge_type]
        if not attendee.badge_num:
            return 'Badge number is required'
        elif not (min_badge <= int(attendee.badge_num) <= max_badge):
            return ('{a.full_name} has a {a.badge_type_label} badge, but '
                    '{a.badge_num} is not a valid number for '
                    '{a.badge_type_label} badges').format(a=attendee)

    if c.COLLECT_EXACT_BIRTHDATE:
        if not attendee.birthdate:
            return 'You may not check someone in without a valid date of birth.'
    elif not attendee.age_group or attendee.age_group == c.AGE_UNKNOWN:
        return 'You may not check someone in without confirming their age.'

    if attendee.checked_in:
        return attendee.full_name + ' was already checked in!'

    if group and attendee.paid == c.PAID_BY_GROUP and group.amount_unpaid:
        return 'This attendee\'s group has an outstanding balance of ${}'.format('%0.2f' % group.amount_unpaid)

    if attendee.paid == c.NOT_PAID:
        return 'You cannot check in an attendee that has not paid.'

    return check(attendee)


def check_atd(func):
    @wraps(func)
    def checking_at_the_door(self, *args, **kwargs):
        if c.AT_THE_CON or c.DEV_BOX:
            return func(self, *args, **kwargs)
        else:
            raise HTTPRedirect('index')
    return checking_at_the_door


@all_renderable()
class Root:
    def index(self, session, message='', page='0', search_text='', uploaded_id='', order='last_first', invalid=''):
        # DEVELOPMENT ONLY: it's an extremely convenient shortcut to show the first page
        # of search results when doing testing. it's too slow in production to do this by
        # default due to the possibility of large amounts of reg stations accessing this
        # page at once. viewing the first page is also rarely useful in production when
        # there are thousands of attendees.
        if c.DEV_BOX and not int(page):
            page = 1

        filter = Attendee.badge_status.in_([c.NEW_STATUS, c.COMPLETED_STATUS, c.WATCHED_STATUS]) if not invalid else None
        attendees = session.query(Attendee) if invalid else session.query(Attendee).filter(filter)
        total_count = attendees.count()
        count = 0
        search_text = search_text.strip()
        if search_text:
            attendees = session.search(search_text) if invalid else session.search(search_text, filter)
            count = attendees.count()
        if not count:
            attendees = attendees.options(joinedload(Attendee.group))
            count = total_count

        attendees = attendees.order(order)

        page = int(page)
        if search_text:
            page = page or 1
            if search_text and count == total_count:
                message = 'No matches found'
            elif search_text and count == 1 and (not c.AT_THE_CON or search_text.isdigit()):
                raise HTTPRedirect(
                    'form?id={}&message={}', attendees.one().id, 'This attendee was the only search result')

        pages = range(1, int(math.ceil(count / 100)) + 1)
        attendees = attendees[-100 + 100*page: 100*page] if page else []

        return {
            'message':        message if isinstance(message, str) else message[-1],
            'page':           page,
            'pages':          pages,
            'invalid':        invalid,
            'search_text':    search_text,
            'search_results': bool(search_text),
            'attendees':      attendees,
            'order':          Order(order),
            'attendee_count': total_count,
            'checkin_count':  session.query(Attendee).filter(Attendee.checked_in != None).count(),
            'attendee':       session.attendee(uploaded_id, allow_invalid=True) if uploaded_id else None,
            'reg_station':    cherrypy.session.get('reg_station', ''),
        }  # noqa: E711

    @log_pageview
    def form(self, session, message='', return_to='', **params):
        attendee = session.attendee(
            params, checkgroups=Attendee.all_checkgroups, bools=Attendee.all_bools, allow_invalid=True)

        if 'first_name' in params:
            message = ''
            
            attendee.group_id = params['group_opt'] or None
            if params.get('no_badge_num') or not attendee.badge_num:
                if params.get('save') == 'save_check_in' and attendee.badge_type not in c.PREASSIGNED_BADGE_TYPES:
                    message = "Please enter a badge number to check this attendee in"
                else:
                    attendee.badge_num = None

            if 'no_override' in params:
                attendee.overridden_price = None

            if c.BADGE_PROMO_CODES_ENABLED and 'promo_code' in params:
                message = session.add_promo_code_to_attendee(attendee, params.get('promo_code'))

            if not message:
                message = check(attendee)

            if not message:
                # Free group badges are only considered 'registered' when they are actually claimed.
                if attendee.paid == c.PAID_BY_GROUP and attendee.group_id and attendee.group.cost == 0:
                    attendee.registered = localized_now()
                session.add(attendee)

                if attendee.is_new and \
                        session.attendees_with_badges().filter_by(first_name=attendee.first_name,
                                                                  last_name=attendee.last_name,
                                                                  email=attendee.email).count():
                    raise HTTPRedirect('duplicate?id={}&return_to={}', attendee.id, return_to or 'index')

                message = '{} has been saved'.format(attendee.full_name)
                stay_on_form = params.get('save') != 'save_return_to_search'
                if params.get('save') == 'save_check_in':
                    session.commit()
                    if attendee.is_not_ready_to_checkin:
                        message = "Attendee saved, but they cannot check in now. Reason: {}".format(
                            attendee.is_not_ready_to_checkin)
                        stay_on_form = True
                    elif attendee.amount_unpaid:
                        message = "Attendee saved, but they must pay ${} before they can check in.".format(
                            attendee.amount_unpaid)
                        stay_on_form = True
                    else:
                        attendee.checked_in = localized_now()
                        session.commit()
                        message = '{} saved and checked in as {}{}'.format(
                            attendee.full_name, attendee.badge, attendee.accoutrements)
                        stay_on_form = False
                        
                if stay_on_form:
                    raise HTTPRedirect('form?id={}&message={}&return_to={}', attendee.id, message, return_to)
                else:
                    if return_to:
                        raise HTTPRedirect(return_to + '&message={}', 'Attendee data saved')
                    else:
                        raise HTTPRedirect(
                            'index?uploaded_id={}&message={}&search_text={}',
                            attendee.id,
                            message,
                            '{} {}'.format(attendee.first_name, attendee.last_name) if c.AT_THE_CON else '')

        return {
            'message':    message,
            'attendee':   attendee,
            'return_to':  return_to,
            'no_badge_num': params.get('no_badge_num'),
            'group_opts': [(g.id, g.name) for g in session.query(Group).order_by(Group.name).all()],
            'unassigned': {
                group_id: unassigned
                for group_id, unassigned in session.query(Attendee.group_id, func.count('*')).filter(
                    Attendee.group_id != None, Attendee.first_name == '').group_by(Attendee.group_id).all()},
            'Charge': Charge if cherrypy.session.get('reg_station') else None,
        }  # noqa: E711

    def change_badge(self, session, id, message='', **params):
        attendee = session.attendee(id, allow_invalid=True)
        if 'badge_type' in params:
            from uber.badge_funcs import reset_badge_if_unchanged
            old_badge_type, old_badge_num = attendee.badge_type, attendee.badge_num
            attendee.badge_type = int(params['badge_type'])
            try:
                attendee.badge_num = int(params['badge_num'])
            except ValueError:
                attendee.badge_num = None

            message = check(attendee)

            if not message:
                message = reset_badge_if_unchanged(attendee, old_badge_type, old_badge_num) or "Badge updated."
                raise HTTPRedirect('form?id={}&message={}', attendee.id, message or '')

        return {
            'message':  message,
            'attendee': attendee
        }

    def promo_code_groups(self, session, message=''):
        groups = session.query(PromoCodeGroup).order_by(PromoCodeGroup.name).all()
        used_counts = {
            group_id: count for group_id, count in
                session.query(PromoCode.group_id, func.count(PromoCode.id))
                    .filter(Attendee.promo_code_id == PromoCode.id,
                            PromoCode.group_id == PromoCodeGroup.id)
                    .group_by(PromoCode.group_id)
        }
        total_costs = {
            group_id: total for group_id, total in
                session.query(PromoCode.group_id, func.sum(PromoCode.cost))
                        .group_by(PromoCode.group_id)
        }
        total_counts = {
            group_id: count for group_id, count in
                session.query(PromoCode.group_id, func.count('*'))
                        .group_by(PromoCode.group_id)
        }
        return {
            'groups': groups,
            'used_counts': used_counts,
            'total_costs': total_costs,
            'total_counts': total_counts,
            'message': message,
        }

    @log_pageview
    def promo_code_group_form(self, session, message='',
                              badges=0, cost_per_badge=0,
                              first_name='', last_name='', email='', **params):
        group = session.promo_code_group(params)
        badges_are_free = params.get('badges_are_free')
        buyer_id = params.get('buyer_id')
        attendee_attrs = session.query(Attendee.id, Attendee.last_first, Attendee.badge_type, Attendee.badge_num) \
            .filter(Attendee.first_name != '', Attendee.badge_status.in_([c.NEW_STATUS, c.COMPLETED_STATUS]))
        attendees = [
            (id, '{} - {}{}'.format(name.title(), c.BADGES[badge_type], ' #{}'.format(badge_num) if badge_num else ''))
            for id, name, badge_type, badge_num in attendee_attrs]

        if cherrypy.request.method == 'POST':
            group.apply(params)
            message = check(group)
            if not buyer_id and not message:
                message = "Please select a group buyer."

            if group.is_new and not message:
                if not badges or not int(badges):
                    message = "You cannot create a group with no badges."
                elif not cost_per_badge and not badges_are_free:
                    message = "Please enter a cost per badge, or confirm that this group is free."

            if not message and buyer_id == "None" and not (first_name and last_name and email):
                message = "To create a new buyer, please enter their first name, last name, and email address."

            if not message:
                if buyer_id == "None":
                    buyer = Attendee(first_name=first_name, last_name=last_name, email=email)
                    buyer.placeholder = True
                    session.add(buyer)
                    group.buyer = buyer

                if badges:
                    session.add_codes_to_pc_group(group, int(badges), 0 if badges_are_free else int(cost_per_badge))
                raise HTTPRedirect('promo_code_group_form?id={}&message={}', group.id, "Group saved")

        return {
            'group': group,
            'badges': badges,
            'cost_per_badge': cost_per_badge or c.GROUP_PRICE,
            'badges_are_free': badges_are_free,
            'buyer_id': buyer_id or (group.buyer.id if group.buyer else ''),
            'all_attendees': sorted(attendees, key=lambda tup: tup[1]),
            'message': message,
        }

    @public
    def qrcode_generator(self, data):
        """
        Takes a piece of data, adds the EVENT_QR_ID, and returns an Aztec barcode as an image stream.
        Args:
            data: A string to create a 2D barcode from.

        Returns: A PNG buffer. Use this function in an img tag's src='' to display an image.

        NOTE: this will be called directly by attendee's client browsers to display their 2D barcode.
        This will potentially be called on the order of 100,000 times per event and serve up a lot of data.
        Be sure that any modifications to this code are fast and don't unnecessarily increase CPU load.

        If you run into performance issues, consider using an external cache to cache the results of
        this function.  Or, offload image generation to a dedicated microservice that replicates this functionality.

        """
        checkin_barcode = treepoem.generate_barcode(
            barcode_type='azteccode',
            data=c.EVENT_QR_ID + str(data),
            options={},
        )
        buffer = BytesIO()
        checkin_barcode.save(buffer, "PNG")
        buffer.seek(0)
        png_file_output = cherrypy.lib.file_generator(buffer)

        # set response headers last so that exceptions are displayed properly to the client
        cherrypy.response.headers['Content-Type'] = "image/png"

        return png_file_output

    def history(self, session, id):
        attendee = session.attendee(id, allow_invalid=True)
        return {
            'attendee':  attendee,
            'emails':    session.query(Email)
                                .filter(or_(Email.to == attendee.email,
                                            and_(Email.model == 'Attendee', Email.fk_id == id)))
                                .order_by(Email.when).all(),
            'changes':   session.query(Tracking)
                                .filter(or_(Tracking.links.like('%attendee({})%'.format(id)),
                                            and_(Tracking.model == 'Attendee', Tracking.fk_id == id)))
                                .order_by(Tracking.when).all(),
            'pageviews': session.query(PageViewTracking).filter(PageViewTracking.what == "Attendee id={}".format(id))
        }

    def duplicate(self, session, id, return_to='index'):
        attendee = session.attendee(id)
        return {
            'attendee': attendee,
            'return_to': return_to
        }

    @cherrypy.expose(['delete_attendee'])
    def delete(self, session, id, return_to='index?', **params):
        attendee = session.attendee(id, allow_invalid=True)
        if attendee.group:
            if attendee.group.leader_id == attendee.id:
                message = 'You cannot delete the leader of a group; ' \
                    'you must make someone else the leader first, or just delete the entire group'
            elif attendee.is_unassigned:
                session.delete_from_group(attendee, attendee.group)
                message = 'Unassigned badge removed.'
            else:
                replacement_attendee = Attendee(**{attr: getattr(attendee, attr) for attr in [
                    'group', 'registered', 'badge_type', 'badge_num', 'paid', 'amount_paid_override', 'amount_extra'
                ]})
                if replacement_attendee.group and replacement_attendee.group.is_dealer:
                    replacement_attendee.ribbon = add_opt(replacement_attendee.ribbon_ints, c.DEALER_RIBBON)
                session.add(replacement_attendee)
                attendee._skip_badge_shift_on_delete = True
                session.delete_from_group(attendee, attendee.group)
                message = 'Attendee deleted, but this badge is still ' \
                    'available to be assigned to someone else in the same group'
        else:
            session.delete(attendee)
            message = 'Attendee deleted'
        
        q_or_a = '?' if '?' not in return_to else '&'
        raise HTTPRedirect(return_to + ('' if return_to[-1] == '?' else q_or_a) + 'message={}', message)

    def check_in_form(self, session, id):
        attendee = session.attendee(id)
        if attendee.paid == c.PAID_BY_GROUP and not attendee.group_id:
            valid_groups = session.query(Group).options(joinedload(Group.leader)).filter(
                Group.status != c.WAITLISTED,
                Group.id.in_(
                    session.query(Attendee.group_id)
                    .filter(Attendee.group_id != None, Attendee.first_name == '')
                    .distinct().subquery()
                )).order_by(Group.name)  # noqa: E711

            groups = [(
                group.id,
                (group.name if len(group.name) < 30 else '{}...'.format(group.name[:27], '...'))
                + (' ({})'.format(group.leader.full_name) if group.leader else ''))
                for group in valid_groups]
        else:
            groups = []

        return {
            'attendee': attendee,
            'groups': groups,
            'Charge': Charge,
        }

    @check_for_encrypted_badge_num
    @ajax
    def check_in(self, session, message='', group_id='', **params):
        bools = ['got_merch'] if c.MERCH_AT_CHECKIN else []
        attendee = session.attendee(params, allow_invalid=True, bools=bools)
        group = attendee.group or (session.group(group_id) if group_id else None)

        pre_badge = attendee.badge_num
        success, increment = False, False

        message = pre_checkin_check(attendee, group)
        if not message and group_id:
            message = session.match_to_group(attendee, group)

        if not message and attendee.paid == c.PAID_BY_GROUP and not attendee.group_id:
            message = 'You must select a group for this attendee.'

        if not message:
            message = ''
            success = True
            attendee.checked_in = localized_now()
            session.commit()
            increment = True
            message += '{} checked in as {}{}'.format(attendee.full_name, attendee.badge, attendee.accoutrements)

        return {
            'success':    success,
            'message':    message,
            'increment':  increment,
            'badge':      attendee.badge,
            'paid':       attendee.paid_label,
            'age_group':  attendee.age_group_conf['desc'],
            'pre_badge':  pre_badge,
            'checked_in': attendee.checked_in and hour_day_format(attendee.checked_in),
        }

    @csrf_protected
    def undo_checkin(self, session, id, pre_badge):
        attendee = session.attendee(id, allow_invalid=True)
        attendee.checked_in, attendee.badge_num = None, pre_badge
        session.add(attendee)
        session.commit()
        return 'Attendee successfully un-checked-in'

    def recent(self, session):
        return {'attendees': session.query(Attendee)
                                    .options(joinedload(Attendee.group))
                                    .order_by(Attendee.registered.desc())
                                    .limit(1000)}

    def lost_badge(self, session, id):
        a = session.attendee(id, allow_invalid=True)
        a.for_review += "Automated message: Badge reported lost on {}. Previous payment type: {}.".format(
            localized_now().strftime('%m/%d, %H:%M'), a.paid_label)
        a.paid = c.LOST_BADGE
        session.add(a)
        session.commit()
        raise HTTPRedirect('index?message={}', 'Badge has been recorded as lost.')

    @public
    @check_atd
    @check_if_can_reg
    def register(self, session, message='', error_message='', **params):
        params['id'] = 'None'
        attendee = session.attendee(params, restricted=True, ignore_csrf=True)
        error_message = check_pii_consent(params, attendee) or error_message
        if not error_message and 'first_name' in params:
            if not attendee.payment_method and (not c.BADGE_PRICE_WAIVED or c.BEFORE_BADGE_PRICE_WAIVED):
                error_message = 'Please select a payment type'
            elif attendee.payment_method == c.MANUAL and not re.match(c.EMAIL_RE, attendee.email):
                error_message = 'Email address is required to pay with a credit card at our registration desk'
            elif attendee.badge_type not in [badge for badge, desc in c.AT_THE_DOOR_BADGE_OPTS]:
                error_message = 'No hacking allowed!'
            else:
                error_message = check(attendee)

            if not error_message and c.BADGE_PROMO_CODES_ENABLED and 'promo_code' in params:
                error_message = session.add_promo_code_to_attendee(attendee, params.get('promo_code'))
            if not error_message:
                session.add(attendee)
                session.commit()
                if c.AFTER_BADGE_PRICE_WAIVED:
                    message = c.AT_DOOR_WAIVED_MSG
                    attendee.paid = c.NEED_NOT_PAY
                elif attendee.payment_method == c.STRIPE:
                    raise HTTPRedirect('pay?id={}', attendee.id)
                elif attendee.payment_method == c.CASH:
                    message = c.AT_DOOR_CASH_MSG.format('${}'.format(attendee.total_cost))
                elif attendee.payment_method == c.MANUAL:
                    message = c.AT_DOOR_MANUAL_MSG
                raise HTTPRedirect('register?message={}', message
                                   or "Thanks! Please proceed to the registration desk to pick up your badge.")

        return {
            'message':  message,
            'error_message':  error_message,
            'attendee': attendee,
            'promo_code': params.get('promo_code', ''),
        }

    @public
    @check_atd
    def pay(self, session, id, message=''):
        attendee = session.attendee(id)
        if attendee.paid != c.NOT_PAID:
            raise HTTPRedirect(
                'register?message={}', c.AT_DOOR_NOPAY_MSG)
        else:
            return {
                'message': message,
                'attendee': attendee,
                'charge': Charge(attendee, description=attendee.full_name)
            }

    @public
    @check_atd
    @credit_card
    def take_payment(self, session, payment_id, stripeToken):
        charge = Charge.get(payment_id)
        [attendee] = charge.attendees
        message = charge.charge_cc(session, stripeToken)
        if message:
            raise HTTPRedirect('pay?id={}&message={}', attendee.id, message)
        else:
            db_attendee = session.query(Attendee).filter_by(id=attendee.id).first()
            if db_attendee:
                attendee = db_attendee
            attendee.paid = c.HAS_PAID
            session.add(session.create_receipt_item(attendee, attendee.total_cost * 100,
                                                        "At-door kiosk payment", charge.stripe_transaction))
            attendee.amount_paid_override = attendee.total_cost
            session.add(attendee)
            raise HTTPRedirect(
                'register?message={}', c.AT_DOOR_PREPAID_MSG)

    def comments(self, session, order='last_name'):
        return {
            'order': Order(order),
            'attendees': session.query(Attendee).filter(Attendee.comments != '').order_by(order).all()
        }

    def new(self, session, show_all='', message='', checked_in=''):
        if 'reg_station' not in cherrypy.session:
            raise HTTPRedirect('index?message={}', 'You must set your reg station number')

        if show_all:
            restrict_to = [Attendee.paid == c.NOT_PAID, Attendee.placeholder == False]  # noqa: E711
        else:
            restrict_to = [
                Attendee.paid != c.NEED_NOT_PAY, Attendee.registered > datetime.now(UTC) - timedelta(minutes=90)]

        return {
            'message':    message,
            'show_all':   show_all,
            'checked_in': checked_in,
            'recent':     session.query(Attendee)
                                 .filter(Attendee.checked_in == None,
                                         Attendee.first_name != '',
                                         Attendee.badge_status.in_([c.NEW_STATUS, c.COMPLETED_STATUS]),
                                         *restrict_to)
                                 .order_by(Attendee.registered.desc()).all(),
            'Charge': Charge
        }  # noqa: E711

    def set_reg_station(self, reg_station='', message=''):
        if not reg_station:
            message = "Please enter a number for this reg station"
            
        if not message and not reg_station.isdigit() or not (0 <= int(reg_station) < 100):
            message = "Reg station must be a positive integer between 0 and 100"

        if not message:
            cherrypy.session['reg_station'] = int(reg_station)
            message = "Reg station number recorded"
            
        raise HTTPRedirect('index?message={}', message)

    @ajax
    def mark_as_paid(self, session, id, payment_method):
        if not cherrypy.session.get('reg_station'):
            return {'success': False, 'message': 'Payments can only be taken by at-door stations.'}
        
        attendee = session.attendee(id)
        attendee.paid = c.HAS_PAID
        if int(payment_method) == c.STRIPE_ERROR:
            attendee.for_review += "Automated message: Stripe payment manually verified by admin."
        attendee.payment_method = payment_method
        attendee.amount_paid_override = attendee.total_cost
        session.add(session.create_receipt_item(attendee, attendee.total_cost * 100,
                                                        "At-door marked as paid", txn_type=c.PAYMENT, payment_method=payment_method))
        attendee.reg_station = cherrypy.session.get('reg_station')
        session.commit()
        return {'success': True, 'message': 'Attendee marked as paid.', 'id': attendee.id}

    @ajax
    @credit_card
    def manual_reg_charge(self, session, payment_id, stripeToken):
        charge = Charge.get(payment_id)
        [attendee] = charge.attendees
        message = charge.charge_cc(session, stripeToken)
        if message:
            return {'success': False, 'message': 'Error processing card: {}'.format(message)}
        else:
            attendee.paid = c.HAS_PAID
            attendee.payment_method = c.MANUAL
            session.add(session.create_receipt_item(attendee, attendee.total_cost * 100,
                                                        "At-door desk payment", charge.stripe_transaction))
            attendee.amount_paid_override = attendee.total_cost
            session.merge(attendee)
            session.commit()
            return {'success': True, 'message': 'Payment accepted.', 'id': attendee.id}

    @check_for_encrypted_badge_num
    @csrf_protected
    def new_checkin(self, session, message='', **params):
        attendee = session.attendee(params, allow_invalid=True)
        group = session.group(attendee.group_id) if attendee.group_id else None

        checked_in = ''
        if 'reg_station' not in cherrypy.session:
            raise HTTPRedirect('index?message={}', 'You must set your reg station number')

        message = pre_checkin_check(attendee, group)

        if message:
            session.rollback()
        else:
            if group:
                session.match_to_group(attendee, group)
            attendee.checked_in = localized_now()
            attendee.reg_station = cherrypy.session.get('reg_station')
            message = '{a.full_name} checked in as {a.badge}{a.accoutrements}'.format(a=attendee)
            checked_in = attendee.id
            session.commit()

        raise HTTPRedirect('new?message={}&checked_in={}', message, checked_in)

    @public
    def arbitrary_charge_form(self, message='', amount=None, description='', sale_id=None):
        raise HTTPRedirect('../merch_admin/arbitrary_charge_form')

    def reg_take_report(self, session, **params):
        if params:
            start = c.EVENT_TIMEZONE.localize(
                datetime.strptime('{startday} {starthour}:{startminute}'.format(**params), '%Y-%m-%d %H:%M'))
            end = c.EVENT_TIMEZONE.localize(
                datetime.strptime('{endday} {endhour}:{endminute}'.format(**params), '%Y-%m-%d %H:%M'))

            sales = session.query(Sale).filter(
                Sale.reg_station == params['reg_station'], Sale.when > start, Sale.when <= end).all()

            attendees = session.query(Attendee).filter(
                Attendee.reg_station == params['reg_station'], Attendee.amount_paid > 0,
                Attendee.registered > start, Attendee.registered <= end).all()

            params['sales'] = sales
            params['attendees'] = attendees
            params['total_cash'] = \
                sum((a.amount_paid / 100) for a in attendees if a.payment_method == c.CASH) \
                + sum(s.cash for s in sales if s.payment_method == c.CASH)
            params['total_credit'] = \
                sum((a.amount_paid / 100) for a in attendees if a.payment_method in [c.STRIPE, c.SQUARE, c.MANUAL]) \
                + sum(s.cash for s in sales if s.payment_method == c.CREDIT)
        else:
            params['endday'] = localized_now().strftime('%Y-%m-%d')
            params['endhour'] = localized_now().strftime('%H')
            params['endminute'] = localized_now().strftime('%M')

        # list all reg stations associated with attendees and sales
        stations_attendees = session.query(Attendee.reg_station).filter(
            Attendee.reg_station != None, Attendee.reg_station > 0)  # noqa: E711

        stations_sales = session.query(Sale.reg_station).filter(
            Sale.reg_station != None, Sale.reg_station > 0)  # noqa: E711

        stations = [r for (r,) in stations_attendees.union(stations_sales).distinct().order_by(Attendee.reg_station)]
        params['reg_stations'] = stations
        params.setdefault('reg_station', stations[0] if stations else 0)
        return params

    def undo_new_checkin(self, session, id):
        attendee = session.attendee(id, allow_invalid=True)
        if attendee.group:
            session.add(Attendee(
                group=attendee.group,
                paid=c.PAID_BY_GROUP,
                badge_type=attendee.badge_type,
                ribbon=attendee.ribbon))
        attendee.badge_num = None
        attendee.checked_in = attendee.group = None
        raise HTTPRedirect('new?message={}', 'Attendee un-checked-in')

    def feed(self, session, message='', page='1', who='', what='', action=''):
        feed = session.query(Tracking).filter(Tracking.action != c.AUTO_BADGE_SHIFT).order_by(Tracking.when.desc())
        what = what.strip()
        if who:
            feed = feed.filter_by(who=who)
        if what:
            like = '%' + what + '%'  # SQLAlchemy should have an icontains for this
            feed = feed.filter(or_(Tracking.data.ilike(like), Tracking.which.ilike(like)))
        if action:
            feed = feed.filter_by(action=action)
        return {
            'message': message,
            'who': who,
            'what': what,
            'page': page,
            'action': action,
            'count': feed.count(),
            'feed': get_page(page, feed),
            'action_opts': [opt for opt in c.TRACKING_OPTS if opt[0] != c.AUTO_BADGE_SHIFT],
            'who_opts': [
                who for [who] in session.query(Tracking).distinct().order_by(Tracking.who).values(Tracking.who)]
        }

    @csrf_protected
    def undo_delete(self, session, id, message='', page='1', who='', what='', action=''):
        if cherrypy.request.method == "POST":
            model_class = None
            tracked_delete = session.query(Tracking).get(id)
            if tracked_delete.action != c.DELETED:
                message = 'Only a delete can be undone'
            else:
                model_class = Session.resolve_model(tracked_delete.model)

            if model_class:
                params = json.loads(tracked_delete.snapshot)
                model_id = params.get('id').strip()
                if model_id:
                    existing_model = session.query(model_class).filter(
                        model_class.id == model_id).first()
                    if existing_model:
                        message = '{} has already been undeleted'.format(tracked_delete.which)
                    else:
                        model = model_class(id=model_id).apply(params, restricted=False)
                else:
                    model = model_class().apply(params, restricted=False)

                if not message:
                    session.add(model)
                    message = 'Successfully undeleted {}'.format(tracked_delete.which)
            else:
                message = 'Could not resolve {}'.format(tracked_delete.model)

        raise HTTPRedirect('feed?page={}&who={}&what={}&action={}&message={}', page, who, what, action, message)

    def staffers(self, session, message='', order='first_name'):
        staffers = session.staffers().all()
        return {
            'order': Order(order),
            'message': message,
            'taken_hours': sum([s.weighted_hours - s.nonshift_hours for s in staffers], 0.0),
            'total_hours': sum([j.weighted_hours * j.slots for j in session.query(Job).all()], 0.0),
            'staffers': sorted(staffers, reverse=order.startswith('-'), key=lambda s: getattr(s, order.lstrip('-')))
        }

    def review(self, session):
        return {'attendees': session.query(Attendee)
                                    .filter(Attendee.for_review != '')
                                    .order_by(Attendee.full_name).all()}

    @site_mappable
    def discount(self, session, message='', **params):
        attendee = session.attendee(params)
        if 'first_name' in params:
            try:
                if not attendee.first_name or not attendee.last_name:
                    message = 'First and Last Name are required'
                elif attendee.overridden_price < 0:
                    message = 'Non-Negative Discounted Price is required'
                elif attendee.overridden_price > c.BADGE_PRICE:
                    message = 'You cannot create a discounted badge that costs more than the regular price!'
                elif attendee.overridden_price == 0:
                    attendee.paid = c.NEED_NOT_PAY
                    attendee.overridden_price = c.BADGE_PRICE
            except TypeError:
                message = 'Discounted Price is required'

            if not message:
                session.add(attendee)
                attendee.placeholder = True
                attendee.badge_type = c.ATTENDEE_BADGE
                raise HTTPRedirect('../preregistration/confirm?id={}', attendee.id)

        return {'message': message}

    def inactive(self, session):
        return {
            'attendees': session.query(Attendee)
                                .filter(~Attendee.badge_status.in_([c.NEW_STATUS, c.COMPLETED_STATUS]))
                                .order_by(Attendee.badge_status, Attendee.full_name).all()
        }

    @public
    def stats(self):
        cherrypy.response.headers["Access-Control-Allow-Origin"] = "*"
        return json.dumps({
            'badges_sold': c.BADGES_SOLD,
            'remaining_badges': c.REMAINING_BADGES,
            'badges_price': c.BADGE_PRICE,
            'server_current_timestamp': int(datetime.utcnow().timestamp()),
            'warn_if_server_browser_time_mismatch': c.WARN_IF_SERVER_BROWSER_TIME_MISMATCH
        })

    @public
    def price(self):
        cherrypy.response.headers["Access-Control-Allow-Origin"] = "*"
        return json.dumps({
            'badges_price': c.BADGE_PRICE
        })
    
    @log_pageview
    @attendee_view
    @cherrypy.expose(['attendee_data'])
    def attendee_form(self, session, message='', tab_view=None, **params):
        attendee = session.attendee(params, allow_invalid=True)

        return_dict = {
            'message': message,
            'attendee': attendee,
            'tab_view': tab_view,
            'group_opts': [(g.id, g.name) for g in session.query(Group).order_by(Group.name).all()],
        }
        
        if 'attendee_data' in cherrypy.url():
            return render('registration/attendee_data.html', return_dict)
        else:
            return return_dict
    
    @log_pageview
    @attendee_view
    def attendee_history(self, session, id, **params):
        attendee = session.attendee(id, allow_invalid=True)
        
        return {
            'attendee': attendee,
            'emails': session.query(Email).filter(
                or_(Email.to == attendee.email,
                    and_(Email.model == 'Attendee', Email.fk_id == id))).order_by(Email.when).all(),
            'changes': session.query(Tracking).filter(
                or_(Tracking.links.like('%attendee({})%'.format(id)),
                    and_(Tracking.model == 'Attendee', Tracking.fk_id == id))).order_by(Tracking.when).all(),
            'pageviews': session.query(PageViewTracking).filter(PageViewTracking.what == "Attendee id={}".format(id)),
        }

    @attendee_view
    @cherrypy.expose(['shifts'])
    def attendee_shifts(self, session, id, **params):
        attendee = session.attendee(id, allow_invalid=True)
        attrs = Shift.to_dict_default_attrs + ['worked_label']
        
        return_dict = {
            'attendee': attendee,
            'message': params.get('message', ''),
            'shifts': {s.id: s.to_dict(attrs) for s in attendee.shifts},
            'jobs': [
                (job.id, '({}) [{}] {}'.format(job.timespan(), job.department_name, job.name))
                for job in attendee.available_jobs
                if job.start_time + timedelta(hours=job.duration + 2) > localized_now()],
        }
        
        if 'attendee_shifts' in cherrypy.url():
            return return_dict
        else:
            return render('registration/shifts.html', return_dict)
    
    @log_pageview
    @attendee_view
    def attendee_watchlist(self, session, id, **params):
        attendee = session.attendee(id, allow_invalid=True)
        return {
            'attendee': attendee,
            'active_entries': session.guess_attendee_watchentry(attendee, active=True),
            'inactive_entries': session.guess_attendee_watchentry(attendee, active=False),
        }
    
    @ajax
    @attendee_view
    def update_attendee(self, session, message='', success=False, **params):
        for key in params:
            if params[key] == "false":
                params[key] = False
            if params[key] == "true":
                params[key] = True
            if params[key] == "null":
                params[key] = ""
                
        attendee = session.attendee(params, allow_invalid=True)

        if attendee.is_new and (not attendee.first_name or not attendee.last_name):
            message = 'Please enter a name for this attendee'
        
        if not message and attendee.is_new and \
                    session.attendees_with_badges().filter_by(first_name=attendee.first_name,
                                                                last_name=attendee.last_name,
                                                                email=attendee.email).count():
                message = 'An attendee with this name and email address already exists.'
        
        if not message:
            if 'group_opt' in params:
                attendee.group_id = params.get('group_opt') or None
            
            if params.get('no_badge_num') or not attendee.badge_num:
                attendee.badge_num = None
                
            if params.get('no_override'):
                attendee.overridden_price = None

            if c.BADGE_PROMO_CODES_ENABLED and 'promo_code' in params:
                message = session.add_promo_code_to_attendee(attendee, params.get('promo_code'))

        if not message:
            message = check(attendee)

        if not message:
            success = True
            message = '{} has been saved'.format(attendee.full_name)
            
            if (attendee.is_new 
                or attendee.badge_type != attendee.orig_value_of('badge_type') 
                or attendee.group_id != attendee.orig_value_of('group_id')
                ) and not session.admin_can_create_attendee(attendee):
                attendee.badge_status = c.PENDING_STATUS
                message += ' as a pending badge'
            
            # Free group badges are only considered 'registered' when they are actually claimed.
            if attendee.paid == c.PAID_BY_GROUP and attendee.group_id and attendee.group.cost == 0:
                attendee.registered = localized_now()

            session.add(attendee)
            session.commit()
  
        return {
            'success': success,
            'message': message,
            'id': attendee.id,
        }
    
    def pending_badges(self, session, message=''):
        return {
            'pending_badges': session.query(Attendee).filter_by(badge_status=c.PENDING_STATUS),
            'message': message,
        }

    @ajax
    def approve_badge(self, session, id):
        attendee = session.attendee(id)
        attendee.badge_status = c.NEW_STATUS
        session.add(attendee)
        session.commit()

        return {'added': id}
