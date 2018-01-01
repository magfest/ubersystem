import json
from datetime import date, datetime
from uuid import uuid4

from pytz import UTC
from sideboard.lib import cached_property, listify, log
from sideboard.lib.sa import CoerceUTF8 as UnicodeText, \
    UTCDateTime, UUID
from sqlalchemy import and_, case, func, or_
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import backref, subqueryload
from sqlalchemy.schema import ForeignKey, Index, UniqueConstraint
from sqlalchemy.types import Boolean, Date, Integer

from uber.config import c
from uber.custom_tags import safe_string
from uber.decorators import classproperty, cost_property, \
    department_id_adapter, predelete_adjustment, presave_adjustment, render
from uber.models import MagModel
from uber.models.group import Group
from uber.models.types import default_relationship as relationship, utcnow, \
    Choice, DefaultColumn as Column, MultiChoice, TakesPaymentMixin
from uber.utils import add_opt, comma_and, get_age_from_birthday, \
    get_real_badge_type, hour_day_format, localized_now, remove_opt, \
    send_email


__all__ = ['Attendee', 'FoodRestrictions']


class Attendee(MagModel, TakesPaymentMixin):
    watchlist_id = Column(
        UUID, ForeignKey('watch_list.id', ondelete='set null'), nullable=True,
        default=None)

    group_id = Column(
        UUID, ForeignKey('group.id', ondelete='SET NULL'), nullable=True)
    group = relationship(
        Group, backref='attendees', foreign_keys=group_id,
        cascade='save-update,merge,refresh-expire,expunge')

    # NOTE: The cascade relationships for promo_code do NOT include
    # "save-update". During the preregistration workflow, before an Attendee
    # has paid, we create ephemeral Attendee objects that are saved in the
    # cherrypy session, but are NOT saved in the database. If the cascade
    # relationships specified "save-update" then the Attendee would
    # automatically be inserted in the database when the promo_code is set on
    # the Attendee object (which we do not want until the attendee pays).
    #
    # The practical result of this is that we must manually set promo_code_id
    # in order for the relationship to be persisted.
    promo_code_id = Column(
        UUID, ForeignKey('promo_code.id'), nullable=True, index=True)
    promo_code = relationship(
        'PromoCode',
        backref=backref('used_by', cascade='merge,refresh-expire,expunge'),
        foreign_keys=promo_code_id,
        cascade='merge,refresh-expire,expunge')

    placeholder = Column(Boolean, default=False, admin_only=True)
    first_name = Column(UnicodeText)
    last_name = Column(UnicodeText)
    legal_name = Column(UnicodeText)
    email = Column(UnicodeText)
    birthdate = Column(Date, nullable=True, default=None)
    age_group = Column(
        Choice(c.AGE_GROUPS), default=c.AGE_UNKNOWN, nullable=True)

    international = Column(Boolean, default=False)
    zip_code = Column(UnicodeText)
    address1 = Column(UnicodeText)
    address2 = Column(UnicodeText)
    city = Column(UnicodeText)
    region = Column(UnicodeText)
    country = Column(UnicodeText)
    no_cellphone = Column(Boolean, default=False)
    ec_name = Column(UnicodeText)
    ec_phone = Column(UnicodeText)
    cellphone = Column(UnicodeText)

    # Represents a request for hotel booking info during preregistration
    requested_hotel_info = Column(Boolean, default=False)

    interests = Column(MultiChoice(c.INTEREST_OPTS))
    found_how = Column(UnicodeText)
    comments = Column(UnicodeText)
    for_review = Column(UnicodeText, admin_only=True)
    admin_notes = Column(UnicodeText, admin_only=True)

    public_id = Column(UUID, default=lambda: str(uuid4()))
    badge_num = Column(Integer, default=None, nullable=True, admin_only=True)
    badge_type = Column(Choice(c.BADGE_OPTS), default=c.ATTENDEE_BADGE)
    badge_status = Column(
        Choice(c.BADGE_STATUS_OPTS), default=c.NEW_STATUS, index=True,
        admin_only=True)
    ribbon = Column(MultiChoice(c.RIBBON_OPTS), admin_only=True)

    affiliate = Column(UnicodeText)

    # attendee shirt size for both swag and staff shirts
    shirt = Column(Choice(c.SHIRT_OPTS), default=c.NO_SHIRT)
    second_shirt = Column(Choice(c.SECOND_SHIRT_OPTS), default=c.UNKNOWN)
    can_spam = Column(Boolean, default=False)
    regdesk_info = Column(UnicodeText, admin_only=True)
    extra_merch = Column(UnicodeText, admin_only=True)
    got_merch = Column(Boolean, default=False, admin_only=True)

    reg_station = Column(Integer, nullable=True, admin_only=True)
    registered = Column(UTCDateTime, server_default=utcnow())
    confirmed = Column(UTCDateTime, nullable=True, default=None)
    checked_in = Column(UTCDateTime, nullable=True)

    paid = Column(
        Choice(c.PAYMENT_OPTS), default=c.NOT_PAID, index=True,
        admin_only=True)
    overridden_price = Column(Integer, nullable=True, admin_only=True)
    base_badge_price = Column(Integer, default=0, admin_only=True)
    amount_paid = Column(Integer, default=0, admin_only=True)
    amount_extra = Column(
        Choice(c.DONATION_TIER_OPTS, allow_unspecified=True), default=0)
    extra_donation = Column(Integer, default=0)
    payment_method = Column(Choice(c.PAYMENT_METHOD_OPTS), nullable=True)
    amount_refunded = Column(Integer, default=0, admin_only=True)

    badge_printed_name = Column(UnicodeText)

    dept_checklist_items = relationship(
        'DeptChecklistItem', backref='attendee')
    dept_memberships = relationship('DeptMembership', backref='attendee')
    dept_membership_requests = relationship(
        'DeptMembershipRequest', backref='attendee')
    anywhere_dept_membership_request = relationship(
        'DeptMembershipRequest',
        primaryjoin='and_('
                    'DeptMembershipRequest.attendee_id == Attendee.id, '
                    'DeptMembershipRequest.department_id == None)',
        uselist=False,
        viewonly=True)
    dept_roles = relationship(
        'DeptRole',
        backref='attendees',
        cascade='save-update,merge,refresh-expire,expunge',
        secondaryjoin='and_('
                      'dept_membership_dept_role.c.dept_role_id '
                      '== DeptRole.id, '
                      'dept_membership_dept_role.c.dept_membership_id '
                      '== DeptMembership.id)',
        secondary='join(DeptMembership, dept_membership_dept_role)',
        order_by='DeptRole.name',
        viewonly=True)
    shifts = relationship('Shift', backref='attendee')
    jobs = relationship(
        'Job',
        backref='attendees_working_shifts',
        cascade='save-update,merge,refresh-expire,expunge',
        secondary='shift',
        order_by='Job.name',
        viewonly=True)
    jobs_in_assigned_depts = relationship(
        'Job',
        backref='attendees_in_dept',
        cascade='save-update,merge,refresh-expire,expunge',
        secondaryjoin='DeptMembership.department_id == Job.department_id',
        secondary='dept_membership',
        order_by='Job.name',
        viewonly=True)
    depts_where_working = relationship(
        'Department',
        backref='attendees_working_shifts',
        cascade='save-update,merge,refresh-expire,expunge',
        secondary='join(Shift, Job)',
        order_by='Department.name',
        viewonly=True)
    dept_memberships_with_inherent_role = relationship(
        'DeptMembership',
        primaryjoin='and_('
                    'Attendee.id == DeptMembership.attendee_id, '
                    'DeptMembership.has_inherent_role == True)',
        viewonly=True)
    dept_memberships_with_role = relationship(
        'DeptMembership',
        primaryjoin='and_('
                    'Attendee.id == DeptMembership.attendee_id, '
                    'DeptMembership.has_role == True)',
        viewonly=True)
    dept_memberships_as_dept_head = relationship(
        'DeptMembership',
        primaryjoin='and_('
                    'Attendee.id == DeptMembership.attendee_id, '
                    'DeptMembership.is_dept_head == True)',
        viewonly=True)
    dept_memberships_as_poc = relationship(
        'DeptMembership',
        primaryjoin='and_('
                    'Attendee.id == DeptMembership.attendee_id, '
                    'DeptMembership.is_poc == True)',
        viewonly=True)
    dept_memberships_where_can_admin_checklist = relationship(
        'DeptMembership',
        primaryjoin='and_('
                    'Attendee.id == DeptMembership.attendee_id, '
                    'or_('
                    'DeptMembership.is_dept_head == True,'
                    'DeptMembership.is_checklist_admin == True))',
        viewonly=True)
    dept_memberships_as_checklist_admin = relationship(
        'DeptMembership',
        primaryjoin='and_('
                    'Attendee.id == DeptMembership.attendee_id, '
                    'DeptMembership.is_checklist_admin == True)',
        viewonly=True)
    pocs_for_depts_where_working = relationship(
        'Attendee',
        cascade='save-update,merge,refresh-expire,expunge',
        primaryjoin='Attendee.id == Shift.attendee_id',
        secondaryjoin='and_('
                      'DeptMembership.attendee_id == Attendee.id, '
                      'DeptMembership.is_poc == True)',
        secondary='join(Shift, Job).join(DeptMembership, '
                  'DeptMembership.department_id == Job.department_id)',
        order_by='Attendee.full_name',
        viewonly=True)
    dept_heads_for_depts_where_working = relationship(
        'Attendee',
        cascade='save-update,merge,refresh-expire,expunge',
        primaryjoin='Attendee.id == Shift.attendee_id',
        secondaryjoin='and_('
                      'DeptMembership.attendee_id == Attendee.id, '
                      'DeptMembership.is_dept_head == True)',
        secondary='join(Shift, Job).join(DeptMembership, '
                  'DeptMembership.department_id == Job.department_id)',
        order_by='Attendee.full_name',
        viewonly=True)

    staffing = Column(Boolean, default=False)
    nonshift_hours = Column(Integer, default=0, admin_only=True)
    past_years = Column(UnicodeText, admin_only=True)
    can_work_setup = Column(Boolean, default=False, admin_only=True)
    can_work_teardown = Column(Boolean, default=False, admin_only=True)

    # TODO: a record of when an attendee is unable to pickup a shirt
    # (which type? swag or staff? prob swag)
    no_shirt = relationship(
        'NoShirt', backref=backref('attendee', load_on_pending=True),
        uselist=False)

    admin_account = relationship(
        'AdminAccount', backref=backref('attendee', load_on_pending=True),
        uselist=False)
    food_restrictions = relationship(
        'FoodRestrictions', backref=backref('attendee', load_on_pending=True),
        uselist=False)

    sales = relationship(
        'Sale', backref='attendee',
        cascade='save-update,merge,refresh-expire,expunge')
    mpoints_for_cash = relationship('MPointsForCash', backref='attendee')
    old_mpoint_exchanges = relationship(
        'OldMPointExchange', backref='attendee')
    dept_checklist_items = relationship(
        'DeptChecklistItem', backref=backref('attendee', lazy='subquery'))

    _attendee_table_args = [Index('ix_attendee_paid_group_id', paid, group_id)]
    if not c.SQLALCHEMY_URL.startswith('sqlite'):
        _attendee_table_args.append(UniqueConstraint(
            'badge_num', deferrable=True, initially='DEFERRED'))

    __table_args__ = tuple(_attendee_table_args)
    _repr_attr_names = ['full_name']

    @predelete_adjustment
    def _shift_badges(self):
        is_skipped = getattr(self, '_skip_badge_shift_on_delete', False)
        if self.badge_num and not is_skipped:
            self.session.shift_badges(
                self.badge_type, self.badge_num + 1, down=True)

    @presave_adjustment
    def _misc_adjustments(self):
        if not self.amount_extra:
            self.affiliate = ''

        if self.birthdate == '':
            self.birthdate = None

        if not self.extra_donation:
            self.extra_donation = 0

        if not self.gets_any_kind_of_shirt:
            self.shirt = c.NO_SHIRT

        if self.paid != c.REFUNDED:
            self.amount_refunded = 0

        if self.badge_cost == 0 and self.paid in [c.NOT_PAID, c.PAID_BY_GROUP]:
            self.paid = c.NEED_NOT_PAY

        if not self.base_badge_price:
            self.base_badge_price = self.new_badge_cost

        if c.AT_THE_CON and self.badge_num and not self.checked_in and \
                self.is_new and \
                self.badge_type not in c.PREASSIGNED_BADGE_TYPES:
            self.checked_in = datetime.now(UTC)

        if self.birthdate:
            self.age_group = self.age_group_conf['val']

        for attr in ['first_name', 'last_name']:
            value = getattr(self, attr)
            if value.isupper() or value.islower():
                setattr(self, attr, value.title())

        if self.legal_name and self.full_name == self.legal_name:
            self.legal_name = ''

    @presave_adjustment
    def _status_adjustments(self):
        if self.badge_status == c.NEW_STATUS and self.banned:
            self.badge_status = c.WATCHED_STATUS
            try:
                send_email(
                    c.SECURITY_EMAIL, [c.REGDESK_EMAIL, c.SECURITY_EMAIL],
                    c.EVENT_NAME + ' WatchList Notification',
                    render('emails/reg_workflow/attendee_watchlist.txt', {
                        'attendee': self}),
                    model='n/a')
            except Exception as ex:
                log.error('unable to send banned email about {}', self)

        elif self.badge_status == c.NEW_STATUS and not self.placeholder and \
                self.first_name and (
                    self.paid in [c.HAS_PAID, c.NEED_NOT_PAY] or
                    self.paid == c.PAID_BY_GROUP and
                    self.group_id and
                    not self.group.is_unpaid):
            self.badge_status = c.COMPLETED_STATUS

    @presave_adjustment
    def _staffing_adjustments(self):
        if self.is_dept_head:
            self.staffing = True
            self.ribbon = add_opt(self.ribbon_ints, c.DEPT_HEAD_RIBBON)
            if c.SHIFT_CUSTOM_BADGES or \
                    c.STAFF_BADGE not in c.PREASSIGNED_BADGE_TYPES:
                self.badge_type = c.STAFF_BADGE
            if self.paid == c.NOT_PAID:
                self.paid = c.NEED_NOT_PAY
        else:
            if c.VOLUNTEER_RIBBON in self.ribbon_ints and self.is_new:
                self.staffing = True

        if not self.is_new:
            old_ribbon = map(int, self.orig_value_of('ribbon').split(',')) \
                if self.orig_value_of('ribbon') else []
            old_staffing = self.orig_value_of('staffing')

            if self.staffing and not old_staffing or \
                    c.VOLUNTEER_RIBBON in self.ribbon_ints and \
                    c.VOLUNTEER_RIBBON not in old_ribbon:
                self.staffing = True

            elif old_staffing and not self.staffing \
                    or c.VOLUNTEER_RIBBON not in self.ribbon_ints \
                    and c.VOLUNTEER_RIBBON in old_ribbon \
                    and not self.is_dept_head:
                self.unset_volunteering()

        if self.badge_type == c.STAFF_BADGE:
            self.ribbon = remove_opt(self.ribbon_ints, c.VOLUNTEER_RIBBON)

        elif self.staffing and self.badge_type != c.STAFF_BADGE and \
                c.VOLUNTEER_RIBBON not in self.ribbon_ints:
            self.ribbon = add_opt(self.ribbon_ints, c.VOLUNTEER_RIBBON)

        if self.badge_type == c.STAFF_BADGE:
            self.staffing = True
            if not self.overridden_price \
                    and self.paid in [c.NOT_PAID, c.PAID_BY_GROUP]:
                self.paid = c.NEED_NOT_PAY

    @presave_adjustment
    def _badge_adjustments(self):
        from uber.badge_funcs import needs_badge_num
        if self.badge_type == c.PSEUDO_DEALER_BADGE:
            self.ribbon = add_opt(self.ribbon_ints, c.DEALER_RIBBON)

        self.badge_type = self.badge_type_real

        old_type = self.orig_value_of('badge_type')
        old_num = self.orig_value_of('badge_num')

        if not needs_badge_num(self):
            self.badge_num = None

        if old_type != self.badge_type or old_num != self.badge_num:
            self.session.update_badge(self, old_type, old_num)
        elif needs_badge_num(self) and not self.badge_num:
            self.badge_num = self.session.get_next_badge_num(self.badge_type)

    @presave_adjustment
    def _use_promo_code(self):
        if c.BADGE_PROMO_CODES_ENABLED and self.promo_code and \
                not self.overridden_price and self.is_unpaid:
            if self.badge_cost > 0:
                self.overridden_price = self.badge_cost
            else:
                self.paid = c.NEED_NOT_PAY

    def unset_volunteering(self):
        self.staffing = False
        self.dept_membership_requests = []
        self.requested_depts = []
        self.dept_memberships = []
        self.ribbon = remove_opt(self.ribbon_ints, c.VOLUNTEER_RIBBON)
        if self.badge_type == c.STAFF_BADGE:
            self.badge_type = c.ATTENDEE_BADGE
            self.badge_num = None
        del self.shifts[:]

    @property
    def assigned_depts_opts(self):
        return [(d.id, d.name) for d in self.assigned_depts]

    @property
    def ribbon_and_or_badge(self):
        if self.ribbon and self.badge_type != c.ATTENDEE_BADGE:
            return ' / '.join([self.badge_type_label] + self.ribbon_labels)
        elif self.ribbon:
            return ' / '.join(self.ribbon_labels)
        else:
            return self.badge_type_label

    @property
    def badge_type_real(self):
        return get_real_badge_type(self.badge_type)

    @cost_property
    def badge_cost(self):
        return self.calculate_badge_cost()

    @property
    def badge_cost_without_promo_code(self):
        return self.calculate_badge_cost(use_promo_code=False)

    def calculate_badge_cost(self, use_promo_code=True):
        if self.paid == c.NEED_NOT_PAY:
            return 0
        elif self.overridden_price is not None:
            return self.overridden_price
        elif self.base_badge_price:
            cost = self.base_badge_price
        else:
            cost = self.new_badge_cost

        if c.BADGE_PROMO_CODES_ENABLED and self.promo_code and use_promo_code:
            return self.promo_code.calculate_discounted_price(cost)
        else:
            return cost

    @property
    def new_badge_cost(self):
        # What this badge would cost if it were new, i.e., not taking into
        # account special overrides
        registered = self.registered_local if self.registered else None
        if self.is_dealer:
            return c.DEALER_BADGE_PRICE
        elif self.badge_type == c.ONE_DAY_BADGE:
            return c.get_oneday_price(registered)
        elif self.is_presold_oneday:
            return c.get_presold_oneday_price(self.badge_type)
        elif self.badge_type in c.BADGE_TYPE_PRICES:
            return int(c.BADGE_TYPE_PRICES[self.badge_type])
        elif self.age_discount != 0:
            return max(0, c.get_attendee_price(registered) + self.age_discount)
        elif self.group and self.paid == c.PAID_BY_GROUP:
            return c.get_attendee_price(registered) - c.GROUP_DISCOUNT
        else:
            return c.get_attendee_price(registered)

    @property
    def promo_code_code(self):
        """
        Convenience property for accessing `promo_code.code` if available.

        Returns:
            str: `promo_code.code` if `promo_code` is not `None`, empty string
                otherwise.
        """
        return self.promo_code.code if self.promo_code else ''

    @property
    def age_discount(self):
        return -self.age_group_conf['discount']

    @property
    def age_group_conf(self):
        if self.birthdate:
            day = c.EPOCH.date() \
                if date.today() <= c.EPOCH.date() \
                else localized_now().date()

            attendee_age = get_age_from_birthday(self.birthdate, day)
            for val, age_group in c.AGE_GROUP_CONFIGS.items():
                if val != c.AGE_UNKNOWN and \
                        age_group['min_age'] <= attendee_age and \
                        attendee_age <= age_group['max_age']:
                    return age_group

        return c.AGE_GROUP_CONFIGS[int(self.age_group or c.AGE_UNKNOWN)]

    @property
    def total_cost(self):
        return self.default_cost + self.amount_extra

    @property
    def total_donation(self):
        return self.total_cost - self.badge_cost

    @cost_property
    def donation_cost(self):
        return self.extra_donation or 0

    @property
    def amount_unpaid(self):
        if self.paid == c.PAID_BY_GROUP:
            personal_cost = max(0, self.total_cost - self.badge_cost)
        else:
            personal_cost = self.total_cost
        return max(0, personal_cost - self.amount_paid)

    @property
    def is_unpaid(self):
        return self.paid == c.NOT_PAID

    @property
    def is_unassigned(self):
        return not self.first_name

    @property
    def is_dealer(self):
        return c.DEALER_RIBBON in self.ribbon_ints or \
            self.badge_type == c.PSEUDO_DEALER_BADGE or (
                self.group and
                self.group.is_dealer and
                self.paid == c.PAID_BY_GROUP)

    @property
    def is_checklist_admin(self):
        return any(m.is_checklist_admin for m in self.dept_memberships)

    @property
    def is_dept_head(self):
        return any(m.is_dept_head for m in self.dept_memberships)

    @property
    def is_presold_oneday(self):
        """
        Returns a boolean indicating whether this is a c.FRIDAY/c.SATURDAY/etc
        badge; see the presell_one_days config option for a full explanation.
        """
        return self.badge_type_label in c.DAYS_OF_WEEK

    @property
    def is_not_ready_to_checkin(self):
        """
        Returns None if we are ready for checkin, otherwise a short error
        message why we can't check them in.
        """
        if self.paid == c.NOT_PAID:
            return "Not paid"

        # When someone claims an unassigned group badge on-site, they first
        # fill out a new registration which is paid-by-group but isn't assigned
        # to a group yet (the admin does that when they check in).
        if self.badge_status != c.COMPLETED_STATUS and not (
                self.badge_status == c.NEW_STATUS and
                self.paid == c.PAID_BY_GROUP and
                not self.group_id):
            return "Badge status"

        if self.is_unassigned:
            return "Badge not assigned"

        if self.is_presold_oneday:
            if self.badge_type_label != localized_now().strftime('%A'):
                return "Wrong day"

        return None

    @property
    def can_abandon_badge(self):
        return not self.amount_paid and not self.paid == c.NEED_NOT_PAY and not self.is_group_leader

    @property
    def shirt_size_marked(self):
        return self.shirt not in [c.NO_SHIRT, c.SIZE_UNKNOWN]

    @property
    def shirt_info_marked(self):
        return self.shirt_size_marked and (
            not self.gets_staff_shirt
            or self.second_shirt != c.UNKNOWN
            or c.AFTER_SHIRT_DEADLINE)

    @property
    def is_group_leader(self):
        return self.group and self.id == self.group.leader_id

    @property
    def unassigned_name(self):
        if self.group_id and self.is_unassigned:
            return '[Unassigned {self.badge}]'.format(self=self)

    @hybrid_property
    def full_name(self):
        return self.unassigned_name or \
            '{self.first_name} {self.last_name}'.format(self=self)

    @full_name.expression
    def full_name(cls):
        return case([(
            or_(cls.first_name == None, cls.first_name == ''),  # noqa: E711
            'zzz'
        )], else_=func.lower(cls.first_name + ' ' + cls.last_name))

    @hybrid_property
    def last_first(self):
        return self.unassigned_name or \
            '{self.last_name}, {self.first_name}'.format(self=self)

    @last_first.expression
    def last_first(cls):
        return case([(
            or_(cls.first_name == None, cls.first_name == ''),  # noqa: E711
            'zzz'
        )], else_=func.lower(cls.last_name + ', ' + cls.first_name))

    @hybrid_property
    def normalized_email(self):
        return self.normalize_email(self.email)

    @normalized_email.expression
    def normalized_email(cls):
        return func.replace(func.lower(func.trim(cls.email)), '.', '')

    @classmethod
    def normalize_email(cls, email):
        return email.strip().lower().replace('.', '')

    @property
    def watchlist_guess(self):
        try:
            from uber.models import Session
            with Session() as session:
                watchentries = session.guess_attendee_watchentry(self)
                return [w.to_dict() for w in watchentries]
        except Exception as ex:
            log.warning('Error guessing watchlist entry: {}', ex)
            return None

    @property
    def banned(self):
        return listify(self.watch_list or self.watchlist_guess)

    @property
    def badge(self):
        if self.paid == c.NOT_PAID:
            badge = 'Unpaid ' + self.badge_type_label
        elif self.badge_num:
            badge = '{} #{}'.format(self.badge_type_label, self.badge_num)
        else:
            badge = self.badge_type_label

        if self.ribbon:
            badge += ' ({})'.format(", ".join(self.ribbon_labels))

        return badge

    @property
    def is_transferable(self):
        return not self.is_new and \
            not self.checked_in and \
            self.paid in [c.HAS_PAID, c.PAID_BY_GROUP] and \
            self.badge_type in c.TRANSFERABLE_BADGE_TYPES and \
            not self.admin_account and \
            not self.has_role_somewhere

    @property
    def paid_for_a_shirt(self):
        return self.amount_extra >= c.SHIRT_LEVEL

    @property
    def volunteer_event_shirt_eligible(self):
        """
        Returns a truthy value if this attendee either automatically gets a
        complementary event shirt for being staff OR if they've eligible for a
        complementary event shirt if they end up working enough volunteer hours
        """
        # Some events want to exclude staff badges from getting event shirts
        # (typically because they are getting staff uniform shirts instead).
        if self.badge_type == c.STAFF_BADGE:
            return c.STAFF_ELIGIBLE_FOR_SWAG_SHIRT
        else:
            return c.VOLUNTEER_RIBBON in self.ribbon_ints

    @property
    def volunteer_event_shirt_earned(self):
        return self.volunteer_event_shirt_eligible and (
            not self.takes_shifts or self.worked_hours >= 6)

    @property
    def replacement_staff_shirts(self):
        """
        Staffers can choose whether or not they want to swap out one of their
        staff shirts for an event shirt.  By default and if the staffer opts
        into this, we deduct 1 staff shirt from the staff shirt count and add 1
        to the event shirt count.
        """
        is_replaced = self.second_shirt in [c.UNKNOWN, c.STAFF_AND_EVENT_SHIRT]
        return 1 if self.gets_staff_shirt and is_replaced else 0

    @property
    def num_event_shirts_owed(self):
        return sum([
            int(self.paid_for_a_shirt),
            int(self.volunteer_event_shirt_eligible),
            self.replacement_staff_shirts
        ])

    @property
    def gets_staff_shirt(self):
        return self.badge_type == c.STAFF_BADGE

    @property
    def num_staff_shirts_owed(self):
        return 0 if not self.gets_staff_shirt else (
            c.SHIRTS_PER_STAFFER - self.replacement_staff_shirts)

    @property
    def gets_any_kind_of_shirt(self):
        return self.gets_staff_shirt or self.num_event_shirts_owed > 0

    @property
    def has_personalized_badge(self):
        return self.badge_type in c.PREASSIGNED_BADGE_TYPES

    @property
    def donation_swag(self):
        donation_items = [
            desc for amount, desc in sorted(c.DONATION_TIERS.items())
            if amount and self.amount_extra >= amount]

        extra_donations = \
            ['Extra donation of ${}'.format(self.extra_donation)] \
            if self.extra_donation else []

        return donation_items + extra_donations

    @property
    def merch(self):
        """
        Here is the business logic surrounding shirts:
        - People who kick in enough to get a shirt get an event shirt.
        - People with staff badges get a configurable number of staff shirts.
        - Volunteers who meet the requirements get a complementary event shirt
            (NOT a staff shirt).
        """
        merch = self.donation_swag

        if self.volunteer_event_shirt_eligible:
            shirt = c.DONATION_TIERS[c.SHIRT_LEVEL]
            if self.paid_for_a_shirt:
                shirt = 'a 2nd ' + shirt
            if not self.volunteer_event_shirt_earned:
                shirt += (
                    ' (this volunteer must work at least 6 hours or '
                    'they will be reported for picking up their shirt)')
            merch.append(shirt)

        if self.gets_staff_shirt:
            staff_shirts = '{} Staff Shirt{}'.format(
                c.SHIRTS_PER_STAFFER, 's' if c.SHIRTS_PER_STAFFER > 1 else '')
            if self.shirt_size_marked:
                staff_shirts += ' [{}]'.format(c.SHIRTS[self.shirt])
            merch.append(staff_shirts)

        if self.staffing:
            merch.append('Staffer Info Packet')

        if self.extra_merch:
            merch.append(self.extra_merch)

        return comma_and(merch)

    @property
    def accoutrements(self):
        stuff = [] \
            if not self.ribbon \
            else ['a ' + s + ' ribbon' for s in self.ribbon_labels]

        if c.WRISTBANDS_ENABLED:
            stuff.append('a {} wristband'.format(
                c.WRISTBAND_COLORS[self.age_group]))
        if self.regdesk_info:
            stuff.append(self.regdesk_info)
        return (' with ' if stuff else '') + comma_and(stuff)

    @property
    def multiply_assigned(self):
        return len(self.dept_memberships) > 1

    @property
    def takes_shifts(self):
        return bool(
            self.staffing and
            any(not d.is_shiftless for d in self.assigned_depts))

    @property
    def hours(self):
        all_hours = set()
        for shift in self.shifts:
            all_hours.update(shift.job.hours)
        return all_hours

    @property
    def hour_map(self):
        all_hours = {}
        for shift in self.shifts:
            for hour in shift.job.hours:
                all_hours[hour] = shift.job
        return all_hours

    @cached_property
    def available_job_filters(self):
        from uber.models.department import Job

        job_filters = [Job.is_unfilled]
        if c.AT_THE_CON:
            return job_filters

        member_dept_ids = set(d.department_id for d in self.dept_memberships)
        requested_dept_ids = set(
            d.department_id for d in self.dept_membership_requests) \
            .difference(member_dept_ids)

        member_filter = Job.department_id.in_(member_dept_ids) \
            if member_dept_ids else None

        max_depts = c.MAX_DEPTS_WHERE_WORKING
        no_max = max_depts < 1

        requested_filter = None
        if requested_dept_ids and (len(member_dept_ids) < max_depts or no_max):
            depts_where_working = set(j.department_id for j in self.jobs)
            if len(depts_where_working) >= max_depts and not no_max:
                requested_dept_ids = depts_where_working \
                    .difference(member_dept_ids)

            requested_any_dept = None in requested_dept_ids
            if requested_any_dept:
                requested_filter = Job.visibility > Job.ONLY_MEMBERS
            elif requested_dept_ids:
                requested_filter = and_(
                    Job.visibility > Job.ONLY_MEMBERS,
                    Job.department_id.in_(requested_dept_ids))

        if member_filter is not None and requested_filter is not None:
            job_filters += [or_(member_filter, requested_filter)]
        elif member_filter is not None:
            job_filters += [member_filter]
        elif requested_filter is not None:
            job_filters += [requested_filter]
        return job_filters

    @cached_property
    def available_jobs(self):
        assert self.session, (
            '{}.available_jobs property may only be accessed for '
            'objects attached to a session'.format(self.__class__.__name__))

        if not self.staffing or (
                not c.AT_THE_CON and
                not self.dept_memberships and
                not self.dept_membership_requests):
            return []

        from uber.models.department import Job
        jobs = self.session.query(Job).filter(*self.available_job_filters) \
            .options(
                subqueryload(Job.shifts),
                subqueryload(Job.department),
                subqueryload(Job.required_roles)) \
            .order_by(Job.start_time, Job.department_id).all()
        return [job for job in jobs if self.has_required_roles(job)]

    @cached_property
    def possible(self):
        assert self.session, (
            '{}.possible property may only be accessed for '
            'objects attached to a session'.format(self.__class__.__name__))

        return [
            job for job in self.available_jobs
            if job.no_overlap(self)
            and (
                job.type != c.SETUP
                or self.can_work_setup
                or job.department.is_setup_approval_exempt)
            and (
                job.type != c.TEARDOWN
                or self.can_work_teardown
                or job.department.is_teardown_approval_exempt)]

    @property
    def possible_opts(self):
        return [
            (job.id, '({}) [{}] {}'.format(
                hour_day_format(job.start_time),
                job.department_name,
                job.name))
            for job in self.possible
            if localized_now() < job.start_time]

    @property
    def possible_and_current(self):
        jobs = [s.job for s in self.shifts]
        for job in jobs:
            job.taken = True
        jobs.extend(self.possible)
        return sorted(jobs, key=lambda j: j.start_time)

    # ========================================================================
    # TODO: Refactor all this stuff regarding assigned_depts and
    #       requested_depts. Maybe a @suffix_property with a setter for the
    #       *_ids fields? The hardcoded *_labels props are also not great.
    #       There's a bigger feature here that I haven't wrapped my head
    #       around yet. A generic way to lazily set relations using ids.
    # ========================================================================

    @classproperty
    def extra_apply_attrs(cls):
        return set(['assigned_depts_ids']).union(
            cls.extra_apply_attrs_restricted)

    @classproperty
    def extra_apply_attrs_restricted(cls):
        return set(['requested_depts_ids'])

    @property
    def assigned_depts_labels(self):
        return [d.name for d in self.assigned_depts]

    @property
    def requested_depts_labels(self):
        return [d.name for d in self.requested_depts]

    @property
    def assigned_depts_ids(self):
        _, ids = self._get_relation_ids('assigned_depts')
        return [str(d.id) for d in self.assigned_depts] if ids is None else ids

    @assigned_depts_ids.setter
    def assigned_depts_ids(self, value):
        values = set(s for s in listify(value) if s)
        for membership in list(self.dept_memberships):
            if membership.department_id not in values:
                # Manually remove dept_memberships to ensure the associated
                # rows in the dept_membership_dept_role table are deleted.
                self.dept_memberships.remove(membership)
        from uber.models.department import Department
        self._set_relation_ids('assigned_depts', Department, list(values))

    @property
    def requested_depts_ids(self):
        return [d.department_id or 'All'
                for d in self.dept_membership_requests]

    @requested_depts_ids.setter
    def requested_depts_ids(self, value):
        from uber.models.department import DeptMembershipRequest
        values = set(
            None if s in ('None', 'All') else s
            for s in listify(value) if s != '')

        for membership in list(self.dept_membership_requests):
            if membership.department_id not in values:
                self.dept_membership_requests.remove(membership)
        department_ids = set(
            str(d.department_id) for d in self.dept_membership_requests)
        for department_id in values:
            if str(department_id) not in department_ids:
                self.dept_membership_requests.append(DeptMembershipRequest(
                    department_id=department_id, attendee_id=self.id))

    @property
    def worked_shifts(self):
        return [s for s in self.shifts if s.worked == c.SHIFT_WORKED]

    @property
    def weighted_hours(self):
        weighted_hours = sum(s.job.weighted_hours for s in self.shifts)
        return weighted_hours + self.nonshift_hours

    @department_id_adapter
    def weighted_hours_in(self, department_id):
        if not department_id:
            return self.weighted_hours
        return sum(
            shift.job.weighted_hours for shift in self.shifts
            if shift.job.department_id == department_id)

    @property
    def worked_hours(self):
        weighted_hours = sum(
            s.job.real_duration * s.job.weight for s in self.worked_shifts)
        return weighted_hours + self.nonshift_hours

    @department_id_adapter
    def dept_membership_for(self, department_id):
        if not department_id:
            return None
        for m in self.dept_memberships:
            if m.department_id == department_id:
                return m
        return None

    @department_id_adapter
    def requested(self, department_id):
        if not department_id or department_id == 'All':
            department_id = None
        return any(
            m.department_id == department_id
            for m in self.dept_membership_requests)

    @department_id_adapter
    def assigned_to(self, department_id):
        if not department_id:
            return False
        return any(
            m.department_id == department_id
            for m in self.dept_memberships)

    def trusted_in(self, department):
        return self.has_role_in(department)

    def can_admin_dept_for(self, department):
        return (self.admin_account
                and c.ACCOUNTS in self.admin_account.access_ints) \
                    or self.has_inherent_role_in(department)

    def can_dept_head_for(self, department):
        return (self.admin_account
                and c.ACCOUNTS in self.admin_account.access_ints) \
                    or self.is_dept_head_of(department)

    @property
    def can_admin_checklist(self):
        return (self.admin_account
                and c.ACCOUNTS in self.admin_account.access_ints) \
            or bool(self.dept_memberships_where_can_admin_checklist)

    @department_id_adapter
    def can_admin_checklist_for(self, department_id):
        if not department_id:
            return False
        return (self.admin_account
                and c.ACCOUNTS in self.admin_account.access_ints) \
            or any(
                m.department_id == department_id
                for m in self.dept_memberships_where_can_admin_checklist)

    @department_id_adapter
    def is_checklist_admin_of(self, department_id):
        if not department_id:
            return False
        return any(
            m.department_id == department_id and m.is_checklist_admin
            for m in self.dept_memberships)

    @department_id_adapter
    def is_dept_head_of(self, department_id):
        if not department_id:
            return False
        return any(
            m.department_id == department_id and m.is_dept_head
            for m in self.dept_memberships)

    @department_id_adapter
    def is_poc_of(self, department_id):
        if not department_id:
            return False
        return any(
            m.department_id == department_id and m.is_poc
            for m in self.dept_memberships)

    def checklist_item_for_slug(self, slug):
        for item in self.dept_checklist_items:
            if item.slug == slug:
                return item
        return None

    def completed_every_checklist_for(self, slug):
        return all(
            d.checklist_item_for_slug(slug) for d in self.checklist_depts)

    @property
    def gets_any_checklist(self):
        return bool(self.dept_memberships_as_checklist_admin)

    def has_role(self, role):
        return any(r.id == role.id for r in self.dept_roles)

    @department_id_adapter
    def has_inherent_role_in(self, department_id):
        if not department_id:
            return False
        return any(
            m.department_id == department_id
            for m in self.dept_memberships_with_inherent_role)

    @department_id_adapter
    def has_role_in(self, department_id):
        if not department_id:
            return False
        return any(
            m.department_id == department_id
            for m in self.dept_memberships_with_role)

    def has_required_roles(self, job):
        if not job.required_roles:
            return True
        required_role_ids = set(r.id for r in job.required_roles)
        role_ids = set(r.id for r in self.dept_roles)
        return required_role_ids.issubset(role_ids)

    @property
    def has_role_somewhere(self):
        """
        Returns True if at least one of the following is true for at least
        one department:
            - is a department head
            - is a point of contact
            - is a checklist admin
            - has a dept role
        """
        return bool(self.dept_memberships_with_role)

    def has_shifts_in(self, department):
        return department in self.depts_where_working

    @property
    def food_restrictions_filled_out(self):
        return self.food_restrictions if c.STAFF_GET_FOOD else True

    @property
    def shift_prereqs_complete(self):
        return not self.placeholder and \
            self.food_restrictions_filled_out and self.shirt_info_marked

    @property
    def past_years_json(self):
        return json.loads(self.past_years or '[]')

    @property
    def must_contact(self):
        dept_chairs = []
        for dept in self.depts_where_working:
            poc_names = ' / '.join(
                sorted(poc.full_name for poc in dept.pocs))
            dept_chairs.append('({}) {}'.format(dept.name, poc_names))
        return safe_string('<br/>'.join(sorted(dept_chairs)))

    def append_admin_note(self, note):
        if self.admin_notes:
            self.admin_notes = '{}\n\n{}'.format(self.admin_notes, note)
        else:
            self.admin_notes = note


class FoodRestrictions(MagModel):
    attendee_id = Column(UUID, ForeignKey('attendee.id'), unique=True)
    standard = Column(MultiChoice(c.FOOD_RESTRICTION_OPTS))
    sandwich_pref = Column(MultiChoice(c.SANDWICH_OPTS))
    freeform = Column(UnicodeText)

    def __getattr__(self, name):
        try:
            return super(FoodRestrictions, self).__getattr__(name)
        except AttributeError:
            restriction = getattr(c, name.upper())
            if restriction not in c.FOOD_RESTRICTIONS:
                return MagModel.__getattr__(self, name)
            elif restriction == c.VEGAN and c.VEGAN in self.standard_ints:
                return False
            elif restriction == c.PORK and c.VEGAN in self.standard_ints:
                return True
            else:
                return restriction in self.standard_ints
