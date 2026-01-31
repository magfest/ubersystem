from datetime import datetime
import stripe
import logging

from pytz import UTC
from residue import JSON, CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy import func, or_

from sqlalchemy.sql.functions import coalesce
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import Boolean, Integer
from sqlalchemy.dialects.postgresql.json import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import backref

from uber.config import c
from uber.custom_tags import format_currency
from uber.decorators import presave_adjustment, classproperty
from uber.models import MagModel
from uber.models.attendee import Attendee
from uber.models.types import default_relationship as relationship, Choice, DefaultColumn as Column
from uber.payments import ReceiptManager

log = logging.getLogger(__name__)


__all__ = [
    'ArbitraryCharge', 'MerchDiscount', 'MerchPickup', 'ModelReceipt', 'MPointsForCash',
    'NoShirt', 'OldMPointExchange', 'ReceiptInfo', 'ReceiptItem', 'ReceiptTransaction', 'Sale', 'TerminalSettlement']


class ArbitraryCharge(MagModel):
    amount = Column(Integer)
    what = Column(UnicodeText)
    when = Column(UTCDateTime, default=lambda: datetime.now(UTC))
    reg_station = Column(Integer, nullable=True)

    _repr_attr_names = ['what']


class MerchDiscount(MagModel):
    """Staffers can apply a single-use discount to any merch purchases."""
    attendee_id = Column(UUID, ForeignKey('attendee.id'), unique=True)
    uses = Column(Integer)


class MerchPickup(MagModel):
    picked_up_by_id = Column(UUID, ForeignKey('attendee.id'))
    picked_up_for_id = Column(UUID, ForeignKey('attendee.id'), unique=True)
    picked_up_by = relationship(
        Attendee,
        primaryjoin='MerchPickup.picked_up_by_id == Attendee.id',
        cascade='save-update,merge,refresh-expire,expunge')
    picked_up_for = relationship(
        Attendee,
        primaryjoin='MerchPickup.picked_up_for_id == Attendee.id',
        cascade='save-update,merge,refresh-expire,expunge')


class MPointsForCash(MagModel):
    attendee_id = Column(UUID, ForeignKey('attendee.id'))
    amount = Column(Integer)
    when = Column(UTCDateTime, default=lambda: datetime.now(UTC))


class NoShirt(MagModel):
    """
    Used to track when someone tried to pick up a shirt they were owed when we
    were out of stock, so that we can contact them later.
    """
    attendee_id = Column(UUID, ForeignKey('attendee.id'), unique=True)


class OldMPointExchange(MagModel):
    attendee_id = Column(UUID, ForeignKey('attendee.id'))
    amount = Column(Integer)
    when = Column(UTCDateTime, default=lambda: datetime.now(UTC))


class Sale(MagModel):
    attendee_id = Column(UUID, ForeignKey('attendee.id', ondelete='set null'), nullable=True)
    what = Column(UnicodeText)
    cash = Column(Integer, default=0)
    mpoints = Column(Integer, default=0)
    when = Column(UTCDateTime, default=lambda: datetime.now(UTC))
    reg_station = Column(Integer, nullable=True)
    payment_method = Column(Choice(c.SALE_OPTS), default=c.MERCH)


