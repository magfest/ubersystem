"""
NO LONGER USED.

The attendee_tournaments module is no longer used, but has been
included for backward compatibility with legacy servers.
"""

from sqlalchemy import func
from sqlalchemy.types import Boolean, String

from uber.config import c
from uber.models import MagModel, Attendee
from uber.models.types import Choice, DefaultColumn as Column, MultiChoice


__all__ = ['AttendeeTournament']


class AttendeeTournament(MagModel):
    first_name = Column(String)
    last_name = Column(String)
    email = Column(String)
    cellphone = Column(String)
    game = Column(String)
    availability = Column(MultiChoice(c.TOURNAMENT_AVAILABILITY_OPTS))
    format = Column(String)
    experience = Column(String)
    needs = Column(String)
    why = Column(String)
    volunteering = Column(Boolean, default=False)

    status = Column(Choice(c.TOURNAMENT_STATUS_OPTS), default=c.NEW, admin_only=True)

    email_model_name = 'app'

    @property
    def full_name(self):
        return self.first_name + ' ' + self.last_name

    @property
    def matching_attendee(self):
        return self.session.query(Attendee).filter(
            Attendee.first_name == self.first_name.title(),
            Attendee.last_name == self.last_name.title(),
            func.lower(Attendee.email) == self.email.lower()
        ).first()
