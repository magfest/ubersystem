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
    hashed = Column(UnicodeText)
    access = Column(MultiChoice(c.ACCESS_OPTS))

    password_reset = relationship(
        'PasswordReset', backref='admin_account', uselist=False)

    api_tokens = relationship('ApiToken', backref='admin_account')

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
        except:
            return None

    @staticmethod
    def admin_email():
        try:
            from uber.models import Session
            with Session() as session:
                return session.admin_attendee().email
        except:
            return None

    @staticmethod
    def access_set(id=None):
        try:
            from uber.models import Session
            with Session() as session:
                id = id or cherrypy.session['account_id']
                return set(session.admin_account(id).access_ints)
        except:
            return set()

    @property
    def allowed_access_opts(self):
        access_opts = []
        admin_access = set(self.access_ints)
        for access, label in c.ACCESS_OPTS:
            required = set(c.REQUIRED_ACCESS.get(access, []))
            if not required or any(a in required for a in admin_access):
                access_opts.append((access, label))
        return access_opts

    @presave_adjustment
    def _disable_api_access(self):
        new_access = set(int(s) for s in self.access.split(',') if s)
        old_access = set(
            int(s) for s in self.orig_value_of('access').split(',') if s)
        removed_access = old_access.difference(new_access)
        if c.API in removed_access:
            revoked_time = datetime.utcnow()
            for api_token in self.api_tokens:
                api_token.revoked_time = revoked_time


class PasswordReset(MagModel):
    account_id = Column(UUID, ForeignKey('admin_account.id'), unique=True)
    generated = Column(UTCDateTime, server_default=utcnow())
    hashed = Column(UnicodeText)

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
