import json
import pytz
import math
import re
from datetime import datetime, timedelta
from functools import wraps
from io import BytesIO

import cherrypy
from aztec_code_generator import AztecCode
from pytz import UTC
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import NoResultFound

from uber.config import c
from uber.custom_tags import format_currency, readable_join
from uber.decorators import ajax, ajax_gettable, any_admin_access, all_renderable, attendee_view, \
    check_for_encrypted_badge_num, credit_card, csrf_protected, log_pageview, not_site_mappable, render, \
    requires_account, site_mappable, public
from uber.errors import HTTPRedirect
from uber.forms import load_forms
from uber.models import Attendee, AttendeeAccount, AdminAccount, Email, Group, Job, PageViewTracking, PrintJob, \
    PromoCode, PromoCodeGroup, ReportTracking, Sale, Session, Shift, Tracking, ReceiptTransaction, \
    WorkstationAssignment
from uber.site_sections.preregistration import check_if_can_reg
from uber.utils import add_opt, check, check_pii_consent, get_page, hour_day_format, \
    localized_now, Order, validate_model
from uber.payments import TransactionRequest, ReceiptManager, SpinTerminalRequest


def check_atd(func):
    @wraps(func)
    def checking_at_the_door(self, *args, **kwargs):
        if c.AT_THE_CON or c.DEV_BOX:
            return func(self, *args, **kwargs)
        else:
            raise HTTPRedirect('index')
    return checking_at_the_door


def load_attendee(session, params):
    id = params.get('id', None)

    if id in [None, '', 'None']:
        attendee = Attendee()
    else:
        attendee = session.attendee(id)

    return attendee


