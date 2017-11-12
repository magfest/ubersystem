from sideboard.lib.sa import UTCDateTime, UUID
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import Boolean

from uber.models import MagModel
from uber.models.types import default_relationship as relationship, \
    DefaultColumn as Column


__all__ = ['ApiToken']


class ApiToken(MagModel):
    admin_account_id = Column(UUID, ForeignKey('admin_account.id'))
    issued_time = Column(UTCDateTime)
    is_revoked = Column(Boolean, default=False)
