from datetime import datetime, timedelta, time

import six
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import backref
from sqlalchemy.schema import ForeignKey, Table, UniqueConstraint, Index
from sqlalchemy.sql import text
from sqlalchemy.types import Boolean, Float, Integer, Time, Uuid, String, DateTime

from uber.config import c
from uber.custom_tags import readable_join
from uber.decorators import presave_adjustment, cached_property, classproperty
from uber.utils import groupify
from uber.models import MagModel
from uber.models.attendee import Attendee
from uber.models.types import default_relationship as relationship, Choice, DefaultColumn as Column, UniqueList, MultiChoice


__all__ = [
    'dept_membership_dept_role', 'job_required_role', 'Department',
    'DeptChecklistItem', 'BulkPrintingRequest', 'DeptMembership', 'DeptMembershipRequest',
    'DeptRole', 'Job', 'Shift', 'JobTemplate']


# Many to many association table to represent the DeptRoles fulfilled
# by a DeptMembership
dept_membership_dept_role = Table(
    'dept_membership_dept_role',
    MagModel.metadata,
    Column('dept_membership_id', Uuid(as_uuid=False), ForeignKey('dept_membership.id')),
    Column('dept_role_id', Uuid(as_uuid=False), ForeignKey('dept_role.id')),
    UniqueConstraint('dept_membership_id', 'dept_role_id'),
    Index('ix_dept_membership_dept_role_dept_role_id', 'dept_role_id'),
    Index('ix_dept_membership_dept_role_dept_membership_id', 'dept_membership_id'),
)


# Many to many association table to represent the DeptRoles required
# to fulfill a Job
job_required_role = Table(
    'job_required_role',
    MagModel.metadata,
    Column('dept_role_id', Uuid(as_uuid=False), ForeignKey('dept_role.id')),
    Column('job_id', Uuid(as_uuid=False), ForeignKey('job.id')),
    UniqueConstraint('dept_role_id', 'job_id'),
    Index('ix_job_required_role_dept_role_id', 'dept_role_id'),
    Index('ix_job_required_role_job_id', 'job_id'),
)


# Many to many association table to store the DeptRoles in JobTemplate
job_template_required_role = Table(
    'job_template_required_role',
    MagModel.metadata,
    Column('dept_role_id', Uuid(as_uuid=False), ForeignKey('dept_role.id')),
    Column('job_template_id', Uuid(as_uuid=False), ForeignKey('job_template.id')),
    UniqueConstraint('dept_role_id', 'job_template_id'),
    Index('ix_job_template_required_role_dept_role_id', 'dept_role_id'),
    Index('ix_job_template_required_role_job_template_id', 'job_template_id'),
)


class DeptChecklistItem(MagModel):
    department_id = Column(Uuid(as_uuid=False), ForeignKey('department.id'))
    attendee_id = Column(Uuid(as_uuid=False), ForeignKey('attendee.id'))
    slug = Column(String)
    comments = Column(String, default='')

    __table_args__ = (
        UniqueConstraint('department_id', 'attendee_id', 'slug'),
    )


class BulkPrintingRequest(MagModel):
    department_id = Column(Uuid(as_uuid=False), ForeignKey('department.id'))
    link = Column(String)
    copies = Column(Integer)
    print_orientation = Column(Choice(c.PRINT_ORIENTATION_OPTS), default=c.PORTRAIT)
    cut_orientation = Column(Choice(c.CUT_ORIENTATION_OPTS), default=c.NONE)
    color = Column(Choice(c.PRINT_REQUEST_COLOR_OPTS), default=c.BW)
    paper_type = Column(Choice(c.PRINT_REQUEST_PAPER_TYPE_OPTS), default=c.STANDARD)
    paper_type_text = Column(String)
    size = Column(Choice(c.PRINT_REQUEST_SIZE_OPTS), default=c.STANDARD)
    size_text = Column(String)
    double_sided = Column(Boolean, default=False)
    stapled = Column(Boolean, default=False)
    notes = Column(String)
    required = Column(Boolean, default=False)
    link_is_shared = Column(Boolean, default=False)


