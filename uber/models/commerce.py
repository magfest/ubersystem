from datetime import datetime

from pytz import UTC
from sideboard.lib.sa import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import Integer

from uber.config import c
from uber.models import MagModel
from uber.models.attendee import Attendee
from uber.models.types import default_relationship as relationship, Choice, \
    DefaultColumn as Column


__all__ = [
    'ArbitraryCharge', 'MerchDiscount', 'MerchPickup', 'MPointsForCash',
    'NoShirt', 'OldMPointExchange', 'Sale', 'StripeTransaction']


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
    attendee_id = Column(
        UUID, ForeignKey('attendee.id', ondelete='set null'), nullable=True)
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
    fk_id = Column(UUID)
    fk_model = Column(UnicodeText)
