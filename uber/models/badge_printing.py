from datetime import datetime
from sqlalchemy.dialects.postgresql.json import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import Boolean, Integer, Uuid, String, DateTime
from sqlmodel import Field, Relationship
from typing import Any

from uber.models import MagModel
from uber.models.types import DefaultColumn as Column, default_relationship as relationship


__all__ = ['PrintJob']


class PrintJob(MagModel, table=True):
    """
    Attendee: joined
    """
    
    attendee_id: str | None = Column(Uuid(as_uuid=False), ForeignKey('attendee.id'))
    admin_id: str | None = Column(Uuid(as_uuid=False), ForeignKey('admin_account.id'), nullable=True)

    admin_name: str = Column(String)  # Preserve admin's name in case their account is removed
    printer_id: str = Column(String)
    reg_station: int | None = Column(Integer, nullable=True)
    print_fee: int = Column(Integer, default=0)
    queued: datetime | None = Column(DateTime(timezone=True), nullable=True, default=None)
    printed: datetime | None = Column(DateTime(timezone=True), nullable=True, default=None)
    ready: bool = Column(Boolean, default=True)
    errors: str = Column(String)
    is_minor: bool = Column(Boolean)
    json_data: dict[str, Any] = Field(sa_type=MutableDict.as_mutable(JSONB), default_factory=dict)
    receipt_item: 'ReceiptItem' = Relationship(sa_relationship=relationship('ReceiptItem',
                                primaryjoin='and_('
                                            'ReceiptItem.fk_model == "PrintJob", '
                                            'ReceiptItem.fk_id == foreign(PrintJob.id))',
                                viewonly=True,
                                uselist=False))
