from datetime import datetime, timedelta

import cherrypy
from pytz import UTC
from residue import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy.dialects.postgresql.json import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import backref
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import Boolean, Date

from uber.config import c
from uber.decorators import presave_adjustment
from uber.models import MagModel
from uber.models.types import default_relationship as relationship, utcnow, DefaultColumn as Column, MultiChoice


__all__ = ['AccessGroup', 'AdminAccount', 'PasswordReset', 'WatchList']


class AdminAccount(MagModel):
    attendee_id = Column(UUID, ForeignKey('attendee.id'), unique=True)
    access_group_id = Column(UUID, ForeignKey('access_group.id', ondelete='SET NULL'), nullable=True)
    access_group = relationship('AccessGroup',
                                backref='admin_accounts',
                                foreign_keys=access_group_id,
                                cascade='save-update,merge,refresh-expire,expunge')
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
    def access_set(id=None, include_read_only=False):
        try:
            from uber.models import Session
            with Session() as session:
                id = id or cherrypy.session['account_id']
                access_group = session.admin_account(id).access_group
                if include_read_only:
                    return set({**access_group.access, **access_group.read_only_access})
                return set(access_group.access)
        except Exception:
            return set()

    @property
    def allowed_access_opts(self):
        return self.session.query(AccessGroup).all()

    @property
    def allowed_api_access_opts(self):
        no_access_set = self.access_group.invalid_api_accesses()
        return [(access, label) for access, label in c.API_ACCESS_OPTS if access not in no_access_set]

    @property
    def is_admin(self):
        return 'devtools' in self.access_set()

    @property
    def is_mivs_judge_or_admin(self):
        return self.judge or 'mivs_judging' in self.access_set(include_read_only=True)

    @presave_adjustment
    def _disable_api_access(self):
        old_access_group = self.session.access_group(self.orig_value_of('access_group_id'))
        if self.access_group != old_access_group:
            invalid_api = self.access_group.invalid_api_accesses()
        if invalid_api:
            self.remove_disabled_api_keys(invalid_api)

    def remove_disabled_api_keys(self, invalid_api):
        revoked_time = datetime.utcnow()
        for api_token in self.active_api_tokens:
            if invalid_api.intersection(api_token.access_ints):
                api_token.revoked_time = revoked_time


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
    _NONE = 0
    _LIMITED = 1
    _CONTACT = 2
    _FULL = 5
    _READ_LEVEL_OPTS = [
        (_NONE, 'Same as Read-Write Access'),
        (_LIMITED, 'Limited'),
        (_CONTACT, 'Contact Info'),
        (_FULL, 'All Info')]
    _WRITE_LEVEL_OPTS = [
        (_NONE, 'No Access'),
        (_LIMITED, 'Limited'),
        (_CONTACT, 'Contact Info'),
        (_FULL, 'All Info')]

    name = Column(UnicodeText)
    access = Column(MutableDict.as_mutable(JSONB), default={})
    read_only_access = Column(MutableDict.as_mutable(JSONB), default={})

    @presave_adjustment
    def _disable_api_access(self):
        # orig_value_of doesn't seem to work for access and read_only_access so we always do this
        invalid_api = self.invalid_api_accesses()
        if invalid_api:
            for account in self.admin_accounts:
                account.remove_disabled_api_keys(invalid_api)

    def invalid_api_accesses(self):
        """
        Builds and returns a set of API accesses that this access group does not have.
        Designed to help remove/hide API keys/options that accounts do not have permissions for.
        """
        removed_api = set(c.API_ACCESS.keys())
        for access, label in c.API_ACCESS_OPTS:
            access_name = 'api_' + label.lower()
            if getattr(self, access_name, None):
                removed_api.remove(access)
        return removed_api

    @property
    def api_read(self):
        return int(self.access.get('api', 0)) or int(self.read_only_access.get('api', 0))

    @property
    def api_update(self):
        return int(self.access.get('api', 0)) >= self._LIMITED

    @property
    def api_create(self):
        return int(self.access.get('api', 0)) >= self._CONTACT

    @property
    def api_delete(self):
        return int(self.access.get('api', 0)) >= self._FULL

    @property
    def full_dept_admin(self):
        return int(self.access.get('dept_admin', 0)) >= self._FULL


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

c.ACCESS_GROUP_WRITE_LEVEL_OPTS = AccessGroup._WRITE_LEVEL_OPTS
c.ACCESS_GROUP_READ_LEVEL_OPTS = AccessGroup._READ_LEVEL_OPTS