import re
from datetime import datetime

from pockets import cached_property, classproperty, groupify
from pytz import UTC
from residue import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy import or_
from sqlalchemy.orm import relationship
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import Boolean, Integer

from uber.config import c
from uber.custom_tags import safe_string
from uber.models import MagModel
from uber.models.types import DefaultColumn as Column
from uber.utils import localized_now


__all__ = ['AutomatedEmail', 'Email']


class ModelClassColumnMixin(object):
    model = Column(UnicodeText)

    @property
    def model_class(self):
        try:
            from uber.models import Session
            return Session.resolve_model(self.model)
        except ValueError:
            return None


class AutomatedEmail(MagModel, ModelClassColumnMixin):
    ident = Column(UnicodeText, unique=True)
    subject = Column(UnicodeText)
    body = Column(UnicodeText)

    sender = Column(UnicodeText)
    cc = Column(UnicodeText)
    bcc = Column(UnicodeText)

    approved = Column(Boolean, default=False)
    needs_approval = Column(Boolean, default=True)
    unapproved_count = Column(Integer, default=0)

    allow_post_con = Column(Boolean, default=False)
    allow_at_the_con = Column(Boolean, default=False)

    active_after = Column(UTCDateTime, nullable=True, default=None)
    active_before = Column(UTCDateTime, nullable=True, default=None)

    emails = relationship('Email', backref='automated_email', order_by='Email.id')

    _repr_attr_names = ['ident']

    @classproperty
    def filters_for_allowed(cls):
        if c.POST_CON:
            return [cls.allow_post_con == True]  # noqa: E712
        elif c.AT_THE_CON:
            return [cls.allow_at_the_con == True]  # noqa: E712
        return []

    @classproperty
    def filters_for_active(cls):
        now = localized_now()
        return cls.filters_for_allowed + [
            or_(cls.active_after == None, cls.active_after <= now),
            or_(cls.active_before == None, cls.active_before >= now)]  # noqa: E711

    @classproperty
    def filters_for_approvable(cls):
        return [
            cls.approved == False,
            cls.needs_approval == True,
            or_(cls.active_before == None, cls.active_before >= localized_now())]  # noqa: E711,E712

    @classproperty
    def filters_for_pending(cls):
        return cls.filters_for_active + [
            cls.approved == False,
            cls.needs_approval == True,
            cls.unapproved_count > 0]  # noqa: E712

    @property
    def emails_by_fk_id(self):
        return groupify(self.emails, 'fk_id')

    def send_to(self, model_instance):
        assert self.session, 'AutomatedEmail.send_to() may only be used by instances attached to a session.'
        raise NotImplementedError('AutomatedEmail.send_to() is not implemented yet.')


class Email(MagModel, ModelClassColumnMixin):
    automated_email_id = Column(
        UUID, ForeignKey('automated_email.id', ondelete='set null'), nullable=True, default=None)

    fk_id = Column(UUID, nullable=True)
    when = Column(UTCDateTime, default=lambda: datetime.now(UTC))

    ident = Column(UnicodeText)
    subject = Column(UnicodeText)
    body = Column(UnicodeText)

    sender = Column(UnicodeText)
    to = Column(UnicodeText)
    cc = Column(UnicodeText)
    bcc = Column(UnicodeText)

    _repr_attr_names = ['subject']

    @cached_property
    def fk(self):
        try:
            return self.session.query(self.model_class).filter_by(id=self.fk_id).first()
        except Exception:
            return None

    @property
    def rcpt_name(self):
        if self.fk:
            is_group = self.model == 'Group'
            return self.fk.leader.full_name if is_group else self.fk.full_name

    @property
    def rcpt_email(self):
        if self.fk:
            is_group = self.model == 'Group'
            return self.fk.leader.email if is_group else self.fk.email
        return self.to or None

    @property
    def is_html(self):
        return '<body' in self.body

    @property
    def html(self):
        if self.is_html:
            body = re.split('<body[^>]*>', self.body)[1].split('</body>')[0]
            return safe_string(body)
        else:
            return safe_string(self.body.replace('\n', '<br/>'))
