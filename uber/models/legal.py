from residue import CoerceUTF8 as UnicodeText, UTCDateTime, UUID

from uber.decorators import presave_adjustment
from uber.models import MagModel
from uber.models.types import DefaultColumn as Column

__all__ = ['SignedDocument']


class SignedDocument(MagModel):
    fk_id = Column(UUID, index=True)
    model = Column(UnicodeText)
    document_id = Column(UnicodeText)
    last_emailed = Column(UTCDateTime, nullable=True, default=None)
    link = Column(UnicodeText)
    ident = Column(UnicodeText)
    signed = Column(UTCDateTime, nullable=True, default=None)
    declined = Column(UTCDateTime, nullable=True, default=None)

    @presave_adjustment
    def null_to_strings(self):
        if not self.document_id:
            self.document_id = ""
        if not self.link:
            self.link = ''
