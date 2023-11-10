import math
from datetime import datetime
from uuid import uuid4

from pytz import UTC
from residue import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy import and_, exists, or_, case, func, select
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.dialects.postgresql.json import JSONB
from sqlalchemy.orm import backref
from sqlalchemy.schema import ForeignKey
from sqlalchemy.sql.elements import not_
from sqlalchemy.types import Boolean, Integer, Numeric

from uber.config import c
from uber.custom_tags import format_currency
from uber.decorators import presave_adjustment
from uber.models import MagModel
from uber.models.types import default_relationship as relationship, utcnow, Choice, DefaultColumn as Column, \
    MultiChoice, TakesPaymentMixin
from uber.utils import add_opt


__all__ = ['Group']


class Group(MagModel, TakesPaymentMixin):
    public_id = Column(UUID, default=lambda: str(uuid4()))
    name = Column(UnicodeText)
    tables = Column(Numeric, default=0)
    zip_code = Column(UnicodeText)
    address1 = Column(UnicodeText)
    address2 = Column(UnicodeText)
    city = Column(UnicodeText)
    region = Column(UnicodeText)
    country = Column(UnicodeText)
    email_address = Column(UnicodeText)
    phone = Column(UnicodeText)
    website = Column(UnicodeText)
    wares = Column(UnicodeText)
    categories = Column(MultiChoice(c.DEALER_WARES_OPTS))
    categories_text = Column(UnicodeText)
    description = Column(UnicodeText)
    special_needs = Column(UnicodeText)

    cost = Column(Integer, default=0, admin_only=True)
    auto_recalc = Column(Boolean, default=True, admin_only=True)
    
    can_add = Column(Boolean, default=False, admin_only=True)
    admin_notes = Column(UnicodeText, admin_only=True)
    status = Column(Choice(c.DEALER_STATUS_OPTS), default=c.UNAPPROVED, admin_only=True)
    registered = Column(UTCDateTime, server_default=utcnow())
    approved = Column(UTCDateTime, nullable=True)
    leader_id = Column(UUID, ForeignKey('attendee.id', use_alter=True, name='fk_leader'), nullable=True)
    creator_id = Column(UUID, ForeignKey('attendee.id'), nullable=True)

    creator = relationship(
        'Attendee',
        foreign_keys=creator_id,
        backref=backref('created_groups', order_by='Group.name', cascade='all,delete-orphan'),
        cascade='save-update,merge,refresh-expire,expunge',
        remote_side='Attendee.id',
        single_parent=True)
    leader = relationship('Attendee', foreign_keys=leader_id, post_update=True, cascade='all')
    studio = relationship('IndieStudio', uselist=False, backref='group')
    guest = relationship('GuestGroup', backref='group', uselist=False)
    active_receipt = relationship(
        'ModelReceipt',
        cascade='save-update,merge,refresh-expire,expunge',
        primaryjoin='and_(remote(ModelReceipt.owner_id) == foreign(Group.id),'
                        'ModelReceipt.owner_model == "Group",'
                        'ModelReceipt.closed == None)',
        uselist=False)

    _repr_attr_names = ['name']

    @presave_adjustment
    def _cost_and_leader(self):
        assigned = [a for a in self.attendees if not a.is_unassigned]
        if len(assigned) == 1:
            [self.leader] = assigned
        if self.auto_recalc:
            self.cost = self.calc_default_cost()
        elif not self.cost:
            self.cost = 0
        if self.status == c.APPROVED and not self.approved:
            self.approved = datetime.now(UTC)
        if self.leader and self.is_dealer and self.leader.paid == c.PAID_BY_GROUP:
            self.leader.ribbon = add_opt(self.leader.ribbon_ints, c.DEALER_RIBBON)
        if not self.is_unpaid or self.orig_value_of('status') != self.status:
            for a in self.attendees:
                a.presave_adjustments()

    def calc_group_price_change(self, **kwargs):
        preview_group = Group(**self.to_dict())
        current_cost = int(self.cost * 100)
        new_cost = None

        if 'cost' in kwargs:
            try:
                preview_group.cost = int(kwargs['cost'])
            except TypeError:
                preview_group.cost = 0
            new_cost = preview_group.cost * 100
        if 'tables' in kwargs:
            preview_group.tables = int(kwargs['tables'])
            return self.default_table_cost * 100, (preview_group.default_table_cost * 100) - (self.default_table_cost * 100)
        if 'badges' in kwargs:
            num_new_badges = int(kwargs['badges']) - self.badges
            return self.current_badge_cost * 100, self.new_badge_cost * num_new_badges * 100

        if not new_cost:
            new_cost = int(preview_group.calc_default_cost() * 100)
        return current_cost, new_cost - current_cost
                
    @presave_adjustment
    def assign_creator(self):
        if self.is_new and not self.creator_id:
            self.creator_id = self.session.admin_attendee().id if self.session.admin_attendee() else None

    @hybrid_property
    def cost_cents(self):
        return self.cost * 100
    
    @property
    def signnow_texts_list(self):
        """
        Returns a list of JSON representing uneditable texts fields to use for this group's document in SignNow. 
        """
        page_number = 2
        textFont = 'Arial'
        textLineHeight = 12
        textSize = 10

        texts_config = [(self.name, 73, 392), (self.email, 73, 436), (self.id, 200, 748)]

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
        from uber.models import Session, SignedDocument

        signed = False
        with Session() as session:
            document = session.query(SignedDocument).filter_by(model="Group", fk_id=self.id).first()
            if document and document.signed:
                signed = True

        return signed

    @property
    def sorted_attendees(self):
        return list(sorted(self.attendees, key=lambda a: (a.is_unassigned, a.id != self.leader_id, a.full_name)))

    @property
    def unassigned(self):
        """
        Returns a list of the unassigned badges for this group, sorted so that
        the paid-by-group badges come last, because when claiming unassigned
        badges we want to claim the "weird" ones first.
        """
        unassigned = [a for a in self.attendees if a.is_unassigned]
        return sorted(unassigned, key=lambda a: a.paid == c.PAID_BY_GROUP)

    @property
    def floating(self):
        """
        Returns the list of paid-by-group unassigned badges for this group.
        This is a separate property from the "Group.unassigned" property
        because when automatically adding or removing unassigned badges, we
        care specifically about paid-by-group badges rather than all unassigned
        badges.
        """
        return [a for a in self.attendees if a.is_unassigned and a.paid == c.PAID_BY_GROUP]
    
    @hybrid_property
    def normalized_name(self):
        return self.name.strip().lower()

    @normalized_name.expression
    def normalized_name(cls):
        return func.lower(func.trim(cls.name))

    @hybrid_property
    def is_valid(self):
        return self.status not in [c.CANCELLED, c.DECLINED, c.IMPORTED]

    @is_valid.expression
    def is_valid(cls):
        return not_(cls.status.in_([c.CANCELLED, c.DECLINED, c.IMPORTED]))
    
    @hybrid_property
    def attendees_have_badges(self):
        return self.is_valid and (not self.is_dealer or self.status == c.APPROVED)
    
    @attendees_have_badges.expression
    def attendees_have_badges(cls):
        return and_(cls.is_valid,
                    or_(cls.is_dealer == False, cls.status == c.APPROVED))

    @property
    def new_ribbon(self):
        return c.DEALER_RIBBON if self.is_dealer else ''

    @property
    def ribbon_and_or_badge(self):
        badge = self.unassigned[0]
        if badge.ribbon and badge.badge_type != c.ATTENDEE_BADGE:
            return ' / '.join([badge.badge_type_label] + self.ribbon_labels)
        elif badge.ribbon:
            return ' / '.join(badge.ribbon_labels)
        else:
            return badge.badge_type_label

    @hybrid_property
    def is_dealer(self):
        return bool(not self.guest and (self.tables or self.cost or self.status not in [c.IMPORTED, c.UNAPPROVED]))

    @is_dealer.expression
    def is_dealer(cls):
        return and_(cls.guest == None, or_(cls.tables > 0, cls.cost > 0, not_(cls.status.in_([c.IMPORTED, c.UNAPPROVED]))))

    @hybrid_property
    def is_unpaid(self):
        return self.cost > 0 and self.amount_paid == 0

    @is_unpaid.expression
    def is_unpaid(cls):
        return and_(cls.cost > 0, cls.amount_paid == 0)

    @property
    def email(self):
        if self.email_address:
            return self.email_address
        if self.studio and self.studio.email:
            return self.studio.email
        elif self.leader and self.leader.email:
            return self.leader.email
        elif self.leader_id:  # unattached groups
            [leader] = [a for a in self.attendees if a.id == self.leader_id]
            return leader.email
        else:
            emails = [a.email for a in self.attendees if a.email]
            if len(emails) == 1:
                return emails[0]

    @hybrid_property
    def badges_purchased(self):
        return len([a for a in self.attendees if a.paid == c.PAID_BY_GROUP])

    @badges_purchased.expression
    def badges_purchased(cls):
        from uber.models import Attendee
        return select([func.count(Attendee.id)]
                      ).where(and_(Attendee.group_id == cls.id, Attendee.paid == c.PAID_BY_GROUP)).label('badges_purchased')

    @property
    def badges(self):
        return len(self.attendees)

    @hybrid_property
    def unregistered_badges(self):
        return len([a for a in self.attendees if a.is_unassigned])

    @unregistered_badges.expression
    def unregistered_badges(cls):
        from uber.models import Attendee
        return exists().where(and_(Attendee.group_id == cls.id, Attendee.first_name == ''))

    @property
    def current_badge_cost(self):
        total_badge_cost = 0

        if not self.auto_recalc:
            return 0
        
        for attendee in self.attendees:
            if attendee.paid == c.PAID_BY_GROUP and attendee.badge_cost:
                total_badge_cost += attendee.badge_cost

        return total_badge_cost

    @property
    def new_badge_cost(self):
        return c.DEALER_BADGE_PRICE if self.is_dealer else c.get_group_price()

    @property
    def amount_extra(self):
        if self.is_new:
            return sum(a.total_cost - a.badge_cost for a in self.attendees if a.paid == c.PAID_BY_GROUP) / 100
        else:
            return 0

    @property
    def total_cost(self):
        if not self.is_valid:
            return 0

        if self.active_receipt:
            return self.active_receipt.item_total / 100
        return (self.cost or self.calc_default_cost()) + self.amount_extra

    @hybrid_property
    def is_paid(self):
        return self.active_receipt and self.active_receipt.current_amount_owed == 0
    
    @is_paid.expression
    def is_paid(cls):
        from uber.models import ModelReceipt

        return exists().select_from(ModelReceipt).where(
            and_(ModelReceipt.owner_id == cls.id,
                 ModelReceipt.owner_model == "Group",
                 ModelReceipt.closed == None,
                 ModelReceipt.current_amount_owed == 0))

    @property
    def amount_unpaid(self):
        if self.is_dealer and self.status != c.APPROVED:
            return 0

        if self.registered:
            return max(0, ((self.total_cost * 100) - self.amount_paid - self.amount_pending) / 100)
        else:
            return self.total_cost

    @property
    def amount_pending(self):
        return self.active_receipt.pending_total if self.active_receipt else 0

    @property
    def amount_paid_repr(self):
        return format_currency(self.amount_paid / 100)
    
    @property
    def amount_refunded_repr(self):
        return format_currency(self.amount_refunded / 100)

    @hybrid_property
    def amount_paid(self):
        return self.active_receipt.payment_total if self.active_receipt else 0
    
    @amount_paid.expression
    def amount_paid(cls):
        from uber.models import ModelReceipt

        return select([ModelReceipt.payment_total]
                     ).where(and_(ModelReceipt.owner_id == cls.id,
                                  ModelReceipt.owner_model == "Group",
                                  ModelReceipt.closed == None)
                     ).label('amount_paid')
    
    @hybrid_property
    def amount_refunded(self):
        return self.active_receipt.refund_total if self.active_receipt else 0
    
    @amount_refunded.expression
    def amount_refunded(cls):
        from uber.models import ModelReceipt

        return select([ModelReceipt.refund_total]
                     ).where(and_(ModelReceipt.owner_id == cls.id,
                                  ModelReceipt.owner_model == "Group")
                     ).label('amount_refunded')

    @property
    def dealer_max_badges(self):
        return c.MAX_DEALERS or math.ceil(self.tables) + 1

    @property
    def dealer_badges_remaining(self):
        return self.dealer_max_badges - self.badges

    @property
    def hours_since_registered(self):
        if not self.registered:
            return 0
        delta = datetime.now(UTC) - self.registered
        return max(0, delta.total_seconds()) / 60.0 / 60.0

    @property
    def hours_remaining_in_grace_period(self):
        return max(0, c.GROUP_UPDATE_GRACE_PERIOD - self.hours_since_registered)

    @property
    def is_in_grace_period(self):
        return self.hours_remaining_in_grace_period > 0

    @property
    def min_badges_addable(self):
        if not c.PRE_CON:
            return 0

        if self.is_dealer and (not self.dealer_badges_remaining or self.amount_unpaid):
            return 0
        elif self.is_dealer or self.can_add:
            return 1
        elif self.guest and self.guest.group_type != c.MIVS:
            return 0
        else:
            return c.MIN_GROUP_ADDITION

    @property
    def physical_address(self):
        address1 = self.address1.strip()
        address2 = self.address2.strip()
        city = self.city.strip()
        region = self.region.strip()
        zip_code = self.zip_code.strip()
        country = self.country.strip()

        country = '' if country == 'United States' else country.strip()

        if city and region:
            city_region = '{}, {}'.format(city, region)
        else:
            city_region = city or region
        city_region_zip = '{} {}'.format(city_region, zip_code).strip()

        physical_address = [address1, address2, city_region_zip, country]
        return '\n'.join([s for s in physical_address if s])

    @property
    def guidebook_name(self):
        return self.name

    @property
    def guidebook_subtitle(self):
        category_labels = [cat for cat in self.categories_labels if 'Other' not in cat] + [self.categories_text]
        return ', '.join(category_labels[:5])

    @property
    def guidebook_desc(self):
        return self.description

    @property
    def guidebook_location(self):
        return ''