def save_attendee(session, attendee, params):
    if cherrypy.request.method == 'POST':
        receipt_items = ReceiptManager.auto_update_receipt(attendee,
                                                           session.get_receipt_by_model(attendee), params.copy())
        session.add_all(receipt_items)

    forms = load_forms(params, attendee, ['PersonalInfo', 'AdminBadgeExtras', 'AdminConsents', 'AdminStaffingInfo',
                                          'AdminBadgeFlags', 'BadgeAdminNotes', 'OtherInfo'])

    for form in forms.values():
        if hasattr(form, 'same_legal_name') and params.get('same_legal_name'):
            form['legal_name'].data = ''
        form.populate_obj(attendee, is_admin=True)

    message = ''

    if c.NUMBERED_BADGES and (params.get('no_badge_num') or not attendee.badge_num):
        if params.get('save_check_in', False) and attendee.badge_type not in c.PREASSIGNED_BADGE_TYPES:
            message = "Please enter a badge number to check this attendee in."
        else:
            attendee.badge_num = None

    if 'no_override' in params:
        attendee.overridden_price = None

    if c.BADGE_PROMO_CODES_ENABLED and 'promo_code_code' in params:
        message = session.add_promo_code_to_attendee(attendee, params.get('promo_code_code'))

    return message


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

        reg_station_id = cherrypy.session.get('reg_station', '')
        workstation_assignment = session.query(WorkstationAssignment
                                               ).filter_by(reg_station_id=reg_station_id or -1).first()

        status_list = [c.NEW_STATUS, c.COMPLETED_STATUS, c.WATCHED_STATUS, c.UNAPPROVED_DEALER_STATUS]
        if c.AT_THE_CON:
            status_list.append(c.AT_DOOR_PENDING_STATUS)
        filter = [Attendee.badge_status.in_(status_list)] if not invalid else []
        total_count = session.query(Attendee.id).filter(*filter).count()
        count = 0
        search_text = search_text.strip()
        if search_text:
            search_results, message = session.search(search_text, *filter)
            if search_results and search_results.count():
                attendees = search_results
                count = attendees.count()
                if count == total_count:
                    message = 'Every{} attendee matched this search.'.format('' if invalid else ' valid')
            elif not message:
                message = 'No matches found.{}'.format(
                    '' if invalid else ' Try showing all badges to expand your search.')
        if not count:
            attendees = session.index_attendees().filter(*filter)
            count = attendees.count()

        attendees = attendees.order(order)

        page = int(page)
        if search_text:
            page = page or 1
            if count == 1 and not c.AT_THE_CON:
                raise HTTPRedirect(
                    'form?id={}&message={}', attendees.one().id,
                    'This attendee was the only{} search result'.format('' if invalid else ' valid'))

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
            'search_count':   count,
            'attendee_count': total_count,
            'checkin_count':  session.query(Attendee).filter(Attendee.checked_in != None).count(),  # noqa: E711
            'attendee':       session.attendee(uploaded_id, allow_invalid=True) if uploaded_id else None,
            'reg_station_id':    reg_station_id,
            'workstation_assignment': workstation_assignment,
        }  # noqa: E711

    @ajax
    @any_admin_access
    def validate_attendee(self, session, form_list=[], **params):
        if params.get('id') in [None, '', 'None']:
            attendee = Attendee()
        else:
            attendee = session.attendee(params.get('id'))

        if not form_list:
            form_list = ['PersonalInfo', 'AdminBadgeExtras', 'AdminConsents', 'AdminStaffingInfo', 'AdminBadgeFlags',
                         'BadgeAdminNotes', 'OtherInfo']
        elif isinstance(form_list, str):
            form_list = [form_list]
        forms = load_forms(params, attendee, form_list, get_optional=False)

        all_errors = validate_model(forms, attendee, Attendee(**attendee.to_dict()), is_admin=True)
        if all_errors:
            return {"error": all_errors}

        if attendee.is_new:
            for form in forms.values():
                form.populate_obj(attendee, is_admin=True)

            if attendee.banned:
                return {"warning": render('registration/banned.html', {'attendee': attendee,
                                                                       'session': session}, encoding=None)}

            old = session.valid_attendees().filter_by(first_name=attendee.first_name,
                                                      last_name=attendee.last_name,
                                                      email=attendee.email).first()
            if old:
                return {"warning": render('registration/duplicate.html', {'attendee': old}, encoding=None),
                        "button_text": "Yes, I'm sure this is someone else!"}

        return {"success": True}

    @ajax
    def validate_attendee_checkin(self, session, form_list, **params):
        if params.get('id') in [None, '', 'None']:
            attendee = Attendee()
        else:
            attendee = session.attendee(params.get('id'))

        normal_validations = json.loads(self.validate_attendee(form_list=form_list, **params))
        if 'error' in normal_validations:
            return {"error": normal_validations['error']}

        if attendee.checked_in:
            # We skip this failure for badge printing since we still want the badge to get printed
            if not c.BADGE_PRINTING_ENABLED or attendee.times_printed > 0:
                return {"error": {'': [attendee.full_name + ' was already checked in!']}}

        if attendee.group and attendee.paid == c.PAID_BY_GROUP and attendee.group.amount_unpaid:
            return {
                "error": {'': ['This attendee\'s group has an outstanding balance of ${}.'.format(
                    format_currency(attendee.group.amount_unpaid))]}
                    }

        if attendee.amount_unpaid_if_valid:
            return {
                "error": {'': ['This attendee has an outstanding balance of ${}.'.format(
                    format_currency(attendee.amount_unpaid_if_valid))]}
                    }

        return {"success": True}

    @log_pageview
    def form(self, session, message='', return_to='', **params):
        attendee = load_attendee(session, params)

        reg_station_id = cherrypy.session.get('reg_station', '')
        workstation_assignment = session.query(WorkstationAssignment
                                               ).filter_by(reg_station_id=reg_station_id or -1).first()

        if cherrypy.request.method == 'POST':
            message = save_attendee(session, attendee, params)

            if not message:
                message = '{} has been saved.'.format(attendee.full_name)
                stay_on_form = params.get('save_return_to_search', False) is False
                session.add(attendee)
                session.commit()
                if params.get('save_check_in', False):
                    if attendee.is_not_ready_to_checkin:
                        message = "Attendee saved, but they cannot check in now. Reason: {}".format(
                            attendee.is_not_ready_to_checkin)
                        stay_on_form = True
                    elif attendee.amount_unpaid_if_valid:
                        message = "Attendee saved, but they must pay ${} before they can check in.".format(
                            attendee.amount_unpaid_if_valid)
                        stay_on_form = True
                    else:
                        attendee.checked_in = localized_now()
                        session.commit()
                        message = '{} saved and checked in as {}{}.'.format(
                            attendee.full_name, attendee.badge, attendee.accoutrements)
                        stay_on_form = False

                if stay_on_form:
                    raise HTTPRedirect('form?id={}&message={}&return_to={}', attendee.id, message, return_to)
                else:
                    if return_to:
                        raise HTTPRedirect(return_to + '&message={}', 'Attendee updated.')
                    else:
                        raise HTTPRedirect(
                            'index?uploaded_id={}&message={}&search_text={}',
                            attendee.id,
                            message,
                            '{} {}'.format(attendee.first_name, attendee.last_name) if c.AT_THE_CON else '')
        receipt = session.refresh_receipt_and_model(attendee)
        session.commit()
        forms = load_forms(params, attendee, ['PersonalInfo', 'AdminBadgeExtras', 'AdminConsents', 'AdminStaffingInfo',
                                              'AdminBadgeFlags', 'BadgeAdminNotes', 'OtherInfo'])

        return {
            'message':    message,
            'attendee':   attendee,
            'forms': forms,
            'return_to':  return_to,
            'no_badge_num': params.get('no_badge_num'),
            'group_opts': [(g.id, g.name) for g in session.query(Group).order_by(Group.name).all()],
            'unassigned': {
                group_id: unassigned
                for group_id, unassigned in session.query(Attendee.group_id, func.count('*')).filter(
                    Attendee.group_id != None,  # noqa: E711
                    Attendee.first_name == '').group_by(Attendee.group_id).all()},
            'payment_enabled': True if reg_station_id else False,
            'reg_station_id': reg_station_id,
            'workstation_assignment': workstation_assignment,
            'receipt': receipt,
        }  # noqa: E711

    @ajax
    def start_terminal_payment(self, session, model_id='', account_id='', **params):
        from uber.tasks.registration import process_terminal_sale

        error, terminal_id = session.get_assigned_terminal_id()

        if error:
            return {'error': error}

        description = ""

        if model_id:
            try:
                attendee = session.attendee(model_id)
                description = f"At-door badge payment for {attendee.full_name}"
            except NoResultFound:
                group = session.group(model_id)
                description = f"At-door payment for {group.name}"

        c.REDIS_STORE.delete(c.REDIS_PREFIX + 'spin_terminal_txns:' + terminal_id)
        process_terminal_sale.delay(workstation_num=cherrypy.session.get('reg_station'),
                                    terminal_id=terminal_id,
                                    model_id=model_id,
                                    account_id=account_id,
                                    description=description)
        return {'success': True}

    def check_txn_status(self, session, intent_id='', **params):
        error, terminal_id = session.get_assigned_terminal_id()

        if error:
            return {'error': error}

        req = SpinTerminalRequest(terminal_id)
        response = req.check_txn_status(intent_id)
        if response:
            response_json = response.json()
            if req.api_response_successful(response_json):
                message = str(response_json)
            else:
                error_message = req.error_message_from_response(response_json)
                message = f"Error checking status of {intent_id}: {error_message}"
        else:
            message = f"Error checking status of {intent_id}: {req.error_message}"

        raise HTTPRedirect('../reg_admin/manage_workstations?message={}', message)

    @ajax
    def poll_terminal_payment(self, session, **params):
        from spin_rest_utils import utils as spin_rest_utils
        error, terminal_id = session.get_assigned_terminal_id()

        if error:
            return {'error': error}

        terminal_status = c.REDIS_STORE.hgetall(c.REDIS_PREFIX + 'spin_terminal_txns:' + terminal_id)
        error_message = terminal_status.get('last_error', '')
        intent_id = terminal_status.get('intent_id', '')
        response = json.loads(terminal_status.get('last_response')) if terminal_status.get('last_response') else {}

        if error_message:
            if intent_id and not response:
                matching_txns = session.query(ReceiptTransaction).filter_by(intent_id=intent_id)
                for txn in matching_txns:
                    txn.cancelled = datetime.now()
                    session.add(txn)
                session.commit()
            custom_error = spin_rest_utils.better_error_message(error_message, response, terminal_id, format_currency)
            if custom_error:
                custom_error['intent_id'] = intent_id
                return custom_error
            return {'error': error_message, 'intent_id': intent_id}
        elif response:
            if not intent_id:
                return {
                    'error': "We could not find which payment this transaction was for. "
                    "You may need a manager to log it manually."
                    }
            return {'success': True, 'intent_id': intent_id}
        else:
            # TODO: Finish and test this
            past_timeout = datetime.now(pytz.UTC) - timedelta(seconds=150)
            if terminal_status.get('request_timestamp') and \
                    terminal_status.get('request_timestamp') < past_timeout.timestamp():
                status_request = SpinTerminalRequest(terminal_id)
                response = status_request.check_txn_status(intent_id)
                if response:
                    status_request.process_sale_response(response)
                else:
                    return {'error': status_request.error_message}

    def promo_code_groups(self, session, message=''):
        groups = session.query(PromoCodeGroup).order_by(PromoCodeGroup.name).all()
        used_counts = {
            group_id: count for group_id, count in
            session.query(PromoCode.group_id, func.count(PromoCode.id))
            .filter(Attendee.promo_code_id == PromoCode.id,
                    PromoCode.group_id == PromoCodeGroup.id).group_by(PromoCode.group_id)
        }
        total_costs = {
            group_id: total for group_id, total in
            session.query(PromoCode.group_id, func.sum(PromoCode.cost)).group_by(PromoCode.group_id)
        }
        total_counts = {
            group_id: count for group_id, count in
            session.query(PromoCode.group_id, func.count('*')).group_by(PromoCode.group_id)
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
                badges = int(badges)
                if buyer_id == "None":
                    buyer = Attendee(first_name=first_name, last_name=last_name, email=email)
                    buyer.placeholder = True
                    session.add(buyer)
                    group.buyer = buyer
                    session.commit()

                if badges:
                    session.add_codes_to_pc_group(group, badges, 0 if badges_are_free else int(cost_per_badge))
                    receipt = session.get_receipt_by_model(group.buyer)
                    if receipt and cost_per_badge:
                        session.add(
                            ReceiptManager().create_receipt_item(receipt,
                                                                 c.REG_RECEIPT_ITEM,
                                                                 c.GROUP_BADGE,
                                                                 f'Adding {badges} Badge{"s" if badges > 1 else ""}',
                                                                 badges * int(cost_per_badge) * 100))
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

    @ajax
    def remove_group_code(self, session, id='', **params):
        code = session.promo_code(id)

        pc_group = code.group
        pc_group.promo_codes.remove(code)

        session.delete(code)
        session.commit()

        return {'removed': id}

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
        checkin_barcode = AztecCode(c.EVENT_QR_ID+str(data), size=(27, True)).image(module_size=4, border=1)
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
            'changes': session.query(Tracking).filter(
                or_(and_(Tracking.links.like('%attendee({})%'.format(id))),
                    and_(Tracking.model == 'Attendee', Tracking.fk_id == id))).order_by(Tracking.when).all(),
            'pageviews': session.query(PageViewTracking).filter(PageViewTracking.which == repr(attendee))
        }

    def delete(self, session, id, return_to='index?', return_msg=False, **params):
        attendee = session.attendee(id, allow_invalid=True)
        if attendee.group:
            if attendee.group.leader_id == attendee.id:
                message = 'You cannot delete the leader of a group; ' \
                    'you must make someone else the leader first, or just delete the entire group'
                if return_msg:
                    return False, message
            elif attendee.is_unassigned:
                session.delete_from_group(attendee, attendee.group)
                message = 'Unassigned badge removed.'
            else:
                replacement_attendee = Attendee(**{attr: getattr(attendee, attr) for attr in [
                    'group', 'registered', 'badge_type', 'badge_num', 'paid', 'amount_extra'
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

        if return_msg:
            session.commit()
            return True, message

        q_or_a = '?' if '?' not in return_to else '&'
        raise HTTPRedirect(return_to + ('' if return_to[-1] == '?' else q_or_a) + 'message={}', message)

    @ajax
    @attendee_view
    def delete_attendee(self, session, id, **params):
        success, msg = self.delete(id=id, return_msg=True, **params)
        return {'success': success, 'message': msg}

    @check_for_encrypted_badge_num
    @ajax
    def print_badge(self, session, message='', printer_id='', **params):
        from uber.site_sections.badge_printing import pre_print_check
        id = params.get('id', None)

        if id in [None, '', 'None']:
            attendee = Attendee()
        else:
            attendee = session.attendee(id)

        forms = load_forms(params, attendee, ['CheckInForm'])

        for form in forms.values():
            form.populate_obj(attendee, is_admin=True)

        if not printer_id:
            return {'success': False, 'message': 'You must set a printer ID.'}

        reg_station_id = cherrypy.session.get('reg_station', '')
        workstation_assignment = session.query(WorkstationAssignment).filter_by(
            reg_station_id=reg_station_id or -1).first()

        if attendee.age_now_or_at_con < 18 and not workstation_assignment:
            return {'success': False,
                    'message': "Your workstation has no printers assigned, "
                    "so we can't tell how to handle this minor's badge."}

        success, message = pre_print_check(session, attendee, printer_id, dry_run=True, **params)

        if not success:
            return {'success': False, 'message': message}

        session.commit()
        if attendee.age_now_or_at_con < 18 and printer_id == workstation_assignment.printer_id:
            if session.query(PrintJob).filter(PrintJob.printer_id == printer_id,
                                              PrintJob.printed == None,  # noqa: E711
                                              PrintJob.errors == '').all():
                return {'success': False,
                        'message': "This is a minor badge and there are still standard badges waiting to "
                        "print on this printer. Please try again soon or set a different printer ID."}
            else:
                return {'success': True, 'minor_check': True}
        else:
            session.add_to_print_queue(attendee, printer_id, cherrypy.session.get('reg_station'),
                                       params.get('fee_amount'))
            session.commit()
            return {'success': True, 'message': message + f" {attendee.full_name} successfully checked in."}

    @ajax
    def print_and_check_in_badges(self, session, message='', printer_id='', minor_printer_id='', **params):
        from uber.site_sections.badge_printing import pre_print_check
        id = params.get('id', None)

        if id in [None, '', 'None']:
            account = AttendeeAccount()
        else:
            account = session.attendee_account(id)

        if not printer_id and not minor_printer_id:
            return {'success': False, 'message': 'You must set a printer ID.'}

        if len(account.at_door_under_18s) != len(account.at_door_attendees) and not printer_id:
            return {'success': False,
                    'message': 'You must set a printer ID for the adult badges that are being checked in.'}

        minor_check_badges = False
        attendee_names_list = []
        checked_in = {}
        printer_messages = []
        cherrypy.session['cart_success_list'] = []
        cherrypy.session['cart_printer_error_list'] = []

        for attendee in account.at_door_attendees:
            success, message = pre_print_check(session, attendee, printer_id, dry_run=True, **params)

            if not success:
                printer_messages.append(f"There was a problem with printing {attendee.full_name}'s badge: {message}")

            session.commit()

            if success and attendee.age_now_or_at_con < 18 and (not minor_printer_id or printer_id == minor_printer_id):
                minor_check_badges = True
            elif success:
                attendee_names_list.append(attendee.full_name)
                session.add_to_print_queue(attendee, printer_id,
                                           cherrypy.session.get('reg_station'), params.get('fee_amount'))

                if attendee.badge_status == c.AT_DOOR_PENDING_STATUS:
                    attendee.badge_status = c.NEW_STATUS
                attendee.checked_in = localized_now()
                checked_in[attendee.id] = {
                    'badge':      attendee.badge,
                    'paid':       attendee.paid_label,
                    'age_group':  attendee.age_group_conf['desc'],
                    'checked_in': attendee.checked_in and hour_day_format(attendee.checked_in),
                }
                session.commit()

        if attendee_names_list:
            success_message = "{} successfully checked in.{}".format(
                readable_join(attendee_names_list),
                (" " + " ".join(printer_messages)) if printer_messages else "")
        else:
            success_message = " ".join(printer_messages)

        if minor_check_badges:
            cherrypy.session['cart_success_list'] = attendee_names_list
            cherrypy.session['cart_printer_error_list'] = printer_messages
            return {
                'success': True,
                'minor_check': True,
                'num_adults': len(attendee_names_list),
                'checked_in': checked_in
                }
        return {'success': True, 'message': success_message, 'checked_in': checked_in}

    def minor_check_form(self, session, printer_id, attendee_id='', account_id='', reprint_fee=0, num_adults=0):
        if account_id:
            account = session.attendee_account(account_id)
            attendees = account.at_door_under_18s
        elif attendee_id:
            attendee = session.attendee(attendee_id)
            attendees = [attendee]

        return {
            'attendees': attendees,
            'account_id': account_id,
            'attendee_id': attendee_id,
            'printer_id': printer_id,
            'reprint_fee': reprint_fee,
            'num_adults': num_adults,
        }

    @ajax_gettable
    def complete_minor_check(self, session, printer_id, attendee_id='', account_id='', reprint_fee=0):
        if account_id:
            account = session.attendee_account(account_id)
            attendees = account.at_door_under_18s
        elif attendee_id:
            attendee = session.attendee(attendee_id)
            attendees = [attendee]

        attendee_names_list = cherrypy.session.get('cart_success_list', [])
        printer_messages = cherrypy.session.get('cart_printer_error_list', [])
        checked_in = {}

        for attendee in attendees:
            _, errors = session.add_to_print_queue(attendee, printer_id,
                                                   cherrypy.session.get('reg_station'), reprint_fee)
            if errors and not account_id:
                return {'success': False, 'message': "<br>".join(errors)}
            elif errors:
                printer_messages.append(f"There was a problem with printing {attendee.full_name}'s "
                                        f"badge: {' '.join(errors)}")
            else:
                if attendee.badge_status == c.AT_DOOR_PENDING_STATUS:
                    attendee.badge_status = c.NEW_STATUS
                attendee.checked_in = localized_now()
                checked_in[attendee.id] = {
                    'badge':      attendee.badge,
                    'paid':       attendee.paid_label,
                    'age_group':  attendee.age_group_conf['desc'],
                    'checked_in': attendee.checked_in and hour_day_format(attendee.checked_in),
                }
                session.commit()
                attendee_names_list.append(attendee.full_name)

        message = "{} successfully checked in.{}".format(readable_join(attendee_names_list),
                                                         (" " + " ".join(printer_messages))
                                                         if printer_messages else "")
        return {'success': True, 'message': message, 'checked_in': checked_in}

    def check_in_form(self, session, id):
        attendee = session.attendee(id)
        session.refresh_receipt_and_model(attendee)
        session.commit()

        if attendee.paid == c.PAID_BY_GROUP and not attendee.group_id:
            valid_groups = session.query(Group).options(joinedload(Group.leader)).filter(
                Group.status != c.WAITLISTED,
                Group.id.in_(
                    session.query(Attendee.group_id)
                    .filter(Attendee.group_id != None, Attendee.first_name == '')  # noqa: E711
                    .distinct().subquery()
                )).order_by(Group.name)  # noqa: E711

            groups = [(
                group.id,
                (group.name if len(group.name) < 30 else '{}...'.format(group.name[:27]))
                + (' ({})'.format(group.leader.full_name) if group.leader else ''))
                for group in valid_groups]
        else:
            groups = []

        forms = load_forms({}, attendee, ['CheckInForm'])

        return {
            'attendee': attendee,
            'groups': groups,
            'forms': forms,
        }

    def check_in_cart_form(self, session, id):
        account = session.attendee_account(id)
        reg_station_id = cherrypy.session.get('reg_station', '')
        workstation_assignment = session.query(WorkstationAssignment).filter_by(
            reg_station_id=reg_station_id or -1).first()
        total_cost = 0
        for attendee in account.at_door_attendees:
            receipt = session.get_receipt_by_model(attendee, create_if_none="DEFAULT")
            total_cost += receipt.current_amount_owed

        return {
            'account': account,
            'total_cost': total_cost,
            'workstation_assignment': workstation_assignment,
        }

    @ajax
    def remove_attendee_from_cart(self, session, **params):
        id = params.get('id', None)

        if id in [None, '', 'None']:
            return {'error': "No ID provided."}

        attendee = session.attendee(id)
        if attendee.badge_status != c.AT_DOOR_PENDING_STATUS:
            return {'error': f"This attendee's badge status is actually {attendee.badge_status_label}. Please refresh."}

        attendee.badge_status = c.NEW_STATUS
        session.commit()

        return {'success': True}

    @check_for_encrypted_badge_num
    @ajax
    def save_no_check_in(self, session, **params):
        id = params.get('id', None)

        if id in [None, '', 'None']:
            return {'error': "No ID provided."}
        attendee = session.attendee(id)

        forms = load_forms(params, attendee, ['CheckInForm'])

        for form in forms.values():
            form.populate_obj(attendee, is_admin=True)

        session.commit()

        return {'success': True}

    @check_for_encrypted_badge_num
    @ajax
    def check_in(self, session, message='', **params):
        id = params.get('id', None)

        if id in [None, '', 'None']:
            attendee = Attendee()
        else:
            attendee = session.attendee(id)

        forms = load_forms(params, attendee, ['CheckInForm'])

        for form in forms.values():
            form.populate_obj(attendee, is_admin=True)

        pre_badge = attendee.badge_num
        success, increment = False, False

        attendee.checked_in = localized_now()
        if attendee.badge_status == c.AT_DOOR_PENDING_STATUS:
            attendee.badge_status = c.NEW_STATUS
        success = True
        session.commit()
        increment = True
        message = '{} checked in as {}{}'.format(attendee.full_name, attendee.badge, attendee.accoutrements)

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
        attendee.checked_in, attendee.badge_num = None, pre_badge if pre_badge else None
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
    @requires_account()
    def register(self, session, message='', error_message='', **params):
        errors = check_if_can_reg()
        if errors:
            return errors

        params['id'] = 'None'
        login_email = None
        payment_method = params.get('payment_method')
        if payment_method:
            payment_method = int(payment_method)

        if 'kiosk_mode' in params:
            cherrypy.session['kiosk_mode'] = True

        in_kiosk_mode = cherrypy.session.get('kiosk_mode')
        if in_kiosk_mode:
            cherrypy.session['attendee_account_id'] = None

        if c.ATTENDEE_ACCOUNTS_ENABLED:
            login_email = params.get('login_email')

        attendee = session.attendee(params, restricted=True, ignore_csrf=True)
        error_message = error_message or check_pii_consent(params, attendee)
        if not error_message and 'first_name' in params:
            if not payment_method and (not c.BADGE_PRICE_WAIVED or c.BEFORE_BADGE_PRICE_WAIVED):
                error_message = 'Please select a payment type'
            elif payment_method == c.MANUAL and not re.match(c.EMAIL_RE, attendee.email):
                error_message = 'Email address is required to pay with a credit card at our registration desk'
            elif attendee.badge_type not in [badge for badge, desc in c.AT_THE_DOOR_BADGE_OPTS]:
                error_message = 'No hacking allowed!'
            else:
                error_message = check(attendee)

            if not error_message and c.BADGE_PROMO_CODES_ENABLED and 'promo_code' in params:
                error_message = session.add_promo_code_to_attendee(attendee, params.get('promo_code'))
            if not error_message:
                if c.ATTENDEE_ACCOUNTS_ENABLED:
                    new_or_existing_account = session.current_attendee_account()
                    if not in_kiosk_mode:
                        cherrypy.session['attendee_account_id'] = new_or_existing_account.id

                session.add(attendee)
                session.get_receipt_by_model(attendee, create_if_none="DEFAULT")
                session.commit()
                if c.AFTER_BADGE_PRICE_WAIVED:
                    message = c.AT_DOOR_WAIVED_MSG
                    attendee.paid = c.NEED_NOT_PAY
                elif payment_method == c.STRIPE:
                    raise HTTPRedirect('pay?id={}', attendee.id)
                elif payment_method == c.CASH:
                    message = c.AT_DOOR_CASH_MSG.format('${}'.format(attendee.total_cost))
                elif payment_method == c.MANUAL:
                    message = c.AT_DOOR_MANUAL_MSG
                message = message or "Thanks! Please proceed to the registration desk to pick up your badge."
                if in_kiosk_mode:
                    raise HTTPRedirect('register?message={}', message)
                else:
                    raise HTTPRedirect('at_door_complete?id={}&message={}', attendee.id, message)

        return {
            'message':  message,
            'error_message':  error_message,
            'attendee': attendee,
            'payment_method_val': payment_method,
            'promo_code': params.get('promo_code', ''),
            'logged_in_account': session.current_attendee_account(),
            'original_location': '../registration/register',
            'kiosk_mode': in_kiosk_mode,
            'logging_in': bool(login_email),
        }

    @public
    @check_atd
    def at_door_complete(self, session, id, message=''):
        attendee = session.attendee(id)
        return {
            'confirm_message': message,
            'attendee': attendee,
        }

    @public
    @check_atd
    def pay(self, session, id, message=''):
        attendee = session.attendee(id)
        if not attendee.amount_unpaid:
            if cherrypy.session.get('kiosk_mode'):
                raise HTTPRedirect('register?message={}', c.AT_DOOR_NOPAY_MSG)
            else:
                raise HTTPRedirect('at_door_complete?id={}&message={}', attendee.id, c.AT_DOOR_NOPAY_MSG)
        else:
            return {
                'message': message,
                'attendee': attendee,
            }

    @public
    @check_atd
    @ajax
    @credit_card
    def take_payment(self, session, id):
        attendee = session.attendee(id)
        receipt = session.get_receipt_by_model(attendee, create_if_none="DEFAULT")
        charge_desc = "{}: {}".format(attendee.full_name, receipt.charge_description_list)
        charge = TransactionRequest(receipt, attendee.email, charge_desc)
        message = charge.prepare_payment()

        if message:
            return {'error': message}

        session.add_all(charge.get_receipt_items_to_add())
        session.commit()
        if cherrypy.session.get('kiosk_mode'):
            success_url = 'register?message={}'.format(c.AT_DOOR_PREPAID_MSG)
        else:
            success_url = 'at_door_complete?id={}&message={}'.format(attendee.id, c.AT_DOOR_PREPAID_MSG)
        return {'stripe_intent': charge.intent,
                'success_url': success_url}

    def comments(self, session, order='last_name'):
        return {
            'order': Order(order),
            'attendees': session.query(Attendee).filter(Attendee.comments != '').order_by(order).all()
        }

    def new(self, session, show_all='', message='', checked_in=''):
        if 'reg_station' not in cherrypy.session:
            raise HTTPRedirect('index?message={}', 'You must set your reg station number')

        if show_all:
            restrict_to = [Attendee.paid == c.NOT_PAID, Attendee.placeholder == False]  # noqa: E712
        else:
            restrict_to = [
                Attendee.paid != c.NEED_NOT_PAY, Attendee.registered > datetime.now(UTC) - timedelta(minutes=90)]

        return {
            'message':    message,
            'show_all':   show_all,
            'checked_in': checked_in,
            'recent':     session.query(Attendee).filter(Attendee.checked_in == None,  # noqa: E711
                                                         Attendee.first_name != '',
                                                         Attendee.badge_status.in_([c.NEW_STATUS, c.COMPLETED_STATUS]),
                                                         *restrict_to).order_by(Attendee.registered.desc()).all(),
        }  # noqa: E711

    @not_site_mappable
    def set_reg_station(self, reg_station_id='', message='', return_to='../registration/index'):
        from urllib.parse import unquote
        if not reg_station_id:
            message = "Please enter a number for this reg station"

        if not message and (not reg_station_id.isdigit() or
                            (reg_station_id.isdigit() and not (0 <= int(reg_station_id) < 1000))):
            message = "Reg station must be a positive integer between 0 and 1000"

        if not message:
            cherrypy.session['reg_station'] = int(reg_station_id)
            message = "Reg station number recorded"

        connect_char = '?'

        return_to = unquote(return_to)
        if '?' in return_to:
            connect_char = '&'

        raise HTTPRedirect(f'{return_to}{connect_char}message={message}')

    def update_printers(self, session, reg_station_id='', **params):
        if not reg_station_id:
            reg_station_id = cherrypy.session.get('reg_station')

        if not reg_station_id:
            raise HTTPRedirect("index?message={}", "No reg station ID set!")

        reg_station_id = int(reg_station_id)
        cherrypy.session['reg_station'] = reg_station_id

        if not params.get('printer_id'):
            raise HTTPRedirect("index?message={}", "Please include a printer ID.")

        workstation_assignment = session.query(WorkstationAssignment).filter_by(reg_station_id=reg_station_id).first()

        if not workstation_assignment:
            workstation_assignment = WorkstationAssignment(reg_station_id=reg_station_id)
            session.add(workstation_assignment)

        workstation_assignment.printer_id = params.get('printer_id', '')
        workstation_assignment.minor_printer_id = params.get('minor_printer_id', '')

        raise HTTPRedirect("index?message=Printer IDs set!")

    @ajax
    def mark_as_paid(self, session, id, payment_method):
        if not cherrypy.session.get('reg_station'):
            return {'success': False, 'message': 'You must set a workstation ID to take payments.'}

        account = None

        try:
            attendee = session.attendee(id)
            attendees = [attendee]
        except NoResultFound:
            account = session.attendee_account(id)

        if account:
            attendees = account.at_door_attendees

        for attendee in attendees:
            receipt = session.get_receipt_by_model(attendee, create_if_none="DEFAULT")
            if receipt.current_amount_owed:
                if attendee.paid in [c.NOT_PAID, c.PENDING]:
                    attendee.paid = c.HAS_PAID
                if int(payment_method) == c.STRIPE_ERROR:
                    desc = f"Automated message: Stripe payment manually verified by {AdminAccount.admin_name()}."
                else:
                    desc = f"At-door marked as paid by {AdminAccount.admin_name()}"

                receipt_manager = ReceiptManager(receipt)
                error = receipt_manager.create_payment_transaction(desc, amount=receipt.current_amount_owed,
                                                                   method=payment_method)
                if error:
                    session.rollback()
                    return {'success': False, 'message': error}
                session.add_all(receipt_manager.items_to_add)

                attendee.reg_station = cherrypy.session.get('reg_station')
        session.commit()
        return {
            'success': True,
            'message': 'Attendee{} marked as paid.'.format('s' if account else ''),
            'id': attendee.id
            }

    @ajax
    @credit_card
    def manual_reg_charge(self, session, id):
        attendee = session.attendee(id)
        receipt = session.get_receipt_by_model(attendee, create_if_none="DEFAULT")
        charge_desc = "{}: {}".format(attendee.full_name, receipt.charge_description_list)
        charge = TransactionRequest(receipt, attendee.email, charge_desc)

        message = charge.prepare_payment(payment_method=c.MANUAL)
        if message:
            return {'error': message}

        session.add_all(charge.get_receipt_items_to_add())
        session.commit()
        return {'stripe_intent': charge.intent, 'success_url': ''}

    @check_for_encrypted_badge_num
    @csrf_protected
    def new_checkin(self, session, message='', **params):
        id = params.get('id', None)

        if id in [None, '', 'None']:
            attendee = Attendee()
        else:
            attendee = session.attendee(id)

        forms = load_forms(params, attendee, ['CheckInForm'])

        for form in forms.values():
            form.populate_obj(attendee, is_admin=True)

        checked_in = ''
        if 'reg_station' not in cherrypy.session:
            raise HTTPRedirect('index?message={}', 'You must set your reg station number')

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

    def feed(self, session, tracking_type='action', message='', page='1', who='', what='', action=''):
        filters = []
        if tracking_type == 'report':
            model = ReportTracking
        elif tracking_type == 'pageview':
            model = PageViewTracking
        elif tracking_type == 'action':
            model = Tracking
            filters.append(Tracking.action != c.AUTO_BADGE_SHIFT)

        feed = session.query(model).filter(*filters).order_by(model.when.desc())
        what = what.strip()
        if who:
            feed = feed.filter_by(who=who)
        if what:
            like = '%' + what + '%'  # SQLAlchemy 2.0 introduces icontains
            or_filters = [model.page.ilike(like)]
            if tracking_type != 'report':
                or_filters.append(model.which.ilike(like))
            if tracking_type == 'action':
                or_filters.append(model.data.ilike(like))
            feed = feed.filter(or_(*or_filters))
        if action:
            feed = feed.filter_by(action=action)
        return {
            'message': message,
            'tracking_type': tracking_type,
            'who': who,
            'what': what,
            'page': page,
            'action': action,
            'count': feed.count(),
            'feed': get_page(page, feed),
            'action_opts': [opt for opt in c.TRACKING_OPTS if opt[0] != c.AUTO_BADGE_SHIFT],
            'who_opts': [
                who for [who] in session.query(model).distinct().order_by(model.who).values(model.who)]
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
            'taken_hours': sum([s.weighted_hours - s.nonshift_minutes / 60 for s in staffers], 0.0),
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
        id = params.get('id', None)

        if id in [None, '', 'None']:
            attendee = Attendee()
        else:
            attendee = session.attendee(id)

        forms = load_forms(params, attendee, ['PersonalInfo', 'AdminBadgeExtras', 'AdminConsents', 'AdminStaffingInfo',
                                              'AdminBadgeFlags', 'BadgeAdminNotes', 'OtherInfo'])

        for form in forms.values():
            form.populate_obj(attendee, is_admin=True)

        return_dict = {
            'message': message,
            'attendee': attendee,
            'forms': forms,
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
            # TODO: Remove `, Tracking.model != 'Attendee'` for next event
            'changes': session.query(Tracking).filter(
                or_(and_(Tracking.links.like('%attendee({})%'.format(id)), Tracking.model != 'Attendee'),
                    and_(Tracking.model == 'Attendee', Tracking.fk_id == id))).order_by(Tracking.when).all(),
            'pageviews': session.query(PageViewTracking).filter(PageViewTracking.which == repr(attendee)),
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
                if job.start_time + timedelta(minutes=job.duration + 120) > localized_now()],
        }

        if 'attendee_shifts' in cherrypy.url():
            return return_dict
        else:
            return render('registration/shifts.html', return_dict)

    @attendee_view
    @cherrypy.expose(['watchlist'])
    def attendee_watchlist(self, session, id, **params):
        attendee = session.attendee(id, allow_invalid=True)
        return_dict = {
            'attendee': attendee,
            'active_entries': session.guess_attendee_watchentry(attendee, active=True),
            'inactive_entries': session.guess_attendee_watchentry(attendee, active=False),
        }

        if 'attendee_watchlist' in cherrypy.url():
            return return_dict
        else:
            return render('registration/watchlist.html', return_dict)

    @ajax
    @attendee_view
    def update_attendee(self, session, message='', success=False, **params):
        attendee = load_attendee(session, params)

        if cherrypy.request.method == 'POST':
            message = save_attendee(session, attendee, params)

        if not message:
            success = True
            message = '{} has been saved'.format(attendee.full_name)

            if (attendee.is_new or attendee.badge_type != attendee.orig_value_of('badge_type')
                    or attendee.group_id != attendee.orig_value_of('group_id'))\
                    and not session.admin_can_create_attendee(attendee):
                attendee.badge_status = c.PENDING_STATUS
                message += ' as a pending badge'

            session.add(attendee)
            session.commit()

        return {
            'success': success,
            'message': message,
            'id': attendee.id,
        }

    def pending_badges(self, session, message=''):
        return {
            'pending_badges': session.query(Attendee)
            .filter_by(badge_status=c.PENDING_STATUS).filter(Attendee.paid != c.PENDING),
            'message': message,
        }

    @ajax
    def approve_badge(self, session, id):
        attendee = session.attendee(id)
        attendee.badge_status = c.NEW_STATUS
        session.add(attendee)
        session.commit()

        return {'added': id}
