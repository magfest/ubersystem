from itertools import chain
from uber.models.attendee import AttendeeAccount

import cherrypy
import json
import re
from datetime import datetime
from decimal import Decimal
from pockets import groupify
from pockets.autolog import log
from sqlalchemy import and_, or_, func
from sqlalchemy.orm import joinedload, raiseload, subqueryload
from sqlalchemy.orm.exc import NoResultFound

from uber.config import c
from uber.custom_tags import datetime_local_filter, pluralize, format_currency, readable_join
from uber.decorators import ajax, all_renderable, csv_file, not_site_mappable, site_mappable
from uber.errors import HTTPRedirect
from uber.models import AdminAccount, ApiJob, ArtShowApplication, Attendee, Group, ModelReceipt, ReceiptItem, \
    ReceiptTransaction, Tracking, WorkstationAssignment
from uber.site_sections import devtools
from uber.utils import check, get_api_service_from_server, normalize_email, normalize_email_legacy, valid_email, \
    TaskUtils
from uber.payments import ReceiptManager, TransactionRequest, SpinTerminalRequest


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
    new_model = model.__class__(**model.to_dict())
    for col_name in item.revert_change:
        setattr(new_model, col_name, item.revert_change[col_name])

    for col_name in item.revert_change:
        receipt_items = ReceiptManager.process_receipt_change(model, col_name, receipt=receipt,
                                                             new_model=new_model)
        session.add_all(receipt_items)
        model.apply(item.revert_change, restricted=False)

    error = check(model)
    if not error:
        session.add(model)

    return error


