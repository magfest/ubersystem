import random
import string

from pockets import classproperty
from sqlalchemy import func, case
from datetime import datetime
from pytz import UTC

from uber.config import c
from uber.models import MagModel
from uber.decorators import presave_adjustment
from uber.models.types import Choice, DefaultColumn as Column, default_relationship as relationship
from uber.utils import RegistrationCode, get_static_file_path

from residue import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import backref
from sqlalchemy.types import Integer, Boolean
from sqlalchemy.schema import ForeignKey


__all__ = ['ArtShowAgentCode', 'ArtShowApplication', 'ArtShowPiece', 'ArtShowPayment', 'ArtShowReceipt', 'ArtShowBidder']


class ArtShowAgentCode(MagModel):
    app_id = Column(UUID, ForeignKey('art_show_application.id'))
    app = relationship('ArtShowApplication',
                       backref=backref('agent_codes', cascade='merge,refresh-expire,expunge'),
                       foreign_keys=app_id,
                       cascade='merge,refresh-expire,expunge')
    attendee_id = Column(UUID, ForeignKey('attendee.id', ondelete='SET NULL'),
                         unique=True, nullable=True)
    attendee = relationship('Attendee',
                            backref=backref('agent_codes', cascade='merge,refresh-expire,expunge'),
                            foreign_keys=attendee_id,
                            cascade='merge,refresh-expire,expunge')
    code = Column(UnicodeText)
    cancelled = Column(UTCDateTime, nullable=True)

    @hybrid_property
    def normalized_code(self):
        return RegistrationCode.normalize_code(self.code)

    @normalized_code.expression
    def normalized_code(cls):
        return RegistrationCode.sql_normalized_code(cls.code)

    @property
    def attendee_first_name(self):
        return self.attendee.first_name if self.attendee else None


