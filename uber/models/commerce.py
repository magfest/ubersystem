from datetime import datetime, timedelta
import stripe

from pytz import UTC
from pockets.autolog import log
from residue import JSON, CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy import and_, case, func, or_, select

from sideboard.lib import request_cached_property
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import Boolean, Integer
from sqlalchemy.orm import backref

from uber.config import c
from uber.custom_tags import format_currency
from uber.models import MagModel
from uber.models.attendee import Attendee, AttendeeAccount, Group
from uber.models.types import default_relationship as relationship, Choice, DefaultColumn as Column
from uber.payments import ReceiptManager


__all__ = [
    'ArbitraryCharge', 'MerchDiscount', 'MerchPickup', 'ModelReceipt', 'MPointsForCash',
    'NoShirt', 'OldMPointExchange', 'ReceiptItem', 'ReceiptTransaction', 'Sale']


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


"""
Attendees and groups have a running receipt that has items and transactions added to it dynamically.

Receipt items can be purchases or credits added to the receipt. They do not involve money changing hands.

Receipt transactions keep track of payments and refunds, along with the method (e.g., cash, Stripe, Square)
and, if applicable, the Stripe ID for that transaction. In some cases, such as during prereg or when an attendee
pays for their art show application and badge at the same time, there may be multiple receipt transactions for one Stripe ID.
"""
class ModelReceipt(MagModel):
    invoice_num = Column(Integer, default=0)
    owner_id = Column(UUID, index=True)
    owner_model = Column(UnicodeText)
    closed = Column(UTCDateTime, nullable=True)

    @property
    def all_sorted_items_and_txns(self):
        return sorted(self.receipt_items + self.receipt_txns, key=lambda x: x.added)
    
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
    def closed_receipt_items(self):
        return [item for item in self.receipt_items if item.closed]

    @property
    def charge_description_list(self):
        return ", ".join([item.desc + " x" + str(item.count) for item in self.open_receipt_items if item.amount > 0])

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

    @hybrid_property
    def payment_total(self):
        return sum([txn.amount for txn in self.receipt_txns if not txn.cancelled and txn.amount > 0 and (txn.charge_id or txn.intent_id == '')])
    
    @payment_total.expression
    def payment_total(cls):
        return select([func.sum(ReceiptTransaction.amount)]
                     ).where(ReceiptTransaction.receipt_id == cls.id
                     ).where(ReceiptTransaction.cancelled == None
                     ).where(ReceiptTransaction.amount > 0
                     ).where(or_(ReceiptTransaction.charge_id != None, ReceiptTransaction.intent_id == '')
                     ).label('payment_total')

    @hybrid_property
    def refund_total(self):
        return sum([txn.amount for txn in self.receipt_txns if txn.amount < 0]) * -1

    @refund_total.expression
    def refund_total(cls):
        return select([func.sum(ReceiptTransaction.amount) * -1]
                     ).where(and_(ReceiptTransaction.amount < 0, ReceiptTransaction.receipt_id == cls.id)
                     ).label('refund_total')

    @hybrid_property
    def current_amount_owed(self):
        return max(0, self.current_receipt_amount)
    
    @current_amount_owed.expression
    def current_amount_owed(cls):
        return case([(cls.current_receipt_amount > 0, cls.current_receipt_amount)],
                    else_=0)

    @hybrid_property
    def current_receipt_amount(self):
        return self.item_total - self.txn_total

    @hybrid_property
    def item_total(self):
        return sum([(item.amount * item.count) for item in self.receipt_items])
    
    @item_total.expression
    def item_total(cls):
        return select([func.sum(ReceiptItem.amount * ReceiptItem.count)]
                     ).where(ReceiptItem.receipt_id == cls.id).label('item_total')

    @hybrid_property
    def txn_total(self):
        return self.payment_total - self.refund_total

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

    def get_last_incomplete_txn(self):
        from uber.models import Session

        for txn in sorted(self.pending_txns, key=lambda t: t.added, reverse=True):
            if c.AUTHORIZENET_LOGIN_ID:
                error = None
            else:
                error = txn.check_stripe_id()
            if error or txn.amount != self.current_amount_owed:
                if error or self.current_amount_owed == 0:
                    txn.cancelled = datetime.now() # TODO: Add logs to txns/items and log the automatic cancellation reason?

                if txn.amount != self.current_amount_owed and self.current_amount_owed:
                    if not c.AUTHORIZENET_LOGIN_ID:
                        txn.amount = self.current_amount_owed
                        stripe.PaymentIntent.modify(txn.intent_id, amount = txn.amount)
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