class ModelReceipt(MagModel):
    """
    Attendees, groups, and art show apps have a running receipt that has items and transactions added to it dynamically.

    Receipt items can be purchases or credits added to the receipt. They do not involve money changing hands.

    Receipt transactions keep track of payments and refunds, along with the method (e.g., cash, Stripe, Square)
    and reference IDs (e.g., Stripe's payment intent and charge IDs) for that transaction. In some cases, such
    as during prereg, there may be multiple receipt transactions created with the same reference ID across multiple
    receipts.
    """
    invoice_num = Column(Integer, default=0)
    owner_id = Column(UUID, index=True)
    owner_model = Column(UnicodeText)
    closed = Column(UTCDateTime, nullable=True)

    def close_all_items(self, session):
        for item in self.open_receipt_items:
            if item.receipt_txn:
                item.closed = item.receipt_txn.added
            else:
                if item.amount < 0:
                    latest_txn = self.sorted_txns[-1]
                else:
                    latest_txn = sorted([txn for txn in self.receipt_txns if txn.amount > 0],
                                        key=lambda x: x.added, reverse=True)[0]
                
                item.receipt_txn = latest_txn
                item.closed = datetime.now()
            session.add(item)
        session.commit()

    @property
    def all_sorted_items_and_txns(self):
        return sorted(self.receipt_items + self.receipt_txns, key=lambda x: x.added)
    
    @property
    def sorted_txns(self):
        return sorted([txn for txn in self.receipt_txns], key=lambda x: x.added)
    
    @property
    def sorted_items(self):
        return sorted([item for item in self.receipt_items], key=lambda x: x.added)

    @property
    def total_processing_fees(self):
        return sum([txn.calc_processing_fee(txn.amount) for txn in self.refundable_txns])

    @property
    def remaining_processing_fees(self):
        return sum([txn.calc_processing_fee(txn.amount_left) for txn in self.refundable_txns])

    @property
    def open_receipt_items(self):
        return [item for item in self.receipt_items if not item.closed]

    @property
    def open_purchase_items(self):
        return [item for item in self.open_receipt_items if item.amount >= 0]
    
    @property
    def open_credit_items(self):
        return [item for item in self.open_receipt_items if item.amount < 0]

    @property
    def charge_description_list(self):
        return ", ".join([item.desc + " x" + str(item.count) for item in self.open_purchase_items])

    @property
    def cancelled_txns(self):
        return [txn for txn in self.receipt_txns if txn.cancelled]

    @property
    def pending_txns(self):
        return [txn for txn in self.receipt_txns if txn.is_pending_charge]

    @property
    def refundable_txns(self):
        return [txn for txn in self.receipt_txns if txn.refundable]

    @property
    def pending_total(self):
        return sum([txn.amount for txn in self.receipt_txns if txn.is_pending_charge])

    @property
    def payment_total(self):
        return sum([txn.amount for txn in self.receipt_txns
                    if not txn.cancelled and txn.amount > 0 and (txn.charge_id or txn.intent_id == '')])

    @classproperty
    def payment_total_sql(cls):
        return coalesce(func.sum(ReceiptTransaction.amount).filter(
            ReceiptTransaction.amount > 0, ReceiptTransaction.cancelled == None).filter(
                or_(ReceiptTransaction.charge_id != '',
                    ReceiptTransaction.intent_id == '')), 0)
    
    @property
    def manual_payments(self):
        return [txn for txn in self.receipt_txns
                if not txn.cancelled and txn.amount > 0 and (
                    txn.intent_id == '' or txn.method == c.SQUARE and c.SPIN_TERMINAL_AUTH_KEY)]

    @property
    def payments_on_hold(self):
        return [txn for txn in self.receipt_txns if txn.on_hold and not txn.cancelled]

    @property
    def refund_total(self):
        return sum([txn.amount for txn in self.receipt_txns if txn.amount < 0]) * -1

    @classproperty
    def refund_total_sql(cls):
        return coalesce(func.sum(ReceiptTransaction.amount).filter(
            ReceiptTransaction.amount < 0) * -1, 0)
    
    @property
    def item_total(self):
        return sum([(item.amount * item.count) for item in self.receipt_items])

    @classproperty
    def item_total_sql(cls):
        return coalesce(func.sum(ReceiptItem.amount * ReceiptItem.count), 0)
    
    @classproperty
    def fkless_item_total_sql(cls):
        return coalesce(func.sum(ReceiptItem.amount * ReceiptItem.count).filter(
            ReceiptItem.fk_id == None
        ), 0)
    
    @property
    def txn_total(self):
        return self.payment_total - self.refund_total

    @property
    def current_receipt_amount(self):
        return self.item_total - self.txn_total

    @property
    def current_amount_owed(self):
        return max(0, self.current_receipt_amount)

    @property
    def has_at_con_payments(self):
        return any([txn for txn in self.receipt_txns if txn.method == c.SQUARE])

    @property
    def total_str(self):
        if self.closed:
            return "{} in {}".format(format_currency(abs(self.txn_total / 100)),
                                     "Payments" if self.txn_total >= 0 else "Refunds")

        return "{} in {} and {} in {} = {} owe {}".format(format_currency(abs(self.item_total / 100)),
                                                          "Purchases" if self.item_total >= 0 else "Credit",
                                                          format_currency(abs(self.txn_total / 100)),
                                                          "Payments" if self.txn_total >= 0 else "Refunds",
                                                          "They" if self.current_receipt_amount >= 0 else "We",
                                                          format_currency(abs(self.current_receipt_amount / 100)))
    
    @property
    def default_department(self):
        from uber.models import Session, Attendee, Group
        cls = Session.resolve_model(self.owner_model)
        if cls in [Attendee, Group]:
            with Session() as session:
                model = session.query(cls).filter_by(id=self.owner_id).first()
                if model and model.is_dealer:
                    return c.DEALER_RECEIPT_ITEM
        return getattr(cls, 'department')

    def get_last_incomplete_txn(self):
        from uber.models import Session

        for txn in sorted(self.pending_txns, key=lambda t: t.added, reverse=True):
            if c.AUTHORIZENET_LOGIN_ID:
                error = None
            else:
                error = txn.check_stripe_id()
            if error or txn.amount != self.current_amount_owed:
                if error or self.current_amount_owed == 0:
                    txn.cancelled = datetime.now()  # TODO: Add logs to txns/items and log the cancellation reason?

                if txn.amount != self.current_amount_owed and self.current_amount_owed:
                    if not c.AUTHORIZENET_LOGIN_ID:
                        txn.amount = self.current_amount_owed
                        stripe.PaymentIntent.modify(txn.intent_id, amount=txn.amount)
                    else:
                        txn.cancelled = datetime.now()

                if self.session:
                    self.session.add(txn)
                    self.session.commit()
                else:
                    with Session() as session:
                        session.add(txn)
                        session.commit()
                if not error and not txn.cancelled:
                    return txn
            else:
                return txn

    def process_full_refund(self, session, model, who='non-admin', exclude_fees=False):
        from uber.payments import RefundRequest

        refund_total = 0
        receipt_manager = ReceiptManager(self, who)
        refunds = receipt_manager.cancel_and_refund(model, exclude_fees=exclude_fees)

        if receipt_manager.error_message:
            return refund_total, receipt_manager.error_message
        else:
            if not refunds:
                session.add_all(receipt_manager.items_to_add)
            for _, (refund_amount, txns) in refunds.items():
                refund = RefundRequest(txns, refund_amount, skip_errors=True)

                error = refund.process_refund()
                if error:
                    return refund_total, error

                refund_total += refund_amount
                session.add_all(refund.items_to_add)
                session.add_all(receipt_manager.items_to_add)
                receipt_manager.items_to_add = []
        return refund_total, ''


