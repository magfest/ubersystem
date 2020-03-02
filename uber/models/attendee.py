import json
import math
import re
from datetime import date, datetime, timedelta
from uuid import uuid4

from pockets import cached_property, classproperty, groupify, listify, is_listy, readable_join
from pockets.autolog import log
from pytz import UTC
from residue import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.dialects.postgresql.json import JSONB
from sqlalchemy.orm import backref, subqueryload
from sqlalchemy.schema import Column as SQLAlchemyColumn, ForeignKey, Index, UniqueConstraint
from sqlalchemy.types import Boolean, Date, Integer

import uber
from uber.config import c
from uber.custom_tags import safe_string, time_day_local
from uber.decorators import cost_property, department_id_adapter, predelete_adjustment, presave_adjustment, \
    render
from uber.models import MagModel
from uber.models.group import Group
from uber.models.types import default_relationship as relationship, utcnow, Choice, DefaultColumn as Column, \
    MultiChoice, TakesPaymentMixin
from uber.utils import add_opt, get_age_from_birthday, hour_day_format, localized_now, mask_string, remove_opt


__all__ = ['Attendee', 'FoodRestrictions']


RE_NONDIGIT = re.compile(r'\D+')


# The order of name_suffixes is important. It should be sorted in descending
# order, using the length of the suffix with periods removed.
name_suffixes = [
    'Sisters of Our Lady of Charity of the Good Shepherd',
    'Sisters of Holy Names of Jesus and Mary',
    'Sisters of Holy Names of Jesus & Mary',
    'United States Marine Corps Reserve',
    'Certified Fund Raising Executive',
    'United States Air Force Reserve',
    'Doctor of Veterinary Medicine',
    'Society of Holy Child Jesus',
    'Certified Public Accountant',
    'United States Navy Reserve',
    'United States Marine Corps',
    'United States Army Reserve',
    'Sister of Saint Mary Order',
    'Registered Nurse Clinician',
    'Congregation of Holy Cross',
    'Chartered Life Underwriter',
    'United States Coast Guard',
    'Doctor of Dental Medicine',
    'Doctor of Dental Surgery',
    'United States Air Force',
    'Doctor of Chiropractic',
    'Protestant Episcopal',
    'Order of St Benedict',
    'Sisters of St. Joseph',
    'Doctor of Philosophy',
    'Doctor of Osteopathy',
    'Doctor of Education',
    'Blessed Virgin Mary',
    'Doctor of Optometry',
    'United States Navy',
    'United States Army',
    'Doctor of Divinity',
    'Doctor of Medicine',
    'Society of Jesus',
    'Registered Nurse',
    'Police Constable',
    'Post Commander',
    'Doctor of Laws',
    'Past Commander',
    'Incorporated',
    'Juris Doctor',
    'The Fourth',
    'The Second',
    'The Third',
    'The First',
    'the 4th',
    'the 3rd',
    'the 2nd',
    'the 1st',
    'Retired',
    'Limited',
    'Esquire',
    'Senior',
    'Junior',
    'USMCR',
    'USAFR',
    'USNR',
    'USMC',
    'USCG',
    'USAR',
    'USAF',
    'S.S.M.O.',
    'S.N.J.M.',
    'S.H.C.J.',
    'CFRE',
    'USN',
    'USA',
    'R.N.C.',
    'R.G.S',
    'Ret.',
    'O.S.B.',
    'Ltd.',
    'LL.D.',
    'Inc.',
    'Ed.D.',
    'D.V.M.',
    'C.S.J.',
    'C.S.C.',
    'CPA',
    'CLU',
    'B.V.M.',
    'Ph.D.',
    'D.M.D.',
    'D.D.S.',
    '4th',
    '3rd',
    '2nd',
    '1st',
    'III',
    'Esq.',
    'S.J.',
    'R.N.',
    'P.E.',
    'P.C.',
    'D.D.',
    'D.C.',
    'O.D.',
    'M.D.',
    'J.D.',
    'D.O.',
    'Sr.',
    'Jr.',
    'IV',
    'II']


normalized_name_suffixes = [re.sub(r'[,\.]', '', s.lower()) for s in name_suffixes]


