import json
import math
import re
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy.sql.elements import not_
from pockets import cached_property, classproperty, groupify, listify, is_listy, readable_join
from pockets.autolog import log
from pytz import UTC
from residue import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy import and_, case, exists, func, or_, select
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import backref, subqueryload
from sqlalchemy.schema import Column as SQLAlchemyColumn, ForeignKey, Index, Table, UniqueConstraint
from sqlalchemy.types import Boolean, Date, Integer

import uber
from uber.config import c
from uber.custom_tags import safe_string, time_day_local
from uber.decorators import department_id_adapter, predelete_adjustment, presave_adjustment, \
    render
from uber.models import MagModel
from uber.models.group import Group
from uber.models.types import default_relationship as relationship, utcnow, Choice, DefaultColumn as Column, \
    MultiChoice, TakesPaymentMixin
from uber.utils import add_opt, get_age_from_birthday, get_age_conf_from_birthday, hour_day_format, \
    localized_now, mask_string, normalize_email, normalize_email_legacy, remove_opt


__all__ = ['Attendee', 'AttendeeAccount', 'FoodRestrictions']


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
        foreign_keys='Attendee.creator_id',
        backref=backref('created_badges', order_by='Attendee.full_name'),
        cascade='save-update,merge,refresh-expire,expunge',
        remote_side='Attendee.id',
        single_parent=True)

    current_attendee_id = Column(UUID, ForeignKey('attendee.id'), nullable=True)
    current_attendee = relationship(
        'Attendee',
        foreign_keys='Attendee.current_attendee_id',
        backref=backref('old_badges', order_by='Attendee.badge_status', cascade='all,delete-orphan'),
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
    ec_name = Column(UnicodeText)
    ec_phone = Column(UnicodeText)
    onsite_contact = Column(UnicodeText)
    no_onsite_contact = Column(Boolean, default=False)
    cellphone = Column(UnicodeText)
    no_cellphone = Column(Boolean, default=False)

    requested_accessibility_services = Column(Boolean, default=False)

    interests = Column(MultiChoice(c.INTEREST_OPTS))
    found_how = Column(UnicodeText)  # TODO: Remove?
    comments = Column(UnicodeText)  # TODO: Remove?
    for_review = Column(UnicodeText, admin_only=True)
    admin_notes = Column(UnicodeText, admin_only=True)

    public_id = Column(UUID, default=lambda: str(uuid4()))
    badge_num = Column(Integer, default=None, nullable=True, admin_only=True)
    badge_type = Column(Choice(c.BADGE_OPTS), default=c.ATTENDEE_BADGE)
    badge_status = Column(Choice(c.BADGE_STATUS_OPTS), default=c.NEW_STATUS, index=True, admin_only=True)
    ribbon = Column(MultiChoice(c.RIBBON_OPTS), admin_only=True)

    affiliate = Column(UnicodeText)  # TODO: Remove

    # If [[staff_shirt]] is the same as [[shirt]], we only use the shirt column
    shirt = Column(Choice(c.SHIRT_OPTS), default=c.NO_SHIRT)
    staff_shirt = Column(Choice(c.STAFF_SHIRT_OPTS), default=c.NO_SHIRT)
    num_event_shirts = Column(Choice(c.STAFF_EVENT_SHIRT_OPTS, allow_unspecified=True), default=-1)
    can_spam = Column(Boolean, default=False)
    regdesk_info = Column(UnicodeText, admin_only=True)
    extra_merch = Column(UnicodeText, admin_only=True)
    got_merch = Column(Boolean, default=False, admin_only=True)
    got_staff_merch = Column(Boolean, default=False, admin_only=True)
    got_swadge = Column(Boolean, default=False, admin_only=True)
    can_transfer = Column(Boolean, default=False, admin_only=True)

    reg_station = Column(Integer, nullable=True, admin_only=True)
    registered = Column(UTCDateTime, server_default=utcnow(), default=lambda: datetime.now(UTC))
    confirmed = Column(UTCDateTime, nullable=True, default=None)
    checked_in = Column(UTCDateTime, nullable=True)

    paid = Column(Choice(c.PAYMENT_OPTS), default=c.NOT_PAID, index=True, admin_only=True)
    badge_cost = Column(Integer, nullable=True, admin_only=True)
    overridden_price = Column(Integer, nullable=True, admin_only=True)
    amount_extra = Column(Choice(c.DONATION_TIER_OPTS, allow_unspecified=True), default=0)
    extra_donation = Column(Integer, default=0)

    badge_printed_name = Column(UnicodeText)

    active_receipt = relationship(
        'ModelReceipt',
        cascade='save-update,merge,refresh-expire,expunge',
        primaryjoin='and_(remote(ModelReceipt.owner_id) == foreign(Attendee.id),'
        'ModelReceipt.owner_model == "Attendee",'
        'ModelReceipt.closed == None)',
        uselist=False)
    default_cost = Column(Integer, nullable=True)

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
        secondary='shift',
        order_by='Job.name',
        viewonly=True)
    jobs_in_assigned_depts = relationship(
        'Job',
        backref='attendees_in_dept',
        secondaryjoin='DeptMembership.department_id == Job.department_id',
        secondary='dept_membership',
        order_by='Job.name',
        viewonly=True)
    depts_where_working = relationship(
        'Department',
        backref='attendees_working_shifts',
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
    reviewed_emergency_procedures = Column(Boolean, default=False)
    name_in_credits = Column(UnicodeText, nullable=True)
    walk_on_volunteer = Column(Boolean, default=False)
    nonshift_minutes = Column(Integer, default=0, admin_only=True)
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
    
    # =========================
    # badge printing
    # =========================
    print_requests = relationship('PrintJob', backref='attendee')

    # =========================
    # art show
    # =========================
    art_show_bidder = relationship('ArtShowBidder', backref=backref('attendee', load_on_pending=True), uselist=False)
    art_show_purchases = relationship(
        'ArtShowPiece',
        backref='buyer',
        cascade='save-update,merge,refresh-expire,expunge',
        secondary='art_show_receipt')
    art_agent_apps = relationship(
        'ArtShowApplication',
        backref='agents',
        secondary='art_show_agent_code',
        viewonly=True)

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

        if self.birthdate == '':
            self.birthdate = None

        if not self.extra_donation:
            self.extra_donation = 0

        if not self.gets_any_kind_of_shirt:
            self.shirt = c.NO_SHIRT

        if not self.badge_cost:
            self.badge_cost = self.calculate_badge_cost()

        if self.badge_cost == 0 and self.paid in [c.NOT_PAID, c.PAID_BY_GROUP]:
            self.paid = c.NEED_NOT_PAY

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
        if self.group and self.paid == c.PAID_BY_GROUP and self.has_or_will_have_badge:
            if not self.group.is_valid:
                self.badge_status = c.INVALID_GROUP_STATUS
            elif self.group.is_dealer and self.group.status not in [c.APPROVED, c.SHARED]:
                self.badge_status = c.UNAPPROVED_DEALER_STATUS

        if self.badge_status == c.INVALID_GROUP_STATUS and (
                not self.group or self.group.is_valid or self.paid != c.PAID_BY_GROUP):
            self.badge_status = c.NEW_STATUS

        if self.badge_status == c.UNAPPROVED_DEALER_STATUS and (not self.group or
                                                                not self.group.is_dealer or
                                                                self.paid != c.PAID_BY_GROUP or
                                                                self.group.status in [c.APPROVED, c.SHARED]):
            self.badge_status = c.NEW_STATUS

        if self.badge_status == c.WATCHED_STATUS and not self.banned:
            self.badge_status = c.NEW_STATUS

        if self.badge_status in [c.NEW_STATUS, c.AT_DOOR_PENDING_STATUS] and self.banned:
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
                    self.paid in [c.HAS_PAID, c.NEED_NOT_PAY, c.REFUNDED]
                    or self.paid == c.PAID_BY_GROUP
                    and self.group
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

        if old_type != self.badge_type or old_num != self.badge_num:
            self.session.update_badge(self, old_type, old_num)
        elif needs_badge_num(self) and not self.badge_num:
            self.badge_num = self.session.get_next_badge_num(self.badge_type)

    @presave_adjustment
    def _use_promo_code(self):
        if c.BADGE_PROMO_CODES_ENABLED and self.promo_code and not self.overridden_price and self.is_unpaid:
            if self.badge_cost_with_promo_code > 0:
                self.overridden_price = self.badge_cost_with_promo_code
            else:
                self.paid = c.NEED_NOT_PAY

    @presave_adjustment
    def refunded_if_receipt_has_refund(self):
        if self.paid == c.HAS_PAID and self.active_receipt and self.active_receipt.refund_total:
            self.paid = c.REFUNDED

    @presave_adjustment
    def update_default_cost(self):
        if self.is_valid or self.badge_status in [c.PENDING_STATUS, c.AT_DOOR_PENDING_STATUS]:
            self.default_cost = self.calc_default_cost()

    @hybrid_property
    def default_cost_cents(self):
        return self.default_cost * 100

    @presave_adjustment
    def assign_creator(self):
        if self.is_new and not self.creator_id:
            self.creator_id = self.session.admin_attendee().id if self.session.admin_attendee() else None

    @presave_adjustment
    def assign_number_after_payment(self):
        if c.AT_THE_CON:
            if self.has_personalized_badge and not self.badge_num:
                if not self.amount_unpaid:
                    self.badge_num = self.session.get_next_badge_num(self.badge_type)

    @presave_adjustment
    def match_account_if_exists(self):
        if c.ATTENDEE_ACCOUNTS_ENABLED and self.email and not self.managers:
            self.session.match_attendee_to_account(self)

    @hybrid_property
    def times_printed(self):
        return len([job.id for job in self.print_requests if job.printed])

    @times_printed.expression
    def times_printed(cls):
        from uber.models import PrintJob

        return select([func.count(PrintJob.id)]
                      ).where(and_(PrintJob.attendee_id == cls.id,
                                   PrintJob.printed != None)).label('times_printed')  # noqa: E711

    @property
    def age_now_or_at_con(self):
        if not self.birthdate:
            return None

        return get_age_from_birthday(self.birthdate, c.NOW_OR_AT_CON)

    @presave_adjustment
    def not_attending_need_not_pay(self):
        if self.badge_status == c.NOT_ATTENDING:
            self.paid = c.NEED_NOT_PAY

    @presave_adjustment
    def child_badge(self):
        if c.CHILD_BADGE in c.PREREG_BADGE_TYPES:
            if self.age_now_or_at_con is not None and self.age_now_or_at_con < 18 \
                    and self.badge_type == c.ATTENDEE_BADGE:
                self.badge_type = c.CHILD_BADGE
                self.session.set_badge_num_in_range(self)
                if self.age_now_or_at_con < 13:
                    self.ribbon = add_opt(self.ribbon_ints, c.UNDER_13)

    @presave_adjustment
    def child_ribbon_or_not(self):
        if c.CHILD_BADGE in c.PREREG_BADGE_TYPES:
            if self.age_now_or_at_con is not None and self.age_now_or_at_con < 13:
                self.ribbon = add_opt(self.ribbon_ints, c.UNDER_13)
            elif c.UNDER_13 in self.ribbon_ints and self.age_now_or_at_con and self.age_now_or_at_con >= 13:
                self.ribbon = remove_opt(self.ribbon_ints, c.UNDER_13)

    @presave_adjustment
    def child_to_attendee(self):
        if c.CHILD_BADGE in c.PREREG_BADGE_TYPES:
            if self.badge_type == c.CHILD_BADGE and self.age_now_or_at_con is not None and self.age_now_or_at_con >= 18:
                self.badge_type = c.ATTENDEE_BADGE
                self.session.set_badge_num_in_range(self)
                self.ribbon = remove_opt(self.ribbon_ints, c.UNDER_13)

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
    def access_sections(self):
        """
        Returns what site sections an attendee 'belongs' to based on their properties.
        We use this list to determine which admins can create, edit, and view the attendee.
        """
        section_list = []
        if self.staffing_or_will_be:
            section_list.append('shifts_admin')
        if (self.group and self.group.guest and self.group.guest.group_type == c.BAND) \
                or (self.badge_type == c.GUEST_BADGE and c.BAND in self.ribbon_ints):
            section_list.append('band_admin')
        if (self.group and self.group.guest and self.group.guest.group_type == c.GUEST) \
                or (self.badge_type == c.GUEST_BADGE and c.BAND not in self.ribbon_ints):
            section_list.append('guest_admin')
        if c.PANELIST_RIBBON in self.ribbon_ints:
            section_list.append('panels_admin')
        if self.is_dealer:
            section_list.append('dealer_admin')
        if self.mits_applicants:
            section_list.append('mits_admin')
        if self.group and self.group.guest and self.group.guest.group_type == c.MIVS:
            section_list.append('mivs_admin')
        if self.art_show_applications or self.art_show_bidder or self.art_show_purchases or self.art_agent_apps:
            section_list.append('art_show_admin')
        if self.marketplace_applications:
            section_list.append('marketplace_admin')
        return section_list

    def admin_read_access(self):
        from uber.models import Session
        with Session() as session:
            return session.admin_attendee_max_access(self)

    def admin_write_access(self):
        from uber.models import Session
        with Session() as session:
            return session.admin_attendee_max_access(self, read_only=False)

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

    @property
    def available_badge_type_opts(self):
        if self.is_new or self.badge_type == c.ATTENDEE_BADGE and self.is_unpaid:
            return c.FORMATTED_BADGE_TYPES

        badge_type_price = c.BADGE_TYPE_PRICES[self.badge_type] if self.badge_type in c.BADGE_TYPE_PRICES else 0

        badge_type_opts = [{
            'name': self.badge_type_label,
            'desc': 'An upgraded badge with perks.'
                    if badge_type_price else 'Allows access to the convention for its duration.',
            'value': self.badge_type
            }]

        for opt in c.FORMATTED_BADGE_TYPES[1:]:
            if 'price' not in opt or badge_type_price < opt['price']:
                badge_type_opts.append(opt)

        return badge_type_opts

    @property
    def available_amount_extra_opts(self):
        if self.is_new or self.amount_extra == 0 or self.is_unpaid:
            return c.FORMATTED_MERCH_TIERS

        preordered_merch_opts = []

        for opt in c.FORMATTED_MERCH_TIERS:
            if 'price' not in opt or self.amount_extra <= opt['price']:
                preordered_merch_opts.append(opt)

        return preordered_merch_opts

    @property
    def badge_cost_with_promo_code(self):
        return self.calculate_badge_cost(use_promo_code=True)

    def calculate_badge_cost(self, use_promo_code=False, include_price_override=True):
        if self.paid == c.NEED_NOT_PAY or self.badge_status == c.NOT_ATTENDING:
            return 0
        elif self.overridden_price is not None and include_price_override:
            return self.overridden_price
        elif self.is_dealer:
            return c.DEALER_BADGE_PRICE
        elif self.promo_code_groups or (self.group and self.group.cost and self.paid == c.PAID_BY_GROUP):
            return c.get_group_price()
        else:
            cost = self.new_badge_cost

        if c.BADGE_PROMO_CODES_ENABLED and self.promo_code and use_promo_code:
            return self.promo_code.calculate_discounted_price(cost)
        else:
            return cost

    @property
    def base_badge_prices_cost(self):
        # This is a special type of cost that accounts for badge upgrades for comped attendees
        # as well as age discounts, which get included in the upgrade price
        if self.paid == c.NEED_NOT_PAY:
            return self.new_badge_cost
        if self.qualifies_for_discounts:
            return self.calculate_badge_cost() - min(self.calculate_badge_cost(), abs(self.age_discount))
        return self.calculate_badge_cost()

    def undo_extras(self):
        if self.active_receipt:
            return "Could not undo extras, this attendee has an open receipt!"
        self.amount_extra = 0
        self.extra_donation = 0
        if self.badge_type in c.BADGE_TYPE_PRICES:
            self.badge_type = c.ATTENDEE_BADGE

    @property
    def qualifies_for_discounts(self):
        return not self.promo_code and self.paid != c.NEED_NOT_PAY and self.overridden_price is None \
            and not self.is_dealer and self.badge_type not in c.BADGE_TYPE_PRICES

    @property
    def in_free_group(self):
        if self.promo_code_groups:
            return not self.promo_code_groups[0].total_cost
        if self.group:
            return not self.group.cost
        return False

    @property
    def new_badge_cost(self):
        # What this badge would cost if it were new, i.e., not taking into
        # account special overrides or upgrades
        registered = self.registered_local if self.registered else uber.utils.localized_now()
        if self.is_dealer:
            return c.DEALER_BADGE_PRICE
        elif self.badge_type == c.ONE_DAY_BADGE:
            return c.get_oneday_price(registered)
        elif self.is_presold_oneday:
            return c.get_presold_oneday_price(self.badge_type)
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
        if self.age_now_or_at_con and self.age_now_or_at_con < 13:
            half_off = math.ceil(self.new_badge_cost / 2)
            if not self.age_group_conf['discount'] or self.age_group_conf['discount'] < half_off:
                return -half_off
        return -self.age_group_conf['discount']

    @property
    def age_group_conf(self):
        return get_age_conf_from_birthday(self.birthdate, c.NOW_OR_AT_CON)

    @property
    def total_cost(self):
        if not self.is_valid:
            return 0

        if self.active_receipt:
            return self.active_receipt.item_total / 100
        return self.default_cost or self.calc_default_cost()

    @property
    def total_cost_if_valid(self):
        if self.active_receipt:
            return self.active_receipt.item_total / 100
        return self.default_cost or self.calc_default_cost()

    @property
    def amount_unpaid_if_valid(self):
        if self.paid == c.PAID_BY_GROUP:
            personal_cost = max(0, self.total_cost_if_valid - self.badge_cost)
        else:
            personal_cost = self.total_cost_if_valid
        return max(0, ((personal_cost * 100) - self.amount_paid) / 100)

    @property
    def total_donation(self):
        return self.total_cost - self.badge_cost

    def calculate_shipping_fee_cost(self):
        # For plugins to override with custom shipping fee logic
        # Also so we can display the potential shipping fee cost to attendees
        return c.MERCH_SHIPPING_FEE

    @property
    def in_reg_cart_group(self):
        if c.ATTENDEE_ACCOUNTS_ENABLED and self.managers:
            return self.badge_status == c.AT_DOOR_PENDING_STATUS and len(self.managers[0].at_door_attendees) > 1
        
    @property
    def has_at_con_payments(self):
        return self.active_receipt.has_at_con_payments if self.active_receipt else False

    @property
    def amount_extra_unpaid(self):
        return self.total_cost - self.badge_cost

    @property
    def amount_pending(self):
        return self.active_receipt.pending_total if self.active_receipt else 0

    @hybrid_property
    def is_paid(self):
        return self.active_receipt and self.active_receipt.current_amount_owed == 0

    @is_paid.expression
    def is_paid(cls):
        from uber.models import ModelReceipt, Group

        return case([(cls.paid == c.PAID_BY_GROUP,
                      exists().select_from(Group).where(
                          and_(cls.group_id == Group.id,
                               Group.is_paid == True)))],  # noqa: E712
                    else_=(exists().select_from(ModelReceipt).where(
                            and_(ModelReceipt.owner_id == cls.id,
                                 ModelReceipt.owner_model == "Attendee",
                                 ModelReceipt.closed == None,  # noqa: E711
                                 ModelReceipt.current_amount_owed == 0))))

    @hybrid_property
    def amount_paid(self):
        return self.active_receipt.payment_total if self.active_receipt else 0

    @amount_paid.expression
    def amount_paid(cls):
        from uber.models import ModelReceipt

        return select([ModelReceipt.payment_total]).where(
            and_(ModelReceipt.owner_id == cls.id,
                 ModelReceipt.owner_model == "Attendee",
                 ModelReceipt.closed == None)).label('amount_paid')  # noqa: E711

    @hybrid_property
    def amount_refunded(self):
        return self.active_receipt.refund_total if self.active_receipt else 0

    @amount_refunded.expression
    def amount_refunded(cls):
        from uber.models import ModelReceipt

        return select([ModelReceipt.refund_total]).where(
            and_(ModelReceipt.owner_id == cls.id,
                 ModelReceipt.owner_model == "Attendee")).label('amount_refunded')

    @property
    def amount_unpaid(self):
        if self.paid == c.PAID_BY_GROUP and not self.active_receipt:
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

    @hybrid_property
    def is_unassigned(self):
        return not self.first_name

    @is_unassigned.expression
    def is_unassigned(cls):
        return cls.first_name == ''

    @property
    def unassigned_group_reg(self):
        return self.group_id and self.is_unassigned

    @property
    def valid_placeholder(self):
        return self.placeholder and self.first_name and self.last_name

    @hybrid_property
    def is_valid(self):
        return self.badge_status not in [c.PENDING_STATUS, c.AT_DOOR_PENDING_STATUS, c.INVALID_STATUS,
                                         c.IMPORTED_STATUS, c.INVALID_GROUP_STATUS, c.REFUNDED_STATUS]

    @is_valid.expression
    def is_valid(cls):
        return not_(cls.badge_status.in_([c.PENDING_STATUS, c.AT_DOOR_PENDING_STATUS, c.INVALID_STATUS,
                                          c.IMPORTED_STATUS, c.INVALID_GROUP_STATUS, c.REFUNDED_STATUS]))

    @hybrid_property
    def has_or_will_have_badge(self):
        return self.is_valid and self.badge_status not in [c.NOT_ATTENDING, c.UNAPPROVED_DEALER_STATUS]

    @has_or_will_have_badge.expression
    def has_or_will_have_badge(cls):
        return and_(cls.is_valid,
                    not_(cls.badge_status.in_([c.REFUNDED_STATUS, c.NOT_ATTENDING, c.UNAPPROVED_DEALER_STATUS])
                         ))

    @hybrid_property
    def has_badge(self):
        return self.has_or_will_have_badge and self.badge_status != c.DEFERRED_STATUS

    @has_badge.expression
    def has_badge(cls):
        return and_(cls.has_or_will_have_badge,
                    not_(cls.badge_status == c.DEFERRED_STATUS))

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
                exists().select_from(Group).where(
                    and_(cls.group_id == Group.id,
                         Group.is_dealer == True))))  # noqa: E712

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
    def cannot_check_in_reason(self):
        """
        Returns None if we are ready for checkin, otherwise a short error
        message why we can't check them in.
        """

        if self.badge_status == c.WATCHED_STATUS:
            if self.banned or not self.regdesk_info:
                regdesk_info_append = " [{}]".format(self.regdesk_info) if self.regdesk_info else ""
                return "MUST TALK TO SECURITY before picking up badge{}".format(regdesk_info_append)
            return self.regdesk_info or "Badge status is {}".format(self.badge_status_label)

        if self.badge_status not in [c.COMPLETED_STATUS, c.NEW_STATUS, c.AT_DOOR_PENDING_STATUS]:
            return "Badge status is {}".format(self.badge_status_label)

        if self.group and self.paid == c.PAID_BY_GROUP and self.group.is_dealer \
                and self.group.status not in [c.APPROVED, c.SHARED]:
            return "Unapproved dealer"

        if self.group and self.paid == c.PAID_BY_GROUP and self.group.amount_unpaid:
            return "Unpaid group"

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
    def cannot_abandon_badge_reason(self):
        from uber.custom_tags import email_only
        if self.checked_in:
            return "This badge has already been picked up."
        if self.badge_type in [c.STAFF_BADGE, c.CONTRACTOR_BADGE]:
            return f"Please contact {email_only(c.STAFF_EMAIL)} to cancel or defer your badge."

        if self.art_show_applications and self.art_show_applications[0].is_valid:
            return f"Please contact {email_only(c.ART_SHOW_EMAIL)} to cancel your art show application first."
        if self.art_agent_apps and any(app.is_valid for app in self.art_agent_apps):
            return "Please ask the artist you're agenting for {} first.".format(
                "assign a new agent" if c.ONE_AGENT_PER_APP else "unassign you as an agent."
            )
        
        reason = ""
        if self.paid == c.NEED_NOT_PAY and not self.promo_code:
            reason = "You cannot abandon a comped badge."
        elif self.is_group_leader and self.group.is_valid:
            reason = f"As a leader of a group, you cannot {'abandon' if not self.group.cost else 'refund'} your badge."
        elif self.amount_paid:
            reason = self.cannot_self_service_refund_reason

        if reason:
            return reason + " Please {} contact us at {}{}.".format(
                "transfer your badge instead or" if self.is_transferable else "",
                email_only(c.REGDESK_EMAIL),
                " to cancel your badge.")

    @property
    def cannot_self_service_refund_reason(self):
        from uber.custom_tags import datetime_local_filter

        if not c.REFUND_CUTOFF:
            return "We do not offer refunds."
        if self.has_at_con_payments:
            return "We cannot automatically refund at-the-door payments."
        if c.AFTER_REFUND_CUTOFF:
            return "Refunds are no longer available."
        if c.BEFORE_REFUND_START:
            return f"Refunds will open at {datetime_local_filter(c.REFUND_START)}."

    @property
    def can_defer_badge(self):
        return self.cannot_abandon_badge_reason and not self.checked_in \
               and self.badge_type not in [c.STAFF_BADGE, c.CONTRACTOR_BADGE] \
               and not self.group and not self.in_promo_code_group \
               and self.badge_status == c.COMPLETED_STATUS and not self.amount_unpaid \
               and c.SELF_SERVICE_DEFERRALS_OPEN

    @property
    def cannot_delete_badge_reason(self):
        if self.paid == c.HAS_PAID:
            return "Cannot delete a paid badge."
        if self.has_personalized_badge and c.AFTER_PRINTED_BADGE_DEADLINE:
            from uber.models import Session
            with Session() as session:
                admin = session.current_admin_account()
                if not admin.is_super_admin:
                    return "Custom badges have already been ordered so you cannot delete this badge."

    @property
    def needs_pii_consent(self):
        return self.is_new or self.placeholder or not self.first_name

    @property
    def has_extras(self):
        return self.amount_extra or self.extra_donation or self.badge_type in c.BADGE_TYPE_PRICES

    @property
    def shirt_size_marked(self):
        if c.STAFF_SHIRT_OPTS == c.SHIRT_OPTS:
            return self.shirt not in [c.NO_SHIRT, c.SIZE_UNKNOWN]
        else:
            return (not self.num_event_shirts_owed or self.shirt not in [c.NO_SHIRT, c.SIZE_UNKNOWN]) and (
                    not self.gets_staff_shirt or self.staff_shirt not in [c.NO_SHIRT, c.SIZE_UNKNOWN])

    @property
    def shirt_info_marked(self):
        return not c.HOURS_FOR_SHIRT or (self.shirt_size_marked and (
                self.num_event_shirts != -1 or not self.gets_staff_shirt or not c.STAFF_EVENT_SHIRT_OPTS))

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
    def primary_account_email(self):
        if self.managers:
            return self.managers[0].email
        return ''

    @primary_account_email.expression
    def primary_account_email(cls):
        return select([AttendeeAccount.email]
                      ).where(AttendeeAccount.id == attendee_attendee_account.c.attendee_account_id
                              ).where(attendee_attendee_account.c.attendee_id == cls.id).label('primary_account_email')

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
            (cls.promo_code != None,  # noqa: E711
             select([PromoCodeGroup.name]).where(PromoCodeGroup.id == PromoCode.group_id)
             .where(PromoCode.id == cls.promo_code_id).label('promo_code_group_name')),
            (cls.promo_code_groups != None,  # noqa: E711
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
        return normalize_email_legacy(self.email)

    @normalized_email.expression
    def normalized_email(cls):
        return func.replace(func.lower(func.trim(cls.email)), '.', '')

    @property
    def gets_emails(self):
        return self.badge_status in [c.NEW_STATUS, c.COMPLETED_STATUS] and (
                                    not self.is_dealer or self.group and
                                    self.group.status not in [c.DECLINED, c.CANCELLED])

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
    def is_inherently_transferable(self):
        return self.badge_status == c.COMPLETED_STATUS \
            and not self.checked_in \
            and (self.paid in [c.HAS_PAID, c.PAID_BY_GROUP] or self.in_promo_code_group) \
            and self.badge_type in c.TRANSFERABLE_BADGE_TYPES \
            and not self.admin_account \
            and not self.has_role_somewhere

    @property
    def is_transferable(self):
        return self.is_inherently_transferable or self.can_transfer

    @property
    def cannot_transfer_reason(self):
        from uber.custom_tags import readable_join

        reasons = []
        if self.admin_account:
            reasons.append("they have an admin account")
        if self.badge_type not in c.TRANSFERABLE_BADGE_TYPES:
            reasons.append("their badge type ({}) is not transferable".format(self.badge_type_label))
        if self.has_role_somewhere:
            reasons.append("they are a department head, checklist admin, \
                           or point of contact for the following departments: {}".format(
                               readable_join(self.get_labels_for_memberships('dept_memberships_with_role'))))
        return reasons

    @presave_adjustment
    def force_no_transfer(self):
        if self.admin_account or self.badge_type not in c.TRANSFERABLE_BADGE_TYPES or self.has_role_somewhere:
            self.can_transfer = False

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
        If someone is staff-shirt-eligible, we use the number of event shirts they have selected (if any).
        Volunteers also get a free event shirt. Staff get an event shirt if staff shirts are turned off for the event.
        Returns: Integer representing the number of free event shirts this attendee should get.
        """
        return max(0, self.num_event_shirts) if self.gets_staff_shirt else bool(
            self.volunteer_event_shirt_eligible or (self.badge_type == c.STAFF_BADGE and c.HOURS_FOR_SHIRT))

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
        return bool(self.badge_type == c.STAFF_BADGE and c.SHIRTS_PER_STAFFER > 0)

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

        if merch and self.volunteer_event_shirt_eligible and not self.volunteer_event_shirt_earned:
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
        return readable_join([item for item in self.merch_items if not is_listy(item)]) if self.merch_items else 'N/A'

    @property
    def staff_merch_items(self):
        """Used by the merch and staff_merch properties for staff swag."""
        merch = []
        num_staff_shirts_owed = self.num_staff_shirts_owed
        if num_staff_shirts_owed > 0:
            staff_shirts = '{} Staff Shirt{}'.format(num_staff_shirts_owed, 's' if num_staff_shirts_owed > 1 else '')
            if self.shirt_size_marked:
                try:
                    if c.STAFF_SHIRT_OPTS != c.SHIRT_OPTS:
                        staff_shirts += ' [{}]'.format(c.STAFF_SHIRTS[self.staff_shirt])
                    else:
                        staff_shirts += ' [{}]'.format(c.SHIRTS[self.shirt])
                except KeyError:
                    staff_shirts += ' [{}]'.format("Size unknown")
            merch.append(staff_shirts)

        if self.staffing:
            merch.append('Staffer Info Packet')

        return merch

    @property
    def staff_merch(self):
        """Used if c.SEPARATE_STAFF_MERCH is true to return the staff swag."""
        return readable_join(self.staff_merch_items) if self.staff_merch_items else 'N/A'

    @property
    def accoutrements(self):
        stuff = [] if not self.ribbon else ['a ' + s + ' ribbon' for s in self.ribbon_labels]

        if c.WRISTBANDS_ENABLED:
            stuff.append('a {} wristband'.format(c.WRISTBAND_COLORS[self.age_group]))
        if self.regdesk_info:
            stuff.append(self.regdesk_info)
        return (' with ' if stuff else '') + readable_join(stuff)

    @property
    def check_in_notes(self):
        notes = []
        if self.age_group_conf['consent_form']:
            notes.append("Before checking this attendee in, please collect a signed parental consent form, \
                         which must be notarized if the guardian is not there. If the guardian is there, and \
                         they have not already completed one, have them sign one in front of you.")

        if self.accoutrements:
            notes.append(f"Please check this attendee in {self.accoutrements}.")

        return "<br/><br/>".join(notes)

    @property
    def multiply_assigned(self):
        return len(self.dept_memberships) > 1

    @property
    def takes_shifts(self):
        return bool(self.staffing and self.badge_type != c.CONTRACTOR_BADGE and any(
            not d.is_shiftless for d in self.assigned_depts))

    @property
    def shift_minutes(self):
        all_minutes = set()
        for shift in self.shifts:
            all_minutes.update(shift.job.minutes)
        return all_minutes

    @cached_property
    def shift_minute_map(self):
        all_minutes = {}
        for shift in self.shifts:
            for minute in shift.job.minutes:
                all_minutes[minute] = shift.job
        return all_minutes

    @cached_property
    def available_job_filters(self):
        from uber.models.department import Job

        job_filters = [Job.is_unfilled]

        member_dept_ids = set(d.department_id for d in self.dept_memberships)
        member_filter = Job.department_id.in_(member_dept_ids) if member_dept_ids else None

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
            if job.no_overlap(self) and job.working_limit_ok(self)
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

    @classproperty
    def searchable_fields(cls):
        fields = [col.name for col in cls.__table__.columns if isinstance(col.type, UnicodeText)]
        if "other_accessibility_requests" in fields:
            fields.remove('other_accessibility_requests')
        return fields

    @classproperty
    def searchable_bools(cls):
        fields = [col.name for col in cls.__table__.columns if isinstance(col.type, Boolean)]
        fields.remove('requested_accessibility_services')
        fields.extend(['confirmed', 'checked_in'])
        return fields

    @classproperty
    def searchable_choices(cls):
        return [col.name for col in cls.__table__.columns if isinstance(col.type, Choice)]

    @classproperty
    def checkin_bools(self):
        return ['got_merch'] if c.MERCH_AT_CHECKIN else []

    @property
    def assigned_depts_labels(self):
        return [d.name for d in self.assigned_depts]

    @property
    def requested_depts_labels(self):
        return [d.name for d in self.requested_depts]

    def get_labels_for_memberships(self, prop_name):
        # Takes a string for one of the 'depts_memberships' properties on the Attendee model
        # (e.g., dept_memberships_where_can_admin_checklist) and returns a list of department names
        return [membership.department.name for membership in getattr(self, prop_name, [])]

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
        return weighted_hours + self.nonshift_minutes / 60

    @property
    def unweighted_hours(self):
        unweighted_hours = sum(s.job.real_duration for s in self.shifts) / 60
        return unweighted_hours + self.nonshift_minutes / 60

    @department_id_adapter
    def weighted_hours_in(self, department_id):
        if not department_id:
            return self.weighted_hours
        return sum(s.job.weighted_hours for s in self.shifts if s.job.department_id == department_id)

    @department_id_adapter
    def unweighted_hours_in(self, department_id):
        if not department_id:
            return self.unweighted_hours
        return sum(s.job.real_duration / 60 for s in self.shifts if s.job.department_id == department_id)

    @property
    def worked_hours(self):
        weighted_hours = sum(s.job.weighted_hours for s in self.worked_shifts)
        return weighted_hours + self.nonshift_minutes / 60

    @property
    def unweighted_worked_hours(self):
        unweighted_hours = sum(s.job.real_duration / 60 for s in self.worked_shifts)
        return unweighted_hours + self.nonshift_minutes / 60

    @department_id_adapter
    def worked_hours_in(self, department_id):
        if not department_id:
            return self.worked_hours
        return sum(s.job.weighted_hours for s in self.worked_shifts if s.job.department_id == department_id)

    @department_id_adapter
    def unweighted_worked_hours_in(self, department_id):
        if not department_id:
            return self.unweighted_worked_hours
        return sum(s.job.real_duration / 60 for s in self.worked_shifts if s.job.department_id == department_id)

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
            'nonshift_hours': self.nonshift_minutes / 60,
            'shifts': [{
                'worked': shift.worked_label,
                'rating': shift.rating_label,
                'comment': shift.comment,
                'job': {
                    'location': shift.job.department_name,
                    'name': shift.job.name,
                    'weight': shift.job.weight,
                    'when': (
                            time_day_local(shift.job.start_time) + ' - ' +
                            time_day_local(shift.job.start_time + timedelta(minutes=shift.job.duration))
                        ).replace('<nobr>', '').replace('</nobr>', ''),
                    'total_hours': shift.job.duration / 60 * shift.job.weight,
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
        if self.badge_type == c.STAFF_BADGE and (self.is_new or self.orig_value_of('badge_type') != c.STAFF_BADGE):
            self.hotel_eligible = True

    @presave_adjustment
    def staffer_setup_teardown(self):
        if self.setup_hotel_approved:
            self.can_work_setup = True
        if self.teardown_hotel_approved:
            self.can_work_teardown = True

    @property
    def hotel_shifts_required(self):
        return bool(c.VOLUNTEER_CHECKLIST_OPEN and self.hotel_nights and not self.is_dept_head and self.takes_shifts)

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
        if not c.PRE_CON:
            return not self.placeholder and (
                not c.VOLUNTEER_AGREEMENT_ENABLED or self.agreed_to_volunteer_agreement) and (
                not c.EMERGENCY_PROCEDURES_ENABLED or self.reviewed_emergency_procedures) \
                and c.SHIFTS_CREATED

        return not self.placeholder and self.food_restrictions_filled_out and self.shirt_info_marked and (
            not self.hotel_eligible
            or self.hotel_requests
            or not c.BEFORE_ROOM_DEADLINE
            or not c.HOTELS_ENABLED
            or c.HOTEL_REQUESTS_URL) and (
            not c.VOLUNTEER_AGREEMENT_ENABLED or self.agreed_to_volunteer_agreement) and (
            not c.EMERGENCY_PROCEDURES_ENABLED or self.reviewed_emergency_procedures) \
            and c.SHIFTS_CREATED

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
    def masked_name(self):
        return self.first_name + ' ' + self.last_name[0] + '.'

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


# Many to many association table to tie Attendees to Attendee Accounts
attendee_attendee_account = Table(
    'attendee_attendee_account',
    MagModel.metadata,
    Column('attendee_id', UUID, ForeignKey('attendee.id')),
    Column('attendee_account_id', UUID, ForeignKey('attendee_account.id')),
    UniqueConstraint('attendee_id', 'attendee_account_id'),
    Index('ix_attendee_attendee_account_attendee_id', 'attendee_id'),
    Index('ix_attendee_attendee_account_attendee_account_id', 'attendee_account_id'),
)


class AttendeeAccount(MagModel):
    public_id = Column(UUID, default=lambda: str(uuid4()), nullable=True)
    email = Column(UnicodeText)
    hashed = Column(UnicodeText, private=True)
    password_reset = relationship('PasswordReset', backref='attendee_account', uselist=False)
    attendees = relationship(
        'Attendee', backref='managers', order_by='Attendee.registered',
        cascade='save-update,merge,refresh-expire,expunge',
        secondary='attendee_attendee_account')
    imported = Column(Boolean, default=False)

    email_model_name = 'account'

    @presave_adjustment
    def strip_email(self):
        self.email = self.email.strip()

    @presave_adjustment
    def normalize_email(self):
        self.email = normalize_email(self.email).lower()

    @hybrid_property
    def normalized_email(self):
        return normalize_email_legacy(self.email)

    @normalized_email.expression
    def normalized_email(cls):
        return func.replace(func.lower(func.trim(cls.email)), '.', '')

    @property
    def is_sso_account(self):
        if c.SSO_EMAIL_DOMAINS:
            local, domain = normalize_email(self.email, split_address=True)
            return domain in c.SSO_EMAIL_DOMAINS

    @property
    def has_dealer(self):
        return any([a.is_dealer for a in self.valid_attendees + self.imported_attendees])

    @property
    def valid_attendees(self):
        return [attendee for attendee in self.attendees if attendee.is_valid]

    @property
    def valid_single_badges(self):
        return [attendee for attendee in self.valid_attendees if not attendee.group or not attendee.group.is_valid]

    @property
    def valid_group_badges(self):
        return [attendee for attendee in self.valid_attendees if attendee.group and attendee.group.is_valid]

    @property
    def imported_attendees(self):
        return [attendee for attendee in self.attendees if attendee.badge_status == c.IMPORTED_STATUS]

    @property
    def imported_single_badges(self):
        return [attendee for attendee in self.imported_attendees if not attendee.group]

    @property
    def imported_group_badges(self):
        return [attendee for attendee in self.imported_attendees if attendee.group]
    
    @property
    def imported_group_leaders(self):
        return [attendee for attendee in self.imported_attendees
                if attendee.group and attendee.id == attendee.group.leader_id]

    @property
    def pending_attendees(self):
        return [attendee for attendee in self.attendees if attendee.badge_status == c.PENDING_STATUS]

    @property
    def at_door_attendees(self):
        return sorted([attendee for attendee in self.attendees if attendee.badge_status == c.AT_DOOR_PENDING_STATUS],
                      key=lambda a: a.first_name)

    @property
    def at_door_under_18s(self):
        return sorted([attendee for attendee in self.attendees if attendee.badge_status == c.AT_DOOR_PENDING_STATUS
                       and attendee.age_now_or_at_con < 18],
                      key=lambda a: a.first_name)

    @property
    def invalid_attendees(self):
        return [attendee for attendee in self.attendees if not attendee.is_valid and
                attendee.badge_status not in [c.PENDING_STATUS, c.AT_DOOR_PENDING_STATUS]]

    @property
    def refunded_deferred_attendees(self):
        return [attendee for attendee in self.attendees
                if attendee.badge_status in [c.REFUNDED_STATUS, c.DEFERRED_STATUS]]


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
            elif c.VEGAN in self.standard_ints:
                return True
            else:
                return restriction in self.standard_ints
