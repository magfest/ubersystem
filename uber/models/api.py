import uuid
from datetime import datetime

from pytz import UTC
from sideboard.lib.sa import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy.schema import ForeignKey

from uber.config import c
from uber.models import MagModel
from uber.models.types import DefaultColumn as Column, MultiChoice


__all__ = ['ApiToken']


class ApiToken(MagModel):
    admin_account_id = Column(UUID, ForeignKey('admin_account.id'))
    token = Column(UUID, default=lambda: str(uuid.uuid4()), private=True)
    access = Column(MultiChoice(c.API_ACCESS_OPTS))
    name = Column(UnicodeText)
    description = Column(UnicodeText)
    issued_time = Column(UTCDateTime, default=lambda: datetime.now(UTC))
    revoked_time = Column(UTCDateTime, default=None, nullable=True)
