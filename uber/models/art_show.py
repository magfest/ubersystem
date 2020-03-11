import random
import string

from sqlalchemy import func
from datetime import datetime
from pytz import UTC

from uber.config import c
from uber.models import MagModel
from uber.decorators import cost_property, presave_adjustment
from uber.models.types import Choice, DefaultColumn as Column, default_relationship as relationship

from residue import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import backref
from sqlalchemy.types import Integer, Boolean
from sqlalchemy.schema import ForeignKey


__all__ = ['ArtShowApplication', 'ArtShowPiece', 'ArtShowPayment', 'ArtShowReceipt', 'ArtShowBidder']


class ArtShowApplication(MagModel):
    attendee_id = Column(UUID, ForeignKey('attendee.id', ondelete='SET NULL'),
                         nullable=True)
    attendee = relationship('Attendee', foreign_keys=attendee_id, cascade='save-update, merge',
                                  backref=backref('art_show_applications', cascade='save-update, merge'))
    agent_id = Column(UUID, ForeignKey('attendee.id', ondelete='SET NULL'),
                         nullable=True)
    agent = relationship('Attendee', foreign_keys=agent_id, cascade='save-update, merge',
                            backref=backref('art_agent_applications', cascade='save-update, merge'))
    agent_code = Column(UnicodeText)
    checked_in = Column(UTCDateTime, nullable=True)
    checked_out = Column(UTCDateTime, nullable=True)
    locations = Column(UnicodeText)
    artist_name = Column(UnicodeText)
    artist_id = Column(UnicodeText, admin_only=True)
    banner_name = Column(UnicodeText)
    check_payable = Column(UnicodeText)
    hotel_name = Column(UnicodeText)
    hotel_room_num = Column(UnicodeText)
    panels = Column(Integer, default=0)
    panels_ad = Column(Integer, default=0)
    tables = Column(Integer, default=0)
    tables_ad = Column(Integer, default=0)
    description = Column(UnicodeText)
    business_name = Column(UnicodeText)
    zip_code = Column(UnicodeText)
    address1 = Column(UnicodeText)
    address2 = Column(UnicodeText)
    city = Column(UnicodeText)
    region = Column(UnicodeText)
    country = Column(UnicodeText)
    paypal_address = Column(UnicodeText)
    website = Column(UnicodeText)
    special_needs = Column(UnicodeText)
    status = Column(Choice(c.ART_SHOW_STATUS_OPTS), default=c.UNAPPROVED)
    delivery_method = Column(Choice(c.ART_SHOW_DELIVERY_OPTS), default=c.BRINGING_IN)
    us_only = Column(Boolean, default=False)
    admin_notes = Column(UnicodeText, admin_only=True)
    base_price = Column(Integer, default=0, admin_only=True)
    overridden_price = Column(Integer, nullable=True, admin_only=True)

    email_model_name = 'app'

    @presave_adjustment
    def _cost_adjustments(self):
        self.base_price = self.default_cost

        if self.overridden_price == '':
            self.overridden_price = None

    @presave_adjustment
    def add_artist_id(self):
        from uber.models import Session
        if self.status in [c.APPROVED, c.PAID] and not self.artist_id:
            with Session() as session:
                # Kind of inefficient, but doing one big query for all the existing
                # codes will be faster than a separate query for each new code.
                old_codes = set(
                    s for (s,) in session.query(ArtShowApplication.artist_id).all())

            code_candidate = self._get_code_from_name(self.artist_name, old_codes) \
                             or self._get_code_from_name(self.attendee.last_name, old_codes) \
                             or self._get_code_from_name(self.attendee.first_name, old_codes)

            if not code_candidate:
                # We're out of manual alternatives, time for a random code
                code_candidates = ''.join([random.choice(string.ascii_uppercase) for _ in range(100)])
                for code_candidate in code_candidates:
                    if code_candidate not in old_codes:
                        break

            self.artist_id = code_candidate.upper()

    def _get_code_from_name(self, name, old_codes):
        name = "".join(list(filter(lambda char: char.isalpha(), name)))
        if len(name) >= 3:
            return name[:3] if name[:3].upper() not in old_codes else None

    @presave_adjustment
    def add_new_agent_code(self):
        if not self.agent_code and self.delivery_method == c.AGENT:
            self.agent_code = self.new_agent_code()

    def new_agent_code(self):
        from uber.models import PromoCode
        new_agent_code = PromoCode.generate_random_code()

        self.session.add(PromoCode(
            discount=0,
            discount_type=PromoCode._FIXED_DISCOUNT,
            code=new_agent_code))

        return new_agent_code

    @property
    def display_name(self):
        return self.banner_name or self.artist_name or self.attendee.full_name

    @property
    def incomplete_reason(self):
        if self.status not in [c.APPROVED, c.PAID]:
            return self.status_label
        if self.delivery_method == c.BY_MAIL \
                and not self.address1:
            return "Mailing address required"
        if self.attendee.placeholder and self.attendee.badge_status != c.NOT_ATTENDING:
            return "Missing registration info"

    @property
    def total_cost(self):
        if self.status not in [c.APPROVED, c.PAID]:
            return 0
        else:
            return self.potential_cost

    @property
    def potential_cost(self):
        if self.overridden_price is not None:
            return self.overridden_price
        else:
            return self.base_price or self.default_cost or 0

    @property
    def email(self):
        return self.attendee.email

    @cost_property
    def panels_cost(self):
        return self.panels * c.COST_PER_PANEL

    @cost_property
    def tables_cost(self):
        return self.tables * c.COST_PER_TABLE

    @cost_property
    def panels_ad_cost(self):
        return self.panels_ad * c.COST_PER_PANEL

    @cost_property
    def tables_ad_cost(self):
        return self.tables_ad * c.COST_PER_TABLE

    @cost_property
    def mailing_fee(self):
        return c.ART_MAILING_FEE if self.delivery_method == c.BY_MAIL else 0

    @property
    def is_unpaid(self):
        return self.status == c.APPROVED

    @property
    def has_general_space(self):
        return self.panels or self.tables

    @property
    def has_mature_space(self):
        return self.panels_ad or self.tables_ad

    @property
    def highest_piece_id(self):
        if len(self.art_show_pieces) > 1:
            return sorted([piece for piece in self.art_show_pieces if piece.piece_id], key=lambda piece: piece.piece_id, reverse=True)[0].piece_id
        elif self.art_show_pieces:
            return 1
        else:
            return 0

    @property
    def total_sales(self):
        cost = 0
        for piece in self.art_show_pieces:
            if piece.status in [c.SOLD, c.PAID]:
                cost += piece.sale_price * 100
        return cost

    @property
    def commission(self):
        return self.total_sales * (c.COMMISSION_PCT / 10000)

    @property
    def check_total(self):
        return round(self.total_sales - self.commission)

    @property
    def amount_paid(self):
        return max(0, self.attendee.amount_paid / 100 - (self.attendee.total_cost - self.total_cost))


