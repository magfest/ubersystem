import uuid
from datetime import datetime

from pytz import UTC
from sqlalchemy import String, Uuid, DateTime
from sqlalchemy.dialects.postgresql.json import JSONB
from sqlalchemy.ext.mutable import MutableDict
from typing import Any

from uber.config import c
from uber.models import MagModel
from uber.models.types import DefaultColumn as Column, MultiChoice, DefaultField as Field, DefaultRelationship as Relationship


__all__ = ['ApiToken', 'ApiJob']


class ApiToken(MagModel, table=True):
    """
    AdminAccount: joined
    """

    admin_account_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='admin_account.id', ondelete='CASCADE')
    admin_account: "AdminAccount" = Relationship(back_populates="api_tokens", sa_relationship_kwargs={'lazy': 'joined'})

    token: str | None = Field(sa_type=Uuid(as_uuid=False), default_factory=lambda: str(uuid.uuid4()), private=True)
    access: str = Field(sa_type=MultiChoice(c.API_ACCESS_OPTS), default='')
    name: str = ''
    description: str = ''
    issued_time: datetime = Field(sa_type=DateTime(timezone=True), default_factory=lambda: datetime.now(UTC))
    revoked_time: datetime = Field(sa_type=DateTime(timezone=True), default=None, nullable=True)

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


class ApiJob(MagModel, table=True):
    admin_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='admin_account.id', nullable=True)
    admin_account: "AdminAccount" = Relationship(back_populates="api_jobs")

    admin_name: str = ''  # Preserve admin's name in case their account is removed
    queued: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True, default=None)
    completed: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True, default=None)
    cancelled: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True, default=None)
    job_name: str = ''
    target_server: str = ''
    query: str = ''
    api_token: str = ''
    errors: str = ''
    json_data: dict[str, Any] = Field(sa_type=MutableDict.as_mutable(JSONB), default_factory=dict)
