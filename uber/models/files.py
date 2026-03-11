from datetime import datetime
from markupsafe import Markup
from sqlalchemy.dialects.postgresql.json import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.types import Uuid, DateTime

from uber.decorators import presave_adjustment
from uber.models import MagModel
from uber.models.types import DefaultField as Field

__all__ = ['SignedDocument', 'File']


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


class File(MagModel, table=True):
    fk_id: str = Field(sa_type=Uuid(as_uuid=False))
    fk_model: str = ''
    description: str = ''
    filename: str = ''
    content_type: str = ''
    extension: str = ''  # Used in exports since we do not use the original filename
    filepath: str = ''
    download_url: str = ''  # Not used for server files
    flags: dict[str, bool] = Field(sa_type=MutableDict.as_mutable(JSONB), default_factory=dict)

    @property
    def true_flags(self):
        return [key for key in self.flags.keys() if self.flags[key]]

    @property
    def url(self):
        return f"../services/download_file?id={self.id}"
    
    @property
    def html_link(self):
        if not self.filename:
            return ''
        return Markup(
            f"""<a href="{self.url}" target="_blank">{self.filename}</a>""")
    
    @property
    def preview_image(self):
        if not self.filename:
            return ''
        return Markup(
            f"""<a href="{self.url}" target="_blank"><img class="img-fluid" src="{self.url}&preview=True" /></a>""")

    @property
    def preview_image_with_filename(self):
        if not self.filename:
            return ''
        return Markup(
            f"""<a href="{self.url}" target="_blank"><img class="img-fluid" src="{self.url}&preview=True" /><br/>{self.filename}</a>""")