class ReceiptTransaction(MagModel):
    """
    Transactions have two key properties: whether or not they were done through Stripe,
        and whether they represent a payment or a refund.

    Refunds have a negative `amount`, payments have a positive `amount`.

    Stripe payments will start with an `intent_id` and, if completed, have a `charge_id` set.
    Stripe refunds will have a `refund_id`.

    Stripe payments will track how much has been refunded for that transaction with `refunded` return
        this is an important number to track because it helps prevent refund errors.

    All payments keep a list of `receipt_items`. This lets admins track what has been paid for already,
        plus it allows admins to refund Stripe payments per item.
    """

    receipt_id = Column(UUID, ForeignKey('model_receipt.id', ondelete='SET NULL'), nullable=True)
    receipt = relationship('ModelReceipt', foreign_keys=receipt_id,
                           cascade='save-update, merge',
                           backref=backref('receipt_txns', cascade='save-update, merge'))
    receipt_info_id = Column(UUID, ForeignKey('receipt_info.id', ondelete='SET NULL'), nullable=True)
    receipt_info = relationship('ReceiptInfo', foreign_keys=receipt_info_id,
                                cascade='save-update, merge',
                                backref=backref('receipt_txns', cascade='save-update, merge'))
    refunded_txn_id = Column(UUID, ForeignKey('receipt_transaction.id', ondelete='SET NULL'), nullable=True)
    refunded_txn = relationship('ReceiptTransaction', foreign_keys='ReceiptTransaction.refunded_txn_id',
                                backref=backref('refund_txns', order_by='ReceiptTransaction.added'),
                                cascade='save-update,merge,refresh-expire,expunge',
                                remote_side='ReceiptTransaction.id',
                                single_parent=True)
    refunded = Column(Integer, default=0)
    intent_id = Column(UnicodeText)
    charge_id = Column(UnicodeText)
    refund_id = Column(UnicodeText)
    method = Column(Choice(c.PAYMENT_METHOD_OPTS), default=c.STRIPE)
    department = Column(Choice(c.RECEIPT_ITEM_DEPT_OPTS), default=c.OTHER_RECEIPT_ITEM)
    amount = Column(Integer)
    txn_total = Column(Integer, default=0)
    processing_fee = Column(Integer, default=0)
    added = Column(UTCDateTime, default=lambda: datetime.now(UTC))
    on_hold = Column(Boolean, default=False)
    cancelled = Column(UTCDateTime, nullable=True)
    who = Column(UnicodeText)
    desc = Column(UnicodeText)

    @property
    def available_actions(self):
        # A list of actions that admins can do to this item.
        # Each action corresponds to a function in reg_admin.py

        actions = []

        if self.receipt.closed or self.cancelled:
            return actions

        if self.intent_id and self.amount > 0:
            if not c.AUTHORIZENET_LOGIN_ID:
                actions.append('refresh_receipt_txn')
            if not self.charge_id:
                actions.append('cancel_receipt_txn')

        if not self.stripe_id:
            actions.append('remove_receipt_item')

        if self.receipt_info and self.receipt_info.fk_email_id:
            actions.append('resend_receipt')

        return actions

    @property
    def refundable(self):
        return not self.receipt.closed and self.charge_id and self.amount > 0 and not self.on_hold and \
            self.amount_left and self.amount_left != self.calc_processing_fee()

    @property
    def card_info(self):
        if self.receipt_info and self.receipt_info.card_data:
            return self.receipt_info.card_data.get('CardType', '') + ' ' + self.receipt_info.card_data['Last4']
        return ''

    @property
    def stripe_url(self):
        if not self.stripe_id or self.method != c.STRIPE:
            return ''

        if c.AUTHORIZENET_LOGIN_ID:
            if not self.charge_id:
                return ''
            if 'test' in c.AUTHORIZENET_ENDPOINT:
                return "https://sandbox.authorize.net/ui/themes/sandbox/transaction/transactiondetail.aspx?transID={}"\
                    .format(self.charge_id)
            else:
                return "https://account.authorize.net/ui/themes/anet/transaction/transactiondetail.aspx?transid={}"\
                    .format(self.charge_id)
        else:
            return "https://dashboard.stripe.com/payments/{}".format(self.intent_id or self.get_intent_id_from_refund())

    @property
    def amount_left(self):
        return self.amount - self.refunded

    @property
    def is_pending_charge(self):
        return self.intent_id and not self.charge_id and not self.cancelled

    @property
    def stripe_id(self):
        # Return the most relevant Stripe ID for admins
        return self.refund_id or self.charge_id or self.intent_id

    @property
    def total_processing_fee(self):
        if self.processing_fee and self.amount == self.txn_total:
            return self.processing_fee

        if c.AUTHORIZENET_LOGIN_ID:
            return 0

        intent = self.get_stripe_intent(expand=['latest_charge.balance_transaction'])
        if not intent.latest_charge.balance_transaction:
            return 0

        return intent.latest_charge.balance_transaction.fee_details[0].amount

    def calc_processing_fee(self, amount=0):
        from decimal import Decimal

        if not amount:
            if self.processing_fee:
                return self.processing_fee

            amount = self.amount

        refund_pct = Decimal(amount) / Decimal(self.txn_total)
        return int(refund_pct * Decimal(self.total_processing_fee))

    def check_stripe_id(self):
        # Check all possible Stripe IDs for invalid request errors
        # Stripe IDs become invalid if, for example, the Stripe API keys change

        if c.AUTHORIZENET_LOGIN_ID or self.method != c.STRIPE or not self.stripe_id:
            return

        refund_intent_id = None
        if self.refund_id:
            try:
                refund = stripe.Refund.retrieve(self.refund_id)
            except Exception as e:
                return e.user_message
            else:
                refund_intent_id = refund.payment_intent

        if self.intent_id or refund_intent_id:
            try:
                stripe.PaymentIntent.retrieve(self.intent_id or refund_intent_id)
            except Exception as e:
                return e.user_message

        if self.charge_id:
            try:
                stripe.Charge.retrieve(self.charge_id)
            except Exception as e:
                return e.user_message

    def get_intent_id_from_refund(self):
        if c.AUTHORIZENET_LOGIN_ID or not self.refund_id:
            return

        try:
            refund = stripe.Refund.retrieve(self.refund_id)
        except Exception as e:
            log.error(e)
        else:
            return refund.payment_intent

    def get_stripe_intent(self, expand=[]):
        if not self.stripe_id or c.AUTHORIZENET_LOGIN_ID:
            return

        intent_id = self.intent_id or self.get_intent_id_from_refund()

        try:
            return stripe.PaymentIntent.retrieve(intent_id, expand=expand)
        except Exception as e:
            log.error(e)

    def check_paid_from_stripe(self, intent=None):
        if self.charge_id or c.AUTHORIZENET_LOGIN_ID or self.method not in [c.STRIPE, c.MANUAL]:
            return

        intent = intent or self.get_stripe_intent()
        if intent and intent.status == "succeeded":
            new_charge_id = intent.latest_charge
            ReceiptManager.mark_paid_from_stripe_intent(intent)
            return new_charge_id

    def update_amount_refunded(self):
        from uber.models import Session
        if c.AUTHORIZENET_LOGIN_ID or not self.intent_id:
            return 0, ''

        last_refund_id = None
        refunded_total = 0
        # TODO: Ideally would like this to work with SPIn terminals too
        for refund in stripe.Refund.list(payment_intent=self.intent_id):
            refunded_total += refund.amount
            last_refund_id = refund.id
            self.refund_id = self.refund_id or last_refund_id
        with Session() as session:
            other_txns = session.query(ReceiptTransaction).filter_by(intent_id=self.intent_id
                                                                     ).filter(ReceiptTransaction.id != self.id)
            other_refunds = sum([txn.refunded for txn in other_txns])

        self.refunded = min(self.amount, refunded_total - other_refunds)
        return self.refunded, last_refund_id

    @property
    def cannot_delete_reason(self):
        if self.stripe_id:
            return "You cannot delete Stripe transactions."


