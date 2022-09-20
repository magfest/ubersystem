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
from sqlalchemy.types import Boolean, Integer, Numeric

from uber.config import c
from uber.decorators import presave_adjustment
from uber.models import MagModel
from uber.models.types import default_relationship as relationship, utcnow, Choice, DefaultColumn as Column, \
    MultiChoice, TakesPaymentMixin
from uber.utils import add_opt, Charge


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

    _repr_attr_names = ['name']

    @presave_adjustment
    def _cost_and_leader(self):
        assigned = [a for a in self.attendees if not a.is_unassigned]
        if len(assigned) == 1:
            [self.leader] = assigned
        if self.auto_recalc:
            self.cost = self.default_cost
        elif not self.cost:
            self.cost = 0
        if self.status == c.APPROVED and not self.approved:
            self.approved = datetime.now(UTC)
        if self.leader and self.is_dealer:
            self.leader.ribbon = add_opt(self.leader.ribbon_ints, c.DEALER_RIBBON)
        if not self.is_unpaid:
            for a in self.attendees:
                a.presave_adjustments()
        
    @property
    def current_purchased_items(self):
        purchased_items = {}
        if not self.auto_recalc:
            # ¯\_(ツ)_/¯
            if self.cost:
                purchased_items['group_total'] = self.cost
        else:
            # Groups tables and paid-by-group badges by cost
            table_count = int(float(self.tables))
            default_price = c.TABLE_PRICES['default_price']
            more_tables = {default_price: 0}
            for i in range(table_count):
                if c.TABLE_PRICES[i] == default_price:
                    more_tables[default_price] += 1
                else:
                    purchased_items['table_' + str(i) + '_cost'] = c.TABLE_PRICES[i]
            if more_tables[default_price]:
                cost_label = str(more_tables[default_price]) + '_extra_table{}_($'.format(
                    's' if more_tables[default_price] > 1 else '') + str(default_price) + '_each)_cost'
                purchased_items[cost_label] = default_price * more_tables[default_price]
            
            badges_by_cost = {}
            for attendee in self.attendees:
                if attendee.paid == c.PAID_BY_GROUP:
                    badges_by_cost[attendee.badge_cost] = bool(badges_by_cost.get(attendee.badge_cost)) + 1
            for cost in badges_by_cost:
                cost_label = str(badges_by_cost[cost]) + '_badge{}_($'.format(
                    's' if badges_by_cost[cost] > 1 else '') + str(cost) + '_each)_cost'
                purchased_items[cost_label] = cost * badges_by_cost[cost]
        
        return purchased_items
                
    @presave_adjustment
    def assign_creator(self):
        if self.is_new and not self.creator_id:
            self.creator_id = self.session.admin_attendee().id if self.session.admin_attendee() else None
    
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
        return bool(
            self.tables
            and self.tables != '0'
            and self.tables != '0.0'
            and (not self.registered or self.cost
                or self.status != c.UNAPPROVED))

    @is_dealer.expression
    def is_dealer(cls):
        return and_(cls.tables > 0, or_(cls.cost > 0, cls.status != c.UNAPPROVED))

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
        return exists().where(and_(Attendee.group_id == cls.id, Attendee.paid == c.PAID_BY_GROUP))

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
    def new_badge_cost(self):
        return c.DEALER_BADGE_PRICE if self.is_dealer else c.get_group_price()

    @property
    def amount_extra(self):
        if self.is_new:
            return sum(a.total_cost - a.badge_cost for a in self.attendees if a.paid == c.PAID_BY_GROUP)
        else:
            return 0

    @property
    def total_cost(self):
        if self.active_receipt:
            return self.active_receipt['current_amount_owed']
        return self.default_cost + self.amount_extra

    @property
    def amount_unpaid(self):
        if self.registered:
            return max(0, ((self.cost * 100) - self.amount_paid - self.amount_pending) / 100)
        else:
            return self.total_cost

    @property
    def amount_pending(self):
        return self.active_receipt.get('pending_total', 0)

    @hybrid_property
    def amount_paid(self):
        return self.active_receipt.get('payment_total', 0)
    
    @amount_paid.expression
    def amount_paid(cls):
        from uber.models import ModelReceipt

        return select([ModelReceipt.payment_total]
                     ).where(and_(ModelReceipt.owner_id == cls.id,
                                  ModelReceipt.owner_model == "Group")
                     ).label('amount_paid')
    
    @hybrid_property
    def amount_refunded(self):
        return self.active_receipt.get('refund_total', 0)
    
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
        if self.is_dealer and not self.dealer_badges_remaining or self.amount_unpaid:
            return 0
        if self.can_add:
            return 1
        elif self.is_dealer:
            return 0
        else:
            return c.MIN_GROUP_ADDITION

    @property
    def requested_hotel_info(self):
        if self.leader:
            return self.leader.requested_hotel_info
        elif self.leader_id:  # unattached groups
            for attendee in self.attendees:
                if attendee.id == self.leader_id:
                    return attendee.requested_hotel_info
        else:
            return any(a.requested_hotel_info for a in self.attendees)

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