class DeptMembership(MagModel):
    is_dept_head = Column(Boolean, default=False)
    is_poc = Column(Boolean, default=False)
    is_checklist_admin = Column(Boolean, default=False)
    attendee_id = Column(Uuid(as_uuid=False), ForeignKey('attendee.id'))
    department_id = Column(Uuid(as_uuid=False), ForeignKey('department.id'))

    __mapper_args__ = {'confirm_deleted_rows': False}
    __table_args__ = (
        UniqueConstraint('attendee_id', 'department_id'),
        Index('ix_dept_membership_attendee_id', 'attendee_id'),
        Index('ix_dept_membership_department_id', 'department_id'),
    )

    @hybrid_property
    def has_role(self):
        return self.has_inherent_role or self.has_dept_role

    @has_role.expression
    def has_role(cls):
        return or_(cls.has_inherent_role, cls.has_dept_role)

    @hybrid_property
    def has_inherent_role(self):
        return self.is_dept_head or self.is_poc or self.is_checklist_admin

    @has_inherent_role.expression
    def has_inherent_role(cls):
        return or_(cls.is_dept_head == True, cls.is_poc == True, cls.is_checklist_admin == True)  # noqa: E712

    @hybrid_property
    def has_dept_role(self):
        return bool(self.dept_roles)

    @has_dept_role.expression
    def has_dept_role(cls):
        return exists().select_from(dept_membership_dept_role) \
            .where(cls.id == dept_membership_dept_role.c.dept_membership_id)

    @property
    def dept_roles_names(self):
        return readable_join([role.name for role in self.dept_roles])


class DeptMembershipRequest(MagModel):
    attendee_id = Column(Uuid(as_uuid=False), ForeignKey('attendee.id'))

    # A NULL value for the department_id indicates the attendee is willing
    # to volunteer for any department (they checked "Anything" for
    # "Where do you want to help?").
    department_id = Column(Uuid(as_uuid=False), ForeignKey('department.id'), nullable=True)

    __mapper_args__ = {'confirm_deleted_rows': False}
    __table_args__ = (
        UniqueConstraint('attendee_id', 'department_id'),
        Index('ix_dept_membership_request_attendee_id', 'attendee_id'),
        Index('ix_dept_membership_request_department_id', 'department_id'),
    )


class DeptRole(MagModel):
    name = Column(String)
    description = Column(String)
    department_id = Column(Uuid(as_uuid=False), ForeignKey('department.id'))

    dept_memberships = relationship(
        'DeptMembership',
        backref='dept_roles',
        cascade='save-update,merge,refresh-expire,expunge',
        secondary='dept_membership_dept_role')

    __table_args__ = (
        UniqueConstraint('name', 'department_id'),
        Index('ix_dept_role_department_id', 'department_id'),
    )

    @hybrid_property
    def dept_membership_count(self):
        return len(self.dept_memberships)

    @dept_membership_count.expression
    def dept_membership_count(cls):
        return func.count(cls.dept_memberships)
    
    @hybrid_property
    def normalized_name(self):
        return self.normalize_name(self.name)

    @normalized_name.expression
    def normalized_name(cls):
        return func.replace(func.replace(func.lower(cls.name), '_', ''), ' ', '')

    @classmethod
    def normalize_name(cls, name):
        return name.lower().replace('_', '').replace(' ', '')

    @classproperty
    def _extra_apply_attrs(cls):
        return set(['dept_memberships_ids']).union(cls._extra_apply_attrs_restricted)

    @property
    def dept_memberships_ids(self):
        _, ids = self._get_relation_ids('dept_memberships')
        return [str(d.id) for d in self.dept_memberships] if ids is None else ids

    @dept_memberships_ids.setter
    def dept_memberships_ids(self, value):
        self._set_relation_ids('dept_memberships', DeptMembership, value)


