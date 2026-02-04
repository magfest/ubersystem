import uuid
from datetime import datetime

from pytz import UTC
from sqlalchemy import String, Uuid, DateTime
from sqlalchemy.schema import ForeignKey
from sqlalchemy.dialects.postgresql.json import JSONB
from sqlalchemy.ext.mutable import MutableDict

from uber.config import c
from uber.models import MagModel
from uber.models.types import DefaultColumn as Column, MultiChoice


__all__ = ['ApiToken', 'ApiJob']


class ApiToken(MagModel):
    admin_account_id = Column(Uuid(as_uuid=False), ForeignKey('admin_account.id'))
    token = Column(Uuid(as_uuid=False), default=lambda: str(uuid.uuid4()), private=True)
    access = Column(MultiChoice(c.API_ACCESS_OPTS))
    name = Column(String)
    description = Column(String)
    issued_time = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    revoked_time = Column(DateTime(timezone=True), default=None, nullable=True)

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
    admin_id = Column(Uuid(as_uuid=False), ForeignKey('admin_account.id'), nullable=True)
    admin_name = Column(String)  # Preserve admin's name in case their account is removed
    queued = Column(DateTime(timezone=True), nullable=True, default=None)
    completed = Column(DateTime(timezone=True), nullable=True, default=None)
    cancelled = Column(DateTime(timezone=True), nullable=True, default=None)
    job_name = Column(String)
    target_server = Column(String)
    query = Column(String)
    api_token = Column(String)
    errors = Column(String)
    json_data = Column(MutableDict.as_mutable(JSONB), default={})
