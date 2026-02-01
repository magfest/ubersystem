from sqlalchemy.dialects.postgresql.json import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import Boolean, Integer, Uuid, String, DateTime


from uber.models import MagModel
from uber.models.types import DefaultColumn as Column, default_relationship as relationship


__all__ = ['PrintJob']


class PrintJob(MagModel):
    attendee_id = Column(Uuid(as_uuid=False), ForeignKey('attendee.id'))
    admin_id = Column(Uuid(as_uuid=False), ForeignKey('admin_account.id'), nullable=True)
    admin_name = Column(String)  # Preserve admin's name in case their account is removed
    printer_id = Column(String)
    reg_station = Column(Integer, nullable=True)
    print_fee = Column(Integer, default=0)
    queued = Column(DateTime(timezone=True), nullable=True, default=None)
    printed = Column(DateTime(timezone=True), nullable=True, default=None)
    ready = Column(Boolean, default=True)
    errors = Column(String)
    is_minor = Column(Boolean)
    json_data = Column(MutableDict.as_mutable(JSONB), default={})
    receipt_item = relationship('ReceiptItem',
                                primaryjoin='and_('
                                            'ReceiptItem.fk_model == "PrintJob", '
                                            'ReceiptItem.fk_id == foreign(PrintJob.id))',
                                viewonly=True,
                                uselist=False)
