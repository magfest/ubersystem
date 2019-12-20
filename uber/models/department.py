import uuid
from datetime import timedelta

import six
from pockets import cached_property, classproperty, groupify, readable_join
from residue import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import backref
from sqlalchemy.schema import ForeignKey, Table, UniqueConstraint, Index
from sqlalchemy.types import Boolean, Float, Integer

from uber.config import c
from uber.models import MagModel
from uber.models.attendee import Attendee
from uber.models.types import default_relationship as relationship, Choice, DefaultColumn as Column


__all__ = [
    'dept_membership_dept_role', 'job_required_role', 'Department',
    'DeptChecklistItem', 'DeptMembership', 'DeptMembershipRequest',
    'DeptRole', 'Job', 'Shift']


# Many to many association table to represent the DeptRoles fulfilled
# by a DeptMembership
dept_membership_dept_role = Table(
    'dept_membership_dept_role',
    MagModel.metadata,
    Column('dept_membership_id', UUID, ForeignKey('dept_membership.id')),
    Column('dept_role_id', UUID, ForeignKey('dept_role.id')),
    UniqueConstraint('dept_membership_id', 'dept_role_id'),
    Index('ix_dept_membership_dept_role_dept_role_id', 'dept_role_id'),
    Index('ix_dept_membership_dept_role_dept_membership_id', 'dept_membership_id'),
)


# Many to many association table to represent the DeptRoles required
# to fulfill a Job
job_required_role = Table(
    'job_required_role',
    MagModel.metadata,
    Column('dept_role_id', UUID, ForeignKey('dept_role.id')),
    Column('job_id', UUID, ForeignKey('job.id')),
    UniqueConstraint('dept_role_id', 'job_id'),
    Index('ix_job_required_role_dept_role_id', 'dept_role_id'),
    Index('ix_job_required_role_job_id', 'job_id'),
)


class DeptChecklistItem(MagModel):
    department_id = Column(UUID, ForeignKey('department.id'))
    attendee_id = Column(UUID, ForeignKey('attendee.id'))
    slug = Column(UnicodeText)
    comments = Column(UnicodeText, default='')

    __table_args__ = (
        UniqueConstraint('department_id', 'attendee_id', 'slug'),
    )


class DeptMembership(MagModel):
    is_dept_head = Column(Boolean, default=False)
    is_poc = Column(Boolean, default=False)
    is_checklist_admin = Column(Boolean, default=False)
    attendee_id = Column(UUID, ForeignKey('attendee.id'))
    department_id = Column(UUID, ForeignKey('department.id'))

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


class DeptMembershipRequest(MagModel):
    attendee_id = Column(UUID, ForeignKey('attendee.id'))

    # A NULL value for the department_id indicates the attendee is willing
    # to volunteer for any department (they checked "Anything" for
    # "Where do you want to help?").
    department_id = Column(UUID, ForeignKey('department.id'), nullable=True)

    __mapper_args__ = {'confirm_deleted_rows': False}
    __table_args__ = (
        UniqueConstraint('attendee_id', 'department_id'),
        Index('ix_dept_membership_request_attendee_id', 'attendee_id'),
        Index('ix_dept_membership_request_department_id', 'department_id'),
    )


