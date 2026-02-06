from uber.config import c
from uber.custom_tags import email_only, email_to_link
from uber.models import MagModel
from uber.decorators import presave_adjustment
from uber.models.types import Choice, DefaultColumn as Column, default_relationship as relationship, MultiChoice, utcnow

from datetime import datetime
from markupsafe import Markup
from pytz import UTC
from sqlalchemy.orm import backref
from sqlalchemy.types import Boolean, Integer, Uuid, String, DateTime
from sqlalchemy.schema import ForeignKey


__all__ = ['ArtistMarketplaceApplication']


class ArtistMarketplaceApplication(MagModel):
    MATCHING_DEALER_FIELDS = ['email_address', 'website', 'name']

    attendee_id = Column(Uuid(as_uuid=False), ForeignKey('attendee.id'))
    attendee = relationship('Attendee', lazy='joined', backref=backref('marketplace_application', uselist=False),
                            cascade='save-update,merge,refresh-expire,expunge',
                            uselist=False)
    name = Column(String)
    display_name = Column(String)
    email_address = Column(String)
    website = Column(String)
    tax_number = Column(String)
    terms_accepted = Column(Boolean, default=False)
    seating_requests = Column(String)
    accessibility_requests = Column(String)

    status = Column(Choice(c.MARKETPLACE_STATUS_OPTS), default=c.PENDING, admin_only=True)
    registered = Column(DateTime(timezone=True), server_default=utcnow(), default=lambda: datetime.now(UTC))
    accepted = Column(DateTime(timezone=True), nullable=True)
    receipt_items = relationship('ReceiptItem',
                                 primaryjoin='and_('
                                             'ReceiptItem.fk_model == "ArtistMarketplaceApplication", '
                                             'remote(ReceiptItem.fk_id) == foreign(ArtistMarketplaceApplication.id))',
                                 viewonly=True,
                                 uselist=True)

    admin_notes = Column(String, admin_only=True)
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
        return self.overridden_price or c.ARTIST_MARKETPLACE_FEE

    @property
    def total_cost(self):
        if self.receipt_items:
            return sum([item.amount for item in self.receipt_items]) / 100
        return self.default_cost

    @property
    def amount_unpaid(self):
        if self.status != c.ACCEPTED:
            return 0
        elif not self.receipt_items or self.was_refunded:
            return self.default_cost

        return sum([item.amount for item in self.receipt_items if not item.closed]) / 100

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
    
    @property
    def incomplete_reason(self):
        if self.attendee.badge_status == c.UNAPPROVED_DEALER_STATUS:
            if self.attendee.group.status == c.UNAPPROVED:
                return Markup(f"Your registration is still pending as part of your {self.attendee.group.status_label} "
                        f"{c.DEALER_APP_TERM}. Please contact us at {email_to_link(email_only(c.MARKETPLACE_EMAIL))}.")
            return Markup(f"Your registration is still pending as part of your {self.attendee.group.status_label} "
                          f"{c.DEALER_APP_TERM}. Please <a href='../preregistration/confirm?id={self.attendee.id}' "
                          "target='_blank'>purchase your badge here</a> and return to this page to complete your "
                          "artist marketplace application.")
        elif not self.attendee.has_badge:
            return Markup("You cannot complete your marketplace application because your badge status is "
                          f"{self.attendee.badge_status_label}. Please contact us at {email_to_link(email_only(c.REGDESK_EMAIL))} "
                          "for more information.")