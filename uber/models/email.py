import re
from collections import OrderedDict
from datetime import datetime

from pockets import cached_property, classproperty, groupify
from pockets.autolog import log
from pytz import UTC
from residue import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy import func, or_, select
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import Boolean, Integer

from uber.config import c
from uber.custom_tags import safe_string
from uber.decorators import renderable_data
from uber.jinja import JinjaEnv
from uber.models import MagModel
from uber.models.types import DefaultColumn as Column
from uber.notifications import send_email
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
    _fixtures = OrderedDict()

    ident = Column(UnicodeText, unique=True)
    subject = Column(UnicodeText)
    body = Column(UnicodeText)
    format = Column(UnicodeText, default='text')

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

    _repr_attr_names = ['subject']

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

    @classmethod
    def reconcile_fixtures(cls):
        from uber.models import Session
        with Session() as session:
            for ident, fixture in cls._fixtures.items():
                automated_email = session.query(AutomatedEmail).filter_by(ident=ident).first() or AutomatedEmail()
                session.add(automated_email.reconcile(fixture))

    @property
    def active_label(self):
        """
        Readable description of when the date filters are active for this email.
        """
        if self.active_after and self.active_before:
            return 'between {} and {}'.format(self.active_after.strftime('%m/%d'), self.active_before.strftime('%m/%d'))
        elif self.active_after:
            return 'after {}'.format(self.active_after.strftime('%m/%d'))
        elif self.active_before:
            return 'before {}'.format(self.active_before.strftime('%m/%d'))
        return ''

    @cached_property
    def emails_by_fk_id(self):
        return groupify(self.emails, 'fk_id')

    @hybrid_property
    def email_count(self):
        return len(self.emails)

    @email_count.expression
    def email_count(cls):
        return select([func.count(cls.emails)]).where(Email.automated_email_id == cls.id).label('email_count')

    @property
    def fixture(self):
        return AutomatedEmail._fixtures.get(self.ident)

    @property
    def ordinal(self):
        try:
            return list(AutomatedEmail._fixtures.keys()).index(self.ident)
        except ValueError:
            return -1

    def reconcile(self, fixture):
        self.model = fixture.model.__name__
        self.ident = fixture.ident
        self.subject = fixture.subject
        self.body = fixture.body
        self.format = fixture.format
        self.sender = fixture.sender
        self.cc = ','.join(fixture.cc)
        self.bcc = ','.join(fixture.bcc)
        self.needs_approval = fixture.needs_approval
        self.allow_at_the_con = fixture.allow_at_the_con
        self.allow_post_con = fixture.allow_post_con
        self.active_after = fixture.active_after
        self.active_before = fixture.active_before
        self.approved = False if self.is_new else self.approved
        self.unapproved_count = 0 if self.is_new else self.unapproved_count
        return self

    def renderable_data(self, model_instance):
        model_name = getattr(model_instance, 'email_model_name', model_instance.__class__.__name__.lower())
        data = {
            model_name: model_instance,
            'EVENT_NAME': c.EVENT_NAME,
            'EVENT_DATE': c.EPOCH.strftime('(%b %Y)')}
        if self.fixture:
            data.update(self.fixture.extra_data)
        return renderable_data(data)

    def render_body(self, model_instance):
        return self.render_template(self.body, self.renderable_data(model_instance))

    def render_subject(self, model_instance):
        return self.render_template(self.subject, self.renderable_data(model_instance))

    def render_template(self, text, data):
        return JinjaEnv.env().from_string(text).render(data).encode('utf-8')

    def send(self, model_instance, raise_errors=False):
        assert self.session, 'AutomatedEmail.send() may only be used by instances attached to a session.'
        try:
            data = self.renderable_data(model_instance)
            send_email(
                self.sender,
                model_instance.email,
                self.render_template(self.subject, data),
                self.render_template(self.body, data),
                self.format,
                model=model_instance,
                cc=self.cc,
                bcc=self.bcc,
                ident=self.ident,
                automated_email=self)
            return True
        except Exception:
            log.error('Error sending {!r} email to {}', self.subject, model_instance.email, exc_info=True)
            if raise_errors:
                raise
        return False

    def send_if_should(self, model_instance, raise_errors=False):
        if self.would_send_if_approved(model_instance):
            if self.approved or not self.needs_approval:
                self.send(model_instance, raise_errors)
            else:
                self.unapproved_count += 1

    def would_send_if_approved(self, model_instance):
        if not model_instance or not self.fixture:
            return False
        return getattr(model_instance, 'email', False) and self.fixture.filter(model_instance)


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
