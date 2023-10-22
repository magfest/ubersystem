from itertools import chain
from uber.models.attendee import AttendeeAccount

import cherrypy
from datetime import datetime
from decimal import Decimal
from pockets import groupify
from pockets.autolog import log
from six import string_types
from sqlalchemy import and_, or_, func
from sqlalchemy.orm import joinedload, raiseload, subqueryload
from sqlalchemy.orm.exc import NoResultFound

from uber.config import c, _config
from uber.custom_tags import datetime_local_filter, pluralize, format_currency
from uber.decorators import ajax, all_renderable, csv_file, not_site_mappable, site_mappable
from uber.errors import HTTPRedirect
from uber.models import AdminAccount, ApiJob, ArtShowApplication, Attendee, Group, ModelReceipt, ReceiptItem, ReceiptTransaction, Tracking
from uber.site_sections import devtools
from uber.utils import check, get_api_service_from_server, normalize_email, normalize_email_legacy, valid_email, TaskUtils
from uber.payments import ReceiptManager, TransactionRequest

def check_custom_receipt_item_txn(params, is_txn=False):
    from decimal import Decimal
    if not params.get('amount'):
        return "You must enter a positive or negative amount."
    
    try:
        amount = Decimal(params['amount'])
    except Exception:
        return "The amount must be a number."

    if amount > 999999 or amount < -999999:
        return "Please enter a realistic number for the amount."
    if amount == 0:
        return "You cannot enter an amount of 0."

    if is_txn:
        if not params.get('method'):
            return "You must choose a payment method."
        if Decimal(params['amount']) < 0 and not params.get('desc'):
            return "You must enter a description when adding a refund."
    elif not params.get('desc'):
        return "You must describe the item you are adding or crediting."


def revert_receipt_item(session, item):
    receipt = item.receipt
    model = session.get_model_by_receipt(receipt)
    for col_name in item.revert_change:
        receipt_item = ReceiptManager.process_receipt_upgrade_item(model, col_name, receipt=receipt, new_val=item.revert_change[col_name])
        session.add(receipt_item)
        model.apply(item.revert_change, restricted=False)

    error = check(model)
    if not error:
        session.add(model)
    
    return error


def comped_receipt_item(item):
    return ReceiptItem(receipt_id=item.receipt.id,
                       desc="Credit for " + item.desc,
                       amount=item.amount * -1,
                       count=item.count,
                       who=AdminAccount.admin_name() or 'non-admin',
                    )


def assign_account_by_email(session, attendee, account_email):
    from uber.site_sections.preregistration import set_up_new_account

    account = session.query(AttendeeAccount).filter_by(normalized_email=normalize_email_legacy(account_email)).first()

    if c.ONE_MANAGER_PER_BADGE and attendee.managers:
        # It's too confusing for an admin to move someone to a new account and still see them on their old account
        # If an admin typoes the new account's email, that's a them problem
        attendee.managers.clear()

    if not account:
        set_up_new_account(session, attendee, account_email)
        session.commit()
        return "New account made for {} under email {}.".format(attendee.full_name, account_email)
    else:
        session.add_attendee_to_account(attendee, account)
        session.commit()
        return "{} is now being managed by account {}.".format(attendee.full_name, account_email)

