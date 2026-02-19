from datetime import datetime, timedelta

import cherrypy
from pytz import UTC
from sqlalchemy import Sequence, Uuid, String, DateTime
from sqlalchemy.dialects.postgresql.json import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.schema import ForeignKey, Table, UniqueConstraint, Index
from sqlalchemy.types import Boolean, Date, Integer
from sqlmodel import Field, Relationship
from typing import ClassVar

from uber.config import c
from uber.decorators import presave_adjustment, classproperty
from uber.models.types import default_relationship as relationship, utcnow, DefaultColumn as Column
from uber.models import MagModel
from uber.utils import listify


__all__ = ['AccessGroup', 'AdminAccount', 'EscalationTicket', 'PasswordReset', 'WatchList', 'WorkstationAssignment']


# Many to many association table to tie Access Groups with Admin Accounts
admin_access_group = Table(
    'admin_access_group',
    MagModel.metadata,
    Column('admin_account_id', Uuid(as_uuid=False), ForeignKey('admin_account.id')),
    Column('access_group_id', Uuid(as_uuid=False), ForeignKey('access_group.id')),
    UniqueConstraint('admin_account_id', 'access_group_id'),
    Index('ix_admin_access_group_admin_account_id', 'admin_account_id'),
    Index('ix_admin_access_group_access_group_id', 'access_group_id'),
)


