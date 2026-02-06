from datetime import datetime

from pytz import UTC
from sqlalchemy.orm import backref
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import Boolean, DateTime, String, Uuid

from uber.models import MagModel
from uber.models.types import default_relationship as relationship, DefaultColumn as Column


__all__ = ['TabletopGame', 'TabletopCheckout']


class TabletopGame(MagModel):
    code = Column(String)
    name = Column(String)
    attendee_id = Column(Uuid(as_uuid=False), ForeignKey('attendee.id'))
    returned = Column(Boolean, default=False)
    checkouts = relationship('TabletopCheckout', order_by='TabletopCheckout.checked_out', backref=backref('game', lazy='joined'))

    _repr_attr_names = ['name']

    @property
    def checked_out(self):
        try:
            return [c for c in self.checkouts if not c.returned][0]
        except Exception:
            pass


class TabletopCheckout(MagModel):
    game_id = Column(Uuid(as_uuid=False), ForeignKey('tabletop_game.id'))
    attendee_id = Column(Uuid(as_uuid=False), ForeignKey('attendee.id'))
    checked_out = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    returned = Column(DateTime(timezone=True), nullable=True)