@all_renderable()
class Root:
    def receipt_items(self, session, id, message=''):
        group_leader_receipt = None
        group_processing_fee = 0
        try:
            model = session.attendee(id)
            if model.in_promo_code_group and model.promo_code.group.buyer:
                group_leader_receipt = session.get_receipt_by_model(model.promo_code.group.buyer)
                potential_refund_amount = model.promo_code.cost * 100
                if group_leader_receipt:
                    txn = sorted([txn for txn in group_leader_receipt.refundable_txns if txn.amount_left >= potential_refund_amount],
                                    key=lambda x: x.added)[0]
                    group_processing_fee = txn.calc_processing_fee(potential_refund_amount)
        except NoResultFound:
            try:
                model = session.group(id)
            except NoResultFound:
                model = session.art_show_application(id)

        receipt = session.get_receipt_by_model(model)
        if receipt:
            receipt.changes = session.query(Tracking).filter(
                or_(Tracking.links.like('%model_receipt({})%'
                                        .format(receipt.id)),
                    and_(Tracking.model == 'ModelReceipt',
                    Tracking.fk_id == receipt.id))).order_by(Tracking.when).all()

        other_receipts = set()
        if isinstance(model, Attendee):
            for app in model.art_show_applications:
                other_receipt = session.get_receipt_by_model(app)
                if other_receipt:
                    other_receipt.changes = session.query(Tracking).filter(
                        or_(Tracking.links.like('%model_receipt({})%'
                                                .format(other_receipt.id)),
                            and_(Tracking.model == 'ModelReceipt',
                            Tracking.fk_id == other_receipt.id))).order_by(Tracking.when).all()
                    other_receipts.add(other_receipt)
            
        return {
            'attendee': model if isinstance(model, Attendee) else None,
            'group': model if isinstance(model, Group) else None,
            'art_show_app': model if isinstance(model, ArtShowApplication) else None,
            'group_leader_receipt': group_leader_receipt,
            'group_processing_fee': group_processing_fee,
            'receipt': receipt,
            'other_receipts': other_receipts,
            'closed_receipts': session.query(ModelReceipt).filter(ModelReceipt.owner_id == id,
                                                                  ModelReceipt.owner_model == model.__class__.__name__,
                                                                  ModelReceipt.closed != None).all(),
            'message': message,
        }

    def create_receipt(self, session, id='', blank=False):
        try:
            model = session.attendee(id)
        except NoResultFound:
            try:
                model = session.group(id)
            except NoResultFound:
                model = session.art_show_application(id)
        receipt = session.get_receipt_by_model(model, create_if_none="BLANK" if blank else "DEFAULT")

        raise HTTPRedirect('../reg_admin/receipt_items?id={}&message={}', model.id, "{} receipt created.".format("Blank" if blank else "Default"))


    @ajax
    def add_receipt_item(self, session, id='', **params):
        from decimal import Decimal

        receipt = session.model_receipt(id)

        message = check_custom_receipt_item_txn(params)
        if message:
            return {'error': message}

        amount = Decimal(params.get('amount', 0))

        if params.get('item_type', '') == 'credit':
            amount = amount * -1

        count = params.get('count')
        if count:
            try:
                count = int(params['count'])
            except Exception:
                return {'error': "The count must be a number."}

        session.add(ReceiptItem(receipt_id=receipt.id,
                                desc=params['desc'],
                                amount=amount * 100,
                                count=int(count or 1),
                                who=AdminAccount.admin_name() or 'non-admin'
                            ))

        try:
            session.commit()
        except Exception:
            return {'error': "Encountered an exception while trying to save item."}

        return {'success': True}

    @ajax
    def remove_receipt_item(self, session, id='', **params):
        try:
            item_or_txn = session.receipt_item(id)
        except NoResultFound:
            item_or_txn = session.receipt_transaction(id)

        if item_or_txn.cannot_delete_reason:
            return {'error': item_or_txn.cannot_delete_reason}

        if isinstance(item_or_txn, ReceiptTransaction):
            for item in item_or_txn.receipt_items:
                item.closed = None
                item.txn_id = None
                session.add(item)

        receipt = item_or_txn.receipt
        
        session.delete(item_or_txn)
        session.commit()

        return {
            'removed': id,
            'new_total': receipt.total_str,
            'disable_button': receipt.current_amount_owed == 0
        }

    @ajax
    def comp_receipt_item(self, session, id='', **params):
        item = session.receipt_item(id)
        credit_item = comped_receipt_item(item)
        session.add(credit_item)
        item.comped = True
        session.commit()

        return {'success': True}

    @ajax
    def undo_receipt_item(self, session, id='', **params):
        item = session.receipt_item(id)
        message = revert_receipt_item(session, item)
        
        if message:
            session.rollback()
            return {'error': message}

        item.reverted = True
        session.commit()

        return {'success': True}

    @ajax
    def comp_refund_receipt_item(self, session, id='', **params):
        item = session.receipt_item(id)
        
        if item.receipt_txn and item.receipt_txn.amount_left:
            refund = TransactionRequest(item.receipt, amount=min(item.amount, item.receipt_txn.amount_left))
            error = refund.refund_or_cancel(item.receipt_txn)
            if error:
                return {'error': error}
            
            model = session.get_model_by_receipt(item.receipt)
            if isinstance(model, Attendee) and model.paid == c.HAS_PAID:
                model.paid = c.REFUNDED
                session.merge(model)

            message_add = f" and its transaction {refund.refund_str}."
            session.add_all(refund.get_receipt_items_to_add())
        else:
            message_add = ". Its corresponding transaction was already fully refunded."

        credit_item = comped_receipt_item(item)
        session.add(credit_item)
        item.comped = True
        session.commit()

        return {'message': "Item comped{}".format(message_add)}

    @ajax
    def undo_refund_receipt_item(self, session, id='', **params):
        item = session.receipt_item(id)
        message = revert_receipt_item(session, item)
        
        if message:
            session.rollback()
            return {'error': message}

        if item.receipt_txn and item.receipt_txn.amount_left:
            refund_amount = min(item.amount, item.receipt_txn.amount_left)
            if params.get('exclude_fees'):
                processing_fees = item.receipt_txn.calc_processing_fee(refund_amount)
                session.add(ReceiptItem(
                    receipt_id=item.receipt.id,
                    desc=f"Processing Fees for Refunding {item.desc}",
                    amount=processing_fees,
                    who=AdminAccount.admin_name() or 'non-admin',
                ))
                refund_amount -= processing_fees

            refund = TransactionRequest(item.receipt, amount=refund_amount)
            error = refund.refund_or_cancel(item.receipt_txn)
            if error:
                return {'error': error}
            
            model = session.get_model_by_receipt(item.receipt)
            if isinstance(model, Attendee) and model.paid == c.HAS_PAID:
                model.paid = c.REFUNDED
                session.merge(model)
            
            message_add = f" and its transaction {refund.refund_str}."
            session.add_all(refund.get_receipt_items_to_add())
        else:
            message_add = ". Its corresponding transaction was already fully refunded."
        
        item.reverted = True
        session.commit()

        return {'message': "Item reverted{}".format(message_add)}

    @ajax
    def add_receipt_txn(self, session, id='', **params):
        from decimal import Decimal

        receipt = session.model_receipt(id)
        model = session.get_model_by_receipt(receipt)

        message = check_custom_receipt_item_txn(params, is_txn=True)
        if message:
            return {'error': message}

        amount = Decimal(params.get('amount', 0))

        if params.get('txn_type', '') == 'refund':
            amount = amount * -1
            if isinstance(model, Attendee) and model.paid == c.HAS_PAID:
                model.paid = c.REFUNDED
                session.add(model)

        new_txn = ReceiptTransaction(receipt_id=receipt.id,
                                     amount=amount * 100,
                                     method=params.get('method'),
                                     desc=params['desc'],
                                     who=AdminAccount.admin_name() or 'non-admin'
                                    )
        session.add(new_txn)

        try:
            session.commit()
        except Exception:
            session.rollback()
            return {'error': "Encountered an exception while trying to save transaction."}

        if (receipt.item_total - receipt.txn_total) <= 0 and amount > 0:
            for item in receipt.open_receipt_items:
                item.txn_id = item.txn_id or new_txn.id
                item.closed = datetime.now()
                session.add(item)
            if isinstance(model, Attendee) and model.paid == c.NOT_PAID:
                model.paid = c.HAS_PAID

            session.commit()

        return {'success': True}
        
    @ajax
    def cancel_receipt_txn(self, session, id='', **params):
        txn = session.receipt_transaction(id)

        if txn.charge_id:
            return {'error': "You cannot cancel a completed Stripe payment."}
        
        if txn.intent_id and not c.AUTHORIZENET_LOGIN_ID:
            error = txn.check_stripe_id()
            if error:
                return {'error': "Error while checking this transaction: " + error}
            charge_id = txn.check_paid_from_stripe()
            if charge_id:
                return {'error': "Stripe indicates that this payment has already completed."}
        
        txn.cancelled = datetime.now()
        for item in txn.receipt_items:
            item.closed = None
            item.txn_id = None
            session.add(item)
        txn.receipt_items = []
        session.commit()

        return {
            'cancelled': id,
            'time': datetime_local_filter(txn.cancelled),
            'new_total': txn.receipt.total_str,
            'disable_button': txn.receipt.current_amount_owed == 0
        }

    @ajax
    def refresh_receipt_txn(self, session, id='', **params):
        txn = session.receipt_transaction(id)
        messages = []

        error = txn.check_stripe_id()
        if not error:
            if txn.intent_id and not txn.charge_id:
                charge_id = txn.check_paid_from_stripe()
                if charge_id:
                    messages.append("Transaction marked as paid from Stripe.")

            if txn.amount_left > 0:
                prior_amount = txn.amount - txn.amount_left
                new_amount, last_refund_id = txn.update_amount_refunded()
                if prior_amount < new_amount:
                    messages.append("Refund amount updated from {} to {}.".format(format_currency(prior_amount / 100),
                                                                              format_currency(new_amount / 100)))
                    session.add(ReceiptTransaction(
                        receipt_id=txn.receipt_id,
                        refund_id=last_refund_id,
                        amount=(new_amount - prior_amount) * -1,
                        desc="Automatic refund of Stripe transaction " + txn.stripe_id,
                        who=AdminAccount.admin_name() or 'non-admin'
                    ))

            session.commit()
        else:
            messages.append("Error while refreshing from Stripe: " + error)
        
        return {
            'refresh': bool(messages),
            'message': ' '.join(messages) if messages else "Transaction already up-to-date.",
        }

    @ajax
    def refund_receipt_txn(self, session, id, amount, **params):
        txn = session.receipt_transaction(id)
        return {'error': float(params.get('amount', 0)) * 100}

        refund = TransactionRequest(txn.receipt, amount=Decimal(amount) * 100)
        error = refund.refund_or_cancel(txn)
        if error:
            return {'error': error}

        return {
            'refunded': id,
            'message': "Successfully refunded {}".format(format_currency(txn.refunded)),
            'refund_total': txn.refunded,
            'new_total': txn.receipt.total_str,
            'disable_button': txn.receipt.current_amount_owed == 0
        }
    
    @not_site_mappable
    def process_full_refund(self, session, id='', attendee_id='', group_id='', exclude_fees=False):
        receipt = session.model_receipt(id)
        refund_total = 0
        processing_fee_total = 0
        group_leader_receipt = None
        group_refund_amount = 0

        if attendee_id:
            model = session.attendee(attendee_id)
            if model.in_promo_code_group and model.promo_code.group.buyer:
                group_leader_receipt = session.get_receipt_by_model(model.promo_code.group.buyer)
                group_refund_amount = model.promo_code.cost * 100
        elif group_id:
            model = session.group(group_id)

        if session.get_receipt_by_model(model) == receipt:
            for txn in receipt.refundable_txns:
                refund_amount = txn.amount_left
                if exclude_fees:
                    processing_fees = txn.calc_processing_fee(txn.amount_left)
                    session.add(ReceiptItem(
                        receipt_id=txn.receipt.id,
                        desc=f"Processing Fees for Full Refund of {txn.desc}",
                        amount=processing_fees,
                        who=AdminAccount.admin_name() or 'non-admin',
                    ))
                    refund_amount -= processing_fees
                    processing_fee_total += processing_fees

                refund = TransactionRequest(receipt, amount=refund_amount)
                error = refund.refund_or_skip(txn)
                if error:
                    raise HTTPRedirect('../reg_admin/receipt_items?id={}&message={}', attendee_id or group_id, error)
                session.add_all(refund.get_receipt_items_to_add())
                refund_total += refund.amount

            session.add(ReceiptItem(
                receipt_id=receipt.id,
                desc=f"Refunding and Cancelling {model.full_name}'s Badge",
                amount=-(refund_total + processing_fee_total),
                who=AdminAccount.admin_name() or 'non-admin',
            ))

            receipt.closed = datetime.now()
            session.add(receipt)

        if attendee_id:
            model.badge_status = c.REFUNDED_STATUS
            model.paid = c.REFUNDED

        if group_id:
            model.status = c.CANCELLED
        
        session.add(model)
        session.commit()

        if group_refund_amount:
            if refund_total:
                error_start = f"This attendee was refunded {format_currency(refund_total / 100)}, but their"
            else:
                error_start = "This attendee's"

            txn = sorted([txn for txn in group_leader_receipt.refundable_txns if txn.amount_left >= group_refund_amount],
                                key=lambda x: x.added)[0]
            if not txn:
                message = f"{error_start} group leader could not be refunded \
                            because there wasn't a transaction with enough money left on it for {model.full_name}'s badge."
                raise HTTPRedirect('../reg_admin/receipt_items?id={}&message={}', attendee_id or group_id, message)
            
            session.add(ReceiptItem(
                receipt_id=txn.receipt.id,
                desc=f"Refunding {model.full_name}'s Promo Code",
                amount=-group_refund_amount,
                who=AdminAccount.admin_name() or 'non-admin',
            ))

            if exclude_fees:
                processing_fees = txn.calc_processing_fee(group_refund_amount)
                session.add(ReceiptItem(
                    receipt_id=txn.receipt.id,
                    desc=f"Processing Fees for Refund of {model.full_name}'s Promo Code",
                    amount=processing_fees,
                    who=AdminAccount.admin_name() or 'non-admin',
                ))
                group_refund_amount -= processing_fees
            
            refund = TransactionRequest(txn.receipt, amount=group_refund_amount)
            error = refund.refund_or_cancel(txn)
            if error:
                message = f"{error_start} group leader could not be refunded: {error}"
                raise HTTPRedirect('../reg_admin/receipt_items?id={}&message={}', attendee_id or group_id, message)
            session.add_all(refund.get_receipt_items_to_add())
            session.commit()

        message_end = f" Their group leader was refunded {format_currency(group_refund_amount / 100)}." if group_refund_amount else ""
        raise HTTPRedirect('../reg_admin/receipt_items?id={}&message={}',
                           attendee_id or group_id,
                           "{}'s registration has been cancelled and they have been refunded {}.{}".format(
                            getattr(model, 'full_name', None) or model.name, format_currency(refund_total / 100), message_end
                           ))

    @not_site_mappable
    def remove_promo_code(self, session, id=''):
        attendee = session.attendee(id)
        attendee.paid = c.NOT_PAID
        attendee.promo_code = None
        attendee.badge_status = c.NEW_STATUS
        raise HTTPRedirect('../registration/form?id={}&message={}', id, "Promo code removed.")

    def attendee_accounts(self, session, message=''):
        return {
            'message': message,
            'accounts': session.query(AttendeeAccount).options(joinedload(AttendeeAccount.attendees), raiseload('*')).all(),
        }

    def delete_attendee_account(self, session, id, message='', **params):
        account = session.attendee_account(id)
        if not account:
            message = "No account found!"
        else:
            session.delete(account)
        raise HTTPRedirect('attendee_accounts?message={}', message or 'Account deleted.')

    @site_mappable
    def orphaned_attendees(self, session, message='', **params):
        attendees = session.query(Attendee).filter(~Attendee.managers.any())

        if not params.get('show_all'):
            attendees = attendees.filter_by(is_valid=True, is_unassigned=False)

        if cherrypy.request.method == 'POST':
            account_email = params.get('account_email').strip()
            attendee = session.attendee(params.get('id'))

            if not attendee:
                message = "Attendee not found!"
            elif not account_email:
                if 'account_id' in params:
                    message = "Please enter an email address."
                else:
                    account_email = attendee.email

            if not message:
                message = valid_email(account_email)
            if not message:
                message = assign_account_by_email(session, attendee, account_email)

            if 'account_id' in params:
                raise HTTPRedirect('attendee_account_form?id={}&message={}', params.get('account_id'), message)

        return {
            'message': message,
            'attendees': attendees.options(raiseload('*')).all(),
            'show_all': params.get('show_all', ''),
        }

    def add_multiple_accounts(self, session, **params):
        attendee_ids = params.get('attendee_ids', '').split(',')
        account_emails = params.get('account_emails', '').split(',')
        tuple_list = zip(attendee_ids, account_emails)

        no_attendee = 0
        invalid_email = 0
        new_account = 0
        assigned = 0
        for id, account_email in tuple_list:
            attendee = session.attendee(id)
            if not attendee:
                no_attendee += 1
                break
            elif not account_email:
                account_email = attendee.email
            if valid_email(account_email):
                invalid_email += 1
                break
            
            message = assign_account_by_email(session, attendee, account_email)
            if 'New account' in message:
                new_account += 1
            else:
                assigned += 1

        messages = []
        if no_attendee:
            messages.append("{} attendee(s) could not be found.".format(no_attendee))
        if invalid_email:
            messages.append("{} email(s) entered were invalid.".format(invalid_email))
        if new_account:
            messages.append("{} new account(s) were created.".format(new_account))
        if assigned:
            messages.append("{} attendee(s) were assigned to existing accounts.".format(assigned))

        return  " ".join(messages)

    def add_all_accounts(self, session, show_all='', email_contains='', **params):
        attendees = session.query(Attendee).filter(~Attendee.managers.any())

        if not show_all:
            attendees = attendees.filter_by(is_valid=True, is_unassigned=False)
        if email_contains:
            attendees = attendees.filter(Attendee.normalized_email.contains(normalize_email_legacy(email_contains)))
        
        new_account = 0
        assigned = 0

        for attendee in attendees:
            message = assign_account_by_email(session, attendee, attendee.email)
            if 'New account' in message:
                new_account += 1
            else:
                assigned += 1
        
        messages = []
        if new_account:
            messages.append("{} new account(s) were created.".format(new_account))
        if assigned:
            messages.append("{} attendee(s) were assigned to existing accounts.".format(assigned))
        
        raise HTTPRedirect('orphaned_attendees?show_all={}&message={}', show_all, ' '.join(messages))

    def payment_pending_attendees(self, session):
        possibles = session.possible_match_list()
        attendees = []
        pending = session.query(Attendee).filter_by(paid=c.PENDING).filter(Attendee.badge_status != c.INVALID_STATUS)
        for attendee in pending:
            attendees.append([attendee, set(possibles[attendee.email.lower()] + 
                                            possibles[attendee.first_name, attendee.last_name])])
        return {
            'attendees': attendees,
        }
    
    @ajax
    def invalidate_badge(self, session, id):
        attendee = session.attendee(id)
        attendee.badge_status = c.INVALID_STATUS
        session.add(attendee)

        session.commit()

        return {'invalidated': id}

    def attendees_who_owe_money(self, session):
        unpaid_attendees = [attendee for attendee in session.attendees_with_badges() 
                            if attendee.amount_unpaid]
        return {
            'attendees': unpaid_attendees,
        }

    @csv_file
    @not_site_mappable
    def attendee_search_export(self, out, session, search_text='', order='last_first', invalid=''):
        filter = Attendee.badge_status.in_([c.NEW_STATUS, c.COMPLETED_STATUS, c.WATCHED_STATUS]) if not invalid else None
        
        search_text = search_text.strip()
        if search_text:
            attendees, error = session.search(search_text) if invalid else session.search(search_text, filter)

        if error:
            raise HTTPRedirect('../registration/index?search_text={}&order={}&invalid={}&message={}'
                              ).format(search_text, order, invalid, error)
        attendees = attendees.order(order)

        rows = devtools.prepare_model_export(Attendee, filtered_models=attendees)
        for row in rows:
            out.writerow(row)

    def attendee_account_form(self, session, id, message='', **params):
        account = session.attendee_account(id)

        new_email = params.get('new_account_email', '')
        if cherrypy.request.method == 'POST' and new_email:
            normalized_new_email = normalize_email(new_email)
            if normalize_email_legacy(normalized_new_email) == normalize_email_legacy(account.normalized_email):
                message = "That is already the email address for this account!"
            else:
                existing_account = session.query(AttendeeAccount).filter_by(normalized_email=normalize_email_legacy(normalized_new_email)).first()
                if existing_account:
                    message = "That account already exists. You can instead reassign this account's attendees."
                else:
                    message = valid_email(new_email)
                    if not message:
                        account.email = new_email
                        session.add(account)
                        raise HTTPRedirect('attendee_account_form?id={}&message={}', account.id, "Account email updated!")

        return {
            'message': message,
            'account': account,
            'new_email': new_email,
        }

    @site_mappable
    def import_attendees(self, session, target_server='', api_token='', query='', message='', which_import='', **params):
        service, service_message, target_url = get_api_service_from_server(target_server, api_token)
        message = message or service_message

        attendees, existing_attendees, results = {}, {}, {}
        accounts, existing_accounts = {}, {}
        groups, existing_groups = {}, {}
        results_name, href_base = '', ''

        if service and which_import:
            try:
                if which_import == 'attendees':
                    results = service.attendee.export(query=query)
                    results_name = 'attendees'
                    href_base = '{}/reg_admin/attendee_account_form?id={}'
                elif which_import == 'accounts':
                    results = service.attendee_account.export(query=query, all=params.get('all', False))
                    results_name = 'accounts'
                    href_base = '{}/registration/form?id={}'
                elif which_import == 'groups':
                    if params.get('dealers', ''):
                        status = c.DEALER_STATUS.get(int(params.get('dealer_status', 0)), None)
                        if not status:
                            message = "Invalid group status."
                        else:
                            results = service.group.dealers(status=status)
                    else:
                        results = service.group.export(query=query)
                    results_name = 'groups'
                    href_base = '{}/group_admin/form?id={}'

            except Exception as ex:
                message = str(ex)

        if cherrypy.request.method == 'POST' and not message:
            models = results.get(results_name, [])
            for model in models:
                model['href'] = href_base.format(target_url, model['id'])

            if models and which_import == 'attendees':
                attendees = models
                attendees_by_name_email = groupify(attendees, lambda a: (
                    a['first_name'].lower(),
                    a['last_name'].lower(),
                    normalize_email_legacy(a['email']),
                ))

                filters = [
                    and_(
                        func.lower(Attendee.first_name) == first,
                        func.lower(Attendee.last_name) == last,
                        Attendee.normalized_email == email,
                    )
                    for first, last, email in attendees_by_name_email.keys()
                ]

                existing_attendees = session.query(Attendee).filter(or_(*filters)).all()
                for attendee in existing_attendees:
                    existing_key = (attendee.first_name.lower(), attendee.last_name.lower(), attendee.normalized_email)
                    attendees_by_name_email.pop(existing_key, {})
                attendees = list(chain(*attendees_by_name_email.values()))

            if models and which_import == 'accounts':
                accounts = models
                accounts_by_email = groupify(accounts, lambda a: normalize_email(a['email']))

                existing_accounts = session.query(AttendeeAccount).filter(
                    AttendeeAccount.email.in_(accounts_by_email.keys())) \
                    .options(subqueryload(AttendeeAccount.attendees)).all()
                for account in existing_accounts:
                    existing_key = account.email
                    accounts_by_email.pop(existing_key, {})
                accounts = list(chain(*accounts_by_email.values()))

            if models and which_import == 'groups':
                groups = models
                groups_by_name = groupify(groups, lambda g: g['name'])

                existing_groups = session.query(Group).filter(Group.name.in_(groups_by_name.keys())) \
                    .options(subqueryload(Group.attendees)).all()
                for group in existing_groups:
                    existing_key = group.name
                    groups_by_name.pop(existing_key, {})
                groups = list(chain(*groups_by_name.values()))

        return {
            'target_server': target_server,
            'api_token': api_token,
            'query': query,
            'message': message,
            'which_import': which_import,
            'unknown_ids': results.get('unknown_ids', []),
            'unknown_emails': results.get('unknown_emails', []),
            'unknown_names': results.get('unknown_names', []),
            'unknown_names_and_emails': results.get('unknown_names_and_emails', []),
            'attendees': attendees,
            'existing_attendees': existing_attendees,
            'accounts': accounts,
            'existing_accounts': existing_accounts,
            'groups': groups,
            'existing_groups': existing_groups,
        }

    def confirm_import_attendees(self, session, badge_type, badge_status, 
                                 admin_notes, target_server, api_token, query, attendee_ids, **params):
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('import_attendees?target_server={}&api_token={}&query={}',
                               target_server,
                               api_token,
                               query)

        admin_id = cherrypy.session.get('account_id')
        admin_name = session.admin_attendee().full_name
        already_queued = 0
        attendee_ids = attendee_ids if isinstance(attendee_ids, list) else [attendee_ids]

        for id in attendee_ids:
            existing_import = session.query(ApiJob).filter(ApiJob.job_name == "attendee_import",
                                            ApiJob.query == id,
                                            ApiJob.cancelled == None,
                                            ApiJob.errors == '').count()
            if existing_import:
                already_queued += 1
            else:
                import_job = ApiJob(
                    admin_id = admin_id,
                    admin_name = admin_name,
                    job_name = "attendee_import",
                    target_server = target_server,
                    api_token = api_token,
                    query = id,
                    json_data = {'badge_type': badge_type, 'admin_notes': admin_notes, 'badge_status': badge_status, 'full': True}
                )
                if len(attendee_ids) < 25:
                    TaskUtils.attendee_import(import_job)
                else:
                    session.add(import_job)
            session.commit()

        attendee_count = len(attendee_ids) - already_queued
        badge_label = c.BADGES[int(badge_type)].lower()

        if len(attendee_ids) > 100:
            query = '' # Clear very large queries to prevent 502 errors

        raise HTTPRedirect(
            'import_attendees?target_server={}&api_token={}&query={}&message={}',
            target_server,
            api_token,
            query,
            '{count} attendee{s} imported with {a}{badge_label} badge{s}.{queued}'.format(
                count=attendee_count,
                s=pluralize(attendee_count),
                a=pluralize(attendee_count, singular='an ' if badge_label.startswith('a') else 'a ', plural=''),
                badge_label=badge_label,
                queued='' if not already_queued else ' {} badges are already queued for import.'.format(already_queued),
            )
        )

    def confirm_import_attendee_accounts(self, session, target_server, api_token, query, account_ids):
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('import_attendees?target_server={}&api_token={}&query={}&which_import={}',
                               target_server,
                               api_token,
                               query,
                               'accounts')

        admin_id = cherrypy.session.get('account_id')
        admin_name = session.admin_attendee().full_name
        already_queued = 0
        account_ids = account_ids if isinstance(account_ids, list) else [account_ids]

        for id in account_ids:
            existing_import = session.query(ApiJob).filter(ApiJob.job_name == "attendee_account_import",
                                            ApiJob.query == id,
                                            ApiJob.completed == None,
                                            ApiJob.cancelled == None,
                                            ApiJob.errors == '').count()
            if existing_import:
                already_queued += 1
            else:
                import_job = ApiJob(
                    admin_id = admin_id,
                    admin_name = admin_name,
                    job_name = "attendee_account_import",
                    target_server = target_server,
                    api_token = api_token,
                    query = id,
                    json_data = {'all': False}
                )
                if len(account_ids) < 25:
                    TaskUtils.attendee_account_import(import_job)
                else:
                    session.add(import_job)
            session.commit()

        attendee_count = len(account_ids) - already_queued

        if len(account_ids) > 100:
            query = '' # Clear very large queries to prevent 502 errors

        raise HTTPRedirect(
            'import_attendees?target_server={}&api_token={}&query={}&message={}&which_import={}',
            target_server,
            api_token,
            query,
            '{count} attendee account{s} queued for import.{queued}'.format(
                count=attendee_count,
                s=pluralize(attendee_count),
                queued='' if not already_queued else ' {} accounts are already queued for import.'.format(already_queued),
            ),
            'accounts',
        )
    
    def confirm_import_groups(self, session, target_server, api_token, query, group_ids):
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect('import_attendees?target_server={}&api_token={}&query={}&which_import={}',
                               target_server,
                               api_token,
                               query,
                               'groups')

        admin_id = cherrypy.session.get('account_id')
        admin_name = session.admin_attendee().full_name
        already_queued = 0
        group_ids = group_ids if isinstance(group_ids, list) else [group_ids]

        for id in group_ids:
            existing_import = session.query(ApiJob).filter(ApiJob.job_name == "group_import",
                                            ApiJob.query == id,
                                            ApiJob.completed == None,
                                            ApiJob.cancelled == None,
                                            ApiJob.errors == '').count()
            if existing_import:
                already_queued += 1
            else:
                import_job = ApiJob(
                    admin_id = admin_id,
                    admin_name = admin_name,
                    job_name = "group_import",
                    target_server = target_server,
                    api_token = api_token,
                    query = id,
                    json_data = {'all': True}
                )
                if len(group_ids) < 25:
                    TaskUtils.group_import(import_job)
                else:
                    session.add(import_job)
            session.commit()

        attendee_count = len(group_ids) - already_queued

        if len(group_ids) > 100:
            query = '' # Clear very large queries to prevent 502 errors

        raise HTTPRedirect(
            'import_attendees?target_server={}&api_token={}&query={}&message={}&which_import={}',
            target_server,
            api_token,
            query,
            '{count} group{s} queued for import.{queued}'.format(
                count=attendee_count,
                s=pluralize(attendee_count),
                queued='' if not already_queued else ' {} groups are already queued for import.'.format(already_queued),
            ),
            'groups',
        )