class AdminAccount(MagModel, table=True):
    """
    Attendee: joined
    AccessGroup: selectin
    ApiToken: select
    PasswordReset: select
    """

    attendee_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='attendee.id', ondelete='CASCADE', unique=True)
    attendee: 'Attendee' = Relationship(
        back_populates="admin_account", sa_relationship_kwargs={'lazy': 'joined', 'cascade': 'save-update,merge,refresh-expire,expunge'})

    hashed: str = Column(String, private=True)

    access_groups: list['AccessGroup'] = Relationship(
        back_populates='admin_accounts',
        sa_relationship_kwargs={'lazy': 'selectin', 'cascade': 'save-update,merge,refresh-expire,expunge', 'secondary': 'admin_access_group'})
    password_reset: "PasswordReset" = Relationship(
        back_populates='admin_account', sa_relationship_kwargs={'lazy': 'select', 'passive_deletes': True})
    api_tokens: list['ApiToken'] = Relationship(back_populates="admin_account", sa_relationship_kwargs={'passive_deletes': True})
    active_api_tokens: list['ApiToken'] = Relationship(sa_relationship=relationship(
        'ApiToken', lazy='select',
        primaryjoin='and_('
                    'AdminAccount.id == ApiToken.admin_account_id, '
                    'ApiToken.revoked_time == None)',
        overlaps="admin_account,api_tokens"))
    api_jobs: list['ApiJob'] = Relationship(
        back_populates="admin_account", sa_relationship_kwargs={'cascade': 'save-update,merge,refresh-expire,expunge'})
    
    attractions: list['Attraction'] = Relationship(
        back_populates="owner", sa_relationship_kwargs={'cascade': 'save-update,merge,refresh-expire,expunge', 'order_by': 'Attraction.name'})
    judge: 'IndieJudge' = Relationship(back_populates="admin_account", sa_relationship_kwargs={'cascade': 'save-update,merge,refresh-expire,expunge'})
    print_requests: list['PrintJob'] = Relationship(
        back_populates="admin_account", sa_relationship_kwargs={'cascade': 'save-update,merge,refresh-expire,expunge'})

    def __repr__(self):
        return f"<Admin full_name='{self.attendee.full_name}'>"

    @staticmethod
    def admin_name():
        try:
            from uber.models import Session
            with Session() as session:
                return session.admin_attendee().full_name
        except Exception:
            return None
        
    @staticmethod
    def admin_or_volunteer_name():
        try:
            from uber.models import Session
            with Session() as session:
                admin = session.admin_attendee()
                volunteer = session.kiosk_operator_attendee()
                if volunteer and not admin:
                    return volunteer.full_name + " (Volunteer)"
                elif not admin:
                    return session.current_supervisor_admin().attendee.full_name
                else:
                    return admin.full_name
        except Exception:
            return None
        
    @staticmethod
    def supervisor_name():
        try:
            from uber.models import Session
            with Session() as session:
                return session.current_supervisor_admin().attendee.full_name
        except Exception:
            return None

    @staticmethod
    def admin_email():
        try:
            from uber.models import Session
            with Session() as session:
                return session.admin_attendee().email
        except Exception:
            return None

    @staticmethod
    def get_access_set(id=None, include_read_only=False):
        try:
            from uber.models import Session
            with Session() as session:
                id = id or cherrypy.session.get('account_id')
                account = session.admin_account(id)
                if include_read_only:
                    return account.read_or_write_access_set
                return account.write_access_set
        except Exception:
            return set()

    @classproperty
    def _extra_apply_attrs(cls):
        return set(['access_groups_ids'])

    @property
    def write_access_set(self):
        access_list = [list(group.access) for group in self.valid_access_groups]
        return set([item for sublist in access_list for item in sublist])

    @property
    def read_access_set(self):
        access_list = [list(group.read_only_access) for group in self.valid_access_groups]
        return set([item for sublist in access_list for item in sublist])

    @property
    def read_or_write_access_set(self):
        return self.read_access_set.union(self.write_access_set)

    @property
    def valid_access_groups(self):
        return [group for group in self.access_groups if group.is_valid]

    @property
    def access_groups_labels(self):
        return [d.name for d in self.access_groups]

    @property
    def access_groups_ids(self):
        _, ids = self._get_relation_ids('access_groups')
        return [str(a.id) for a in self.access_groups] if ids is None else ids

    @access_groups_ids.setter
    def access_groups_ids(self, value):
        values = set(s for s in listify(value) if s)
        for group in list(self.access_groups):
            if group.id not in values:
                # Manually remove the group to ensure the associated
                # rows in the admin_access_group table are deleted.
                self.access_groups.remove(group)
        self._set_relation_ids('access_groups', AccessGroup, list(values))

    @property
    def allowed_access_opts(self):
        return self.session.query(AccessGroup).all()

    @property
    def allowed_api_access_opts(self):
        no_access_set = self.invalid_api_accesses()
        return [(access, label) for access, label in c.API_ACCESS_OPTS if access not in no_access_set]

    @property
    def viewable_guest_group_types(self):
        if 'guest_admin' in self.read_or_write_access_set:
            return [opt for opt in c.GROUP_TYPE_VARS if opt.lower() + "_admin"
                    in self.read_or_write_access_set or opt.lower() + "_admin" not in c.ADMIN_PAGES]
        return [opt for opt in c.GROUP_TYPE_VARS if opt.lower() + "_admin" in self.read_or_write_access_set]

    @property
    def is_super_admin(self):
        return 'devtools' in self.write_access_set

    @property
    def is_mivs_judge_or_admin(self, id=None):
        try:
            from uber.models import Session
            with Session() as session:
                id = id or cherrypy.session.get('account_id')
                admin_account = session.admin_account(id)
                return admin_account.judge or 'showcase_judging' in admin_account.read_or_write_access_set
        except Exception:
            return None

    @property
    def api_read(self):
        return any([group.has_any_access('api', read_only=True) for group in self.access_groups])

    @property
    def api_update(self):
        return any([group.has_access_level('api', AccessGroup.LIMITED) for group in self.access_groups])

    @property
    def api_create(self):
        return any([group.has_access_level('api', AccessGroup.CONTACT) for group in self.access_groups])

    @property
    def api_delete(self):
        return any([group.has_full_access('api') for group in self.access_groups])

    @property
    def full_dept_admin(self):
        return any([group.has_full_access('dept_admin') for group in self.access_groups])

    @property
    def full_shifts_admin(self):
        return any([group.has_full_access('shifts_admin') for group in self.access_groups])

    @property
    def full_dept_checklist_admin(self):
        return any([group.has_full_access('dept_checklist') for group in self.access_groups])

    @property
    def full_attractions_admin(self):
        return any([group.has_full_access('attractions_admin') for group in self.access_groups])

    @property
    def full_email_admin(self):
        return any([group.has_full_access('email_admin') for group in self.access_groups])

    @property
    def full_registration_admin(self):
        return any([group.has_full_access('registration') for group in self.access_groups])

    def max_level_access(self, site_section_or_page, read_only=False):
        write_access_list = [int(group.access.get(site_section_or_page, 0)) for group in self.access_groups]
        read_access_list = [int(group.read_only_access.get(site_section_or_page, 0)) for group in self.access_groups]
        return max(write_access_list + read_access_list) if read_only else max(write_access_list)

    @presave_adjustment
    def disable_api_access(self):
        invalid_api = self.invalid_api_accesses()
        if invalid_api:
            self.remove_disabled_api_keys(invalid_api)

    def remove_disabled_api_keys(self, invalid_api):
        revoked_time = datetime.utcnow()
        for api_token in self.active_api_tokens:
            if invalid_api.intersection(api_token.access_ints):
                api_token.revoked_time = revoked_time

    def invalid_api_accesses(self):
        """
        Builds and returns a set of API accesses that this account does not have.
        Designed to help remove/hide API keys/options that accounts do not have permissions for.
        """
        removed_api = set(c.API_ACCESS.keys())
        for access, label in c.API_ACCESS_OPTS:
            access_name = 'api_' + label.lower()
            if getattr(self, access_name, None):
                removed_api.remove(access)
        return removed_api


