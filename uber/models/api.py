from sideboard.lib.sa import UTCDateTime, UUID
from sqlalchemy.schema import ForeignKey, Index

from uber.models import MagModel
from uber.models.types import DefaultColumn as Column


__all__ = ['ApiToken']


class ApiToken(MagModel):
    admin_account_id = Column(UUID, ForeignKey('admin_account.id'))
    issued_time = Column(UTCDateTime)
    revoked_time = Column(UTCDateTime, default=None, nullable=True)

    __table_args__ = (
        Index('ix_api_token_id_revoked_time', 'id', 'revoked_time'),
    )
