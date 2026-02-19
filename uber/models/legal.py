from datetime import datetime
from sqlalchemy.types import Uuid, String, DateTime

from uber.decorators import presave_adjustment
from uber.models import MagModel
from uber.models.types import DefaultField as Field

__all__ = ['SignedDocument']


class SignedDocument(MagModel, table=True):
    fk_id: str = Field(sa_type=Uuid(as_uuid=False), index=True)
    model: str = ''
    document_id: str = ''
    last_emailed: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True, default=None)
    link: str = ''
    ident: str = ''
    signed: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True, default=None)
    declined: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True, default=None)

    @presave_adjustment
    def null_to_strings(self):
        if not self.document_id:
            self.document_id = ""
        if not self.link:
            self.link = ''
