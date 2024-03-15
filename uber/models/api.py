import uuid
from datetime import datetime

from pytz import UTC
from residue import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy.schema import ForeignKey
from sqlalchemy.dialects.postgresql.json import JSONB
from sqlalchemy.ext.mutable import MutableDict

from uber.config import c
from uber.models import MagModel
from uber.models.types import DefaultColumn as Column, MultiChoice


__all__ = ['ApiToken', 'ApiJob']


class ApiToken(MagModel):
    admin_account_id = Column(UUID, ForeignKey('admin_account.id'))
    token = Column(UUID, default=lambda: str(uuid.uuid4()), private=True)
    access = Column(MultiChoice(c.API_ACCESS_OPTS))
    name = Column(UnicodeText)
    description = Column(UnicodeText)
    issued_time = Column(UTCDateTime, default=lambda: datetime.now(UTC))
    revoked_time = Column(UTCDateTime, default=None, nullable=True)

    @property
    def api_read(self):
        return c.API_READ in self.access_ints

    @property
    def api_update(self):
        return c.API_UPDATE in self.access_ints

    @property
    def api_create(self):
        return c.API_CREATE in self.access_ints

    @property
    def api_delete(self):
        return c.API_DELETE in self.access_ints


class ApiJob(MagModel):
    admin_id = Column(UUID, ForeignKey('admin_account.id'), nullable=True)
    admin_name = Column(UnicodeText)  # Preserve admin's name in case their account is removed
    queued = Column(UTCDateTime, nullable=True, default=None)
    completed = Column(UTCDateTime, nullable=True, default=None)
    cancelled = Column(UTCDateTime, nullable=True, default=None)
    job_name = Column(UnicodeText)
    target_server = Column(UnicodeText)
    query = Column(UnicodeText)
    api_token = Column(UnicodeText)
    errors = Column(UnicodeText)
    json_data = Column(MutableDict.as_mutable(JSONB), default={})
