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
Each receipt is owned by an attendee, group, or attendee account. Accounts own receipts bought during
prereg, which often cover multiple attendees. If attendee accounts are turned off, receipts are instead
owned by the first attendee listed on the receipt.

Receipt items can be purchases or credits added to the receipt. They do not involve money changing hands.

Receipt transactions keep track of payments and refunds, along with the method (e.g., cash, Stripe, Square)
and, if applicable, the Stripe ID for that transaction.



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
    
    # If the receipt covers attendees/groups besides the owner, they're tracked here
    attendee_ids = Column(UnicodeText)
    group_ids = Column(UnicodeText)

    @property
    def open_receipt_items(self):
        return [item for item in self.receipt_items if not item.closed]

    @property
    def closed_receipt_items(self):
        return [item for item in self.receipt_items if item.closed]

    @property
    def pending_txns(self):
        return [txn for txn in self.receipt_txns if txn.type == c.PENDING]

    @property
    def payment_txns(self):
        return [txn for txn in self.receipt_txns if txn.type == c.PAYMENT]

    @property
    def refund_txns(self):
        return [txn for txn in self.receipt_txns if txn.type == c.REFUND]

    @property
    def cancelled_txns(self):
        return [txn for txn in self.receipt_txns if txn.type == c.CANCELLED]

    @property
    def current_amount_owed(self):
        return sum([item.amount for item in self.open_receipt_items])

    def get_owner_email(self):
        from uber.models import Session
        with Session() as session:
            if self.owner_model == "Attendee":
                model = session.query(Attendee).filter_by(id=self.owner_id).first()
            elif self.owner_model == "Group":
                model = session.query(Group).filter_by(id=self.owner_id).first()
            elif self.owner_model == "AttendeeAccount":
                model = session.query(AttendeeAccount).filter_by(id=self.owner_id).first()
            
            return model.email if model else ''


class ReceiptTransaction(MagModel):
    receipt_id = Column(UUID, ForeignKey('model_receipt.id', ondelete='SET NULL'), nullable=True)
    receipt = relationship('ModelReceipt', foreign_keys=receipt_id,
                           cascade='save-update, merge',
                           backref=backref('receipt_txns', cascade='save-update, merge'))
    stripe_id = Column(UnicodeText, nullable=True)
    type = Column(Choice(c.TRANSACTION_TYPE_OPTS), default=c.PENDING)
    txn_method = Column(Choice(c.PAYMENT_METHOD_OPTS), default=c.STRIPE)
    amount = Column(Integer)
    added = Column(UTCDateTime, default=lambda: datetime.now(UTC))
    who = Column(UnicodeText)
    desc = Column(UnicodeText)


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
    fk_id = Column(UUID, index=True, nullable=True)
    fk_model = Column(UnicodeText)