class PasswordReset(MagModel, table=True):
    admin_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='admin_account.id', ondelete='CASCADE', unique=True)
    admin_account: 'AdminAccount' = Relationship(back_populates="password_reset")

    attendee_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='attendee_account.id', ondelete='CASCADE', unique=True)
    attendee_account: 'AttendeeAccount' = Relationship(back_populates="password_reset")

    generated: datetime = Column(DateTime(timezone=True), server_default=utcnow(), default=lambda: datetime.now(UTC))
    hashed: str = Column(String, private=True)

    @property
    def is_expired(self):
        return self.generated < datetime.now(UTC) - timedelta(hours=c.PASSWORD_RESET_HOURS)


class AccessGroup(MagModel, table=True):
    """
    Sets of accesses to grant to admin accounts.
    """
    NONE: ClassVar = 0
    LIMITED: ClassVar = 1
    CONTACT: ClassVar = 2
    DEPT: ClassVar = 3
    FULL: ClassVar = 5
    READ_LEVEL_OPTS: ClassVar = [
        (NONE, 'Same as Read-Write Access'),
        (LIMITED, 'Limited'),
        (CONTACT, 'Contact Info'),
        (DEPT, 'All Info in Own Dept(s)'),
        (FULL, 'All Info')]
    WRITE_LEVEL_OPTS: ClassVar = [
        (NONE, 'No Access'),
        (LIMITED, 'Limited'),
        (CONTACT, 'Contact Info'),
        (DEPT, 'All Info in Own Dept(s)'),
        (FULL, 'All Info')]
    
    admin_accounts: list['AdminAccount'] = Relationship(
        back_populates='access_groups',
        sa_relationship_kwargs={'secondary': 'admin_access_group', 'cascade': 'save-update,merge,refresh-expire,expunge'})

    name: str = Column(String)
    access: dict[str, int] = Field(sa_type=MutableDict.as_mutable(JSONB), default_factory=dict)
    read_only_access: dict[str, int] = Field(sa_type=MutableDict.as_mutable(JSONB), default_factory=dict)
    start_time: datetime | None = Column(DateTime(timezone=True), nullable=True)
    end_time: datetime | None = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<AccessGroup id='{self.id}' name='{self.name}'>"

    @presave_adjustment
    def _disable_api_access(self):
        # orig_value_of doesn't seem to work for access and read_only_access so we always do this
        for account in self.admin_accounts:
            account.disable_api_access()

    def has_full_access(self, access_to, read_only=False):
        return self.has_access_level(access_to, self.FULL, read_only)

    def has_any_access(self, access_to, read_only=False):
        return self.has_access_level(access_to, self.LIMITED, read_only)

    @property
    def is_valid(self):
        if self.start_time and self.start_time > datetime.utcnow().replace(tzinfo=UTC):
            return False
        if self.end_time and self.end_time < datetime.utcnow().replace(tzinfo=UTC):
            return False
        return True

    def has_access_level(self, access_to, access_level, read_only=False, max_level=False):
        if not self.is_valid:
            return

        import operator
        if max_level:
            compare = operator.eq
        else:
            compare = operator.ge

        if read_only:
            return compare(int(self.access.get(access_to, 0)), access_level) \
                   or compare(int(self.read_only_access.get(access_to, 0)), access_level)

        return compare(int(self.access.get(access_to, 0)), access_level)


