import re
import traceback
import logging
from collections import OrderedDict
from datetime import datetime, date
from dateutil import parser as dateparser

from pytz import UTC
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.types import Uuid, DateTime, JSON
from typing import Any, ClassVar

from uber import utils
from uber.config import c
from uber.decorators import presave_adjustment, renderable_data, cached_property, classproperty
from uber.jinja import JinjaEnv
from uber.models import MagModel
from uber.models.types import DefaultField as Field, DefaultRelationship as Relationship, Choice, DefaultColumn as Column
from uber.utils import normalize_newlines, request_cached_context, groupify

log = logging.getLogger(__name__)


__all__ = ['AutomatedEmail', 'Email']


class BaseEmailMixin(object):
    model: str = ''
    shared_ident: str = ''

    subject: str = ''
    body: str = ''

    sender: str = ''
    cc: str = ''
    bcc: str = ''
    replyto: str = ''

    _repr_attr_names: ClassVar = ['subject']

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


class AutomatedEmail(MagModel, BaseEmailMixin, table=True):
    _fixtures: ClassVar = OrderedDict()
    initialized: ClassVar = False

    format: str = 'text'
    ident: str = Field(default='', unique=True)
    policy: int | None = Field(sa_column=Column(Choice(c.EMAIL_POLICY_OPTS), index=True, nullable=True), default=None)
    allow_at_the_con: bool = False
    allow_post_con: bool = False
    active_after: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True, default=None)
    active_before: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True, default=None)

    emails: list['Email'] = Relationship(back_populates="automated_email", sa_relationship_kwargs={'order_by': 'Email.id'})

    @presave_adjustment
    def date_adjustments(self):
        if self.active_after == '':
            self.active_after = None
        elif isinstance(self.active_after, str):
            try:
                self.active_after = datetime.strptime(self.active_after, c.DATE_FORMAT)
            except ValueError:
                self.active_after = dateparser.parse(self.active_after)

        if self.active_before == '':
            self.active_before = None
        elif isinstance(self.active_before, str):
            try:
                self.active_before = datetime.strptime(self.active_before, c.DATE_FORMAT)
            except ValueError:
                self.active_before = dateparser.parse(self.active_before)

    @classproperty
    def filters_for_allowed(cls):
        allowed = [cls.policy != c.DISABLED, cls.policy != c.REMOVE]
        if c.AT_THE_CON:
            return allowed + [cls.allow_at_the_con == True]  # noqa: E712
        if c.POST_CON:
            return allowed + [cls.allow_post_con == True]  # noqa: E712
        return allowed

    @classproperty
    def filters_for_active(cls):
        now = utils.localized_now()
        return cls.filters_for_allowed + [
            or_(cls.active_after == None, cls.active_after <= now),  # noqa: E711
            or_(cls.active_before == None, cls.active_before >= now)]  # noqa: E711

    @staticmethod
    def reset_fixture_attr(session, ident, key):
        fixture = AutomatedEmail._fixtures.get(ident, None)
        if not fixture:
            log.error(f"We tried to update fixture ident {ident}, but it wasn't in our list of email fixtures!")
            return
        
        automated_email = session.query(AutomatedEmail).filter_by(ident=ident).first() or AutomatedEmail(ident=ident)

        session.add(automated_email.reconcile(fixture))

    @staticmethod
    def reconcile_fixtures(cleanup=False):
        from uber.models import Session
        with Session() as session:
            existing_automated_emails = session.query(AutomatedEmail)

            existing_idents = set([email.ident for email in existing_automated_emails])
            fixture_idents = set(AutomatedEmail._fixtures.keys())

            new_idents = fixture_idents - existing_idents
            orphaned_idents = existing_idents - fixture_idents
            for ident in new_idents:
                fixture = AutomatedEmail._fixtures[ident]
                automated_email = AutomatedEmail(ident=ident)
                session.add(automated_email.reconcile(fixture))
                if not fixture.template_plugin_name or not fixture.template_url:
                    fixture.update_template_plugin_info()

            for automated_email in existing_automated_emails:
                ident = automated_email.ident
                if ident not in orphaned_idents:
                    fixture = AutomatedEmail._fixtures[ident]
                    pending_emails = session.query(Email).filter(Email.ident == ident, Email.status != c.SENT)
                    
                    # We want to update any pending emails, but emails can be generated with custom attributes
                    # This updates emails while avoiding changing any attributes that don't match the fixture
                    changed_vals = {}
                    for attr in ['subject', 'sender', 'cc', 'bcc', 'replyto']:
                        fixture_attr = getattr(fixture, attr) if attr in ['subject', 'sender'] else ','.join(getattr(fixture, attr))
                        if getattr(automated_email, attr) != fixture_attr:
                            changed_vals[attr] = fixture_attr
                    
                    for pending in pending_emails:
                        changed = False
                        for attr in changed_vals.keys():
                            if getattr(pending, attr) == getattr(automated_email, attr):
                                setattr(pending, attr, changed_vals[attr])
                                changed = True
                        if changed:
                            if pending.generated:
                                pending.generated = datetime.now(UTC)
                            session.add(pending)
                    session.add(automated_email.reconcile(fixture))

            if not cleanup:
                session.commit()
                return

            # TODO: This will repeatedly mark panel-related emails for removal. We may want to just get rid of cleanup
            for automated_email in session.query(AutomatedEmail).filter(AutomatedEmail.ident.in_(orphaned_idents)).all():
                automated_email.policy = c.REMOVE
                session.add(automated_email)
            session.commit()

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
    
    @property
    def inactive_reason(self):
        if self.policy in [c.DISABLED, c.REMOVE]:
            return "disabled"
        
        if c.AT_THE_CON and not self.allow_at_the_con:
            return "not allowed during the event"
        if c.POST_CON and not self.allow_post_con:
            return "not allowed after the event"

        now = utils.localized_now()
        if self.active_after and self.active_after > now or self.active_before and self.active_before < now:
            return f"only active {self.active_when_label}"

    @cached_property
    def emails_by_fk_id(self):
        return groupify(self.emails, 'fk_id')

    @hybrid_property
    def email_count(self):
        return len(self.emails)

    @email_count.expression
    def email_count(cls):
        return select(func.count(cls.emails)).where(Email.automated_email_id == cls.id).label('email_count')

    @property
    def filter(self):
        if not self.fixture:
            if not self.ident.startswith('panelapps_'):
                log.error(f"We want to send {self.ident} but it has no fixture!")
            return lambda x: False
        return self.fixture.filter

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
    def is_html(self):
        return self.format == 'html'

    def reconcile(self, fixture):
        self.model = fixture.model.__name__ if fixture.model else ''
        self.subject = fixture.subject
        self.body = fixture.body
        self.format = fixture.format
        self.sender = fixture.sender
        self.cc = ','.join(fixture.cc)
        self.bcc = ','.join(fixture.bcc)
        self.replyto = ','.join(fixture.replyto)
        self.allow_at_the_con = fixture.allow_at_the_con
        self.allow_post_con = fixture.allow_post_con
        self.active_after = fixture.active_after
        self.active_before = fixture.active_before
        return self

    def renderable_data(self, model_instance=None, render_data={}):
        data = {'email_signature': c.get_signature_by_sender(self.sender)}
        if model_instance:
            model_name = getattr(model_instance, 'email_model_name', model_instance.__class__.__name__.lower())
            data[model_name] = model_instance

        if self.fixture:
            data.update(self.fixture.extra_data)

        data.update(render_data)
        return renderable_data(data)

    def render_body(self, model_instance=None, render_data={}):
        return self.render_template(self.body, self.renderable_data(model_instance, render_data))

    def render_subject(self, model_instance, render_data={}):
        return self.subject.format(self.renderable_data(model_instance, render_data))

    def render_template(self, text, data):
        with request_cached_context(clear_cache_on_start=True):
            return JinjaEnv.env().from_string(text).render(data)

    def send_to(self, model_instance, delay=True, raise_errors=False, session=None):
        return
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
                cc=self.cc or model_instance.cc_emails_for_ident(self.ident),
                bcc=self.bcc or model_instance.bcc_emails_for_ident(self.ident),
                replyto=self.replyto or model_instance.replyto_emails_for_ident(self.ident),
                ident=self.ident,
                automated_email=self.to_dict('id'),
                session=session)
            return True
        except Exception:
            traceback.print_exc()
            log.error(f'Error sending {self.subject} email to {model_instance.email_to_address}', exc_info=True)
            if raise_errors:
                raise
        return False

    def would_send_if_approved(self, model_instance):
        return model_instance and getattr(model_instance, 'email_to_address', False) and self.filter(model_instance)


class Email(MagModel, BaseEmailMixin, table=True):
    automated_email_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='automated_email.id', nullable=True, index=True)
    automated_email: 'AutomatedEmail' = Relationship(back_populates="emails", sa_relationship_kwargs={'lazy': 'joined'})

    fk_id: str | None = Field(sa_type=Uuid(as_uuid=False), nullable=True)
    ident: str = ''
    to: str = ''
    render_data: dict[str, Any] = Field(sa_type=JSON, default_factory=dict)
    status: int = Field(sa_column=Column(Choice(c.EMAIL_STATUS_OPTS), index=True), default=c.UNAPPROVED)
    generated: str = Field(sa_type=DateTime(timezone=True), default_factory=lambda: datetime.now(UTC))
    sent: str | None = Field(sa_type=DateTime(timezone=True), nullable=True, default=None)
    error: str = ''

    @cached_property
    def fk(self):
        return self.session.get(self.model_class, self.fk_id) \
            if self.session and self.fk_id else None

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
