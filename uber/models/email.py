import re
from collections import OrderedDict
from datetime import datetime

from pockets import cached_property, classproperty, groupify
from pockets.autolog import log
from pytz import UTC
from residue import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import Boolean, Integer

from uber import utils
from uber.config import c
from uber.decorators import presave_adjustment, renderable_data
from uber.jinja import JinjaEnv
from uber.models import MagModel
from uber.models.types import DefaultColumn as Column
from uber.utils import normalize_newlines, request_cached_context


__all__ = ['AutomatedEmail', 'Email']


class BaseEmailMixin(object):
    model = Column(UnicodeText)

    subject = Column(UnicodeText)
    body = Column(UnicodeText)

    sender = Column(UnicodeText)
    cc = Column(UnicodeText)
    bcc = Column(UnicodeText)

    _repr_attr_names = ['subject']

    @property
    def body_with_body_tag_stripped(self):
        body = re.split(r'<\s*body[^>]*>', self.body)[-1]
        return re.split(r'<\s*\/\s*body\s*>', body)[0]

    @property
    def body_as_html(self):
        if self.is_html:
            return self.body_with_body_tag_stripped
        else:
            return normalize_newlines(self.body).replace('\n', '<br>')

    @property
    def is_html(self):
        return '<body' in self.body

    @property
    def model_class(self):
        if self.model and self.model != 'n/a':
            from uber.models import Session
            return Session.resolve_model(self.model)
        else:
            return None