class WatchList(MagModel, table=True):
    """
    Attendee: selectin
    """

    first_names: str = Column(String)
    last_name: str = Column(String)
    email: str = Column(String, default='')
    birthdate: datetime | None = Column(Date, nullable=True, default=None)
    reason: str = Column(String)
    action: str = Column(String)
    expiration: datetime | None = Column(Date, nullable=True, default=None)
    active: bool = Column(Boolean, default=True)
    attendees: list['Attendee'] = Relationship(
        back_populates="watch_list",
        sa_relationship_kwargs={'lazy': 'selectin', 'cascade': 'save-update,merge,refresh-expire,expunge'})

    @property
    def full_name(self):
        return '{} {}'.format(self.first_names, self.last_name).strip() or 'Unknown'

    @property
    def first_name_list(self):
        return [name.strip().lower() for name in self.first_names.split(',')]

    @presave_adjustment
    def fix_birthdate(self):
        if self.birthdate == '':
            self.birthdate = None


# Many to many association table to tie Attendees to Escalation Tickets
attendee_escalation_ticket = Table(
    'attendee_escalation_ticket',
    MagModel.metadata,
    Column('attendee_id', Uuid(as_uuid=False), ForeignKey('attendee.id')),
    Column('escalation_ticket_id', Uuid(as_uuid=False), ForeignKey('escalation_ticket.id')),
    UniqueConstraint('attendee_id', 'escalation_ticket_id'),
    Index('ix_attendee_escalation_ticket_attendee_id', 'attendee_id'),
    Index('ix_attendee_escalation_ticket_escalation_ticket_id', 'escalation_ticket_id'),
)


class EscalationTicket(MagModel, table=True):
    """
    Attendee: selectin
    """
    attendees: list['Attendee'] = Relationship(
        back_populates="escalation_tickets",
        sa_relationship_kwargs={'lazy': 'selectin', 'order_by': 'Attendee.full_name',
                                'cascade': 'save-update,merge,refresh-expire,expunge', 'secondary': 'attendee_escalation_ticket'})
    ticket_id_seq: ClassVar = Sequence('escalation_ticket_ticket_id_seq')
    ticket_id: int = Column(Integer, ticket_id_seq, server_default=ticket_id_seq.next_value(), unique=True)
    who: str = Column(String)
    description: str = Column(String)
    admin_notes: str = Column(String)
    resolved: datetime | None = Column(DateTime(timezone=True), nullable=True)

    @property
    def attendee_names(self):
        return [a.full_name for a in self.attendees]


class WorkstationAssignment(MagModel, table=True):
    reg_station_id: int = Column(Integer)
    printer_id: str = Column(String)
    minor_printer_id: str = Column(String)
    terminal_id: str = Column(String)

    @property
    def separate_printers(self):
        return self.minor_printer_id != '' and self.printer_id != self.minor_printer_id

    @property
    def minor_or_adult_printer_id(self):
        return self.minor_printer_id or self.printer_id


c.ACCESS_GROUP_WRITE_LEVEL_OPTS = AccessGroup.WRITE_LEVEL_OPTS
c.ACCESS_GROUP_READ_LEVEL_OPTS = AccessGroup.READ_LEVEL_OPTS