class ArtShowPiece(MagModel):
    app_id = Column(UUID, ForeignKey('art_show_application.id', ondelete='SET NULL'), nullable=True)
    app = relationship('ArtShowApplication', foreign_keys=app_id,
                         cascade='save-update, merge',
                         backref=backref('art_show_pieces',
                                         cascade='save-update, merge'))
    receipt_id = Column(UUID, ForeignKey('art_show_receipt.id', ondelete='SET NULL'), nullable=True)
    receipt = relationship('ArtShowReceipt', foreign_keys=receipt_id,
                           cascade='save-update, merge',
                           backref=backref('pieces',
                                           cascade='save-update, merge'))
    piece_id = Column(Integer)
    name = Column(UnicodeText)
    for_sale = Column(Boolean, default=False)
    type = Column(Choice(c.ART_PIECE_TYPE_OPTS), default=c.PRINT)
    gallery = Column(Choice(c.ART_PIECE_GALLERY_OPTS), default=c.GENERAL)
    media = Column(UnicodeText)
    print_run_num = Column(Integer, default=0, nullable=True)
    print_run_total = Column(Integer, default=0, nullable=True)
    opening_bid = Column(Integer, default=0, nullable=True)
    quick_sale_price = Column(Integer, default=0, nullable=True)
    winning_bid = Column(Integer, default=0, nullable=True)
    no_quick_sale = Column(Boolean, default=False)
    voice_auctioned = Column(Boolean, default=False)

    status = Column(Choice(c.ART_PIECE_STATUS_OPTS), default=c.EXPECTED,
                    admin_only=True)

    @presave_adjustment
    def create_piece_id(self):
        if not self.piece_id:
            self.piece_id = int(self.app.highest_piece_id) + 1

    @presave_adjustment
    def set_voice_auctioned(self):
        if self.status == c.VOICE_AUCTION:
            self.voice_auctioned = True

    @property
    def artist_and_piece_id(self):
        return str(self.app.artist_id) + "-" + str(self.piece_id)

    @property
    def barcode_data(self):
        return "*" + self.artist_and_piece_id + "*"

    @property
    def valid_quick_sale(self):
        return self.for_sale and not self.no_quick_sale and self.quick_sale_price

    @property
    def valid_for_sale(self):
        return self.for_sale and self.opening_bid

    @property
    def sale_price(self):
        return self.winning_bid or self.quick_sale_price if self.valid_quick_sale else self.winning_bid

    @property
    def winning_bidder_num(self):
        return self.receipt.attendee.art_show_bidder.bidder_num