class Department(MagModel):
    name = Column(String, unique=True)
    description = Column(String)
    solicits_volunteers = Column(Boolean, default=True)
    parent_id = Column(Uuid(as_uuid=False), ForeignKey('department.id'), nullable=True)
    max_consecutive_minutes = Column(Integer, default=0)
    from_email = Column(String)
    manages_panels = Column(Boolean, default=False)
    handles_cash = Column(Boolean, default=False)
    panels_desc = Column(String)

    jobs = relationship('Job', backref='department')
    job_templates = relationship('JobTemplate', backref='department')
    locations = relationship('EventLocation', backref='department')
    events = relationship('Event', backref='department')

    dept_checklist_items = relationship('DeptChecklistItem', backref='department')
    dept_roles = relationship('DeptRole', backref='department')
    dept_heads = relationship(
        'Attendee',
        backref=backref('headed_depts', order_by='Department.name'),
        primaryjoin='and_('
                    'Department.id == DeptMembership.department_id, '
                    'DeptMembership.is_dept_head == True)',
        secondary='dept_membership',
        order_by='Attendee.full_name',
        viewonly=True)
    checklist_admins = relationship(
        'Attendee',
        backref=backref('checklist_admin_depts', order_by='Department.name'),
        primaryjoin='and_('
                    'Department.id == DeptMembership.department_id, '
                    'DeptMembership.is_checklist_admin == True)',
        secondary='dept_membership',
        order_by='Attendee.full_name',
        viewonly=True)
    members_with_inherent_role = relationship(
        'Attendee',
        backref=backref('depts_with_inherent_role', order_by='Department.name'),
        primaryjoin='and_('
                    'Department.id == DeptMembership.department_id, '
                    'DeptMembership.has_inherent_role)',
        secondary='dept_membership',
        order_by='Attendee.full_name',
        viewonly=True)
    members_who_can_admin_checklist = relationship(
        'Attendee',
        backref=backref('can_admin_checklist_depts', order_by='Department.name'),
        primaryjoin='and_('
                    'Department.id == DeptMembership.department_id, '
                    'or_('
                    'DeptMembership.is_checklist_admin == True, '
                    'DeptMembership.is_dept_head == True))',
        secondary='dept_membership',
        order_by='Attendee.full_name',
        viewonly=True)
    pocs = relationship(
        'Attendee',
        backref=backref('poc_depts', order_by='Department.name'),
        primaryjoin='and_('
                    'Department.id == DeptMembership.department_id, '
                    'DeptMembership.is_poc == True)',
        secondary='dept_membership',
        order_by='Attendee.full_name',
        viewonly=True)
    members = relationship(
        'Attendee',
        backref=backref('assigned_depts', order_by='Department.name', overlaps="dept_memberships,attendee"),
        cascade='save-update,merge,refresh-expire,expunge',
        order_by='Attendee.full_name',
        overlaps="attendee,dept_memberships",
        secondary='dept_membership')
    memberships = relationship('DeptMembership', backref=backref('department', overlaps="assigned_depts,members"), overlaps="assigned_depts,members")
    membership_requests = relationship('DeptMembershipRequest', backref='department')
    explicitly_requesting_attendees = relationship(
        'Attendee',
        backref=backref('explicitly_requested_depts', order_by='Department.name', overlaps="attendee,dept_membership_requests,department,membership_requests"),
        cascade='save-update,merge,refresh-expire,expunge',
        secondary='dept_membership_request',
        order_by='Attendee.full_name',
        overlaps="membership_requests,department,attendee,dept_membership_requests")
    requesting_attendees = relationship(
        'Attendee',
        backref=backref('requested_depts', order_by='Department.name'),
        primaryjoin='or_('
                    'DeptMembershipRequest.department_id == Department.id, '
                    'DeptMembershipRequest.department_id == None)',
        secondary='dept_membership_request',
        order_by='Attendee.full_name',
        viewonly=True)
    unassigned_requesting_attendees = relationship(
        'Attendee',
        primaryjoin='and_(or_('
                    'DeptMembershipRequest.department_id == Department.id, '
                    'DeptMembershipRequest.department_id == None), '
                    'not_(exists().where(and_('
                    'DeptMembership.department_id == Department.id, '
                    'DeptMembership.attendee_id == DeptMembershipRequest.attendee_id))))',
        secondary='dept_membership_request',
        order_by='Attendee.full_name',
        viewonly=True)
    unassigned_explicitly_requesting_attendees = relationship(
        'Attendee',
        primaryjoin='and_('
                    'DeptMembershipRequest.department_id == Department.id, '
                    'not_(exists().where(and_('
                    'DeptMembership.department_id == Department.id, '
                    'DeptMembership.attendee_id == DeptMembershipRequest.attendee_id))))',
        secondary='dept_membership_request',
        order_by='Attendee.full_name',
        viewonly=True)
    parent = relationship(
        'Department',
        backref=backref('sub_depts', order_by='Department.name', cascade='all,delete-orphan'),
        cascade='save-update,merge,refresh-expire,expunge',
        remote_side='Department.id',
        single_parent=True)

    @hybrid_property
    def member_count(self):
        return len(self.memberships)

    @member_count.expression
    def member_count(cls):
        return func.count(cls.memberships)
    
    @property
    def members_with_roles(self):
        return [a for a in self.memberships if a.has_role]
    
    @property
    def members_with_shifts(self):
        return [a for a in self.members if a.weighted_hours_in(self) > 0]

    @property
    def member_emails(self):
        return [a.email for a in self.members if a.email and (a.has_badge or a.weighted_hours_in(self) > 0)]

    @property
    def everyone_with_shifts_emails(self):
        return [a.email for a in self.attendees_working_shifts]

    def member_emails_role(self, role):
        return [a.email for a in self.members if a.email and (a.has_badge or a.weighted_hours_in(self) > 0) and a.has_role(role)]

    @classmethod
    def to_id(cls, department):
        if not department:
            return None

        if isinstance(department, six.string_types):
            try:
                department = int(department)
            except ValueError:
                return department

        return department.id

    def checklist_item_for_slug(self, slug):
        for item in self.dept_checklist_items:
            if item.slug == slug:
                return item
        return None

    @hybrid_property
    def normalized_name(self):
        return self.normalize_name(self.name)

    @normalized_name.expression
    def normalized_name(cls):
        return func.replace(func.replace(func.lower(cls.name), '_', ''), ' ', '')

    @classmethod
    def normalize_name(cls, name):
        return name.lower().replace('_', '').replace(' ', '')
    
    @property
    def dept_roles_choices(self):
        return [(role.id, role.name) for role in self.dept_roles]

    @property
    def dept_roles_by_id(self):
        return groupify(self.dept_roles, 'id')

    @property
    def dept_roles_by_name(self):
        return groupify(self.dept_roles, 'name')
    
    @property
    def job_templates_choices(self):
        return [(template.id, template.template_name) for template in self.job_templates]
    
    @property
    def job_templates_by_id(self):
        return groupify(self.job_templates, 'id')

    @property
    def job_templates_by_name(self):
        return groupify(self.job_templates, 'template_name')


