import re
from datetime import datetime

from pockets import cached_property
from pytz import UTC
from residue import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import Boolean, Integer

from uber.custom_tags import safe_string
from uber.models import MagModel
from uber.models.types import DefaultColumn as Column


__all__ = ['AutomatedEmail', 'Email']


class AutomatedEmail(MagModel):
    model = Column(UnicodeText)

    ident = Column(UnicodeText, unique=True)
    subject = Column(UnicodeText)
    body = Column(UnicodeText)

    sender = Column(UnicodeText)
    cc = Column(UnicodeText)
    bcc = Column(UnicodeText)

    approved = Column(Boolean, default=True)
    needs_approval = Column(Boolean, default=True)
    unapproved_count = Column(Integer, default=0)

    post_con = Column(Boolean, default=False)
    allow_during_con = Column(Boolean, default=False)

    active_after = Column(UTCDateTime, nullable=True, default=None)
    active_before = Column(UTCDateTime, nullable=True, default=None)

    _repr_attr_names = ['ident']


class Email(MagModel):
    automated_email_id = Column(
        UUID, ForeignKey('automated_email.id', ondelete='set null'), nullable=True, default=None)

    fk_id = Column(UUID, nullable=True)
    model = Column(UnicodeText)
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
            from uber.models import Session
            model_class = Session.resolve_model(self.model)
            query = self.session.query(model_class)
            return query.filter_by(id=self.fk_id).first()
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