class ReceiptItem(MagModel):
    purchaser_id = Column(UUID, index=True, nullable=True)
    receipt_id = Column(UUID, ForeignKey('model_receipt.id', ondelete='SET NULL'), nullable=True)
    receipt = relationship('ModelReceipt', foreign_keys=receipt_id,
                           cascade='save-update, merge',
                           backref=backref('receipt_items', cascade='save-update, merge'))
    txn_id = Column(UUID, ForeignKey('receipt_transaction.id', ondelete='SET NULL'), nullable=True)
    receipt_txn = relationship('ReceiptTransaction', foreign_keys=txn_id,
                               cascade='save-update, merge',
                               backref=backref('receipt_items', cascade='save-update, merge'))
    fk_id = Column(UUID, index=True, nullable=True)
    fk_model = Column(UnicodeText)
    department = Column(Choice(c.RECEIPT_ITEM_DEPT_OPTS), default=c.OTHER_RECEIPT_ITEM)
    category = Column(Choice(c.RECEIPT_CATEGORY_OPTS), default=c.OTHER)
    amount = Column(Integer)
    comped = Column(Boolean, default=False)
    reverted = Column(Boolean, default=False)
    count = Column(Integer, default=1)
    added = Column(UTCDateTime, default=lambda: datetime.now(UTC))
    closed = Column(UTCDateTime, nullable=True)
    who = Column(UnicodeText)
    desc = Column(UnicodeText)
    admin_notes = Column(UnicodeText)
    revert_change = Column(JSON, default={}, server_default='{}')

    @presave_adjustment
    def process_item_close(self):
        if self.closed and not self.orig_value_of('closed') and self.fk_id:
            if self.fk_model == 'PrintJob':
                print_job = self.session.print_job(self.fk_id)
                print_job.ready = True

    @property
    def total_amount(self):
        return self.amount * self.count

    @property
    def paid(self):
        if not self.closed:
            return
        return self.receipt_txn.added and self.receipt_txn.amount > 0
    
    @property
    def closed_type(self):
        if not self.closed:
            return ""
        if self.amount > 0 and self.receipt_txn.amount > 0:
            return "Paid"
        if self.amount < 0 and self.receipt_txn.amount < 0:
            return "Refunded"
        return "Closed"

    @property
    def available_actions(self):
        # A list of actions that admins can do to this item.
        # Each action should correspond to a function in reg_admin.py

        actions = []

        if self.receipt.closed:
            return actions

        if not self.closed:
            actions.append('remove_receipt_item')

        if not self.comped and self.amount > 0 and not self.reverted:
            actions.append('comp_receipt_item')
        if self.revert_change and not self.reverted and not self.comped:
            actions.append('undo_receipt_item')

        return actions

    @property
    def refundable(self):
        return self.receipt_txn and self.receipt_txn.refundable and not self.comped and not self.reverted and self.amount > 0

    @property
    def cannot_delete_reason(self):
        if self.closed:
            return "You cannot delete items with payments attached. \
                If necessary, please delete or cancel the payment first."


