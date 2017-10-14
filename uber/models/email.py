import re
from datetime import datetime

from pytz import UTC
from sideboard.lib import cached_property
from sideboard.lib.sa import CoerceUTF8 as UnicodeText, UTCDateTime, UUID

from uber.custom_tags import safe_string
from uber.models import MagModel
from uber.models.types import DefaultColumn as Column


__all__ = ['ApprovedEmail', 'Email']


class ApprovedEmail(MagModel):
    ident = Column(UnicodeText)

    _repr_attr_names = ['ident']


class Email(MagModel):
    fk_id = Column(UUID, nullable=True)
    ident = Column(UnicodeText)
    model = Column(UnicodeText)
    when = Column(UTCDateTime, default=lambda: datetime.now(UTC))
    subject = Column(UnicodeText)
    dest = Column(UnicodeText)
    body = Column(UnicodeText)

    _repr_attr_names = ['subject']

    @cached_property
    def fk(self):
        try:
            from uber.models import Session
            model_class = Session.resolve_model(self.model)
            query = self.session.query(model_class)
            return query.filter_by(id=self.fk_id).first()
        except:
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
        return self.dest or None

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
