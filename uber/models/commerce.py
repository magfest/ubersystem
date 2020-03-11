from datetime import datetime

from pytz import UTC
from residue import JSON, CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import Integer

from uber.config import c
from uber.models import MagModel
from uber.models.attendee import Attendee, Group
from uber.models.types import default_relationship as relationship, Choice, DefaultColumn as Column


__all__ = [
    'ArbitraryCharge', 'MerchDiscount', 'MerchPickup', 'MPointsForCash',
    'NoShirt', 'OldMPointExchange', 'ReceiptItem', 'Sale', 'StripeTransaction']


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


class StripeTransaction(MagModel):
    stripe_id = Column(UnicodeText, nullable=True)
    type = Column(Choice(c.TRANSACTION_TYPE_OPTS), default=c.PAYMENT)
    amount = Column(Integer)
    when = Column(UTCDateTime, default=lambda: datetime.now(UTC))
    who = Column(UnicodeText)
    desc = Column(UnicodeText)
    attendees = relationship('StripeTransactionAttendee', backref='stripe_transaction')
    groups = relationship('StripeTransactionGroup', backref='stripe_transaction')


class StripeTransactionAttendee(MagModel):
    txn_id = Column(UUID, ForeignKey('stripe_transaction.id'))
    attendee_id = Column(UUID, ForeignKey('attendee.id'))
    share = Column(Integer)


class StripeTransactionGroup(MagModel):
    txn_id = Column(UUID, ForeignKey('stripe_transaction.id'))
    group_id = Column(UUID, ForeignKey('group.id'))
    share = Column(Integer)


class ReceiptItem(MagModel):
    attendee_id = Column(UUID, ForeignKey('attendee.id', ondelete='SET NULL'), nullable=True)
    attendee = relationship(
        Attendee, backref='receipt_items', foreign_keys=attendee_id, cascade='save-update,merge,refresh-expire,expunge')

    group_id = Column(UUID, ForeignKey('group.id', ondelete='SET NULL'), nullable=True)
    group = relationship(
        Group, backref='receipt_items', foreign_keys=group_id, cascade='save-update,merge,refresh-expire,expunge')

    txn_id = Column(UUID, ForeignKey('stripe_transaction.id', ondelete='SET NULL'), nullable=True)
    stripe_transaction = relationship(
        StripeTransaction, backref='receipt_items',
        foreign_keys=txn_id, cascade='save-update,merge,refresh-expire,expunge')
    txn_type = Column(Choice(c.TRANSACTION_TYPE_OPTS), default=c.PAYMENT)
    payment_method = Column(Choice(c.PAYMENT_METHOD_OPTS), default=c.STRIPE)
    amount = Column(Integer)
    when = Column(UTCDateTime, default=lambda: datetime.now(UTC))
    who = Column(UnicodeText)
    desc = Column(UnicodeText)
    cost_snapshot = Column(JSON, default={}, server_default='{}')
    refund_snapshot = Column(JSON, default={}, server_default='{}')