class ReceiptInfo(MagModel):
    fk_email_model = Column(UnicodeText)
    fk_email_id = Column(UnicodeText)
    terminal_id = Column(UnicodeText)
    reference_id = Column(UnicodeText)
    charged = Column(UTCDateTime)
    voided = Column(UTCDateTime, nullable=True)
    card_data = Column(MutableDict.as_mutable(JSONB), default={})
    emv_data = Column(MutableDict.as_mutable(JSONB), default={})
    txn_info = Column(MutableDict.as_mutable(JSONB), default={})
    signature = Column(UnicodeText)
    receipt_html = Column(UnicodeText)

    @property
    def response_code_str(self):
        if not self.txn_info or not self.txn_info['response']:
            return ''

        if self.receipt_txns[0].method == c.STRIPE and c.AUTHORIZENET_LOGIN_ID:
            match self.txn_info['response'].get('response_code', ''):
                case '1':
                    return 'Approved'
                case '2':
                    return 'Declined'
                case '3':
                    return 'Error'
                case '4':
                    return 'Held for Review'
                case _:
                    return ''

    @property
    def avs_str(self):
        if not self.txn_info or not self.txn_info['fraud_info']:
            log.error(self.txn_info['fraud_info'])
            return ''
        
        if self.receipt_txns[0].method == c.STRIPE and c.AUTHORIZENET_LOGIN_ID:
            match self.txn_info['fraud_info'].get('avs', ''):
                case 'A':
                    return "The street address matched, but the postal code did not."
                case 'B':
                    return "No address information was provided."
                case 'E':
                    return "The AVS check returned an error."
                case 'G':
                    return "The card was issued by a bank outside the U.S. and does not support AVS."
                case 'N':
                    return "Neither the street address nor postal code matched."
                case 'P':
                    return "AVS is not applicable for this transaction."
                case 'R':
                    return "Retry — AVS was unavailable or timed out."
                case 'S':
                    return "AVS is not supported by card issuer."
                case 'U':
                    return "Address information is unavailable."
                case 'W':
                    return "The US ZIP+4 code matches, but the street address does not."
                case 'X':
                    return "Both the street address and the US ZIP+4 code matched."
                case 'Y':
                    return "The street address and postal code matched."
                case 'Z':
                    return "The postal code matched, but the street address did not."
                case _:
                    return ''
    
    @property
    def cvv_str(self):
        if not self.txn_info or not self.txn_info['fraud_info']:
            return ''
        
        if self.receipt_txns[0].method == c.STRIPE and c.AUTHORIZENET_LOGIN_ID:
            match self.txn_info['fraud_info'].get('cvv', ''):
                case 'M':
                    return "CVV matched."
                case 'N':
                    return "CVV did not match."
                case 'P':
                    return "CVV was not processed."
                case 'S':
                    return "CVV should have been present but was not indicated."
                case 'U':
                    return "The issuer was unable to process the CVV check."
                case _:
                    return ''
                
    @property
    def cavv_str(self):
        if not self.txn_info or not self.txn_info['fraud_info']:
            return ''
        
        if self.receipt_txns[0].method == c.STRIPE and c.AUTHORIZENET_LOGIN_ID:
            match self.txn_info['fraud_info'].get('cavv', ''):
                case '0':
                    return "CAVV was not validated because erroneous data was submitted."
                case '1':
                    return "CAVV failed validation."
                case '2':
                    return "CAVV passed validation."
                case '3':
                    return "CAVV validation could not be performed; issuer attempt incomplete."
                case '4':
                    return "CAVV validation could not be performed; issuer system error."
                case '5':
                    return "Reserved for future use."
                case '6':
                    return "Reserved for future use."
                case '7':
                    return "CAVV failed validation, but the issuer is available. Valid for U.S.-issued card submitted to non-U.S acquirer."
                case '8':
                    return "CAVV passed validation and the issuer is available. Valid for U.S.-issued card submitted to non-U.S. acquirer."
                case '9':
                    return "CAVV failed validation and the issuer is unavailable. Valid for U.S.-issued card submitted to non-U.S acquirer."
                case 'A':
                    return "CAVV passed validation but the issuer unavailable. Valid for U.S.-issued card submitted to non-U.S acquirer."
                case 'B':
                    return "CAVV passed validation, information only, no liability shift."
                case _:
                    return "CAVV not validated."


class TerminalSettlement(MagModel):
    batch_timestamp = Column(UnicodeText)
    batch_who = Column(UnicodeText)
    requested = Column(UTCDateTime, default=lambda: datetime.now(UTC))
    workstation_num = Column(Integer, default=0)
    terminal_id = Column(UnicodeText)
    response = Column(MutableDict.as_mutable(JSONB), default={})
    error = Column(UnicodeText)
