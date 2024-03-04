from residue import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy.dialects.postgresql.json import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import Boolean, Integer

from uber.models import MagModel
from uber.models.types import DefaultColumn as Column


__all__ = ['PrintJob']


class PrintJob(MagModel):
    attendee_id = Column(UUID, ForeignKey('attendee.id'))
    admin_id = Column(UUID, ForeignKey('admin_account.id'), nullable=True)
    admin_name = Column(UnicodeText)  # Preserve admin's name in case their account is removed
    printer_id = Column(UnicodeText)
    reg_station = Column(Integer, nullable=True)
    print_fee = Column(Integer, default=0)
    queued = Column(UTCDateTime, nullable=True, default=None)
    printed = Column(UTCDateTime, nullable=True, default=None)
    errors = Column(UnicodeText)
    is_minor = Column(Boolean)
    json_data = Column(MutableDict.as_mutable(JSONB), default={})