class AutomatedEmail(MagModel, BaseEmailMixin):
    _fixtures = OrderedDict()

    format = Column(UnicodeText, default='text')
    ident = Column(UnicodeText, unique=True)

    approved = Column(Boolean, default=False)
    needs_approval = Column(Boolean, default=True)
    unapproved_count = Column(Integer, default=0)

    allow_at_the_con = Column(Boolean, default=False)
    allow_post_con = Column(Boolean, default=False)

    active_after = Column(UTCDateTime, nullable=True, default=None)
    active_before = Column(UTCDateTime, nullable=True, default=None)

    emails = relationship('Email', backref='automated_email', order_by='Email.id')
    
    @presave_adjustment
    def date_adjustments(self):
        if self.active_after == '':
            self.active_after = None
        elif isinstance(self.active_after, str):
            self.active_after = datetime.strptime(self.active_after, c.DATE_FORMAT)
        
        if self.active_before == '':
            self.active_before = None
        elif isinstance(self.active_before, str):
            self.active_before = datetime.strptime(self.active_before, c.DATE_FORMAT)

    @classproperty
    def filters_for_allowed(cls):
        if c.AT_THE_CON:
            return [cls.allow_at_the_con == True]  # noqa: E712
        if c.POST_CON:
            return [cls.allow_post_con == True]  # noqa: E712
        return []

    @classproperty
    def filters_for_active(cls):
        now = utils.localized_now()
        return cls.filters_for_allowed + [
            or_(cls.active_after == None, cls.active_after <= now),
            or_(cls.active_before == None, cls.active_before >= now)]  # noqa: E711

    @classproperty
    def filters_for_approvable(cls):
        return [
            cls.approved == False,
            cls.needs_approval == True,
            or_(cls.active_before == None, cls.active_before >= utils.localized_now())]  # noqa: E711,E712

    @classproperty
    def filters_for_pending(cls):
        return cls.filters_for_active + [
            cls.approved == False,
            cls.needs_approval == True,
            cls.unapproved_count > 0]  # noqa: E712

    @staticmethod
    def reconcile_fixtures():
        from uber.models import Session
        with Session() as session:
            for ident, fixture in AutomatedEmail._fixtures.items():
                automated_email = session.query(AutomatedEmail).filter_by(ident=ident).first() or AutomatedEmail()
                session.add(automated_email.reconcile(fixture))
            session.flush()
            for automated_email in session.query(AutomatedEmail).all():
                if automated_email.ident in AutomatedEmail._fixtures:
                    # This automated email exists in our email fixtures.
                    session.execute(update(Email).where(Email.ident == automated_email.ident).values(
                        automated_email_id=automated_email.id))
                else:
                    # This automated email no longer exists in our email
                    # fixtures. It was probably deleted because it was no
                    # longer relevant, or perhaps it was removed by disabling
                    # a feature flag. Either way, we want to clean up and
                    # delete it from the database.
                    session.execute(update(Email).where(Email.ident == automated_email.ident).values(
                        automated_email_id=None))
                    session.delete(automated_email)

    @property
    def active_when_label(self):
        """
        Readable description of when the date filters are active for this email.
        """
        fmt = '%b %-d'
        if self.active_after and self.active_before:
            return 'between {} and {}'.format(self.active_after.strftime(fmt), self.active_before.strftime(fmt))
        elif self.active_after:
            return 'after {}'.format(self.active_after.strftime(fmt))
        elif self.active_before:
            return 'before {}'.format(self.active_before.strftime(fmt))
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
    def filter(self):
        return self.fixture.filter if self.fixture else lambda x: True

    @property
    def fixture(self):
        return AutomatedEmail._fixtures.get(self.ident)

    @property
    def ordinal(self):
        try:
            return list(AutomatedEmail._fixtures.keys()).index(self.ident)
        except ValueError:
            return -1

    @property
    def query(self):
        return self.fixture.query if self.fixture else tuple()

    @property
    def query_options(self):
        return self.fixture.query_options if self.fixture else tuple()

    @property
    def is_html(self):
        return self.format == 'html'

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
        data = {model_name: model_instance}
        if self.fixture:
            data.update(self.fixture.extra_data)
        return renderable_data(data)

    def render_body(self, model_instance):
        return self.render_template(self.body, self.renderable_data(model_instance))

    def render_subject(self, model_instance):
        return self.render_template(self.subject, self.renderable_data(model_instance))

    def render_template(self, text, data):
        with request_cached_context(clear_cache_on_start=True):
            return JinjaEnv.env().from_string(text).render(data)

    def send_to(self, model_instance, delay=True, raise_errors=False):
        try:
            from uber.tasks.email import send_email
            data = self.renderable_data(model_instance)
            send_func = send_email.delay if delay else send_email
            send_func(
                self.sender,
                model_instance.email_to_address,
                self.render_template(self.subject, data),
                self.render_template(self.body, data),
                self.format,
                model=model_instance.to_dict('id'),
                cc=self.cc,
                bcc=self.bcc,
                ident=self.ident,
                automated_email=self.to_dict('id'))
            return True
        except Exception:
            log.error('Error sending {!r} email to {}', self.subject, model_instance.email_to_address, exc_info=True)
            if raise_errors:
                raise
        return False

    def would_send_if_approved(self, model_instance):
        return model_instance and getattr(model_instance, 'email_to_address', False) and self.filter(model_instance)


class Email(MagModel, BaseEmailMixin):
    automated_email_id = Column(
        UUID, ForeignKey('automated_email.id', ondelete='set null'), nullable=True, default=None)

    fk_id = Column(UUID, nullable=True)
    ident = Column(UnicodeText)
    to = Column(UnicodeText)
    when = Column(UTCDateTime, default=lambda: datetime.now(UTC))

    @cached_property
    def fk(self):
        return self.session.query(self.model_class).filter_by(id=self.fk_id).first() if self.session and self.fk_id else None

    @property
    def fk_email(self):
        if self.fk:
            return self.fk.leader.email_to_address if (self.model == 'Group') else self.fk.email_to_address
        return self.to

    @property
    def format(self):
        return 'html' if self.is_html else 'text'

    @property
    def is_html(self):
        return self.automated_email.is_html \
            if self.automated_email_id and self.automated_email \
            else super(Email, self).is_html
