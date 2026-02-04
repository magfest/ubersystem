from sqlalchemy.types import Uuid, String, DateTime

from uber.decorators import presave_adjustment
from uber.models import MagModel
from uber.models.types import DefaultColumn as Column

__all__ = ['SignedDocument']


class SignedDocument(MagModel):
    fk_id = Column(Uuid(as_uuid=False), index=True)
    model = Column(String)
    document_id = Column(String)
    last_emailed = Column(DateTime(timezone=True), nullable=True, default=None)
    link = Column(String)
    ident = Column(String)
    signed = Column(DateTime(timezone=True), nullable=True, default=None)
    declined = Column(DateTime(timezone=True), nullable=True, default=None)

    @presave_adjustment
    def null_to_strings(self):
        if not self.document_id:
            self.document_id = ""
        if not self.link:
            self.link = ''
