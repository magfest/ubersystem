from datetime import datetime

from pytz import UTC
from residue import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import Boolean

from uber.models import MagModel
from uber.models.types import default_relationship as relationship, DefaultColumn as Column


__all__ = ['TabletopGame', 'TabletopCheckout']


class TabletopGame(MagModel):
    code = Column(UnicodeText)
    name = Column(UnicodeText)
    attendee_id = Column(UUID, ForeignKey('attendee.id'))
    returned = Column(Boolean, default=False)
    checkouts = relationship('TabletopCheckout', order_by='TabletopCheckout.checked_out', backref='game')

    _repr_attr_names = ['name']

    @property
    def checked_out(self):
        try:
            return [c for c in self.checkouts if not c.returned][0]
        except Exception:
            pass


class TabletopCheckout(MagModel):
    game_id = Column(UUID, ForeignKey('tabletop_game.id'))
    attendee_id = Column(UUID, ForeignKey('attendee.id'))
    checked_out = Column(UTCDateTime, default=lambda: datetime.now(UTC))
    returned = Column(UTCDateTime, nullable=True)
