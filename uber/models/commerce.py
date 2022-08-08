from datetime import datetime

from pytz import UTC
from residue import JSON, CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import Integer

from sqlalchemy.orm import backref

from uber.config import c
from uber.models import MagModel
from uber.models.attendee import Attendee, AttendeeAccount, Group
from uber.models.types import default_relationship as relationship, Choice, DefaultColumn as Column


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



Right now we have a bunch of cost properties, hardcoded config, and some date-based functions for returning
cost. The most complex cost is the base badge price. This price includes:
- a base price per badge type
- early bird discounts (either by date or by quantity)
- late bird discounts (rolling badge prices)
- a promo code discount
- an age group discount
- a group discount
- a special price for dealer badges

If the badge price is set by an admin, nothing else applies. Dealer badges don't get any discounts either.
Age discounts are prioritized over group discounts. If none of these other credits apply, a promo code can be used.
This logic can all be changed in plugins.
"""
class ModelReceipt(MagModel):
    invoice_num = Column(Integer, default=0)
    owner_id = Column(UUID, index=True)
    owner_model = Column(UnicodeText)
    closed = Column(UTCDateTime, nullable=True)

    def get_open_receipt_items_before_datetime(self, dt):
        return [item for item in self.open_receipt_items if item.added < dt]

    @property
    def all_sorted_items_and_txns(self):
        return sorted(self.receipt_items + self.receipt_txns, key=lambda x: x.added)

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
    def pending_total(self):
        return sum([txn.amount for txn in self.receipt_txns if txn.intent_id and not txn.charge_id and not txn.cancelled])

    @property
    def payment_total(self):
        return sum([txn.amount for txn in self.receipt_txns if txn.charge_id or txn.method != c.STRIPE and txn.amount > 0])

    @property
    def refund_total(self):
        return sum([txn.amount for txn in self.receipt_txns if txn.refund_id or txn.amount < 0])

    @property
    def current_amount_owed(self):
        return sum([(item.amount * item.count) for item in self.open_receipt_items])

    @property
    def item_total(self):
        # This counts ALL purchases/credits, not just open ones
        return sum([(item.amount * item.count) for item in self.receipt_items])

    @property
    def txn_total(self):
        return self.payment_total + self.refund_total


class ReceiptTransaction(MagModel):
    receipt_id = Column(UUID, ForeignKey('model_receipt.id', ondelete='SET NULL'), nullable=True)
    receipt = relationship('ModelReceipt', foreign_keys=receipt_id,
                           cascade='save-update, merge',
                           backref=backref('receipt_txns', cascade='save-update, merge'))
    intent_id = Column(UnicodeText)
    charge_id = Column(UnicodeText)
    refund_id = Column(UnicodeText)
    method = Column(Choice(c.PAYMENT_METHOD_OPTS), default=c.STRIPE)
    amount = Column(Integer)
    refunded = Column(Integer, nullable=True)
    added = Column(UTCDateTime, default=lambda: datetime.now(UTC))
    cancelled = Column(UTCDateTime, nullable=True)
    who = Column(UnicodeText)
    desc = Column(UnicodeText)

    @property
    def is_pending_charge(self):
        return self.intent_id and not self.charge_id and not self.cancelled

    @property
    def stripe_id(self):
        # Return the most relevant Stripe ID for admins
        return self.refund_id or self.charge_id or self.intent_id


class ReceiptItem(MagModel):
    receipt_id = Column(UUID, ForeignKey('model_receipt.id', ondelete='SET NULL'), nullable=True)
    receipt = relationship('ModelReceipt', foreign_keys=receipt_id,
                           cascade='save-update, merge',
                           backref=backref('receipt_items', cascade='save-update, merge'))
    amount = Column(Integer)
    count = Column(Integer, default=1)
    added = Column(UTCDateTime, default=lambda: datetime.now(UTC))
    closed = Column(UTCDateTime, nullable=True)
    who = Column(UnicodeText)
    desc = Column(UnicodeText)
    revert_change = Column(JSON, default={}, server_default='{}')


