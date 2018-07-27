from datetime import datetime

from pytz import UTC
from residue import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import Integer

from uber.config import c
from uber.models import MagModel
from uber.models.admin import AdminAccount
from uber.models.attendee import Attendee
from uber.models.types import default_relationship as relationship, Choice, DefaultColumn as Column
from uber.utils import report_critical_exception


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
    fk_id = Column(UUID)
    fk_model = Column(UnicodeText)

    def process_refund(self):
        """
        Attempts to refund self
        Returns:
            error: an error message
            response: a Stripe Refund() object, or None
        """
        import stripe
        from pockets.autolog import log

        if self.type != c.PAYMENT:
            return 'This is not a payment and cannot be refunded.', None
        else:
            log.debug(
                'REFUND: attempting to refund stripeID {} {} cents for {}',
                self.stripe_id, self.amount, self.desc)
            try:
                response = stripe.Refund.create(
                    charge=self.stripe_id, reason='requested_by_customer')
            except stripe.StripeError as e:
                error_txt = 'Error while calling process_refund' \
                            '(self, stripeID={!r})'.format(self.stripe_id)
                report_critical_exception(
                    msg=error_txt,
                    subject='ERROR: MAGFest Stripe invalid request error')
                return 'An unexpected problem occurred: ' + str(e), None

            if self.session:
                self.session.add(StripeTransaction(
                    stripe_id=response.id or None,
                    amount=response.amount,
                    desc=self.desc,
                    type=c.REFUND,
                    who=AdminAccount.admin_name() or 'non-admin',
                    fk_id=self.fk_id,
                    fk_model=self.fk_model)
                )

            return '', response
