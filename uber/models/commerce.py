from datetime import datetime

from pytz import UTC
from sideboard.lib.sa import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import Integer

from uber.config import c
from uber.models import MagModel
from uber.models.types import Choice, DefaultColumn as Column


__all__ = [
    'MerchDiscount', 'MPointsForCash', 'OldMPointExchange', 'Sale',
    'ArbitraryCharge', 'StripeTransaction']


class MerchDiscount(MagModel):
    """Staffers can apply a single-use discount to any merch purchases."""
    attendee_id = Column(UUID, ForeignKey('attendee.id'), unique=True)
    uses = Column(Integer)


class MPointsForCash(MagModel):
    attendee_id = Column(UUID, ForeignKey('attendee.id'))
    amount = Column(Integer)
    when = Column(UTCDateTime, default=lambda: datetime.now(UTC))


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


class ArbitraryCharge(MagModel):
    amount = Column(Integer)
    what = Column(UnicodeText)
    when = Column(UTCDateTime, default=lambda: datetime.now(UTC))
    reg_station = Column(Integer, nullable=True)

    _repr_attr_names = ['what']


class StripeTransaction(MagModel):
    stripe_id = Column(UnicodeText, nullable=True)
    type = Column(Choice(c.TRANSACTION_TYPE_OPTS), default=c.PAYMENT)
    amount = Column(Integer)
    when = Column(UTCDateTime, default=lambda: datetime.now(UTC))
    who = Column(UnicodeText)
    desc = Column(UnicodeText)
    fk_id = Column(UUID)
    fk_model = Column(UnicodeText)
