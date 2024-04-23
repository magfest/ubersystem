from sqlalchemy.types import UnicodeText, DateTime, UUID

from uber.decorators import presave_adjustment
from uber.models import MagModel
from uber.models.types import DefaultColumn as Column

__all__ = ['SignedDocument']


class SignedDocument(MagModel):
    fk_id = Column(UUID, index=True)
    model = Column(UnicodeText)
    document_id = Column(UnicodeText)
    last_emailed = Column(DateTime, nullable=True, default=None)
    link = Column(UnicodeText)
    ident = Column(UnicodeText)
    signed = Column(DateTime, nullable=True, default=None)
    declined = Column(DateTime, nullable=True, default=None)

    @presave_adjustment
    def null_to_strings(self):
        if not self.document_id:
            self.document_id = ""
        if not self.link:
            self.link = ''
