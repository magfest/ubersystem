from uber.config import c
from uber.models import MagModel
from uber.decorators import presave_adjustment
from uber.models.types import Choice, DefaultColumn as Column, default_relationship as relationship, MultiChoice, utcnow

from datetime import datetime
from pytz import UTC
from residue import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy.orm import backref
from sqlalchemy.types import Boolean, Integer
from sqlalchemy.schema import ForeignKey


__all__ = ['ArtistMarketplaceApplication']


class ArtistMarketplaceApplication(MagModel):
    MATCHING_DEALER_FIELDS = ['email_address', 'website', 'name']

    attendee_id = Column(UUID, ForeignKey('attendee.id'))
    attendee = relationship('Attendee', backref=backref('marketplace_application', uselist=False),
                            cascade='save-update,merge,refresh-expire,expunge',
                            uselist=False)
    name = Column(UnicodeText)
    display_name = Column(UnicodeText)
    email_address = Column(UnicodeText)
    website = Column(UnicodeText)
    tax_number = Column(UnicodeText)
    terms_accepted = Column(Boolean, default=False)
    seating_requests = Column(UnicodeText)
    accessibility_requests = Column(UnicodeText)

    status = Column(Choice(c.MARKETPLACE_STATUS_OPTS), default=c.PENDING, admin_only=True)
    registered = Column(UTCDateTime, server_default=utcnow(), default=lambda: datetime.now(UTC))
    accepted = Column(UTCDateTime, nullable=True)
    receipt_items = relationship('ReceiptItem',
                                 primaryjoin='and_('
                                             'ReceiptItem.fk_model == "ArtistMarketplaceApplication", '
                                             'remote(ReceiptItem.fk_id) == foreign(ArtistMarketplaceApplication.id))',
                                 viewonly=True,
                                 uselist=True)

    admin_notes = Column(UnicodeText, admin_only=True)
    overridden_price = Column(Integer, nullable=True, admin_only=True)

    email_model_name = 'app'

    @presave_adjustment
    def _cost_adjustments(self):
        if self.overridden_price == '':
            self.overridden_price = None

    @property
    def email(self):
        return self.email_address or self.attendee.email
    
    @property
    def default_cost(self):
        return (self.overridden_price or c.ARTIST_MARKETPLACE_FEE) * 100

    @property
    def total_cost(self):
        if self.receipt_items:
            return sum([item.amount for item in self.receipt_items])
        return self.default_cost

    @property
    def amount_unpaid(self):
        if self.status != c.ACCEPTED:
            return 0
        elif not self.receipt_items or self.was_refunded:
            return self.default_cost

        return sum([item.amount for item in self.receipt_items if not item.closed])

    @property
    def was_refunded(self):
        if not self.receipt_items:
            return False
        return all([item.receipt_txn and item.receipt_txn.refunded for item in self.receipt_items])

    @property
    def amount_paid(self):
        if self.receipt_items:
            return sum([item.amount for item in self.receipt_items if item.closed and (
                not item.receipt_txn or not item.receipt_txn.refunded)])
        return 0