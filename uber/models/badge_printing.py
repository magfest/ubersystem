from datetime import datetime
from sqlalchemy.dialects.postgresql.json import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.types import Boolean, Integer, Uuid, String, DateTime
from typing import Any

from uber.models import MagModel
from uber.models.types import default_relationship as relationship, DefaultField as Field, DefaultRelationship as Relationship


__all__ = ['PrintJob']


class PrintJob(MagModel, table=True):
    """
    Attendee: joined
    """
    
    attendee_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='attendee.id', ondelete='CASCADE')
    attendee: 'Attendee' = Relationship(back_populates="print_requests", sa_relationship_kwargs={'lazy': 'joined'})

    admin_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='admin_account.id', nullable=True)
    admin_account: "AdminAccount" = Relationship(back_populates="print_requests")

    admin_name: str = ''  # Preserve admin's name in case their account is removed
    printer_id: str = ''
    reg_station: int | None = Field(nullable=True)
    print_fee: int = 0
    queued: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True, default=None)
    printed: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True, default=None)
    ready: bool = True
    errors: str = ''
    is_minor: bool = False
    json_data: dict[str, Any] = Field(sa_type=MutableDict.as_mutable(JSONB), default_factory=dict)
    receipt_item: 'ReceiptItem' = Relationship(sa_relationship=relationship('ReceiptItem',
                                primaryjoin='and_('
                                            'ReceiptItem.fk_model == "PrintJob", '
                                            'ReceiptItem.fk_id == foreign(PrintJob.id))',
                                viewonly=True,
                                uselist=False))