class ReceiptTransaction(MagModel):
    """
    Transactions have two key properties: whether or not they were done through Stripe,
        and whether they represent a payment or a refund.

    Refunds have a negative `amount`, payments have a positive `amount`.

    Stripe payments will start with an `intent_id` and, if completed, have a `charge_id` set.
    Stripe refunds will have a `refund_id`.

    Stripe payments will track how much has been refunded for that transaction with `refunded` --
        this is an important number to track because it helps prevent refund errors.

    All payments keep a list of `receipt_items`. This lets admins track what has been paid for already,
        plus it allows admins to refund Stripe payments per item.
    """

    receipt_id = Column(UUID, ForeignKey('model_receipt.id', ondelete='SET NULL'), nullable=True)
    receipt = relationship('ModelReceipt', foreign_keys=receipt_id,
                           cascade='save-update, merge',
                           backref=backref('receipt_txns', cascade='save-update, merge'))
    intent_id = Column(UnicodeText)
    charge_id = Column(UnicodeText)
    refund_id = Column(UnicodeText)
    method = Column(Choice(c.PAYMENT_METHOD_OPTS), default=c.STRIPE)
    amount = Column(Integer)
    txn_total = Column(Integer, default=0)
    processing_fee = Column(Integer, default=0)
    refunded = Column(Integer, default=0)
    added = Column(UTCDateTime, default=lambda: datetime.now(UTC))
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
        
        return actions

    @property
    def refundable(self):
        return not self.receipt.closed and self.charge_id and self.amount > 0 and \
            self.amount_left and self.amount_left != self.calc_processing_fee()

    @property
    def stripe_url(self):
        if not self.stripe_id:
            return ''
        
        if c.AUTHORIZENET_LOGIN_ID:
            if not self.charge_id:
                return ''
            if 'test' in c.AUTHORIZENET_ENDPOINT:
                return "https://sandbox.authorize.net/ui/themes/sandbox/transaction/transactiondetail.aspx?transID={}".format(self.charge_id)
            else:
                return "https://account.authorize.net/ui/themes/anet/transaction/transactiondetail.aspx?transid={}".format(self.charge_id)
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
        
        intent = self.get_stripe_intent(expand=['charges.data.balance_transaction'])
        if not intent.charges.data:
            return 0
        
        return intent.charges.data[0].balance_transaction.fee_details[0].amount
    
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

        if c.AUTHORIZENET_LOGIN_ID or not self.stripe_id:
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
                intent = stripe.PaymentIntent.retrieve(self.intent_id or refund_intent_id)
            except Exception as e:
                return e.user_message
            
        if self.charge_id:
            try:
                charge = stripe.Charge.retrieve(self.charge_id)
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
        if self.charge_id or c.AUTHORIZENET_LOGIN_ID:
            return

        intent = intent or self.get_stripe_intent()
        if intent and intent.status == "succeeded":
            new_charge_id = intent.charges.data[0].id
            ReceiptManager.mark_paid_from_stripe_intent(intent)
            return new_charge_id

    def update_amount_refunded(self):
        from uber.models import Session
        if c.AUTHORIZENET_LOGIN_ID or not self.intent_id:
            return 0, ''
        
        last_refund_id = None
        refunded_total = 0
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
    receipt_id = Column(UUID, ForeignKey('model_receipt.id', ondelete='SET NULL'), nullable=True)
    receipt = relationship('ModelReceipt', foreign_keys=receipt_id,
                           cascade='save-update, merge',
                           backref=backref('receipt_items', cascade='save-update, merge'))
    txn_id = Column(UUID, ForeignKey('receipt_transaction.id', ondelete='SET NULL'), nullable=True)
    receipt_txn = relationship('ReceiptTransaction', foreign_keys=txn_id,
                           cascade='save-update, merge',
                           backref=backref('receipt_items', cascade='save-update, merge'))
    amount = Column(Integer)
    comped = Column(Boolean, default=False)
    reverted = Column(Boolean, default=False)
    count = Column(Integer, default=1)
    added = Column(UTCDateTime, default=lambda: datetime.now(UTC))
    closed = Column(UTCDateTime, nullable=True)
    who = Column(UnicodeText)
    desc = Column(UnicodeText)
    revert_change = Column(JSON, default={}, server_default='{}')

    @property
    def total_amount(self):
        return self.amount * self.count

    @property
    def paid(self):
        if not self.closed:
            return
        return self.receipt_txn.added

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
        return self.receipt_txn.refundable and not self.comped and not self.reverted and self.amount > 0

    @property
    def cannot_delete_reason(self):
        if self.closed:
            return "You cannot delete items with payments attached. If necessary, please delete or cancel the payment first."
