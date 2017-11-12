from datetime import datetime

from pytz import UTC
from sideboard.lib.sa import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy.schema import ForeignKey, Index

from uber.config import c
from uber.models import MagModel
from uber.models.types import DefaultColumn as Column, MultiChoice


__all__ = ['ApiToken']


class ApiToken(MagModel):
    admin_account_id = Column(UUID, ForeignKey('admin_account.id'))
    access = Column(MultiChoice(c.API_ACCESS_OPTS))
    name = Column(UnicodeText)
    description = Column(UnicodeText)
    issued_time = Column(UTCDateTime, default=lambda: datetime.now(UTC))
    revoked_time = Column(UTCDateTime, default=None, nullable=True)

    __table_args__ = (
        Index('ix_api_token_id_revoked_time', 'id', 'revoked_time'),
    )
