import uuid
from datetime import datetime

from pytz import UTC
from sqlalchemy import String, Uuid, DateTime
from sqlalchemy.dialects.postgresql.json import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlmodel import Field, Relationship
from typing import Any

from uber.config import c
from uber.models import MagModel
from uber.models.types import DefaultColumn as Column, MultiChoice


__all__ = ['ApiToken', 'ApiJob']


class ApiToken(MagModel, table=True):
    """
    AdminAccount: joined
    """

    admin_account_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='admin_account.id', ondelete='CASCADE')
    admin_account: "AdminAccount" = Relationship(back_populates="api_tokens", sa_relationship_kwargs={'lazy': 'joined'})

    token: str | None = Column(Uuid(as_uuid=False), default=lambda: str(uuid.uuid4()), private=True)
    access: str = Column(MultiChoice(c.API_ACCESS_OPTS))
    name: str = Column(String)
    description: str = Column(String)
    issued_time: datetime = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    revoked_time: datetime = Column(DateTime(timezone=True), default=None, nullable=True)

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

    admin_name: str = Column(String)  # Preserve admin's name in case their account is removed
    queued: datetime | None = Column(DateTime(timezone=True), nullable=True, default=None)
    completed: datetime | None = Column(DateTime(timezone=True), nullable=True, default=None)
    cancelled: datetime | None = Column(DateTime(timezone=True), nullable=True, default=None)
    job_name: str = Column(String)
    target_server: str = Column(String)
    query: str = Column(String)
    api_token: str = Column(String)
    errors: str = Column(String)
    json_data: dict[str, Any] = Field(sa_type=MutableDict.as_mutable(JSONB), default_factory=dict)