class ArtShowPayment(MagModel):
    receipt_id = Column(UUID, ForeignKey('art_show_receipt.id', ondelete='SET NULL'), nullable=True)
    receipt = relationship('ArtShowReceipt', foreign_keys=receipt_id,
                           cascade='save-update, merge',
                           backref=backref('art_show_payments',
                                           cascade='save-update, merge'))
    amount = Column(Integer, default=0)
    type = Column(Choice(c.ART_SHOW_PAYMENT_OPTS), default=c.STRIPE, admin_only=True)
    when = Column(UTCDateTime, default=lambda: datetime.now(UTC))


class ArtShowReceipt(MagModel):
    invoice_num = Column(Integer, default=0)
    attendee_id = Column(UUID, ForeignKey('attendee.id', ondelete='SET NULL'), nullable=True)
    attendee = relationship('Attendee', foreign_keys=attendee_id,
                            cascade='save-update, merge',
                            backref=backref('art_show_receipts',
                                            cascade='save-update, merge'))
    closed = Column(UTCDateTime, nullable=True)

    @presave_adjustment
    def add_invoice_num(self):
        if not self.invoice_num:
            from uber.models import Session
            with Session() as session:
                highest_num = session.query(func.max(ArtShowReceipt.invoice_num)).first()

            self.invoice_num = 1 if not highest_num[0] else highest_num[0] + 1

    @property
    def subtotal(self):
        cost = 0
        for piece in self.pieces:
            cost += piece.sale_price * 100
        return cost

    @property
    def tax(self):
        return self.subtotal * (c.SALES_TAX / 10000)

    @property
    def total(self):
        return round(self.subtotal + self.tax)

    @property
    def paid(self):
        paid = 0
        for payment in self.art_show_payments:
            if payment.type == c.REFUND:
                paid -= payment.amount
            else:
                paid += payment.amount
        return paid

    @property
    def owed(self):
        return max(0, self.total - self.paid)

    @property
    def stripe_payments(self):
        return [payment for payment in self.art_show_payments if payment.type == c.STRIPE]

    @property
    def stripe_total(self):
        return sum([payment.amount for payment in self.art_show_payments if payment.type == c.STRIPE])

    @property
    def cash_total(self):
        return sum([payment.amount for payment in self.art_show_payments if payment.type == c.CASH]) - sum(
            [payment.amount for payment in self.art_show_payments if payment.type == c.REFUND])


class ArtShowBidder(MagModel):
    attendee_id = Column(UUID, ForeignKey('attendee.id', ondelete='SET NULL'), nullable=True)
    bidder_num = Column(UnicodeText)
    hotel_name = Column(UnicodeText)
    hotel_room_num = Column(UnicodeText)
    admin_notes = Column(UnicodeText)
    signed_up = Column(UTCDateTime, nullable=True)

    @hybrid_property
    def bidder_num_stripped(self):
        return int(self.bidder_num[2:]) if self.bidder_num else 0

    @bidder_num_stripped.expression
    def bidder_num_stripped(cls):
        return func.cast("0" + func.substr(cls.bidder_num, 3, func.length(cls.bidder_num)), Integer)