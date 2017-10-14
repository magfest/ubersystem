import math
from datetime import datetime
from uuid import uuid4

from pytz import UTC
from sideboard.lib.sa import CoerceUTF8 as UnicodeText, \
    UTCDateTime, UUID
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import Boolean, Integer, Numeric

from uber.config import c
from uber.decorators import cost_property, presave_adjustment
from uber.models import MagModel
from uber.models.types import default_relationship as relationship, utcnow, \
    Choice, DefaultColumn as Column, MultiChoice, TakesPaymentMixin
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
    website = Column(UnicodeText)
    wares = Column(UnicodeText)
    categories = Column(MultiChoice(c.DEALER_WARES_OPTS))
    categories_text = Column(UnicodeText)
    description = Column(UnicodeText)
    special_needs = Column(UnicodeText)
    amount_paid = Column(Integer, default=0, index=True, admin_only=True)
    amount_refunded = Column(Integer, default=0, admin_only=True)
    cost = Column(Integer, default=0, admin_only=True)
    auto_recalc = Column(Boolean, default=True, admin_only=True)
    can_add = Column(Boolean, default=False, admin_only=True)
    admin_notes = Column(UnicodeText, admin_only=True)
    status = Column(
        Choice(c.DEALER_STATUS_OPTS), default=c.UNAPPROVED, admin_only=True)
    registered = Column(UTCDateTime, server_default=utcnow())
    approved = Column(UTCDateTime, nullable=True)
    leader_id = Column(
        UUID, ForeignKey('attendee.id', use_alter=True, name='fk_leader'),
        nullable=True)
    leader = relationship(
        'Attendee', foreign_keys=leader_id, post_update=True, cascade='all')

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
        if not self.amount_paid:
            self.amount_paid = 0
        if not self.amount_refunded:
            self.amount_refunded = 0
        if self.status == c.APPROVED and not self.approved:
            self.approved = datetime.now(UTC)
        if self.leader and self.is_dealer:
            self.leader.ribbon = add_opt(
                self.leader.ribbon_ints, c.DEALER_RIBBON)
        if not self.is_unpaid:
            for a in self.attendees:
                a.presave_adjustments()

    @property
    def sorted_attendees(self):
        return list(sorted(self.attendees, key=lambda a: (
            a.is_unassigned,
            a.id != self.leader_id,
            a.full_name)))

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
        return [
            a for a in self.attendees
            if a.is_unassigned and a.paid == c.PAID_BY_GROUP]

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

    @property
    def is_dealer(self):
        return bool(
            self.tables and
            self.tables != '0' and
            self.tables != '0.0' and
            (not self.registered or self.amount_paid or self.cost))

    @property
    def is_unpaid(self):
        return self.cost > 0 and self.amount_paid == 0

    @property
    def email(self):
        if self.leader and self.leader.email:
            return self.leader.email
        elif self.leader_id:  # unattached groups
            [leader] = [a for a in self.attendees if a.id == self.leader_id]
            return leader.email
        else:
            emails = [a.email for a in self.attendees if a.email]
            if len(emails) == 1:
                return emails[0]

    @property
    def badges_purchased(self):
        return len([a for a in self.attendees if a.paid == c.PAID_BY_GROUP])

    @property
    def badges(self):
        return len(self.attendees)

    @property
    def unregistered_badges(self):
        return len([a for a in self.attendees if a.is_unassigned])

    @cost_property
    def table_cost(self):
        table_count = int(float(self.tables))
        return sum(c.TABLE_PRICES[i] for i in range(1, 1 + table_count))

    @property
    def new_badge_cost(self):
        return c.DEALER_BADGE_PRICE if self.is_dealer else c.get_group_price()

    @cost_property
    def badge_cost(self):
        total = 0
        for attendee in self.attendees:
            if attendee.paid == c.PAID_BY_GROUP:
                total += attendee.badge_cost
        return total

    @property
    def amount_extra(self):
        if self.is_new:
            return sum(
                a.total_cost - a.badge_cost for a in self.attendees
                if a.paid == c.PAID_BY_GROUP)
        else:
            return 0

    @property
    def total_cost(self):
        return self.default_cost + self.amount_extra

    @property
    def amount_unpaid(self):
        if self.registered:
            return max(0, self.cost - self.amount_paid)
        else:
            return self.total_cost

    @property
    def dealer_max_badges(self):
        return math.ceil(self.tables) + 1

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
        return max(
            0, c.GROUP_UPDATE_GRACE_PERIOD - self.hours_since_registered)

    @property
    def is_in_grace_period(self):
        return self.hours_remaining_in_grace_period > 0

    @property
    def min_badges_addable(self):
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
