from datetime import datetime, timedelta

import cherrypy
from pytz import UTC
from sideboard.lib.sa import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy.orm import backref
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import Boolean, Date

from uber.config import c
from uber.decorators import presave_adjustment
from uber.models import MagModel
from uber.models.types import default_relationship as relationship, utcnow, \
    DefaultColumn as Column, MultiChoice


__all__ = ['AdminAccount', 'PasswordReset', 'WatchList']


class AdminAccount(MagModel):
    attendee_id = Column(UUID, ForeignKey('attendee.id'), unique=True)
    hashed = Column(UnicodeText, private=True)
    access = Column(MultiChoice(c.ACCESS_OPTS))

    password_reset = relationship(
        'PasswordReset', backref='admin_account', uselist=False)

    api_tokens = relationship('ApiToken', backref='admin_account')
    active_api_tokens = relationship(
        'ApiToken',
        primaryjoin='and_('
                    'AdminAccount.id == ApiToken.admin_account_id, '
                    'ApiToken.revoked_time == None)')

    def __repr__(self):
        return '<{}>'.format(self.attendee.full_name)

    @staticmethod
    def is_nick():
        return AdminAccount.admin_name() in c.JERKS

    @staticmethod
    def admin_name():
        try:
            from uber.models import Session
            with Session() as session:
                return session.admin_attendee().full_name
        except Exception as ex:
            return None

    @staticmethod
    def admin_email():
        try:
            from uber.models import Session
            with Session() as session:
                return session.admin_attendee().email
        except Exception as ex:
            return None

    @staticmethod
    def access_set(id=None):
        try:
            from uber.models import Session
            with Session() as session:
                id = id or cherrypy.session['account_id']
                return set(session.admin_account(id).access_ints)
        except Exception as ex:
            return set()

    def _allowed_opts(self, opts, required_access):
        access_opts = []
        admin_access = set(self.access_ints)
        for access, label in opts:
            required = set(required_access.get(access, []))
            if not required or any(a in required for a in admin_access):
                access_opts.append((access, label))
        return access_opts

    @property
    def allowed_access_opts(self):
        return self._allowed_opts(c.ACCESS_OPTS, c.REQUIRED_ACCESS)

    @property
    def allowed_api_access_opts(self):
        required_access = {a: [a] for a in c.API_ACCESS.keys()}
        return self._allowed_opts(c.API_ACCESS_OPTS, required_access)

    @property
    def is_admin(self):
        return c.ADMIN in self.access_ints

    @presave_adjustment
    def _disable_api_access(self):
        new_access = set(int(s) for s in self.access.split(',') if s)
        old_access = set(
            int(s) for s in self.orig_value_of('access').split(',') if s)
        removed = old_access.difference(new_access)
        removed_api = set(a for a in c.API_ACCESS.keys() if a in removed)
        if removed_api:
            revoked_time = datetime.utcnow()
            for api_token in self.active_api_tokens:
                if removed_api.intersection(api_token.access_ints):
                    api_token.revoked_time = revoked_time


class PasswordReset(MagModel):
    account_id = Column(UUID, ForeignKey('admin_account.id'), unique=True)
    generated = Column(UTCDateTime, server_default=utcnow())
    hashed = Column(UnicodeText, private=True)

    @property
    def is_expired(self):
        return self.generated < datetime.now(UTC) - timedelta(days=7)


class WatchList(MagModel):
    first_names = Column(UnicodeText)
    last_name = Column(UnicodeText)
    email = Column(UnicodeText, default='')
    birthdate = Column(Date, nullable=True, default=None)
    reason = Column(UnicodeText)
    action = Column(UnicodeText)
    active = Column(Boolean, default=True)
    attendees = relationship(
        'Attendee', backref=backref('watch_list', load_on_pending=True))

    @presave_adjustment
    def _fix_birthdate(self):
        if self.birthdate == '':
            self.birthdate = None