def comped_receipt_item(item):
    return ReceiptItem(receipt_id=item.receipt.id,
                       department=item.department,
                       category=c.ITEM_COMP,
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
        refund_txn_candidates = []

        try:
            model = session.attendee(id)
            if model.in_promo_code_group and model.promo_code.group.buyer:
                group_leader_receipt = session.get_receipt_by_model(model.promo_code.group.buyer)
                potential_refund_amount = model.promo_code.cost * 100
                if group_leader_receipt:
                    txn = sorted([txn for txn in group_leader_receipt.refundable_txns
                                  if txn.amount_left >= potential_refund_amount], key=lambda x: x.added)[0]
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
            if receipt.current_receipt_amount < 0:
                refund_amount = receipt.current_receipt_amount * -1
                for txn in receipt.refundable_txns:
                    if txn.amount_left >= refund_amount:
                        refund_txn_candidates.append(txn.id)

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
                                                                  ModelReceipt.closed != None).all(),  # noqa: E711
            'message': message,
            'processors': {
                c.STRIPE: "Authorize.net" if c.AUTHORIZENET_LOGIN_ID else "Stripe",
                c.SQUARE: "SPIn" if c.SPIN_TERMINAL_AUTH_KEY else "Square",
                c.MANUAL: "Stripe"},
            'refund_txn_candidates': refund_txn_candidates,
        }
    
    def receipt_items_guide(self, session, message=''):
        return {
            'message': message,
            'processors': {
                c.STRIPE: "Authorize.net" if c.AUTHORIZENET_LOGIN_ID else "Stripe",
                c.SQUARE: "SPIn" if c.SPIN_TERMINAL_AUTH_KEY else "Square",
                c.MANUAL: "Stripe"}
        }

    def create_receipt(self, session, id='', blank=False):
        try:
            model = session.attendee(id)
        except NoResultFound:
            try:
                model = session.group(id)
            except NoResultFound:
                model = session.art_show_application(id)
        session.get_receipt_by_model(model, create_if_none="BLANK" if blank else "DEFAULT")

        raise HTTPRedirect('../reg_admin/receipt_items?id={}&message={}', model.id,
                           "{} receipt created.".format("Blank" if blank else "Default"))
    
    def edit_receipt_item(self, session, **params):
        item = session.receipt_item(params)
        txn_id = params.get('receipt_txn_id', None)

        if txn_id:
            receipt_txn = session.receipt_transaction(params.get('receipt_txn_id'))
            item.receipt_txn = receipt_txn
            if not item.closed:
                item.closed = receipt_txn.added
        elif txn_id == '':
            item.closed = None
            item.receipt_txn = None
        
        message = check(item)
        if message:
            session.rollback()
        else:
            message = "Receipt item updated."

        model = session.get_model_by_receipt(item.receipt)
        raise HTTPRedirect('../reg_admin/receipt_items?id={}&message={}', model.id, message)

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
                                department=params.get('department', c.OTHER_RECEIPT_ITEM),
                                category=params.get('category', c.OTHER),
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
                item.receipt_txn = None
                session.add(item)

        receipt = item_or_txn.receipt

        session.delete(item_or_txn)
        session.commit()

        return {
            'removed': id,
            'new_total': receipt.total_str,
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
            refund_amount = min(item.amount * item.count, item.receipt_txn.amount_left)
            if item.receipt_txn.method == c.SQUARE and c.SPIN_TERMINAL_AUTH_KEY:
                refund = SpinTerminalRequest(receipt=item.receipt, amount=refund_amount,
                                             method=item.receipt_txn.method)
            else:
                refund = TransactionRequest(receipt=item.receipt, amount=refund_amount, method=item.receipt_txn.method)

            # Add credit item first so that the refund is attached to it
            credit_item = comped_receipt_item(item)
            session.add(credit_item)
            session.commit()
            session.refresh(item.receipt)

            error = refund.refund_or_cancel(item.receipt_txn, department=item.receipt_txn.department)
            if error:
                return {'error': error}

            model = session.get_model_by_receipt(item.receipt)
            if isinstance(model, Attendee) and model.paid == c.HAS_PAID:
                model.paid = c.REFUNDED
                session.merge(model)

            if refund.refund_str == 'voided':
                # We had to void the payment so we need to update all other matching transactions and their receipts
                matching_txns = session.query(ReceiptTransaction).filter_by(
                    intent_id=item.receipt_txn.intent_id).filter(ReceiptTransaction.id != item.receipt_txn.id)
                for txn in matching_txns:
                    session.add(txn)
                    txn.refunded = txn.amount
                    refund_id = str(refund.response_id) or getattr(refund, 'ref_id')
                    refund.receipt_manager.create_refund_transaction(txn,
                                                                     "Automatic void of transaction " +
                                                                     txn.stripe_id, refund_id,
                                                                     txn.amount, method=refund.method)
                    refund.receipt_manager.update_transaction_refund(txn, txn.amount)
                    for voided_item in txn.receipt_items:
                        # We don't do this in other refund cases, but
                        # voiding is roughly equivalent to cancelling
                        session.add(voided_item)
                        voided_item.closed = None
                        voided_item.receipt_txn = None

            message_add = f" and its transaction {refund.refund_str}."
            session.add_all(refund.get_receipt_items_to_add())
        else:
            message_add = ". Its corresponding transaction was already fully refunded."

        item.comped = True
        session.commit()
        session.check_receipt_closed(item.receipt)

        return {'message': "Item comped{}".format(message_add)}

    @ajax
    def undo_refund_receipt_item(self, session, id='', **params):
        item = session.receipt_item(id)
        message = revert_receipt_item(session, item)

        if message:
            session.rollback()
            return {'error': message}
        
        session.commit()
        session.refresh(item.receipt)

        if item.receipt_txn and item.receipt_txn.amount_left:
            refund_amount = min(item.amount * item.count, item.receipt_txn.amount_left)
            if params.get('exclude_fees') and params['exclude_fees'].strip().lower() not in ('f', 'false', 'n', 'no', '0'):
                processing_fees = item.receipt_txn.calc_processing_fee(refund_amount)
                session.add(ReceiptItem(
                    receipt_id=item.receipt.id,
                    department=c.OTHER_RECEIPT_ITEM,
                    category=c.PROCESSING_FEES,
                    desc=f"Processing Fees for Refunding {item.desc}",
                    amount=processing_fees,
                    who=AdminAccount.admin_name() or 'non-admin',
                    txn_id=item.txn_id,
                    closed=datetime.now()
                ))
                refund_amount -= processing_fees

            if item.receipt_txn.method == c.SQUARE and c.SPIN_TERMINAL_AUTH_KEY:
                refund = SpinTerminalRequest(receipt=item.receipt, amount=refund_amount, method=item.receipt_txn.method)
            else:
                refund = TransactionRequest(receipt=item.receipt, amount=refund_amount, method=item.receipt_txn.method)

            error = refund.refund_or_cancel(item.receipt_txn, department=item.receipt_txn.department)
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
        session.check_receipt_closed(item.receipt)

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
                                     department=receipt.default_department,
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

        session.refresh(receipt)
        if receipt.current_amount_owed == 0:
            for item in receipt.open_purchase_items + receipt.open_credit_items:
                if item.receipt_txn:
                    item.closed = item.receipt_txn.added
                else:
                    item.txn_id = new_txn.id
                    item.closed = new_txn.added
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
                        department=txn.receipt.default_department,
                        amount=(new_amount - prior_amount) * -1,
                        receipt_items=txn.receipt.open_credit_items,
                        desc="Automatic refund of Stripe transaction " + txn.stripe_id,
                        who=AdminAccount.admin_name() or 'non-admin'
                    ))
                    for item in txn.receipt.open_credit_items:
                        item.closed = datetime.now()

            session.commit()
        else:
            messages.append("Error while refreshing from Stripe: " + error)

        return {
            'refresh': bool(messages),
            'message': ' '.join(messages) if messages else "Transaction already up-to-date.",
        }

    @ajax
    def resend_receipt(self, session, id, **params):
        from uber.tasks.registration import send_receipt_email
        txn = session.receipt_transaction(id)
        if not txn.receipt_info:
            return {'error': "There is no receipt info for this transaction!"}

        send_receipt_email.delay(txn.receipt_info.id)
        return {}

    @not_site_mappable
    def settle_up(self, session, id=''):
        txn = session.receipt_transaction(id)
        receipt = txn.receipt
        refund_amount = receipt.current_receipt_amount * -1
        if refund_amount <= 0:
            raise HTTPRedirect('../reg_admin/receipt_items?id={}&message={}',
                               session.get_model_by_receipt(receipt).id,
                               "We do not owe any money on this receipt!")
        elif not txn.refundable:
            raise HTTPRedirect('../reg_admin/receipt_items?id={}&message={}',
                               session.get_model_by_receipt(receipt).id,
                               "This transaction cannot be refunded automatically.")
        elif txn.amount_left < refund_amount:
            raise HTTPRedirect('../reg_admin/receipt_items?id={}&message={}',
                               session.get_model_by_receipt(receipt).id,
                               f"This transaction does not have {format_currency(refund_amount / 100)}"
                               " left to refund!")

        if txn.method == c.SQUARE and c.SPIN_TERMINAL_AUTH_KEY:
            refund = SpinTerminalRequest(receipt=txn.receipt, amount=refund_amount, method=txn.method)
        else:
            refund = TransactionRequest(receipt=txn.receipt, amount=refund_amount, method=txn.method)

        error = refund.refund_or_cancel(txn, department=txn.department)
        if error:
            raise HTTPRedirect('../reg_admin/receipt_items?id={}&message={}',
                               session.get_model_by_receipt(receipt).id, error)

        session.add_all(refund.get_receipt_items_to_add())
        session.commit()
        session.check_receipt_closed(receipt)

        raise HTTPRedirect('../reg_admin/receipt_items?id={}&message={}',
                           session.get_model_by_receipt(receipt).id,
                           f"{format_currency(refund_amount / 100)} refunded.")

    @not_site_mappable
    def process_full_refund(self, session, id='', attendee_id='', group_id='', exclude_fees=False):
        receipt = session.model_receipt(id)
        refund_total = 0
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
            refund_desc = f"Full Refund for {model.id}"
            if isinstance(model, Attendee):
                refund_desc = f"Refunding and Cancelling {model.full_name}'s Badge",
            elif isinstance(model, Group):
                refund_desc = f"Refunding and Cancelling Group {model.name}"

            session.add(ReceiptItem(
                receipt_id=receipt.id,
                department=receipt.default_department,
                category=c.CANCEL_ITEM,
                desc=refund_desc,
                amount=-(receipt.payment_total - receipt.refund_total),
                who=AdminAccount.admin_name() or 'non-admin',
            ))
            session.commit()
            session.refresh(receipt)

            for txn in receipt.refundable_txns:
                if txn.department == getattr(model, 'department', c.OTHER_RECEIPT_ITEM):
                    refund_amount = txn.amount_left
                    if exclude_fees:
                        processing_fees = txn.calc_processing_fee(refund_amount)
                        session.add(ReceiptItem(
                            receipt_id=txn.receipt.id,
                            department=c.OTHER_RECEIPT_ITEM,
                            category=c.PROCESSING_FEES,
                            desc=f"Processing Fees for Full Refund of {txn.desc}",
                            amount=processing_fees,
                            who=AdminAccount.admin_name() or 'non-admin',
                        ))
                        refund_amount -= processing_fees
                        session.commit()
                        session.refresh(receipt)

                    if txn.method == c.SQUARE and c.SPIN_TERMINAL_AUTH_KEY:
                        refund = SpinTerminalRequest(receipt=receipt, amount=refund_amount, method=txn.method)
                    else:
                        refund = TransactionRequest(receipt=receipt, amount=refund_amount, method=txn.method)

                    error = refund.refund_or_skip(txn)
                    if error:
                        raise HTTPRedirect('../reg_admin/receipt_items?id={}&message={}',
                                           attendee_id or group_id, error)
                    session.add_all(refund.get_receipt_items_to_add())
                    refund_total += refund.amount

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

            txn = sorted([txn for txn in group_leader_receipt.refundable_txns
                          if txn.amount_left >= group_refund_amount], key=lambda x: x.added)[0]
            if not txn:
                message = f"{error_start} group leader could not be refunded because "\
                    f"there wasn't a transaction with enough money left on it for {model.full_name}'s badge."
                raise HTTPRedirect('../reg_admin/receipt_items?id={}&message={}', attendee_id or group_id, message)

            session.add(ReceiptItem(
                receipt_id=txn.receipt.id,
                department=c.REG_RECEIPT_ITEM,
                category=c.REFUND,
                desc=f"Refunding {model.full_name}'s Promo Code",
                amount=-group_refund_amount,
                who=AdminAccount.admin_name() or 'non-admin',
            ))

            if exclude_fees:
                processing_fees = txn.calc_processing_fee(group_refund_amount)
                session.add(ReceiptItem(
                    receipt_id=txn.receipt.id,
                    department=c.OTHER_RECEIPT_ITEM,
                    category=c.PROCESSING_FEES,
                    desc=f"Processing Fees for Refund of {model.full_name}'s Promo Code",
                    amount=processing_fees,
                    who=AdminAccount.admin_name() or 'non-admin',
                ))
                group_refund_amount -= processing_fees
            
            session.commit()
            session.refresh(txn.receipt)

            if txn.method == c.SQUARE and c.SPIN_TERMINAL_AUTH_KEY:
                refund = SpinTerminalRequest(receipt=txn.receipt, amount=group_refund_amount, method=txn.method)
            else:
                refund = TransactionRequest(receipt=txn.receipt, amount=group_refund_amount, method=txn.method)

            error = refund.refund_or_cancel(txn, department=txn.department)
            if error:
                message = f"{error_start} group leader could not be refunded: {error}"
                raise HTTPRedirect('../reg_admin/receipt_items?id={}&message={}', attendee_id or group_id, message)
            session.add_all(refund.get_receipt_items_to_add())
            session.commit()
            session.check_receipt_closed(receipt)

        message_end = f" Their group leader was refunded {format_currency(group_refund_amount / 100)}."\
            if group_refund_amount else ""
        raise HTTPRedirect('../reg_admin/receipt_items?id={}&message={}',
                           attendee_id or group_id,
                           "{}'s registration has been cancelled and they have been refunded {}.{}".format(
                               getattr(model, 'full_name', None) or model.name, format_currency(refund_total / 100),
                               message_end
                               ))

    @ajax
    def refresh_model_receipt(self, session, id=''):
        try:
            model = session.attendee(id)
        except NoResultFound:
            try:
                model = session.group(id)
            except NoResultFound:
                model = session.art_show_application(id)

        receipt = session.get_receipt_by_model(model)

        old_cost = getattr(model, 'default_cost', getattr(model, 'cost', -1)) * 100
        old_receipt_total = receipt.item_total

        session.refresh_receipt_and_model(model)

        new_cost = getattr(model, 'default_cost', getattr(model, 'cost', -1)) * 100
        new_receipt_total = receipt.item_total
        formatted_new_cost = format_currency(new_cost / 100)
        formatted_new_receipt_total = format_currency(new_receipt_total / 100)

        if new_cost == old_cost and new_receipt_total == old_receipt_total:
            message = 'Model and receipt refreshed, but nothing changed.'
        elif new_cost == new_receipt_total:
            return {'message': 'Model and receipt refreshed and all discrepancies resolved!'}
        elif new_cost != old_cost and new_receipt_total != old_receipt_total:
            message = 'Model\'s default cost and receipt total updated.'
        else:
            message = "{} updated.".format('Model\'s default cost' if new_cost != old_cost else 'Receipt total')
        return {'new_cost': formatted_new_cost, 'new_receipt_total': formatted_new_receipt_total, 'message': message}

    @not_site_mappable
    def remove_promo_code(self, session, id=''):
        attendee = session.attendee(id)
        receipt = session.get_receipt_by_model(attendee)
        if attendee.paid == c.NEED_NOT_PAY:
            attendee.paid = c.NOT_PAID
        attendee.overridden_price = None
        if receipt:
            receipt_items = ReceiptManager.auto_update_receipt(attendee, receipt, {'promo_code_code': ''})
            session.add_all(receipt_items)

        attendee.promo_code = None
        attendee.badge_status = c.NEW_STATUS
        raise HTTPRedirect('../registration/form?id={}&message={}', id, "Promo code removed.")

    def attendee_accounts(self, session, message=''):
        return {
            'message': message,
            'accounts': session.query(AttendeeAccount).options(joinedload(AttendeeAccount.attendees),
                                                               raiseload('*')).all(),
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

        for domain in c.SSO_EMAIL_DOMAINS:
            attendees = attendees.filter(~Attendee.email.ilike(f"%{domain}%"))

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
                elif attendee.group_leader_account:
                    account_email = attendee.group_leader_account.email
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
            'attendees': attendees.options(joinedload(Attendee.group)).all(),
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
                account_email = attendee.group_leader_account.email if attendee.group_leader_account \
                    else attendee.email
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

        return " ".join(messages)

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

    def manage_workstations(self, session, message='', **params):
        if cherrypy.request.method == 'POST':
            skipped_reg_stations = []
            terminal_ids = []
            unmatched_terminal_ids = []
            new_workstation_params = []
            extra_warning = ""

            workstation_ids = [key.split('_', 1)[0] for key in params.keys()
                               if key.endswith('_reg_station_id') and not key.startswith('new')]
            for id in workstation_ids:
                specific_params = {key.split('_', 1)[1]: val for key, val in params.items() if key.startswith(id)}
                workstation = session.workstation_assignment(id)
                if not specific_params.get('reg_station_id'):
                    session.delete(workstation)
                else:
                    workstation.apply(specific_params)

                if specific_params.get('terminal_id'):
                    terminal_ids.append(specific_params['terminal_id'])

            if params.get('new_reg_station_id'):
                if isinstance(params['new_reg_station_id'], str):
                    new_workstation_params = [{key.split('_', 1)[1]: val for key, val in params.items()
                                              if key.startswith('new')}]
                else:
                    new_workstation_params = [{key.split('_', 1)[1]: val[i] for key, val in params.items()
                                              if key.startswith('new')}
                                              for i in range(len(params['new_reg_station_id']))]

            for new_params in new_workstation_params:
                reg_station_id = new_params['reg_station_id']
                if session.query(WorkstationAssignment).filter_by(reg_station_id=reg_station_id or -1).first():
                    skipped_reg_stations.append(new_params['reg_station_id'])
                else:
                    if new_params.get('terminal_id'):
                        terminal_ids.append(new_params['terminal_id'])
                    new_workstation = WorkstationAssignment()
                    session.add(new_workstation)
                    new_workstation.apply(new_params)

            for terminal_id in terminal_ids:
                terminal_lookup_key = terminal_id.lower().replace('-', '')
                if terminal_lookup_key not in c.TERMINAL_ID_TABLE:
                    unmatched_terminal_ids.append(terminal_id)

            if skipped_reg_stations:
                extra_warning += f" Station(s) {readable_join(skipped_reg_stations)} "\
                    "skipped because those assignments already exist."

            if unmatched_terminal_ids:
                extra_warning += " We could not find terminal ID(s) "\
                    f"{readable_join(unmatched_terminal_ids)} in our terminal lookup table."

            raise HTTPRedirect('manage_workstations?message={}', f"Workstations updated.{extra_warning}")

        return {
            'workstation_assignments': session.query(WorkstationAssignment).all(),
            'settlements': session.get_terminal_settlements(),
            'message': message,
        }

    def delete_workstation(self, session, id):
        try:
            workstation = session.workstation_assignment(id)
        except NoResultFound:
            raise HTTPRedirect('manage_workstations?message={}', f"Workstation {id} not found!")

        message = f"Workstation {workstation.reg_station_id} assignment deleted."
        session.delete(workstation)
        raise HTTPRedirect('manage_workstations?message={}', message)

    @ajax
    def update_workstation(self, session, id, **params):
        try:
            workstation = session.workstation_assignment(id)
        except NoResultFound:
            return {'success': False, 'message': "Workstation not found!"}

        workstation.reg_station_id = params.get('reg_station_id', '')
        workstation.terminal_id = params.get('terminal_id', '')
        workstation.printer_id = params.get('printer_id', '')
        workstation.minor_printer_id = params.get('minor_printer_id', '')
        session.commit()
        return {'success': True, 'message': "Workstation assignment updated."}

    def close_out_check(self, session):
        closeout_requests = c.REDIS_STORE.hgetall(c.REDIS_PREFIX + 'closeout_requests')
        processed_list = []

        for request_timestamp, terminal_ids in closeout_requests.items():
            closeout_report = c.REDIS_STORE.hget(c.REDIS_PREFIX + 'completed_closeout_requests', request_timestamp)
            if closeout_report:
                # TODO: Finish the report part of this
                report_dict = json.loads(closeout_report)
                log.debug(report_dict)
                return "All terminals have been closed out!"
            for terminal_id in terminal_ids:
                if c.REDIS_STORE.hget(c.REDIS_PREFIX + 'spin_terminal_closeout:' + terminal_id,
                                      'last_request_timestamp'):
                    processed_list.append(terminal_id)

    def close_out_terminals(self, session, **params):
        from uber.tasks.registration import close_out_terminals

        if not params.get('workstation_ids'):
            raise HTTPRedirect('manage_workstations?message={}',
                               "Please enter one or more workstation IDs to close out.")

        expanded_ids = re.sub(
            r'(\d+)-(\d+)',
            lambda match: ','.join(
                str(i) for i in range(
                    int(match.group(1)),
                    int(match.group(2)) + 1
                )
            ), params['workstation_ids']
        )
        id_list = [id.strip() for id in expanded_ids.split(',')]

        workstation_and_terminal_ids = []
        missing_terminals = []
        unmatched_terminals = []
        no_matching_workstations = True
        no_valid_workstations = True
        extra_warning = ""

        for id in id_list:
            terminal_id = ""
            workstation_assignment = session.query(WorkstationAssignment).filter_by(reg_station_id=id).first()
            if not workstation_assignment:
                pass
            elif not workstation_assignment.terminal_id:
                missing_terminals.append(id)
            else:
                lookup_key = workstation_assignment.terminal_id.lower().replace('-', '')
                if lookup_key not in c.TERMINAL_ID_TABLE:
                    unmatched_terminals.append(id)
                else:
                    terminal_id = c.TERMINAL_ID_TABLE[lookup_key]

            if workstation_assignment:
                no_matching_workstations = False

            if terminal_id:
                no_valid_workstations = False
                workstation_and_terminal_ids.append((id, terminal_id))

        close_out_terminals.delay(workstation_and_terminal_ids, AdminAccount.admin_name())

        if no_matching_workstations:
            raise HTTPRedirect('manage_workstations?message={}',
                               f"No workstations found matching ID(s) {params.get('workstation_ids')}")

        if missing_terminals:
            extra_warning += f" Workstation(s) {readable_join(missing_terminals)} did not have terminals assigned."
        if unmatched_terminals:
            extra_warning += " We could not find the terminals for workstation(s) "\
                f"{readable_join(unmatched_terminals)} in our lookup table."

        if no_valid_workstations:
            raise HTTPRedirect('manage_workstations?message={}',
                               "No workstations matching ID(s) "
                               f"{params.get('workstation_ids')} could be closed out.{extra_warning}")

        raise HTTPRedirect('manage_workstations?message={}',
                           "Started closeout for workstations matching ID(s) "
                           f"{params.get('workstation_ids')}.{extra_warning}")

    @csv_file
    @not_site_mappable
    def attendee_search_export(self, out, session, search_text='', order='last_first', invalid=''):
        filter = Attendee.badge_status.in_([c.NEW_STATUS, c.COMPLETED_STATUS, c.WATCHED_STATUS]
                                           ) if not invalid else None

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
                existing_account = session.query(AttendeeAccount).filter_by(
                    normalized_email=normalize_email_legacy(normalized_new_email)).first()
                if existing_account:
                    message = "That account already exists. You can instead reassign this account's attendees."
                else:
                    message = valid_email(new_email)
                    if not message:
                        account.email = new_email
                        session.add(account)
                        raise HTTPRedirect('attendee_account_form?id={}&message={}', account.id,
                                           "Account email updated!")

        return {
            'message': message,
            'account': account,
            'new_email': new_email,
        }

    @site_mappable
    def import_attendees(self, session, target_server='', api_token='',
                         query='', message='', which_import='', **params):
        from uber.tasks.registration import import_attendee_accounts
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
                admin_id = cherrypy.session.get('account_id')
                admin_name = session.admin_attendee().full_name
                import_attendee_accounts.delay(accounts, admin_id, admin_name, target_server, api_token)
                message = f"{len(accounts)} attendee accounts queued for import." 

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
                                                           ApiJob.cancelled == None,  # noqa: E711
                                                           ApiJob.errors == '').count()
            if existing_import:
                already_queued += 1
            else:
                import_job = ApiJob(
                    admin_id=admin_id,
                    admin_name=admin_name,
                    job_name="attendee_import",
                    target_server=target_server,
                    api_token=api_token,
                    query=id,
                    json_data={'badge_type': badge_type, 'admin_notes': admin_notes,
                               'badge_status': badge_status, 'full': True}
                )
                if len(attendee_ids) < 25:
                    TaskUtils.attendee_import(import_job)
                else:
                    session.add(import_job)
        session.commit()

        attendee_count = len(attendee_ids) - already_queued
        badge_label = c.BADGES[int(badge_type)].lower()

        if len(attendee_ids) > 100:
            query = ''  # Clear very large queries to prevent 502 errors

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
                                                           ApiJob.completed == None,  # noqa: E711
                                                           ApiJob.cancelled == None,  # noqa: E711
                                                           ApiJob.errors == '').count()
            if existing_import:
                already_queued += 1
            else:
                import_job = ApiJob(
                    admin_id=admin_id,
                    admin_name=admin_name,
                    job_name="group_import",
                    target_server=target_server,
                    api_token=api_token,
                    query=id,
                    json_data={'all': True}
                )
                if len(group_ids) < 25:
                    TaskUtils.group_import(import_job)
                else:
                    session.add(import_job)
        session.commit()

        attendee_count = len(group_ids) - already_queued

        if len(group_ids) > 100:
            query = ''  # Clear very large queries to prevent 502 errors

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