class ArtShowApplication(MagModel):
    attendee_id = Column(UUID, ForeignKey('attendee.id', ondelete='SET NULL'),
                         nullable=True)
    attendee = relationship('Attendee', foreign_keys=attendee_id, cascade='save-update, merge',
                            backref=backref('art_show_applications', cascade='save-update, merge'))
    checked_in = Column(UTCDateTime, nullable=True)
    checked_out = Column(UTCDateTime, nullable=True)
    locations = Column(UnicodeText)
    artist_name = Column(UnicodeText)
    artist_id = Column(UnicodeText, admin_only=True)
    payout_method = Column(Choice(c.ARTIST_PAYOUT_METHOD_OPTS), default=c.CHECK)
    banner_name = Column(UnicodeText)
    banner_name_ad = Column(UnicodeText)
    artist_id_ad = Column(UnicodeText, admin_only=True)
    check_payable = Column(UnicodeText)
    hotel_name = Column(UnicodeText)
    hotel_room_num = Column(UnicodeText)
    contact_at_con = Column(UnicodeText)
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
    check_in_notes = Column(UnicodeText)
    overridden_price = Column(Integer, nullable=True, admin_only=True)
    active_receipt = relationship(
        'ModelReceipt',
        cascade='save-update,merge,refresh-expire,expunge',
        primaryjoin='and_(remote(ModelReceipt.owner_id) == foreign(ArtShowApplication.id),'
        'ModelReceipt.owner_model == "ArtShowApplication",'
        'ModelReceipt.closed == None)',
        uselist=False)
    default_cost = Column(Integer, nullable=True)

    email_model_name = 'app'

    @presave_adjustment
    def _cost_adjustments(self):
        if self.overridden_price == '':
            self.overridden_price = None
        if self.is_valid:
            self.default_cost = self.calc_default_cost()

    @presave_adjustment
    def add_artist_id(self):
        if self.status == c.APPROVED and not self.artist_id:
            self.artist_id = self.generate_artist_id(self.banner_name)
    
    @presave_adjustment
    def add_artist_id_ad(self):
        if self.status == c.APPROVED and self.has_mature_space and self.banner_name_ad and not self.artist_id_ad:
            self.artist_id_ad = self.generate_artist_id(self.banner_name_ad)

    def generate_artist_id(self, banner_name):
        from uber.models import Session
        with Session() as session:
            # Kind of inefficient, but doing one big query for all the existing
            # codes will be faster than a separate query for each new code.
            old_codes = set(
                s for (s,) in session.query(ArtShowApplication.artist_id).all())

        code_candidate = self._get_code_from_name(banner_name, old_codes) \
            or self._get_code_from_name(self.artist_name, old_codes) \
            or self._get_code_from_name(self.attendee.last_name, old_codes) \
            or self._get_code_from_name(self.attendee.first_name, old_codes)

        if not code_candidate:
            # We're out of manual alternatives, time for a random code
            code_candidates = [''.join(random.choices(string.ascii_uppercase, k=3)) for _ in range(100)]
            for code_candidate in code_candidates:
                if code_candidate not in old_codes:
                    break

        return code_candidate.upper()

    def _get_code_from_name(self, name, old_codes):
        name = "".join(list(filter(lambda char: char.isalpha(), name)))
        if len(name) >= 3:
            return name[:3] if name[:3].upper() not in old_codes else None
    
    @property
    def artist_codes(self):
        if self.artist_id_ad:
            return f"{self.artist_id}/{self.artist_id_ad}"
        return f"{self.artist_id}"
        
    def generate_new_agent_code(self):
        from uber.utils import RegistrationCode
        return ArtShowAgentCode(
            app_id = self.id,
            code=RegistrationCode.generate_random_code(ArtShowAgentCode.code)
            )

    @property
    def valid_agent_codes(self):
        return sorted([code for code in self.agent_codes if not code.cancelled],
                      key=lambda c: c.attendee_first_name)

    @property
    def current_agents(self):
        return [code.attendee for code in self.valid_agent_codes if code.attendee is not None]

    @property
    def single_agent(self):
        return self.current_agents[0] if self.current_agents else None

    @property
    def display_name(self):
        return self.banner_name or self.artist_name or self.attendee.full_name
    
    @property
    def mature_display_name(self):
        return self.banner_name_ad or self.banner_name or self.artist_name or self.attendee.full_name
    
    @property
    def artist_or_full_name(self):
        return self.artist_name or self.attendee.full_name

    @property
    def incomplete_reason(self):
        if self.status != c.APPROVED:
            return self.status_label
        if not self.attendee:
            return "No attendee assigned to application"
        if self.delivery_method == c.BY_MAIL \
                and not self.address1 and not self.attendee.address1:
            return "Mailing address required"
        if self.attendee.placeholder and self.attendee.badge_status != c.NOT_ATTENDING:
            return "Missing registration info"

    @hybrid_property
    def is_valid(self):
        return self.status != c.DECLINED

    @hybrid_property
    def true_default_cost(self):
        # why did I do this
        if self.overridden_price is None:
            return self.default_cost if self.default_cost is not None else self.calc_default_cost()
        return self.overridden_price

    @true_default_cost.expression
    def true_default_cost(cls):
        return case(
            [(cls.overridden_price == None, cls.default_cost)],  # noqa: E711
            else_=cls.overridden_price)

    @hybrid_property
    def true_default_cost_cents(self):
        return self.true_default_cost * 100
    
    @property
    def panels_and_tables_cost(self):
        # Mail-in fees are applied on top of this price
        return c.COST_PER_PANEL * (self.panels + self.panels_ad) + c.COST_PER_TABLE * (self.tables + self.tables_ad)

    @property
    def total_cost(self):
        if self.status != c.APPROVED:
            return 0
        else:
            if self.active_receipt:
                return self.active_receipt.item_total / 100
            return self.true_default_cost or self.calc_default_cost()

    @property
    def potential_cost(self):
        return self.true_default_cost or 0

    @property
    def email(self):
        return self.attendee.email

    @property
    def is_unpaid(self):
        return not self.amount_paid and (self.total_cost or self.status != c.APPROVED and self.potential_cost)

    @property
    def amount_unpaid(self):
        return max(0, ((self.total_cost * 100) - self.amount_paid) / 100)

    @property
    def amount_pending(self):
        return self.active_receipt.pending_total if self.active_receipt else 0

    @property
    def amount_paid(self):
        return self.active_receipt.payment_total if self.active_receipt else 0

    @property
    def amount_refunded(self):
        return self.active_receipt.refund_total if self.active_receipt else 0

    @property
    def has_general_space(self):
        return self.panels or self.tables

    @property
    def has_mature_space(self):
        return self.panels_ad or self.tables_ad

    @property
    def highest_piece_id(self):
        if len(self.art_show_pieces) > 1:
            return sorted([piece for piece in self.art_show_pieces if piece.piece_id],
                          key=lambda piece: piece.piece_id, reverse=True)[0].piece_id
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
    winning_bidder_id = Column(UUID, ForeignKey('art_show_bidder.id', ondelete='SET NULL'), nullable=True)
    winning_bidder = relationship('ArtShowBidder', foreign_keys=winning_bidder_id,
                                  cascade='save-update, merge',
                                  backref=backref('art_show_pieces',
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
        if not self.app:
            return '???-' + str(self.piece_id)

        if self.gallery == c.MATURE and self.app.artist_id_ad:
            return str(self.app.artist_id_ad) + "-" + str(self.piece_id)
        return str(self.app.artist_id) + "-" + str(self.piece_id)

    @property
    def app_display_name(self):
        if not self.app:
            return "???"

        if self.gallery == c.MATURE:
            return self.app.mature_display_name
        else:
            return self.app.display_name

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
    
    def print_bidsheet(self, pdf, sheet_num, normal_font_name, bold_font_name, set_fitted_font_size):
        xplus = yplus = 0

        if sheet_num in [1, 3]:
            xplus = 306
        if sheet_num in [2, 3]:
            yplus = 396

        # Location, Piece ID, and barcode
        pdf.image(get_static_file_path('bidsheet.png'), x=0 + xplus, y=0 + yplus, w=306)
        pdf.set_font(normal_font_name, size=10)
        pdf.set_xy(81 + xplus, 27 + yplus)
        pdf.cell(80, 16, txt=self.app.locations, ln=1, align="C")
        pdf.set_font("3of9", size=22)
        pdf.set_xy(163 + xplus, 15 + yplus)
        pdf.cell(132, 22, txt=self.barcode_data, ln=1, align="C")
        pdf.set_font(bold_font_name, size=8,)
        pdf.set_xy(163 + xplus, 32 + yplus)
        pdf.cell(132, 12, txt=self.artist_and_piece_id, ln=1, align="C")

        # Artist, Title, Media
        pdf.set_font(normal_font_name, size=12)
        set_fitted_font_size(self.app_display_name)
        pdf.set_xy(81 + xplus, 54 + yplus)
        pdf.cell(160, 24,
                    txt=(self.app_display_name),
                    ln=1, align="C")
        pdf.set_xy(81 + xplus, 80 + yplus)
        set_fitted_font_size(self.name)
        pdf.cell(160, 24, txt=self.name, ln=1, align="C")
        pdf.set_font(normal_font_name, size=12)
        pdf.set_xy(81 + xplus, 105 + yplus)
        pdf.cell(
            160, 24,
            txt=self.media +
                (' ({} of {})'.format(self.print_run_num, self.print_run_total) if self.type == c.PRINT else ''),
            ln=1, align="C"
        )

        # Type, Minimum Bid, QuickSale Price
        pdf.set_font(normal_font_name, size=10)
        pdf.set_xy(242 + xplus, 54 + yplus)
        pdf.cell(53, 24, txt=self.type_label, ln=1, align="C")
        pdf.set_font(normal_font_name, size=8)
        pdf.set_xy(242 + xplus, 90 + yplus)
        # Note: we want the prices on the PDF to always have a trailing .00
        pdf.cell(53, 14, txt=('${:,.2f}'.format(self.opening_bid)) if self.valid_for_sale else 'N/A', ln=1)
        pdf.set_xy(242 + xplus, 116 + yplus)
        pdf.cell(
            53, 14, txt=('${:,.2f}'.format(self.quick_sale_price)) if self.valid_quick_sale else 'N/A', ln=1)


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
    def card_payments(self):
        return [payment for payment in self.art_show_payments if payment.type in [c.STRIPE, c.SQUARE]]

    @property
    def card_total(self):
        return sum([payment.amount for payment in self.art_show_payments if payment.type in [c.STRIPE, c.SQUARE]])

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

    @presave_adjustment
    def zfill_bidder_num(self):
        if not self.bidder_num:
            return
        base_bidder_num = ArtShowBidder.strip_bidder_num(self.bidder_num)
        self.bidder_num = self.bidder_num[:2] + str(base_bidder_num).zfill(4)

    @classmethod
    def strip_bidder_num(cls, num):
        return int(num[2:])

    @hybrid_property
    def bidder_num_stripped(self):
        return ArtShowBidder.strip_bidder_num(self.bidder_num) if self.bidder_num else 0

    @bidder_num_stripped.expression
    def bidder_num_stripped(cls):
        return func.cast("0" + func.substr(cls.bidder_num, 3, func.length(cls.bidder_num)), Integer)
    
    @classproperty
    def required_fields(cls):
        # Override for independent art shows to force attendee fields to be filled out
        return {
            'bidder_num': "bidder number",
        }
