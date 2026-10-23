from uber.config import c
from uber.custom_tags import email_only, email_to_link
from uber.models import MagModel
from uber.decorators import presave_adjustment
from uber.models.types import (Choice, default_relationship as relationship, DefaultColumn as Column,
                               DefaultField as Field, DefaultRelationship as Relationship)

from datetime import datetime
from markupsafe import Markup
from pytz import UTC
from sqlalchemy.orm import backref
from sqlalchemy.types import Uuid, DateTime
from typing import ClassVar


__all__ = ['ArtistMarketplaceApplication']


class ArtistMarketplaceApplication(MagModel, table=True):
    MATCHING_DEALER_FIELDS: ClassVar = ['email_address', 'website', 'name']

    attendee_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='attendee.id', ondelete='CASCADE', unique=True)
    attendee: 'Attendee' = Relationship(back_populates="marketplace_application", sa_relationship_kwargs={'lazy': 'joined', 'single_parent': True})
    name: str = ''
    display_name: str = ''
    email_address: str = ''
    website: str = ''
    tax_number: str = ''
    terms_accepted: bool = False
    seating_requests: str = ''
    accessibility_requests: str = ''

    status: int = Field(sa_column=Column(Choice(c.MARKETPLACE_STATUS_OPTS)), default=c.PENDING)
    registered: datetime = Field(sa_type=DateTime(timezone=True), default_factory=lambda: datetime.now(UTC))
    accepted: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True)
    admin_notes: str = ''
    overridden_price: int | None = Field(default=0, nullable=True)

    receipt_items: list['ReceiptItem'] = Relationship(sa_relationship=relationship('ReceiptItem',
                                 primaryjoin='and_('
                                             'ReceiptItem.fk_model == "ArtistMarketplaceApplication", '
                                             'remote(ReceiptItem.fk_id) == foreign(ArtistMarketplaceApplication.id))',
                                 viewonly=True,
                                 uselist=True))
    terms_conditions_doc: 'SignedDocument' = Relationship(sa_relationship=relationship(
        'SignedDocument',
        primaryjoin='and_(SignedDocument.fk_id == foreign(ArtistMarketplaceApplication.id),'
        'SignedDocument.model == "ArtistMarketplaceApplication")'))

    email_model_name: ClassVar = 'app'

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
                          f"{c.DEALER_APP_TERM}. Please purchase your badge using the button below "
                          "and return to this page to complete your artist marketplace application."
                          f"</p><p><a href='../preregistration/purchase_dealer_badge?id={self.attendee.id}&"
                          f"return_to=../marketplace/edit?id={self.id}' class='btn btn-success'>Purchase Badge</a>")
        elif not self.attendee.has_badge:
            return Markup("You cannot complete your marketplace application because your badge status is "
                          f"{self.attendee.badge_status_label}. Please contact us at {email_to_link(email_only(c.REGDESK_EMAIL))} "
                          "for more information.")
        
    @property
    def signnow_config(self):
        return {
            'template_id': c.SIGNNOW_MARKETPLACE_TEMPLATE_ID,
            'folder_id': c.SIGNNOW_MARKETPLACE_FOLDER_ID,
            'doc_title': f"MFF {c.EVENT_YEAR} Artist Marketplace Terms - {self.name}",
            'redirect_link': f'/marketplace/edit?id={self.id}'
        }

    @property
    def signnow_email_invite(self):
        first_name = self.attendee.first_name if self.attendee else ''
        last_name = self.attendee.last_name if self.attendee else ''
        return {
            "to": [
                {"email": self.email, "printed_name": f"{first_name} {last_name}",
                "role": "Marketplace", "order": 1}
            ],
            "from": email_only(c.ARTIST_MARKETPLACE_EMAIL),
            "cc": [],
            "subject": f"ACTION REQUIRED: {c.EVENT_NAME} Artist Marketplace Terms and Conditions",
            "message": (f"Congratulations on being accepted into the {c.EVENT_NAME} Artist Marketplace! "
                        "Please click the button below to review and sign the terms and conditions. "
                        "You MUST sign this in order to complete your application."),
            "redirect_uri": (c.REDIRECT_URL_BASE or c.URL_BASE) + self.signnow_config['redirect_link']
        }

    @property
    def signnow_texts_list(self):
        """
        Returns a list of JSON representing uneditable texts fields to use for this group's document in SignNow.
        """
        page_number = 2
        textFont = 'Arial'
        textLineHeight = 12
        textSize = 10

        texts_config = [(self.name, 77, 375), (self.email, 77, 420), (self.id, 200, 748)]

        texts = []

        for field, x, y in texts_config:
            texts.append({
                "page_number": page_number,
                "data":        field,
                "x":           x,
                "y":           y,
                "font":        textFont,
                "line_height": textLineHeight,
                "size":        6 if field == self.id else textSize,
            })

        return texts

    @property
    def signnow_document_signed(self):
        return bool(self.terms_conditions_doc and self.terms_conditions_doc.signed)