class Job(MagModel):
    _ONLY_MEMBERS = 0
    _ALL_VOLUNTEERS = 2
    _VISIBILITY_OPTS = [
        (_ONLY_MEMBERS, 'Members of this department'),
        (_ALL_VOLUNTEERS, 'All volunteers')]

    job_template_id = Column(Uuid(as_uuid=False), ForeignKey('job_template.id'), nullable=True)
    department_id = Column(Uuid(as_uuid=False), ForeignKey('department.id'))

    name = Column(String)
    description = Column(String)
    start_time = Column(DateTime(timezone=True))
    duration = Column(Integer)
    weight = Column(Float, default=1)
    slots = Column(Integer)
    extra15 = Column(Boolean, default=False)
    visibility = Column(Choice(_VISIBILITY_OPTS), default=_ONLY_MEMBERS)
    all_roles_required = Column(Boolean, default=True)

    required_roles = relationship(
        'DeptRole', backref='jobs', cascade='save-update,merge,refresh-expire,expunge', secondary='job_required_role')
    shifts = relationship('Shift', backref='job')

    __table_args__ = (
        Index('ix_job_department_id', department_id),
    )

    _repr_attr_names = ['name']

    @presave_adjustment
    def zero_slots(self):
        if not self.slots and not self.slots == 0:
            self.slots = 0

    def fill_gaps(self, session):
        old_start_time = self.orig_value_of('start_time')
        old_duration = self.orig_value_of('duration')
        if self.template and self.template.type == c.FILL_GAPS and (self.duration != old_duration or
                                                                    self.start_time != old_start_time):
            self.template.fill_gap(session, self.start_time_local, self)
            if old_start_time.date() != self.start_time.date():
                self.template.fill_gap(session, old_start_time.astimezone(c.EVENT_TIMEZONE))

    @classproperty
    def _extra_apply_attrs(cls):
        return set(['required_roles_ids']).union(cls._extra_apply_attrs_restricted)

    @hybrid_property
    def department_name(self):
        return self.department.name

    @department_name.expression
    def department_name(cls):
        return select(Department.name).where(Department.id == cls.department_id).label('department_name')

    @hybrid_property
    def max_consecutive_minutes(self):
        return self.department.max_consecutive_minutes

    @max_consecutive_minutes.expression
    def max_consecutive_minutes(cls):
        return select(Department.max_consecutive_minutes) \
            .where(Department.id == cls.department_id).label('max_consecutive_minutes')

    @hybrid_property
    def restricted(self):
        return bool(self.required_roles)

    @restricted.expression
    def restricted(cls):
        return exists([job_required_role.c.dept_role_id]) \
            .where(job_required_role.c.job_id == cls.id).label('restricted')

    @property
    def required_roles_labels(self):
        return readable_join([r.name for r in self.required_roles])

    @property
    def required_roles_ids(self):
        _, ids = self._get_relation_ids('required_roles')
        return [str(d.id) for d in self.required_roles] if ids is None else ids

    @required_roles_ids.setter
    def required_roles_ids(self, value):
        self._set_relation_ids('required_roles', DeptRole, value)

    @property
    def minutes(self):
        minutes = set()
        for i in range(int(self.duration)):
            minutes.add(self.start_time + timedelta(minutes=i))
        return minutes

    @hybrid_property
    def end_time(self):
        return self.start_time + timedelta(minutes=self.duration)
    
    @end_time.expression
    def end_time(cls):
        return cls.start_time + (cls.duration * text("interval '1 minute'"))

    def working_limit_ok(self, attendee):
        """
        Prevent signing up for too many shifts in a row. `minutes_worked` is the
        number of minutes that the attendee is working immediately before plus
        immediately after this job, plus this job's minutes. `working_minutes_limit`
        is the *min* of Department.max_consecutive_minutes for all the jobs we've
        seen (including self). This means that if dept A has a limit of 3 minutes,
        and dept B has a limit of 2 minutes, (for one-hour shifts), if we try to
        sign up for the shift order of [A, A, B], B's limits will kick in and
        block the signup.
        """

        attendee_minute_map = attendee.shift_minute_map
        minutes_worked = self.duration
        working_minutes_limit = self.max_consecutive_minutes
        if working_minutes_limit == 0:
            working_minutes_limit = 60000  # just default to something large

        # count the number of filled minutes before this shift
        current_shift_minute = self.start_time - timedelta(minutes=1)
        while current_shift_minute in attendee_minute_map:
            minutes_worked += 1
            this_job_minute_limit = attendee_minute_map[current_shift_minute].max_consecutive_minutes
            if this_job_minute_limit > 0:
                working_minutes_limit = min(working_minutes_limit, this_job_minute_limit)
            current_shift_minute = current_shift_minute - timedelta(minutes=1)

        # count the number of filled minutes after this shift
        current_shift_minute = self.start_time + timedelta(minutes=self.duration)
        while current_shift_minute in attendee_minute_map:
            minutes_worked += 1
            this_job_minute_limit = attendee_minute_map[current_shift_minute].max_consecutive_minutes
            if this_job_minute_limit > 0:
                working_minutes_limit = min(working_minutes_limit, this_job_minute_limit)
            current_shift_minute = current_shift_minute + timedelta(minutes=1)

        return minutes_worked <= working_minutes_limit

    def no_overlap(self, attendee):
        before = self.start_time - timedelta(minutes=1)
        after = self.start_time + timedelta(minutes=self.duration)
        return not self.minutes.intersection(attendee.shift_minutes) and (
            before not in attendee.shift_minute_map
            or not attendee.shift_minute_map[before].extra15
            or self.department_id == attendee.shift_minute_map[before].department_id
        ) and (
            after not in attendee.shift_minute_map
            or not self.extra15
            or self.department_id == attendee.shift_minute_map[after].department_id
        )

    @hybrid_property
    def signups_enabled(self):
        return self.slots != 0

    @hybrid_property
    def slots_taken(self):
        return len(self.shifts)

    @slots_taken.expression
    def slots_taken(cls):
        return select(func.count(Shift.id)).where(Shift.job_id == cls.id).label('slots_taken')

    @hybrid_property
    def is_public(self):
        return self.visibility > Job._ONLY_MEMBERS

    @is_public.expression
    def is_public(cls):
        return cls.visibility > Job._ONLY_MEMBERS

    @hybrid_property
    def is_unfilled(self):
        return self.slots_taken < self.slots

    @is_unfilled.expression
    def is_unfilled(cls):
        return cls.slots_taken < cls.slots

    @property
    def slots_untaken(self):
        return max(0, self.slots - self.slots_taken)

    @property
    def is_setup(self):
        return self.start_time < c.EPOCH

    @property
    def is_teardown(self):
        return self.end_time >= c.ESCHATON

    @property
    def hotel_night(self):
        # Determines what hotel night this job qualifies a staffer for
        start_time = self.start_time_local
        start_day_before = start_time - timedelta(days=1)
        end_day_before = self.end_time_local - timedelta(days=1)
        hotel_night = getattr(c, start_time.strftime('%A').upper())

        if start_time.date() < c.EPOCH.date():
            return hotel_night if hotel_night in c.SETUP_NIGHTS else 0
        elif self.end_time_local.date() > c.ESCHATON.date():
            return getattr(c, end_day_before.strftime('%A').upper())
        else:
            if start_time.date() == c.EPOCH.date() and start_time.hour < 9:
                return getattr(c, start_day_before.strftime('%A').upper())
            elif start_time.date() == c.ESCHATON.date():
                return hotel_night if self.end_time_local.hour >= 5 else getattr(c, end_day_before.strftime('%A').upper())
            return hotel_night

    @property
    def real_duration(self):
        return self.duration + (15 if self.extra15 else 0)

    @property
    def weighted_hours(self):
        return self.weight * (self.real_duration / 60)

    @property
    def total_hours(self):
        return self.weighted_hours * self.slots

    def _potential_volunteers(self, staffing_only=False, order_by=Attendee.full_name):
        """
        Return a list of attendees who:

            1. Are assigned to this job's department.
            2. Are allowed to work this job (job has no required roles
               or the attendee's department membership fulfills all the
               required roles).

        Args:
            staffing_only: Restrict result to attendees where staffing==True.
            order_by: Order by another Attendee attribute.
        """
        query = self.session.query(Attendee)

        if staffing_only:
            query = query.filter(Attendee.staffing == True)  # noqa: E712

        if self.required_roles:
            query = query.join(Attendee.dept_roles, aliased=True).filter(
                and_(*[DeptRole.id == r.id for r in self.required_roles]))
        else:
            query = query.join(Attendee.dept_memberships, aliased=True).filter(
                DeptMembership.department_id == self.department_id)

        return query.order_by(order_by).all()

    @property
    def capable_volunteers_opts(self):
        """
        Format output for use with the {{ options() }} template decorator .
        """
        return [(a.id, a.full_name) for a in self.capable_volunteers]

    @property
    def capable_volunteers(self):
        """
        Return a list of volunteers who could sign up for this job.

        Important: Just because a volunteer is capable of working
        this job doesn't mean they are actually available to work it.
        They may have other shift hours during that time period.
        """
        return self._potential_volunteers(staffing_only=True)

    @cached_property
    def available_volunteers(self):
        """
        Returns a list of volunteers who are allowed to sign up for
        this Job and have the free time to work it.
        """
        return [s for s in self._potential_volunteers(order_by=Attendee.last_first) if self.no_overlap(s)
                and self.working_limit_ok(s)]


