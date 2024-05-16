from uber.config import c
from uber.models import MagModel
from uber.decorators import presave_adjustment
from uber.models.types import Choice, DefaultColumn as Column, default_relationship as relationship, MultiChoice, utcnow

from sqlalchemy.orm import backref
from sqlalchemy.types import Integer, UnicodeText, DateTime, UUID
from sqlalchemy.schema import ForeignKey


__all__ = ['MarketplaceApplication']


class MarketplaceApplication(MagModel):
    MATCHING_DEALER_FIELDS = ['categories', 'categories_text', 'description', 'special_needs']

    attendee_id = Column(UUID, ForeignKey('attendee.id', ondelete='SET NULL'),
                         nullable=True)
    attendee = relationship('Attendee', foreign_keys=attendee_id, cascade='save-update, merge',
                            backref=backref('marketplace_applications', cascade='save-update, merge'))
    business_name = Column(UnicodeText)
    status = Column(Choice(c.MARKETPLACE_STATUS_OPTS), default=c.UNAPPROVED, admin_only=True)
    registered = Column(DateTime, server_default=utcnow())
    approved = Column(DateTime, nullable=True)

    categories = Column(MultiChoice(c.DEALER_WARES_OPTS))
    categories_text = Column(UnicodeText)
    description = Column(UnicodeText)
    special_needs = Column(UnicodeText)

    admin_notes = Column(UnicodeText, admin_only=True)
    overridden_price = Column(Integer, nullable=True, admin_only=True)

    email_model_name = 'app'

    @presave_adjustment
    def _cost_adjustments(self):
        if self.overridden_price == '':
            self.overridden_price = None

    @property
    def incomplete_reason(self):
        if self.status not in [c.APPROVED, c.PAID]:
            return self.status_label
        if self.attendee.placeholder:
            return "Missing registration info"

    @property
    def email(self):
        return self.attendee.email

    @property
    def is_unpaid(self):
        return self.status == c.APPROVED