class DeptRole(MagModel):
    name = Column(UnicodeText)
    description = Column(UnicodeText)
    department_id = Column(UUID, ForeignKey('department.id'))

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
    name = Column(UnicodeText, unique=True)
    description = Column(UnicodeText)
    solicits_volunteers = Column(Boolean, default=True)
    is_shiftless = Column(Boolean, default=False)
    parent_id = Column(UUID, ForeignKey('department.id'), nullable=True)
    is_setup_approval_exempt = Column(Boolean, default=False)
    is_teardown_approval_exempt = Column(Boolean, default=False)
    max_consecutive_hours = Column(Integer, default=0)

    jobs = relationship('Job', backref='department')

    dept_checklist_items = relationship('DeptChecklistItem', backref='department')
    dept_roles = relationship('DeptRole', backref='department')
    dept_heads = relationship(
        'Attendee',
        backref=backref('headed_depts', order_by='Department.name'),
        cascade='save-update,merge,refresh-expire,expunge',
        primaryjoin='and_('
                    'Department.id == DeptMembership.department_id, '
                    'DeptMembership.is_dept_head == True)',
        secondary='dept_membership',
        order_by='Attendee.full_name',
        viewonly=True)
    checklist_admins = relationship(
        'Attendee',
        backref=backref('checklist_admin_depts', order_by='Department.name'),
        cascade='save-update,merge,refresh-expire,expunge',
        primaryjoin='and_('
                    'Department.id == DeptMembership.department_id, '
                    'DeptMembership.is_checklist_admin == True)',
        secondary='dept_membership',
        order_by='Attendee.full_name',
        viewonly=True)
    members_with_inherent_role = relationship(
        'Attendee',
        backref=backref('depts_with_inherent_role', order_by='Department.name'),
        cascade='save-update,merge,refresh-expire,expunge',
        primaryjoin='and_('
                    'Department.id == DeptMembership.department_id, '
                    'DeptMembership.has_inherent_role)',
        secondary='dept_membership',
        order_by='Attendee.full_name',
        viewonly=True)
    members_who_can_admin_checklist = relationship(
        'Attendee',
        backref=backref('can_admin_checklist_depts', order_by='Department.name'),
        cascade='save-update,merge,refresh-expire,expunge',
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
        cascade='save-update,merge,refresh-expire,expunge',
        primaryjoin='and_('
                    'Department.id == DeptMembership.department_id, '
                    'DeptMembership.is_poc == True)',
        secondary='dept_membership',
        order_by='Attendee.full_name',
        viewonly=True)
    members = relationship(
        'Attendee',
        backref=backref('assigned_depts', order_by='Department.name'),
        cascade='save-update,merge,refresh-expire,expunge',
        order_by='Attendee.full_name',
        secondary='dept_membership')
    memberships = relationship('DeptMembership', backref='department')
    membership_requests = relationship('DeptMembershipRequest', backref='department')
    explicitly_requesting_attendees = relationship(
        'Attendee',
        backref=backref('explicitly_requested_depts', order_by='Department.name'),
        cascade='save-update,merge,refresh-expire,expunge',
        secondary='dept_membership_request',
        order_by='Attendee.full_name')
    requesting_attendees = relationship(
        'Attendee',
        backref=backref('requested_depts', order_by='Department.name'),
        cascade='save-update,merge,refresh-expire,expunge',
        primaryjoin='or_('
                    'DeptMembershipRequest.department_id == Department.id, '
                    'DeptMembershipRequest.department_id == None)',
        secondary='dept_membership_request',
        order_by='Attendee.full_name',
        viewonly=True)
    unassigned_requesting_attendees = relationship(
        'Attendee',
        cascade='save-update,merge,refresh-expire,expunge',
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
        cascade='save-update,merge,refresh-expire,expunge',
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
    def member_emails(self):
        return [a.email for a in self.members if a.email]

    @property
    def members_with_shifts_emails(self):
        return [a.email for a in self.members if a.weighted_hours_in(self) > 0]

    @classmethod
    def to_id(cls, department):
        if not department:
            return None

        if isinstance(department, six.string_types):
            try:
                department = int(department)
            except ValueError:
                return department

        if isinstance(department, int):
            # This is the same algorithm used by the migration script to
            # convert c.JOB_LOCATIONS into department ids in the database.
            prefix = '{:07x}'.format(department)
            return prefix + str(uuid.uuid5(cls.NAMESPACE, str(department)))[7:]

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
    def dept_roles_by_id(self):
        return groupify(self.dept_roles, 'id')

    @property
    def dept_roles_by_name(self):
        return groupify(self.dept_roles, 'name')


class Job(MagModel):
    _ONLY_MEMBERS = 0
    _ALL_VOLUNTEERS = 2
    _VISIBILITY_OPTS = [
        (_ONLY_MEMBERS, 'Members of this department'),
        (_ALL_VOLUNTEERS, 'All volunteers')]

    type = Column(Choice(c.JOB_TYPE_OPTS), default=c.REGULAR)
    name = Column(UnicodeText)
    description = Column(UnicodeText)
    start_time = Column(UTCDateTime)
    duration = Column(Integer)
    weight = Column(Float, default=1)
    slots = Column(Integer)
    extra15 = Column(Boolean, default=False)
    department_id = Column(UUID, ForeignKey('department.id'))
    visibility = Column(Choice(_VISIBILITY_OPTS), default=_ONLY_MEMBERS)

    required_roles = relationship(
        'DeptRole', backref='jobs', cascade='save-update,merge,refresh-expire,expunge', secondary='job_required_role')
    shifts = relationship('Shift', backref='job')

    __table_args__ = (
        Index('ix_job_department_id', department_id),
    )

    _repr_attr_names = ['name']

    @classproperty
    def _extra_apply_attrs(cls):
        return set(['required_roles_ids']).union(cls._extra_apply_attrs_restricted)

    @hybrid_property
    def department_name(self):
        return self.department.name

    @department_name.expression
    def department_name(cls):
        return select([Department.name]).where(Department.id == cls.department_id).label('department_name')

    @hybrid_property
    def max_consecutive_hours(self):
        return self.department.max_consecutive_hours

    @max_consecutive_hours.expression
    def max_consecutive_hours(cls):
        return select([Department.max_consecutive_hours]) \
            .where(Department.id == cls.department_id).label('max_consecutive_hours')

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
    def hours(self):
        hours = set()
        for i in range(self.duration):
            hours.add(self.start_time + timedelta(hours=i))
        return hours

    @property
    def end_time(self):
        return self.start_time + timedelta(hours=self.duration)

    def working_limit_ok(self, attendee):
        """
        Prevent signing up for too many shifts in a row. `hours_worked` is the
        number of hours that the attendee is working immediately before plus
        immediately after this job, plus this job's hours. `working_hour_limit`
        is the *min* of Department.max_consecutive_hours for all the jobs we've
        seen (including self). This means that if dept A has a limit of 3 hours,
        and dept B has a limit of 2 hours, (for one-hour shifts), if we try to
        sign up for the shift order of [A, A, B], B's limits will kick in and
        block the signup.
        """

        attendee_hour_map = attendee.hour_map
        hours_worked = self.duration
        working_hour_limit = self.max_consecutive_hours
        if working_hour_limit == 0:
            working_hour_limit = 1000  # just default to something large

        # count the number of filled hours before this shift
        current_shift_hour = self.start_time - timedelta(hours=1)
        while current_shift_hour in attendee_hour_map:
            hours_worked += 1
            this_job_hour_limit = attendee_hour_map[current_shift_hour].max_consecutive_hours
            if this_job_hour_limit > 0:
                working_hour_limit = min(working_hour_limit, this_job_hour_limit)
            current_shift_hour = current_shift_hour - timedelta(hours=1)

        # count the number of filled hours after this shift
        current_shift_hour = self.start_time + timedelta(hours=self.duration)
        while current_shift_hour in attendee_hour_map:
            hours_worked += 1
            this_job_hour_limit = attendee_hour_map[current_shift_hour].max_consecutive_hours
            if this_job_hour_limit > 0:
                working_hour_limit = min(working_hour_limit, this_job_hour_limit)
            current_shift_hour = current_shift_hour + timedelta(hours=1)

        return hours_worked <= working_hour_limit

    def no_overlap(self, attendee):
        before = self.start_time - timedelta(hours=1)
        after = self.start_time + timedelta(hours=self.duration)
        return not self.hours.intersection(attendee.hours) and (
            before not in attendee.hour_map
            or not attendee.hour_map[before].extra15
            or self.department_id == attendee.hour_map[before].department_id
        ) and (
            after not in attendee.hour_map
            or not self.extra15
            or self.department_id == attendee.hour_map[after].department_id
        ) and self.working_limit_ok(attendee)

    @hybrid_property
    def slots_taken(self):
        return len(self.shifts)

    @slots_taken.expression
    def slots_taken(cls):
        return select([func.count(Shift.id)]).where(Shift.job_id == cls.id).label('slots_taken')

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
        return self.start_time >= c.ESCHATON

    @property
    def real_duration(self):
        return self.duration + (0.25 if self.extra15 else 0)

    @property
    def weighted_hours(self):
        return self.weight * self.real_duration

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
        return [s for s in self._potential_volunteers(order_by=Attendee.last_first) if self.no_overlap(s)]


class Shift(MagModel):
    job_id = Column(UUID, ForeignKey('job.id', ondelete='cascade'))
    attendee_id = Column(UUID, ForeignKey('attendee.id', ondelete='cascade'))
    worked = Column(Choice(c.WORKED_STATUS_OPTS), default=c.SHIFT_UNMARKED)
    rating = Column(Choice(c.RATING_OPTS), default=c.UNRATED)
    comment = Column(UnicodeText)

    __table_args__ = (
        Index('ix_shift_job_id', job_id),
        Index('ix_shift_attendee_id', attendee_id),
    )

    @property
    def name(self):
        return "{}'s {!r} shift".format(self.attendee.full_name, self.job.name)
