from datetime import datetime

from pytz import UTC
from sqlalchemy.orm import backref
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import Boolean, DateTime, String, Uuid
from sqlmodel import Field, Relationship
from typing import ClassVar

from uber.models import MagModel
from uber.models.types import default_relationship as relationship, DefaultColumn as Column


__all__ = ['TabletopGame', 'TabletopCheckout']


class TabletopGame(MagModel, table=True):
    code: str = Column(String)
    name: str = Column(String)
    attendee_id: str | None = Field(sa_column=Column(Uuid(as_uuid=False), ForeignKey('attendee.id')))
    returned: bool = Column(Boolean, default=False)
    checkouts: list['TabletopCheckout'] = Relationship(sa_relationship=relationship('TabletopCheckout', order_by='TabletopCheckout.checked_out', backref=backref('game', lazy='joined')))

    _repr_attr_names: ClassVar = ['name']

    @property
    def checked_out(self):
        try:
            return [c for c in self.checkouts if not c.returned][0]
        except Exception:
            pass


class TabletopCheckout(MagModel, table=True):
    """
    Attendee: joined
    TabletopGame: joined
    """

    game_id: str | None = Field(sa_column=Column(Uuid(as_uuid=False), ForeignKey('tabletop_game.id')))
    attendee_id: str | None = Field(sa_column=Column(Uuid(as_uuid=False), ForeignKey('attendee.id')))
    checked_out: datetime = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    returned: datetime | None = Column(DateTime(timezone=True), nullable=True)
