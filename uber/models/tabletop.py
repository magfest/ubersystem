from datetime import datetime

from pytz import UTC
from sqlalchemy.types import Boolean, DateTime, String, Uuid
from sqlmodel import Field, Relationship
from typing import ClassVar

from uber.models import MagModel
from uber.models.types import default_relationship as relationship, DefaultColumn as Column


__all__ = ['TabletopGame', 'TabletopCheckout']


class TabletopGame(MagModel, table=True):
    attendee_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='attendee.id', ondelete='CASCADE')
    attendee: 'Attendee' = Relationship(back_populates="games")

    code: str = Column(String)
    name: str = Column(String)
    returned: bool = Column(Boolean, default=False)

    checkouts: list['TabletopCheckout'] = Relationship(
        back_populates="game", sa_relationship_kwargs={'order_by': 'TabletopCheckout.checked_out', 'passive_deletes': True})

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

    game_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='tabletop_game.id', ondelete='CASCADE')
    game: 'TabletopGame' = Relationship(back_populates="checkouts", sa_relationship_kwargs={'lazy': 'joined'})

    attendee_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='attendee.id', ondelete='CASCADE')
    attendee: 'Attendee' = Relationship(back_populates="checkouts", sa_relationship_kwargs={'lazy': 'joined'})

    checked_out: datetime = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    returned: datetime | None = Column(DateTime(timezone=True), nullable=True)
