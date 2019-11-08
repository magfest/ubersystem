from datetime import datetime, timedelta

import cherrypy
from pockets import classproperty, listify
from pytz import UTC
from residue import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy.dialects.postgresql.json import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import backref
from sqlalchemy.schema import ForeignKey, Table, UniqueConstraint, Index
from sqlalchemy.types import Boolean, Date
from sqlalchemy.sql import and_, or_

from uber.config import c
from uber.decorators import presave_adjustment
from uber.models import MagModel
from uber.models.types import default_relationship as relationship, utcnow, DefaultColumn as Column, MultiChoice


__all__ = ['AccessGroup', 'AdminAccount', 'PasswordReset', 'WatchList']


# Many to many association table to tie Access Groups with Admin Accounts
admin_access_group = Table(
    'admin_access_group',
    MagModel.metadata,
    Column('admin_account_id', UUID, ForeignKey('admin_account.id')),
    Column('access_group_id', UUID, ForeignKey('access_group.id')),
    UniqueConstraint('admin_account_id', 'access_group_id'),
    Index('ix_admin_access_group_admin_account_id', 'admin_account_id'),
    Index('ix_admin_access_group_access_group_id', 'access_group_id'),
)


class AdminAccount(MagModel):
    attendee_id = Column(UUID, ForeignKey('attendee.id'), unique=True)
    access_groups = relationship(
        'AccessGroup', backref='admin_accounts', cascade='save-update,merge,refresh-expire,expunge',
        secondary='admin_access_group')
    hashed = Column(UnicodeText, private=True)

    password_reset = relationship('PasswordReset', backref='admin_account', uselist=False)

    api_tokens = relationship('ApiToken', backref='admin_account')
    active_api_tokens = relationship(
        'ApiToken',
        primaryjoin='and_('
                    'AdminAccount.id == ApiToken.admin_account_id, '
                    'ApiToken.revoked_time == None)')

    judge = relationship('IndieJudge', uselist=False, backref='admin_account')

    def __repr__(self):
        return '<{}>'.format(self.attendee.full_name)

    @staticmethod
    def admin_name():
        try:
            from uber.models import Session
            with Session() as session:
                return session.admin_attendee().full_name
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
        access_list = [list(group.access) for group in self.access_groups]
        return set([item for sublist in access_list for item in sublist])

    @property
    def read_access_set(self):
        access_list = [list(group.read_only_access) for group in self.access_groups]
        return set([item for sublist in access_list for item in sublist])

    @property
    def read_or_write_access_set(self):
        return self.read_access_set.union(self.write_access_set)

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
        return [opt for opt in c.GROUP_TYPE_VARS if opt.lower() + "_admin" in self.read_or_write_access_set]

    @property
    def is_admin(self):
        return 'devtools' in self.write_access_set

    @property
    def is_mivs_judge_or_admin(self, id=None):
        try:
            from uber.models import Session
            with Session() as session:
                id = id or cherrypy.session.get('account_id')
                admin_account = session.admin_account(id)
                return admin_account.judge or 'mivs_judging' in admin_account.read_or_write_access_set
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

    def has_dept_level_access(self, site_section_or_page):
        return any([group.has_access_level(site_section_or_page, AccessGroup.DEPT) for group in self.access_groups])

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


class PasswordReset(MagModel):
    account_id = Column(UUID, ForeignKey('admin_account.id'), unique=True)
    generated = Column(UTCDateTime, server_default=utcnow())
    hashed = Column(UnicodeText, private=True)

    @property
    def is_expired(self):
        return self.generated < datetime.now(UTC) - timedelta(days=7)


class AccessGroup(MagModel):
    """
    Sets of accesses to grant to admin accounts.
    """
    NONE = 0
    LIMITED = 1
    CONTACT = 2
    DEPT = 3
    FULL = 5
    READ_LEVEL_OPTS = [
        (NONE, 'Same as Read-Write Access'),
        (LIMITED, 'Limited'),
        (CONTACT, 'Contact Info'),
        (DEPT, 'All Info in Own Dept(s)'),
        (FULL, 'All Info')]
    WRITE_LEVEL_OPTS = [
        (NONE, 'No Access'),
        (LIMITED, 'Limited'),
        (CONTACT, 'Contact Info'),
        (DEPT, 'All Info in Own Dept(s)'),
        (FULL, 'All Info')]

    name = Column(UnicodeText)
    access = Column(MutableDict.as_mutable(JSONB), default={})
    read_only_access = Column(MutableDict.as_mutable(JSONB), default={})

    @presave_adjustment
    def _disable_api_access(self):
        # orig_value_of doesn't seem to work for access and read_only_access so we always do this
        for account in self.admin_accounts:
            account.disable_api_access()

    def has_full_access(self, access_to, read_only=False):
        return self.has_access_level(access_to, self.FULL, read_only)

    def has_any_access(self, access_to, read_only=False):
        return self.has_access_level(access_to, self.LIMITED, read_only)

    def has_access_level(self, access_to, access_level, read_only=False):
        if read_only:
            return int(self.access.get(access_to, 0)) >= access_level \
                   or int(self.read_only_access.get(access_to, 0)) >= access_level

        return int(self.access.get(access_to, 0)) >= access_level


class WatchList(MagModel):
    first_names = Column(UnicodeText)
    last_name = Column(UnicodeText)
    email = Column(UnicodeText, default='')
    birthdate = Column(Date, nullable=True, default=None)
    reason = Column(UnicodeText)
    action = Column(UnicodeText)
    active = Column(Boolean, default=True)
    attendees = relationship('Attendee', backref=backref('watch_list', load_on_pending=True))

    @property
    def full_name(self):
        return '{} {}'.format(self.first_names, self.last_name).strip() or 'Unknown'

    @presave_adjustment
    def _fix_birthdate(self):
        if self.birthdate == '':
            self.birthdate = None

c.ACCESS_GROUP_WRITE_LEVEL_OPTS = AccessGroup.WRITE_LEVEL_OPTS
c.ACCESS_GROUP_READ_LEVEL_OPTS = AccessGroup.READ_LEVEL_OPTS