class JobTemplate(MagModel):
    department_id = Column(Uuid(as_uuid=False), ForeignKey('department.id'))

    template_name = Column(String)
    type = Column(Choice(c.JOB_TEMPLATE_TYPE_OPTS), default=c.FILL_GAPS)
    name = Column(String)
    description = Column(String)
    duration = Column(Integer)
    weight = Column(Float, default=1)
    extra15 = Column(Boolean, default=False)
    visibility = Column(Choice(Job._VISIBILITY_OPTS), default=Job._ONLY_MEMBERS)
    all_roles_required = Column(Boolean, default=True)

    min_slots = Column(Integer)  # Future improvement: a bulk-edit for slots in jobs by time of day
    days = Column(MultiChoice(c.JOB_DAY_OPTS))
    open_time = Column(Time, nullable=True)
    close_time = Column(Time, nullable=True)
    interval = Column(Integer, nullable=True)

    required_roles = relationship(
        'DeptRole', backref='job_templates', cascade='save-update,merge,refresh-expire,expunge', secondary='job_template_required_role')
    jobs = relationship('Job', backref='template', cascade='save-update,merge,refresh-expire,expunge')

    @presave_adjustment
    def zero_slots(self):
        if not self.min_slots and not self.min_slots == 0:
            self.min_slots = 0

    @property
    def needs_refresh(self):
        if self.type == c.CUSTOM:
            return False
        elif self.type != self.orig_value_of('type'):
            return True

        if self.type == c.INTERVAL:
            return self.interval != self.orig_value_of('interval')
        elif self.type == c.FILL_GAPS:
            return self.duration != self.orig_value_of('duration')
    
    @property
    def required_roles_ids(self):
        _, ids = self._get_relation_ids('required_roles')
        return [str(d.id) for d in self.required_roles] if ids is None else ids

    @required_roles_ids.setter
    def required_roles_ids(self, value):
        self._set_relation_ids('required_roles', DeptRole, value)

    def create_jobs(self, session, days_ints=None, reset=True):
        if reset:
            for job in self.jobs:
                session.delete(job)
        
        days_ints = days_ints or self.days_ints

        for day_int in days_ints:
            first_shift = c.EVENT_TIMEZONE.localize(datetime.strptime(f"{day_int} {self.open_time}", '%Y%m%d %H:%M:%S'))
            self.fill_working_hours(session, first_shift, day_int, skip_first_shift=False)

        session.commit()

    def fill_working_hours(self, session, shift_start, day_int, skip_first_shift=True):
        cutoff_time = self.real_cutoff_time(day_int)
        interval_delta = timedelta(minutes=(self.duration if self.type == c.FILL_GAPS else self.interval))
        next_shift_start = (shift_start + interval_delta) if skip_first_shift else shift_start

        while next_shift_start < cutoff_time:
            if self.type == c.FILL_GAPS and (next_shift_start + interval_delta) > cutoff_time:
                duration = (cutoff_time - next_shift_start).seconds // 60
            else:
                duration = self.duration

            next_job = Job(department_id=self.department_id, job_template_id=self.id,
                           name=self.name, description=self.description,
                           start_time=next_shift_start, duration=duration,
                           weight=self.weight, slots=self.min_slots,
                           extra15=self.extra15, visibility=self.visibility,
                           all_roles_required=self.all_roles_required)
            session.add(next_job)
            next_shift_start += interval_delta

    def update_jobs(self, session):
        """
        Updates this template's existing jobs based on changes made to the template.
        Order of operations:
            1. Check for differences in days: if different, set aside jobs on removed days
            so we don't process them in the next steps. Added days are saved for the end.
            2. Update all the basic attributes that don't require extra logic. Required roles and min slots need
            some simple custom logic, but otherwise they are applied to jobs the same as the others.
            3. If the open or close time has changed, build a list of jobs by day for processing.
            We shift the start time of jobs while building this list if the open time has changed.
            4. Ship each list to update_last_jobs so that it can delete extra jobs, adjust the last job's duration
            (if the template is a "Fill Gaps" type), and add new jobs until the cutoff time is hit.
            5. Add shifts for any added days from step 1 -- we save this till the end to avoid extra processing.
        """

        from uber.utils import date_trunc_day
        from collections import defaultdict

        update_attrs = ['name', 'description', 'duration', 'weight', 'extra15',
                        'min_slots', 'visibility', 'all_roles_required']

        changes = {}
        add_days = None
        deleted_jobs = []
        jobs_by_day = defaultdict(list)

        # Storing these now prevents extra hits to the DB
        old_open_time = self.orig_value_of('open_time')
        old_close_time = self.orig_value_of('close_time')
        
        old_days_ints = set([int(i) for i in str(self.orig_value_of('days')).split(',') if i])

        new_days_ints = set(self.days_ints)

        if old_days_ints != new_days_ints:
            delete_days = old_days_ints - new_days_ints
            add_days = new_days_ints - old_days_ints

            if delete_days:
                jobs_by_date = session.query(
                    date_trunc_day(Job.start_time), Job
                    ).join(Job.template).filter(Job.job_template_id == self.id)
                for dt, job_to_delete in jobs_by_date:
                    if int(dt.strftime('%Y%m%d')) in delete_days:
                        deleted_jobs.append(job_to_delete)
                        session.delete(job_to_delete)
        
        jobs_to_process = [j for j in self.jobs if j.id not in deleted_jobs]

        for attr in update_attrs:
            if self.orig_value_of(attr) != getattr(self, attr):
                changes[attr] = getattr(self, attr)
        
        old_required_roles_ids = [role.id for role in self.required_roles]
        if old_required_roles_ids != self.required_roles_ids:
            changes['required_roles_ids'] = self.required_roles_ids

        for job in jobs_to_process:
            job_updated = False
            for attr_name, new_val in changes.items():
                if attr_name == 'min_slots':
                    if job.slots and job.slots < new_val:
                        job.slots = new_val
                        job_updated = True
                else:
                    setattr(job, attr_name, new_val)
                    job_updated = True
            if job_updated:
                session.add(job)

        if self.type != c.CUSTOM and (old_open_time != self.open_time or old_close_time != self.close_time):
            old_open_minutes = (old_open_time.hour * 60) + old_open_time.minute
            new_open_minutes = (self.open_time.hour * 60) + self.open_time.minute
            start_time_delta = timedelta(minutes=abs(new_open_minutes - old_open_minutes))

            for job in jobs_to_process:
                jobs_by_day[job.start_time_local.strftime('%Y%m%d')].append(job)
                if self.open_time > old_open_time:
                    job.start_time += start_time_delta
                elif self.open_time < old_open_time:
                    job.start_time -= start_time_delta

            for day, jobs in jobs_by_day.items():
                self.update_last_jobs(session, day, jobs)

        if add_days:
            self.create_jobs(session, add_days, reset=False)

    def update_last_jobs(self, session, day_int, jobs):
        cutoff_time = self.real_cutoff_time(day_int)
        jobs = sorted(jobs, key=lambda x: x.start_time, reverse=True)

        for job in jobs:
            if job.start_time >= cutoff_time:
                session.delete(job)
            else:
                last_job = job
                break

        if self.type == c.FILL_GAPS:
            last_job_time = last_job.start_time + timedelta(minutes=last_job.duration)
        elif self.type == c.INTERVAL:
            last_job_time = last_job.start_time

        if last_job_time < cutoff_time and self.type == c.FILL_GAPS and last_job.duration != self.duration:
            last_job.duration = min(self.duration, (cutoff_time - last_job.start_time).seconds // 60)
            last_job_time = last_job.start_time + timedelta(minutes=self.duration)
            session.add(last_job)

        if last_job_time < cutoff_time:
            self.fill_working_hours(session, last_job.start_time, day_int)
        elif last_job_time > cutoff_time and self.type == c.FILL_GAPS:
            last_job.duration = (cutoff_time - last_job.start_time).seconds // 60
            session.add(last_job)

    def fill_gap(self, session, start_time, job=None):
        from uber.utils import date_trunc_day
        prev_job_end = None
        day_int = start_time.strftime('%Y%m%d')
        cutoff_time = self.real_cutoff_time(day_int)
        job_query = session.query(Job).filter(Job.job_template_id == self.id,
                                              date_trunc_day(Job.start_time) == start_time.date())
        if job:
            other_jobs = job_query.filter(Job.id != job.id).all()
            jobs = sorted([job] + other_jobs, key=lambda x: x.start_time)
        else:
            jobs = job_query.order_by(Job.start_time).all()

        for next_job in jobs:
            if prev_job_end:
                gap = 0
                if prev_job_end > next_job.start_time:
                    gap = (prev_job_end - next_job.start_time).seconds // 60
                elif prev_job_end < next_job.start_time:
                    gap = (next_job.start_time - prev_job_end).seconds // 60 * -1
                if gap != 0:
                    next_job.start_time += timedelta(minutes=gap)
                    next_job.duration = min(self.duration, (cutoff_time - next_job.start_time).seconds // 60)
                    session.add(next_job)
            prev_job_end = next_job.start_time + timedelta(minutes=next_job.duration)
        self.fill_working_hours(session, jobs[-1].start_time, day_int)
    
    def real_cutoff_time(self, day_int):
        cutoff_time = c.EVENT_TIMEZONE.localize(datetime.strptime(f"{day_int} {self.close_time}", '%Y%m%d %H:%M:%S'))
        if self.close_time == time(hour=23, minute=59):
            cutoff_time += timedelta(minutes=1)
        return cutoff_time


class Shift(MagModel):
    job_id = Column(Uuid(as_uuid=False), ForeignKey('job.id', ondelete='cascade'))
    attendee_id = Column(Uuid(as_uuid=False), ForeignKey('attendee.id', ondelete='cascade'))
    worked = Column(Choice(c.WORKED_STATUS_OPTS), default=c.SHIFT_UNMARKED)
    rating = Column(Choice(c.RATING_OPTS), default=c.UNRATED)
    comment = Column(String)

    __table_args__ = (
        Index('ix_shift_job_id', job_id),
        Index('ix_shift_attendee_id', attendee_id),
    )

    @property
    def name(self):
        return "{}'s {!r} shift".format(self.attendee.full_name, self.job.name)