class Attendee(MagModel, TakesPaymentMixin):
    watchlist_id = Column(UUID, ForeignKey('watch_list.id', ondelete='set null'), nullable=True, default=None)
    group_id = Column(UUID, ForeignKey('group.id', ondelete='SET NULL'), nullable=True)
    group = relationship(
        Group, backref='attendees', foreign_keys=group_id, cascade='save-update,merge,refresh-expire,expunge')
    
    creator_id = Column(UUID, ForeignKey('attendee.id'), nullable=True)
    creator = relationship(
        'Attendee',
        backref=backref('created_badges', order_by='Attendee.full_name', cascade='all,delete-orphan'),
        cascade='save-update,merge,refresh-expire,expunge',
        remote_side='Attendee.id',
        single_parent=True)

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
    promo_code_id = Column(UUID, ForeignKey('promo_code.id'), nullable=True, index=True)
    promo_code = relationship(
        'PromoCode',
        backref=backref('used_by', cascade='merge,refresh-expire,expunge'),
        foreign_keys=promo_code_id,
        cascade='merge,refresh-expire,expunge')

    placeholder = Column(Boolean, default=False, admin_only=True, index=True)
    first_name = Column(UnicodeText)
    last_name = Column(UnicodeText)
    legal_name = Column(UnicodeText)
    email = Column(UnicodeText)
    birthdate = Column(Date, nullable=True, default=None)
    age_group = Column(Choice(c.AGE_GROUPS), default=c.AGE_UNKNOWN, nullable=True)

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
    requested_accessibility_services = Column(Boolean, default=False)

    interests = Column(MultiChoice(c.INTEREST_OPTS))
    found_how = Column(UnicodeText)
    comments = Column(UnicodeText)
    for_review = Column(UnicodeText, admin_only=True)
    admin_notes = Column(UnicodeText, admin_only=True)

    public_id = Column(UUID, default=lambda: str(uuid4()))
    badge_num = Column(Integer, default=None, nullable=True, admin_only=True)
    badge_type = Column(Choice(c.BADGE_OPTS), default=c.ATTENDEE_BADGE)
    badge_status = Column(Choice(c.BADGE_STATUS_OPTS), default=c.NEW_STATUS, index=True, admin_only=True)
    ribbon = Column(MultiChoice(c.RIBBON_OPTS), admin_only=True)

    affiliate = Column(UnicodeText)

    # attendee shirt size for both swag and staff shirts
    shirt = Column(Choice(c.SHIRT_OPTS), default=c.NO_SHIRT)
    num_event_shirts = Column(Choice(c.STAFF_EVENT_SHIRT_OPTS), default=0)
    can_spam = Column(Boolean, default=False)
    regdesk_info = Column(UnicodeText, admin_only=True)
    extra_merch = Column(UnicodeText, admin_only=True)
    got_merch = Column(Boolean, default=False, admin_only=True)
    got_staff_merch = Column(Boolean, default=False, admin_only=True)
    got_swadge = Column(Boolean, default=False, admin_only=True)

    reg_station = Column(Integer, nullable=True, admin_only=True)
    registered = Column(UTCDateTime, server_default=utcnow())
    confirmed = Column(UTCDateTime, nullable=True, default=None)
    checked_in = Column(UTCDateTime, nullable=True)

    paid = Column(Choice(c.PAYMENT_OPTS), default=c.NOT_PAID, index=True, admin_only=True)
    overridden_price = Column(Integer, nullable=True, admin_only=True)
    base_badge_price = Column(Integer, default=0, admin_only=True)
    amount_paid_override = Column(Integer, default=0, admin_only=True)
    amount_extra = Column(Choice(c.DONATION_TIER_OPTS, allow_unspecified=True), default=0)
    extra_donation = Column(Integer, default=0)
    payment_method = Column(Choice(c.PAYMENT_METHOD_OPTS), nullable=True)
    amount_refunded_override = Column(Integer, default=0, admin_only=True)
    stripe_txn_share_logs = relationship('StripeTransactionAttendee', backref='attendee')
    purchased_items = Column(MutableDict.as_mutable(JSONB), default={}, server_default='{}')
    refunded_items = Column(MutableDict.as_mutable(JSONB), default={}, server_default='{}')

    badge_printed_name = Column(UnicodeText)

    dept_memberships = relationship('DeptMembership', backref='attendee')
    dept_membership_requests = relationship('DeptMembershipRequest', backref='attendee')
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
                      'dept_membership_dept_role.c.dept_role_id == DeptRole.id, '
                      'dept_membership_dept_role.c.dept_membership_id == DeptMembership.id)',
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
                    'DeptMembership.has_inherent_role)',
        viewonly=True)
    dept_memberships_with_role = relationship(
        'DeptMembership',
        primaryjoin='and_('
                    'Attendee.id == DeptMembership.attendee_id, '
                    'DeptMembership.has_role)',
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
    agreed_to_volunteer_agreement = Column(Boolean, default=False)
    name_in_credits = Column(UnicodeText, nullable=True)
    nonshift_hours = Column(Integer, default=0, admin_only=True)
    past_years = Column(UnicodeText, admin_only=True)
    can_work_setup = Column(Boolean, default=False, admin_only=True)
    can_work_teardown = Column(Boolean, default=False, admin_only=True)

    # TODO: a record of when an attendee is unable to pickup a shirt
    # (which type? swag or staff? prob swag)
    no_shirt = relationship('NoShirt', backref=backref('attendee', load_on_pending=True), uselist=False)

    admin_account = relationship('AdminAccount', backref=backref('attendee', load_on_pending=True), uselist=False)
    food_restrictions = relationship(
        'FoodRestrictions', backref=backref('attendee', load_on_pending=True), uselist=False)

    sales = relationship('Sale', backref='attendee', cascade='save-update,merge,refresh-expire,expunge')
    mpoints_for_cash = relationship('MPointsForCash', backref='attendee')
    old_mpoint_exchanges = relationship('OldMPointExchange', backref='attendee')
    dept_checklist_items = relationship('DeptChecklistItem', backref=backref('attendee', lazy='subquery'))

    hotel_eligible = Column(Boolean, default=False, admin_only=True)
    hotel_requests = relationship('HotelRequests', backref=backref('attendee', load_on_pending=True), uselist=False)
    room_assignments = relationship('RoomAssignment', backref=backref('attendee', load_on_pending=True))

    # The PIN/password used by third party hotel reservation systems
    hotel_pin = SQLAlchemyColumn(UnicodeText, nullable=True, unique=True)

    # =========================
    # mits
    # =========================
    mits_applicants = relationship('MITSApplicant', backref='attendee')

    # =========================
    # panels
    # =========================
    assigned_panelists = relationship('AssignedPanelist', backref='attendee')
    panel_applicants = relationship('PanelApplicant', backref='attendee')
    panel_applications = relationship('PanelApplication', backref='poc')
    panel_feedback = relationship('EventFeedback', backref='attendee')

    # =========================
    # attractions
    # =========================
    _NOTIFICATION_EMAIL = 0
    _NOTIFICATION_TEXT = 1
    _NOTIFICATION_NONE = 2
    _NOTIFICATION_PREF_OPTS = [
        (_NOTIFICATION_EMAIL, 'Email'),
        (_NOTIFICATION_TEXT, 'Text'),
        (_NOTIFICATION_NONE, 'None')]

    notification_pref = Column(Choice(_NOTIFICATION_PREF_OPTS), default=_NOTIFICATION_EMAIL)
    attractions_opt_out = Column(Boolean, default=False)

    attraction_signups = relationship('AttractionSignup', backref='attendee', order_by='AttractionSignup.signup_time')
    attraction_event_signups = association_proxy('attraction_signups', 'event')
    attraction_notifications = relationship(
        'AttractionNotification', backref='attendee', order_by='AttractionNotification.sent_time')

    # =========================
    # tabletop
    # =========================
    games = relationship('TabletopGame', backref='attendee')
    checkouts = relationship('TabletopCheckout', backref='attendee')
    entrants = relationship('TabletopEntrant', backref='attendee')
    
    # =========================
    # badge printing
    # =========================
    times_printed = Column(Integer, default=0)
    print_pending = Column(Boolean, default=False)
    
    # =========================
    # art show
    # =========================
    art_show_bidder = relationship('ArtShowBidder', backref=backref('attendee', load_on_pending=True), uselist=False)
    art_show_purchases = relationship(
        'ArtShowPiece',
        backref='buyer',
        cascade='save-update,merge,refresh-expire,expunge',
        secondary='art_show_receipt')

    _attendee_table_args = [
        Index('ix_attendee_paid_group_id', paid, group_id),
        Index('ix_attendee_badge_status_badge_type', badge_status, badge_type),
    ]
    if not c.SQLALCHEMY_URL.startswith('sqlite'):
        _attendee_table_args.append(UniqueConstraint('badge_num', deferrable=True, initially='DEFERRED'))

    __table_args__ = tuple(_attendee_table_args)
    _repr_attr_names = ['full_name']

    def to_dict(self, *args, **kwargs):
        # Kludgey fix for SQLAlchemy breaking our stuff
        d = super().to_dict(*args, **kwargs)
        d.pop('attraction_event_signups', None)
        return d

    @predelete_adjustment
    def _shift_badges(self):
        is_skipped = getattr(self, '_skip_badge_shift_on_delete', False)
        if self.badge_num and not is_skipped:
            self.session.shift_badges(self.badge_type, self.badge_num + 1, down=True)

    @presave_adjustment
    def _misc_adjustments(self):
        if not self.hotel_pin or not self.hotel_pin.strip():
            self.hotel_pin = None

        if not self.amount_extra:
            self.affiliate = ''

        if self.birthdate == '':
            self.birthdate = None

        if not self.extra_donation:
            self.extra_donation = 0

        if not self.gets_any_kind_of_shirt:
            self.shirt = c.NO_SHIRT

        if self.badge_cost == 0 and self.paid in [c.NOT_PAID, c.PAID_BY_GROUP]:
            self.paid = c.NEED_NOT_PAY

        if not self.base_badge_price:
            self.base_badge_price = self.new_badge_cost

        if c.AT_THE_CON and self.badge_num and not self.checked_in and self.is_new \
                and self.badge_type not in c.PREASSIGNED_BADGE_TYPES:
            self.checked_in = datetime.now(UTC)

        if self.birthdate:
            self.age_group = self.age_group_conf['val']

        for attr in ['first_name', 'last_name']:
            value = getattr(self, attr)
            if value.isupper() or value.islower():
                setattr(self, attr, value.title())

        if self.legal_name and self.full_name == self.legal_name:
            self.legal_name = ''

        if self.promo_code and self.promo_code_groups:
            self.promo_code = None

    @presave_adjustment
    def _status_adjustments(self):
        if self.badge_status == c.WATCHED_STATUS and not self.banned:
            self.badge_status = c.NEW_STATUS
        
        if self.badge_status == c.NEW_STATUS and self.banned:
            self.badge_status = c.WATCHED_STATUS
            try:
                uber.tasks.email.send_email.delay(
                    c.SECURITY_EMAIL,
                    [c.REGDESK_EMAIL, c.SECURITY_EMAIL],
                    c.EVENT_NAME + ' WatchList Notification',
                    render('emails/reg_workflow/attendee_watchlist.txt', {'attendee': self}, encoding=None),
                    model='n/a')
            except Exception:
                log.error('unable to send banned email about {}', self, exc_info=True)

        elif self.badge_status == c.NEW_STATUS and not self.placeholder and self.first_name and (
                    self.paid in [c.HAS_PAID, c.NEED_NOT_PAY]
                    or self.paid == c.PAID_BY_GROUP
                    and self.group_id
                    and not self.group.is_unpaid):
            self.badge_status = c.COMPLETED_STATUS

    @presave_adjustment
    def _staffing_adjustments(self):
        if self.is_dept_head:
            self.staffing = True
            if self.paid == c.NOT_PAID:
                self.paid = c.NEED_NOT_PAY
        else:
            if self.volunteering_badge_or_ribbon and self.is_new:
                self.staffing = True

        if not self.is_new:
            old_ribbon = map(int, self.orig_value_of('ribbon').split(',')) if self.orig_value_of('ribbon') else []
            old_staffing = self.orig_value_of('staffing')

            if old_staffing and not self.staffing or c.VOLUNTEER_RIBBON not in self.ribbon_ints \
                    and c.VOLUNTEER_RIBBON in old_ribbon and not self.is_dept_head:
                self.unset_volunteering()

    @presave_adjustment
    def staffing_badge_and_ribbon_adjustments(self):
        if self.badge_type in [c.STAFF_BADGE, c.CONTRACTOR_BADGE]:
            self.ribbon = remove_opt(self.ribbon_ints, c.VOLUNTEER_RIBBON)

        elif self.staffing and not self.volunteering_badge_or_ribbon:
            self.ribbon = add_opt(self.ribbon_ints, c.VOLUNTEER_RIBBON)

        if self.badge_type in [c.STAFF_BADGE, c.CONTRACTOR_BADGE]:
            self.staffing = True
            if not self.overridden_price and self.paid in [c.NOT_PAID, c.PAID_BY_GROUP]:
                self.paid = c.NEED_NOT_PAY

    @presave_adjustment
    def _badge_adjustments(self):
        from uber.badge_funcs import needs_badge_num
        if self.badge_type == c.PSEUDO_DEALER_BADGE:
            self.ribbon = add_opt(self.ribbon_ints, c.DEALER_RIBBON)

        self.badge_type = self.badge_type_real

        old_type = self.orig_value_of('badge_type')
        old_num = self.orig_value_of('badge_num')

        if not needs_badge_num(self) and not c.AT_THE_CON:
            self.badge_num = None

        if old_type != self.badge_type or old_num != self.badge_num:
            self.session.update_badge(self, old_type, old_num)
        elif needs_badge_num(self) and not self.badge_num:
            self.badge_num = self.session.get_next_badge_num(self.badge_type)

    @presave_adjustment
    def _use_promo_code(self):
        if c.BADGE_PROMO_CODES_ENABLED and self.promo_code and not self.overridden_price and self.is_unpaid:
            if self.badge_cost > 0:
                self.overridden_price = self.badge_cost
            else:
                self.paid = c.NEED_NOT_PAY
                
    @presave_adjustment
    def update_purchased_items(self):
        self.purchased_items.clear()
        for name in self.cost_property_names:
            value = getattr(self, name, 0)
            if value:
                self.purchased_items[name] = value
        if self.amount_extra:
            self.purchased_items['kick_in_cost'] = self.amount_extra
        if self.paid == c.PAID_BY_GROUP and self.purchased_items['badge_cost']:
            del self.purchased_items['badge_cost']
    
    @presave_adjustment
    def set_payment_method(self):
        if not self.payment_method and self.stripe_txn_share_logs:
            self.payment_method = c.STRIPE

    @presave_adjustment
    def assign_creator(self):
        if self.is_new and not self.creator_id:
            self.creator_id = self.session.admin_attendee().id if self.session.admin_attendee() else None
    
    @presave_adjustment
    def assign_number_after_payment(self):
        if c.AT_THE_CON:
            if self.has_personalized_badge and not self.badge_num:
                if not self.amount_unpaid:
                    self.badge_num = self.session.next_badge_num(self.badge_type, old_badge_num=0)

    @presave_adjustment
    def print_ready_before_event(self):
        if c.PRE_CON:
            if self.badge_status == c.COMPLETED_STATUS\
                    and not self.is_not_ready_to_checkin\
                    and self.times_printed < 1:
                self.print_pending = True

    @presave_adjustment
    def print_ready_at_event(self):
        if c.AT_THE_CON:
            if self.checked_in and self.times_printed < 1:
                self.print_pending = True
                
    @cost_property
    def reprint_cost(self):
        return c.BADGE_REPRINT_FEE or 0

    @property
    def age_now_or_at_con(self):
        if not self.birthdate:
            return None
        day = c.EPOCH.date() if date.today() <= c.EPOCH.date()\
            else uber.utils.localized_now().date()
        return day.year - self.birthdate.year - (
            (day.month, day.day) < (self.birthdate.month, self.birthdate.day))
        
    @presave_adjustment
    def not_attending_need_not_pay(self):
        if self.badge_status == c.NOT_ATTENDING:
            self.paid = c.NEED_NOT_PAY

    @presave_adjustment
    def add_as_agent(self):
        if self.promo_code:
            art_apps = self.session.lookup_agent_code(self.promo_code.code)
            for app in art_apps:
                app.agent_id = self.id

    @cost_property
    def art_show_app_cost(self):
        cost = 0
        if self.art_show_applications:
            for app in self.art_show_applications:
                cost += app.total_cost
        return cost

    @property
    def art_show_receipt(self):
        open_receipts = [receipt for receipt in self.art_show_receipts if not receipt.closed]
        if open_receipts:
            return open_receipts[0]

    @property
    def full_address(self):
        if self.country and self.city and (
                    self.region or self.country not in ['United States', 'Canada']) and self.address1:
            return True

    @property
    def payment_page(self):
        if self.art_show_applications:
            for app in self.art_show_applications:
                if app.total_cost and app.status != c.PAID:
                    return '../art_show_applications/edit?id={}'.format(app.id)
        return 'attendee_donation_form?id={}'.format(self.id)

    def unset_volunteering(self):
        self.staffing = False
        self.dept_membership_requests = []
        self.requested_depts = []
        self.dept_memberships = []
        self.ribbon = remove_opt(self.ribbon_ints, c.VOLUNTEER_RIBBON)
        if self.badge_type in [c.STAFF_BADGE, c.CONTRACTOR_BADGE]:
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
        return uber.badge_funcs.get_real_badge_type(self.badge_type)

    @cost_property
    def badge_cost(self):
        return self.calculate_badge_cost()

    @property
    def badge_cost_without_promo_code(self):
        return self.calculate_badge_cost(use_promo_code=False)

    def calculate_badge_cost(self, use_promo_code=True):
        registered = self.registered_local if self.registered else None
        base_badge_price = self.base_badge_price or c.get_attendee_price(registered)

        if self.paid == c.NEED_NOT_PAY:
            return 0
        elif self.overridden_price is not None:
            return self.overridden_price
        elif self.is_dealer:
            return c.DEALER_BADGE_PRICE
        elif self.badge_type in c.DISCOUNTABLE_BADGE_TYPES and self.age_discount != 0:
            return max(0, base_badge_price + self.age_discount)
        elif self.badge_type in c.DISCOUNTABLE_BADGE_TYPES and (
                self.promo_code_groups or self.group and self.paid == c.PAID_BY_GROUP):
            return base_badge_price - c.GROUP_DISCOUNT
        elif self.base_badge_price:
            cost = base_badge_price
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
        registered = self.registered_local if self.registered else uber.utils.localized_now()
        if self.badge_type == c.ONE_DAY_BADGE:
            return c.get_oneday_price(registered)
        elif self.is_presold_oneday:
            return c.get_presold_oneday_price(self.badge_type)
        elif self.badge_type in c.BADGE_TYPE_PRICES:
            return int(c.BADGE_TYPE_PRICES[self.badge_type])
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
        # We dynamically calculate the age discount to be half the
        # current badge price. If for some reason the default discount
        # (if it exists) is greater than half off, we use that instead.
        if self.age_group_conf.get('val') == c.UNDER_13:
            half_off = math.ceil(c.BADGE_PRICE / 2)
            if not self.age_group_conf['discount'] or self.age_group_conf['discount'] < half_off:
                return -half_off
        return -self.age_group_conf['discount']

    @property
    def age_group_conf(self):
        if self.birthdate:
            day = c.EPOCH.date() if date.today() <= c.EPOCH.date() else localized_now().date()

            attendee_age = get_age_from_birthday(self.birthdate, day)
            for val, age_group in c.AGE_GROUP_CONFIGS.items():
                if val != c.AGE_UNKNOWN and age_group['min_age'] <= attendee_age \
                        and attendee_age <= age_group['max_age']:
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

    @cost_property
    def promo_code_group_cost(self):
        return sum(group.total_cost for group in self.promo_code_groups)

    @cost_property
    def marketplace_cost(self):
        return sum(app.total_cost - app.amount_paid for app in self.marketplace_applications)

    @property
    def amount_extra_unpaid(self):
        return self.total_cost - self.badge_cost

    @hybrid_property
    def amount_paid(self):
        return sum([item.amount for item in self.receipt_items if item.txn_type == c.PAYMENT])

    @amount_paid.expression
    def amount_paid(cls):
        from uber.models import ReceiptItem

        return select([func.sum(ReceiptItem.amount)]
                      ).where(and_(ReceiptItem.attendee_id == cls.id,
                                   ReceiptItem.txn_type == c.PAYMENT)).label('amount_paid')

    @hybrid_property
    def amount_refunded(self):
        return sum([item.amount for item in self.receipt_items if item.txn_type == c.REFUND])

    @amount_refunded.expression
    def amount_refunded(cls):
        from uber.models import ReceiptItem

        return select([func.sum(ReceiptItem.amount)]
                      ).where(and_(ReceiptItem.attendee_id == cls.id,
                                   ReceiptItem.txn_type == c.REFUND)).label('amount_refunded')

    @property
    def amount_unpaid(self):
        if self.paid == c.PAID_BY_GROUP:
            personal_cost = max(0, self.total_cost - self.badge_cost)
        else:
            personal_cost = self.total_cost
        return max(0, ((personal_cost * 100) - self.amount_paid) / 100)

    @property
    def paid_for_badge(self):
        return self.paid == c.HAS_PAID or \
                self.paid == c.PAID_BY_GROUP and self.group and self.group.amount_paid or \
                self.in_promo_code_group and self.promo_code.cost
                
    @property
    def has_been_refunded(self):
        return self.paid == c.REFUNDED or \
                self.group and self.group.amount_refunded or \
                self.in_promo_code_group and self.promo_code.group.buyer.paid == c.REFUNDED

    @hybrid_property
    def is_unpaid(self):
        return self.paid == c.NOT_PAID

    @is_unpaid.expression
    def is_unpaid(cls):
        return cls.paid == c.NOT_PAID

    def balance_by_item_type(self, item_type):
        """
        Return a sum of all the receipt item payments, minus the refunds, for this model by item type
        """
        return sum([amt for type, amt in self.itemized_payments if type == item_type]) \
                        - sum([amt for type, amt in self.itemized_refunds if type == item_type])

    @property
    def itemized_payments(self):
        return [(item.item_type, item.amount) for item in self.receipt_items if item.txn_type == c.PAYMENT]

    @property
    def itemized_refunds(self):
        return [(item.item_type, item.amount) for item in self.receipt_items if item.txn_type == c.REFUND]

    @hybrid_property
    def is_unassigned(self):
        return not self.first_name

    @is_unassigned.expression
    def is_unassigned(cls):
        return cls.first_name == ''

    @property
    def volunteering_badge_or_ribbon(self):
        return self.badge_type in [c.STAFF_BADGE, c.CONTRACTOR_BADGE] or c.VOLUNTEER_RIBBON in self.ribbon_ints

    @property
    def staffing_or_will_be(self):
        # This is for use in our model checks -- it includes attendees who are going to be marked staffing
        return self.staffing or self.volunteering_badge_or_ribbon

    @hybrid_property
    def is_dealer(self):
        return c.DEALER_RIBBON in self.ribbon_ints or self.badge_type == c.PSEUDO_DEALER_BADGE or (
            self.group and self.group.is_dealer and self.paid == c.PAID_BY_GROUP)

    @is_dealer.expression
    def is_dealer(cls):
        return or_(
            cls.ribbon.like('%{}%'.format(c.DEALER_RIBBON)),
            and_(
                cls.paid == c.PAID_BY_GROUP,
                Group.id == cls.group_id,
                Group.is_dealer == True))  # noqa: E712

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
        
        if self.badge_status == c.WATCHED_STATUS:
            if self.banned or not self.regdesk_info:
                regdesk_info_append = " [{}]".format(self.regdesk_info) if self.regdesk_info else ""
                return "MUST TALK TO SECURITY before picking up badge{}".format(regdesk_info_append)
            return self.regdesk_info or "Badge status is {}".format(self.badge_status_label)

        if self.badge_status not in [c.COMPLETED_STATUS, c.NEW_STATUS]:
            return "Badge status is {}".format(self.badge_status_label)
        
        if self.placeholder:
            return "Placeholder badge"

        if self.is_unassigned:
            return "Badge not assigned"

        if self.is_presold_oneday:
            if self.badge_type_label != localized_now().strftime('%A'):
                return "Wrong day"

        message = uber.utils.check(self)
        return message

    @property
    def can_abandon_badge(self):
        return not self.amount_paid and (
            (not self.paid == c.NEED_NOT_PAY or self.in_promo_code_group) or self.badge_type == c.STAFF_BADGE
        ) and not self.is_group_leader and not self.checked_in

    @property
    def can_self_service_refund_badge(self):
        return self.amount_paid \
               and self.amount_paid > 0 \
               and self.paid not in [c.NEED_NOT_PAY, c.REFUNDED] \
               and not self.is_group_leader \
               and self.stripe_txn_share_logs \
               and not self.checked_in \
               and c.SELF_SERVICE_REFUNDS_OPEN

    @property
    def needs_pii_consent(self):
        return self.is_new or self.placeholder or not self.first_name

    @property
    def shirt_size_marked(self):
        return self.shirt not in [c.NO_SHIRT, c.SIZE_UNKNOWN]

    @property
    def shirt_info_marked(self):
        return self.shirt_size_marked if c.HOURS_FOR_SHIRT else True

    @property
    def is_group_leader(self):
        return self.group and self.id == self.group.leader_id or self.promo_code_groups

    @property
    def in_promo_code_group(self):
        return self.promo_code and self.promo_code.group

    @property
    def unassigned_name(self):
        if self.group_id and self.is_unassigned:
            return '[Unassigned {self.badge}]'.format(self=self)

    @hybrid_property
    def full_name(self):
        return self.unassigned_name or '{self.first_name} {self.last_name}'.format(self=self)

    @full_name.expression
    def full_name(cls):
        return case(
            [(or_(cls.first_name == None, cls.first_name == ''), 'zzz')],  # noqa: E711
            else_=func.lower(cls.first_name + ' ' + cls.last_name))
        
    @hybrid_property
    def group_name(self):
        if self.group:
            return self.group.name
        return ''

    @group_name.expression
    def group_name(cls):
        return select([Group.name]).where(Group.id == cls.group_id).label('group_name')

    @hybrid_property
    def promo_code_group_name(self):
        if self.promo_code and self.promo_code.group:
            return self.promo_code.group.name
        elif self.promo_code_groups:
            return self.promo_code_groups[0].name
        return ''

    @promo_code_group_name.expression
    def promo_code_group_name(cls):
        from uber.models.promo_code import PromoCode, PromoCodeGroup
        return case([
            (cls.promo_code != None,
             select([PromoCodeGroup.name]).where(PromoCodeGroup.id==PromoCode.group_id)
             .where(PromoCode.id==cls.promo_code_id).label('promo_code_group_name')),
            (cls.promo_code_groups != None,
             select([PromoCodeGroup.name]).where(PromoCodeGroup.buyer_id == cls.id)
             .label('promo_code_group_name'))
        ])

    @hybrid_property
    def last_first(self):
        return self.unassigned_name or '{self.last_name}, {self.first_name}'.format(self=self)

    @last_first.expression
    def last_first(cls):
        return case(
            [(or_(cls.first_name == None, cls.first_name == ''), 'zzz')],  # noqa: E711
            else_=func.lower(cls.last_name + ', ' + cls.first_name))

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
    def gets_emails(self):
        return self.badge_status in [c.NEW_STATUS, c.COMPLETED_STATUS]

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
        return not self.is_new \
            and not self.checked_in \
            and (self.paid in [c.HAS_PAID, c.PAID_BY_GROUP] or self.in_promo_code_group) \
            and self.badge_type in c.TRANSFERABLE_BADGE_TYPES \
            and not self.admin_account \
            and not self.has_role_somewhere

    # TODO: delete this after Super MAGFest 2018
    @property
    def gets_swadge(self):
        return self.amount_extra >= c.SUPPORTER_LEVEL

    @property
    def paid_for_a_shirt(self):
        return self.amount_extra >= c.SHIRT_LEVEL

    @property
    def num_free_event_shirts(self):
        """
        If someone is staff-shirt-eligible, we use the number of event shirts they have selected (if any)
        Volunteers also get a free event shirt.
        Returns: Integer representing the number of free event shirts this attendee should get.

        """
        return self.num_event_shirts if self.gets_staff_shirt else self.volunteer_event_shirt_eligible

    @property
    def volunteer_event_shirt_eligible(self):
        return bool(c.VOLUNTEER_RIBBON in self.ribbon_ints and c.HOURS_FOR_SHIRT)

    @property
    def volunteer_event_shirt_earned(self):
        return self.volunteer_event_shirt_eligible and (not self.takes_shifts or self.worked_hours >= c.HOURS_FOR_SHIRT)

    @property
    def num_event_shirts_owed(self):
        return sum([
            int(self.paid_for_a_shirt),
            self.num_free_event_shirts
        ])

    @property
    def gets_staff_shirt(self):
        return bool(self.badge_type == c.STAFF_BADGE and c.HOURS_FOR_SHIRT)

    @property
    def num_staff_shirts_owed(self):
        return 0 if not self.gets_staff_shirt else (c.SHIRTS_PER_STAFFER - self.num_free_event_shirts)

    @property
    def gets_any_kind_of_shirt(self):
        return self.gets_staff_shirt or self.num_event_shirts_owed > 0

    @property
    def has_personalized_badge(self):
        return self.badge_type in c.PREASSIGNED_BADGE_TYPES

    @property
    def donation_swag(self):
        donation_items = [
            desc for amount, desc in sorted(c.DONATION_TIERS.items()) if amount and self.amount_extra >= amount]
        extra_donations = ['Extra donation of ${}'.format(self.extra_donation)] if self.extra_donation else []
        return donation_items + extra_donations

    @property
    def donation_tier(self):
        for amount, desc in sorted(c.DONATION_TIERS.items()):
            if self.amount_extra <= amount:
                return amount
        return 0

    @property
    def donation_tier_label(self):
        return c.DONATION_TIERS[self.donation_tier]

    @property
    def donation_tier_paid(self):
        return self.amount_unpaid <= 0

    @property
    def merch_items(self):
        """
        Here is the business logic surrounding shirts:
        - People who kick in enough to get a shirt get an event shirt.
        - People with staff badges get a configurable number of staff shirts.
        - Volunteers who meet the requirements get a complementary event shirt
            (NOT a staff shirt).

        If the c.SEPARATE_STAFF_SWAG setting is true, then this excludes staff
        merch; see the staff_merch property.

        This property returns a list containing strings and sub-lists of each
        donation tier with multiple sub-items, e.g.
            [
                'tshirt',
                'Supporter Pack',
                [
                    'Swag Bag',
                    'Badge Holder'
                ],
                'Season Pass Certificate'
            ]
        """
        merch = []
        for amount, desc in sorted(c.DONATION_TIERS.items()):
            if amount and self.amount_extra >= amount:
                merch.append(desc)
                items = c.DONATION_TIER_ITEMS.get(amount, [])
                if len(items) == 1:
                    merch[-1] = items[0]
                elif len(items) > 1:
                    merch.append(items)

        if self.num_event_shirts_owed == 1 and not self.paid_for_a_shirt:
            merch.append('A T-shirt')
        elif self.num_event_shirts_owed > 1:
            merch.append('A 2nd T-Shirt')

        if self.volunteer_event_shirt_eligible and not self.volunteer_event_shirt_earned:
            merch[-1] += (
                ' (this volunteer must work at least {} hours or they will be reported for picking up their shirt)'
                    .format(c.HOURS_FOR_SHIRT))

        if not c.SEPARATE_STAFF_MERCH:
            merch.extend(self.staff_merch_items)

        if self.extra_merch:
            merch.append(self.extra_merch)

        return merch

    @property
    def merch(self):
        """
        Textual version of merch_items, excluding the expanded donation tier
        item lists.  This is useful for displaying a high-level description,
        e.g. saying that someone gets a 'Supporter Pack' without listing each
        individual item in the pack.
        """
        return readable_join([item for item in self.merch_items if not is_listy(item)])

    @property
    def staff_merch_items(self):
        """Used by the merch and staff_merch properties for staff swag."""
        merch = []
        num_staff_shirts_owed = self.num_staff_shirts_owed
        if num_staff_shirts_owed > 0:
            staff_shirts = '{} Staff Shirt{}'.format(num_staff_shirts_owed, 's' if num_staff_shirts_owed > 1 else '')
            if self.shirt_size_marked:
                staff_shirts += ' [{}]'.format(c.SHIRTS[self.shirt])
            merch.append(staff_shirts)

        if self.staffing:
            merch.append('Staffer Info Packet')

        return merch

    @property
    def staff_merch(self):
        """Used if c.SEPARATE_STAFF_MERCH is true to return the staff swag."""
        return readable_join(self.staff_merch_items)

    @property
    def accoutrements(self):
        stuff = [] if not self.ribbon else ['a ' + s + ' ribbon' for s in self.ribbon_labels]

        if c.WRISTBANDS_ENABLED:
            stuff.append('a {} wristband'.format(c.WRISTBAND_COLORS[self.age_group]))
        if self.regdesk_info:
            stuff.append(self.regdesk_info)
        return (' with ' if stuff else '') + readable_join(stuff)

    @property
    def payment_page(self):
        # Some plugins need to redirect attendees to custom payment pages under certain circumstances
        return 'attendee_donation_form?id={}'.format(self.id)

    @property
    def multiply_assigned(self):
        return len(self.dept_memberships) > 1

    @property
    def takes_shifts(self):
        return bool(self.staffing and self.badge_type != c.CONTRACTOR_BADGE and any(
            not d.is_shiftless for d in self.assigned_depts))

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

        member_dept_ids = set(d.department_id for d in self.dept_memberships)
        member_filter = Job.department_id.in_(member_dept_ids) if member_dept_ids else None

        max_depts = c.MAX_DEPTS_WHERE_WORKING
        no_max = max_depts < 1

        requested_filter = Job.visibility > Job._ONLY_MEMBERS

        if member_filter is not None:
            job_filters += [or_(member_filter, requested_filter)]
        else:
            job_filters += [requested_filter]
        return job_filters

    @cached_property
    def available_jobs(self):
        assert self.session, (
            '{}.available_jobs property may only be accessed for '
            'objects attached to a session'.format(self.__class__.__name__))

        if not self.staffing or (not c.AT_THE_CON and not self.dept_memberships and not self.dept_membership_requests):
            return []

        from uber.models.department import Job
        jobs = self.session.query(Job).filter(*self.available_job_filters).options(
            subqueryload(Job.shifts),
            subqueryload(Job.department),
            subqueryload(Job.required_roles)
        ).order_by(Job.start_time, Job.department_id).all()

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
            for job in self.possible if localized_now() < job.start_time]

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
    def _extra_apply_attrs(cls):
        return set(['assigned_depts_ids']).union(cls._extra_apply_attrs_restricted)

    @classproperty
    def _extra_apply_attrs_restricted(cls):
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
        return [d.department_id or 'All' for d in self.dept_membership_requests]

    @requested_depts_ids.setter
    def requested_depts_ids(self, value):
        from uber.models.department import DeptMembershipRequest
        values = set(
            None if s in ('None', 'All') else s
            for s in listify(value) if s != '')

        for membership in list(self.dept_membership_requests):
            if membership.department_id not in values:
                self.dept_membership_requests.remove(membership)
        department_ids = set(str(d.department_id) for d in self.dept_membership_requests)
        for department_id in values:
            if str(department_id) not in department_ids:
                self.dept_membership_requests.append(
                    DeptMembershipRequest(department_id=department_id, attendee_id=self.id))

    @property
    def worked_shifts(self):
        return [s for s in self.shifts if s.worked == c.SHIFT_WORKED]

    @property
    def weighted_hours(self):
        weighted_hours = sum(s.job.weighted_hours for s in self.shifts)
        return weighted_hours + self.nonshift_hours

    @property
    def unweighted_hours(self):
        unweighted_hours = sum(s.job.real_duration for s in self.shifts)
        return unweighted_hours + self.nonshift_hours

    @department_id_adapter
    def weighted_hours_in(self, department_id):
        if not department_id:
            return self.weighted_hours
        return sum(s.job.weighted_hours for s in self.shifts if s.job.department_id == department_id)

    @department_id_adapter
    def unweighted_hours_in(self, department_id):
        if not department_id:
            return self.unweighted_hours
        return sum(s.job.real_duration for s in self.shifts if s.job.department_id == department_id)

    @property
    def worked_hours(self):
        weighted_hours = sum(s.job.weighted_hours for s in self.worked_shifts)
        return weighted_hours + self.nonshift_hours

    @property
    def unweighted_worked_hours(self):
        unweighted_hours = sum(s.job.real_duration for s in self.worked_shifts)
        return unweighted_hours + self.nonshift_hours

    @department_id_adapter
    def worked_hours_in(self, department_id):
        if not department_id:
            return self.worked_hours
        return sum(s.job.weighted_hours for s in self.worked_shifts if s.job.department_id == department_id)

    @department_id_adapter
    def unweighted_worked_hours_in(self, department_id):
        if not department_id:
            return self.unweighted_worked_hours
        return sum(s.job.real_duration for s in self.worked_shifts if s.job.department_id == department_id)

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
        return any(m.department_id == department_id for m in self.dept_membership_requests)

    @department_id_adapter
    def assigned_to(self, department_id):
        if not department_id:
            return False
        return any(m.department_id == department_id for m in self.dept_memberships)

    def trusted_in(self, department):
        return self.has_role_in(department)

    def can_admin_dept_for(self, department):
        return (self.admin_account and self.admin_account.full_dept_admin) \
            or self.has_inherent_role_in(department)

    def can_dept_head_for(self, department):
        return (self.admin_account and self.admin_account.full_dept_admin) \
            or self.is_dept_head_of(department)

    @department_id_adapter
    def can_admin_shifts_for(self, department_id):
        if not department_id:
            return False
        return self.admin_account and self.admin_account.full_shifts_admin \
               or any(m.department_id == department_id for m in self.dept_memberships_with_inherent_role)

    @property
    def can_admin_checklist(self):
        return (self.admin_account and self.admin_account.full_dept_checklist_admin) \
            or bool(self.dept_memberships_where_can_admin_checklist)

    @department_id_adapter
    def can_admin_checklist_for(self, department_id):
        if not department_id:
            return False
        return (self.admin_account and self.admin_account.full_dept_checklist_admin) \
            or any(m.department_id == department_id for m in self.dept_memberships_where_can_admin_checklist)

    @department_id_adapter
    def is_checklist_admin_of(self, department_id):
        if not department_id:
            return False
        return any(m.department_id == department_id and m.is_checklist_admin for m in self.dept_memberships)

    @department_id_adapter
    def is_dept_head_of(self, department_id):
        if not department_id:
            return False
        return any(m.department_id == department_id and m.is_dept_head for m in self.dept_memberships)

    @department_id_adapter
    def is_poc_of(self, department_id):
        if not department_id:
            return False
        return any(m.department_id == department_id and m.is_poc for m in self.dept_memberships)

    def checklist_item_for_slug(self, slug):
        for item in self.dept_checklist_items:
            if item.slug == slug:
                return item
        return None

    def completed_every_checklist_for(self, slug):
        return all(d.checklist_item_for_slug(slug) for d in self.checklist_depts)

    @property
    def gets_any_checklist(self):
        return bool(self.dept_memberships_as_checklist_admin)

    def has_role(self, role):
        return any(r.id == role.id for r in self.dept_roles)

    @department_id_adapter
    def has_inherent_role_in(self, department_id):
        if not department_id:
            return False
        return any(m.department_id == department_id for m in self.dept_memberships_with_inherent_role)

    @department_id_adapter
    def has_role_in(self, department_id):
        if not department_id:
            return False
        return any(m.department_id == department_id for m in self.dept_memberships_with_role)

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

    @property
    def depts_where_can_admin(self):
        if self.admin_account and self.admin_account.full_dept_admin:
            from uber.models.department import Department
            return self.session.query(Department).order_by(Department.name).all()
        return self.depts_with_inherent_role

    def has_shifts_in(self, department):
        return department in self.depts_where_working

    @property
    def food_restrictions_filled_out(self):
        return self.food_restrictions if c.HOURS_FOR_FOOD else True

    @property
    def past_years_json(self):
        return json.loads(self.past_years or '[]')

    @property
    def all_years(self):
        """
        Work history for all past years, plus this year's work history,
        as a json formatted string.
        """
        return json.dumps(self.all_years_json)

    @property
    def all_years_json(self):
        """
        Work history for all past years, plus this year's work history.
        """
        return self.past_years_json + [{
            'year': '{} {}'.format(c.EVENT_NAME, c.EVENT_YEAR),
            'admin_notes': self.admin_notes,
            'worked_hours': self.worked_hours,
            'unworked_hours': self.weighted_hours - self.worked_hours,
            'nonshift_hours': self.nonshift_hours,
            'shifts': [{
                'worked': shift.worked_label,
                'rating': shift.rating_label,
                'comment': shift.comment,
                'job': {
                    'location': shift.job.location_label,
                    'name': shift.job.name,
                    'weight': shift.job.weight,
                    'when': (
                            time_day_local(shift.job.start_time) + ' - ' +
                            time_day_local(shift.job.start_time + timedelta(hours=shift.job.duration))
                        ).replace('<nobr>', '').replace('</nobr>', ''),
                    'total_hours': shift.job.duration * shift.job.weight,
                }
            } for shift in self.shifts]
        }]

    @property
    def must_contact(self):
        dept_chairs = []
        for dept in self.depts_where_working:
            poc_names = ' / '.join(sorted(poc.full_name for poc in dept.pocs))
            dept_chairs.append('({}) {}'.format(dept.name, poc_names))
        return safe_string('<br/>'.join(sorted(dept_chairs)))

    def append_admin_note(self, note):
        if self.admin_notes:
            self.admin_notes = '{}\n\n{}'.format(self.admin_notes, note)
        else:
            self.admin_notes = note

    @presave_adjustment
    def staffer_hotel_eligibility(self):
        if self.badge_type == c.STAFF_BADGE:
            self.hotel_eligible = True

    @presave_adjustment
    def staffer_setup_teardown(self):
        if self.setup_hotel_approved:
            self.can_work_setup = True
        if self.teardown_hotel_approved:
            self.can_work_teardown = True

    @property
    def hotel_shifts_required(self):
        return bool(c.SHIFTS_CREATED and self.hotel_nights and not self.is_dept_head and self.takes_shifts)

    @property
    def setup_hotel_approved(self):
        requests = self.hotel_requests
        return bool(requests and requests.approved and set(requests.nights_ints).intersection(c.SETUP_NIGHTS))

    @property
    def teardown_hotel_approved(self):
        requests = self.hotel_requests
        return bool(
            requests
            and requests.approved
            and set(requests.nights_ints).intersection(c.TEARDOWN_NIGHTS))

    @property
    def shift_prereqs_complete(self):
        return not self.placeholder and self.food_restrictions_filled_out and self.shirt_info_marked and (
            not self.hotel_eligible
            or self.hotel_requests
            or not c.BEFORE_ROOM_DEADLINE)

    @property
    def hotel_nights(self):
        try:
            return self.hotel_requests.nights
        except Exception:
            return []

    @property
    def hotel_nights_without_shifts_that_day(self):
        if not self.hotel_requests:
            return []

        hotel_nights = set(self.hotel_requests.nights_ints)
        shift_nights = set()
        for shift in self.shifts:
            start_time = shift.job.start_time.astimezone(c.EVENT_TIMEZONE)
            shift_night = getattr(c, start_time.strftime('%A').upper())
            shift_nights.add(shift_night)
        discrepancies = hotel_nights.difference(shift_nights)
        return list(sorted(discrepancies, key=c.NIGHT_DISPLAY_ORDER.index))

    @cached_property
    def hotel_status(self):
        hr = self.hotel_requests
        if not hr:
            return 'Has not filled out volunteer checklist'
        elif not hr.nights:
            return 'Declined hotel space'
        elif hr.setup_teardown:
            return 'Hotel nights: {} ({})'.format(hr.nights_display, 'approved' if hr.approved else 'not yet approved')
        else:
            return 'Hotel nights: ' + hr.nights_display

    @property
    def legal_first_name(self):
        """
        Hotel exports need split legal names, but we don't collect split
        legal names, so we're going to have to guess.

        Returns one of the following:
            The first part of the legal name, if the legal name ends with
                the last name
            The first part of the legal name before a space, if the legal
                name has multiple parts
            The legal name itself, if the legal name is one word -- this is
                because attendees are more likely to use a different first
                name than their legal name, so might just enter,
                e.g. "Victoria" for their legal name
            The first name, if there is no legal name
        """
        if self.legal_name:
            legal_name = re.sub(r'\s+', ' ', self.legal_name.strip())
            last_name = re.sub(r'\s+', ' ', self.last_name.strip())
            low_legal_name = legal_name.lower()
            low_last_name = last_name.lower()
            if low_legal_name.endswith(low_last_name):
                # Catches 95% of the cases.
                return legal_name[:-len(last_name)].strip()
            else:
                norm_legal_name = re.sub(r'[,\.]', '', low_legal_name)
                norm_last_name = re.sub(r'[,\.]', '', low_last_name)
                # Before iterating through all the suffixes, check to make
                # sure the last name is even part of the legal name.
                start_index = norm_legal_name.rfind(norm_last_name)
                if start_index >= 0:
                    actual_suffix_index = start_index + len(norm_last_name)
                    actual_suffix = norm_legal_name[actual_suffix_index:].strip()

                    for suffix in normalized_name_suffixes:
                        actual_suffix = re.sub(suffix, '', actual_suffix).strip()

                        if not actual_suffix:
                            index = low_legal_name.rfind(low_last_name)
                            if index >= 0:
                                return legal_name[:index].strip()
                            # Should never get here, but if we do, we should
                            # stop iterating because none of the remaining
                            # suffixes will match.
                            break

                if ' ' in legal_name:
                    return legal_name.split(' ', 1)[0]
                return legal_name

        return self.first_name

    @property
    def legal_last_name(self):
        """
        Hotel exports need split legal names, but we don't collect split
        legal names, so we're going to have to guess.

        Returns one of the following:
            The second part of the legal name, if the legal name starts
                with the legal first name
            The second part of the legal name after a space, if the
                legal name has multiple parts
            The last name, if there is no legal name or if the legal name
                is just one word
        """
        legal_name = re.sub(r'\s+', ' ', self.legal_name.strip())
        if legal_name and ' ' in legal_name:
            legal_first_name = re.sub(r'\s+', ' ', self.legal_first_name.strip())

            if legal_name.lower().startswith(legal_first_name.lower()):
                return legal_name[len(legal_first_name):].strip()
            elif ' ' in legal_name:
                return legal_name.split(' ', 1)[1]
        return self.last_name

    # =========================
    # attractions
    # =========================

    @property
    def attraction_features(self):
        return list({e.feature for e in self.attraction_events})

    @property
    def attractions(self):
        return list({e.feature.attraction for e in self.attraction_events})

    @property
    def masked_email(self):
        name, _, domain = self.email.partition('@')
        sub_domain, _, tld = domain.rpartition('.')
        return '{}@{}.{}'.format(mask_string(name), mask_string(sub_domain), tld)

    @property
    def masked_cellphone(self):
        cellphone = RE_NONDIGIT.sub(' ', self.cellphone).strip()
        digits = cellphone.replace(' ', '')
        return '*' * (len(cellphone) - 4) + digits[-4:]

    @property
    def masked_notification_pref(self):
        if self.notification_pref == self._NOTIFICATION_EMAIL:
            return self.masked_email
        elif self.notification_pref == self._NOTIFICATION_TEXT:
            return self.masked_cellphone or self.masked_email
        return ''

    @property
    def signups_by_attraction_by_feature(self):
        signups = sorted(self.attraction_signups, key=lambda s: (s.event.feature.attraction.name, s.event.feature.name))
        return groupify(signups, [lambda s: s.event.feature.attraction, lambda s: s.event.feature])

    def is_signed_up_for_attraction(self, attraction):
        return attraction in self.attractions

    def is_signed_up_for_attraction_feature(self, feature):
        return feature in self.attraction_features

    def can_admin_attraction(self, attraction):
        if not self.admin_account:
            return False
        return self.admin_account.id == attraction.owner_id or self.can_admin_dept_for(attraction.department_id)

    # =========================
    # guests
    # =========================

    @property
    def guest_group(self):
        """
        The Guest Group to which this attendee belongs (either as a
        guest or a +1 comp), or None.
        """
        return self.group and self.group.guest


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
            elif restriction == c.PORK and c.VEGAN in self.standard_ints:
                return True
            else:
                return restriction in self.standard_ints
