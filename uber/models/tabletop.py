from datetime import datetime, timedelta

from pytz import UTC
from residue import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy.schema import ForeignKey, UniqueConstraint
from sqlalchemy.types import Boolean

from uber.config import c
from uber.decorators import presave_adjustment
from uber.models import MagModel
from uber.models.types import default_relationship as relationship, DefaultColumn as Column
from uber.utils import localized_now, normalize_phone


__all__ = [
    'TabletopGame', 'TabletopCheckout', 'TabletopTournament',
    'TabletopEntrant', 'TabletopSmsReminder', 'TabletopSmsReply']


class TabletopGame(MagModel):
    code = Column(UnicodeText)
    name = Column(UnicodeText)
    attendee_id = Column(UUID, ForeignKey('attendee.id'))
    returned = Column(Boolean, default=False)
    checkouts = relationship('TabletopCheckout', backref='game')

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


class TabletopTournament(MagModel):
    event_id = Column(UUID, ForeignKey('event.id'), unique=True)

    # Separate from the event name for cases where we want a shorter name in our SMS messages.
    name = Column(UnicodeText)

    entrants = relationship('TabletopEntrant', backref='tournament')


class TabletopEntrant(MagModel):
    tournament_id = Column(UUID, ForeignKey('tabletop_tournament.id'))
    attendee_id = Column(UUID, ForeignKey('attendee.id'))
    signed_up = Column(UTCDateTime, default=lambda: datetime.now(UTC))
    confirmed = Column(Boolean, default=False)

    reminder = relationship('TabletopSmsReminder', backref='entrant', uselist=False)
    replies = relationship('TabletopSmsReply', backref='entrant')

    @presave_adjustment
    def _within_cutoff(self):
        if self.is_new:
            tournament = self.tournament or self.session.tabletop_tournament(self.tournament_id)
            cutoff = timedelta(minutes=c.TABLETOP_SMS_CUTOFF_MINUTES)
            if self.signed_up > tournament.event.start_time - cutoff:
                self.confirmed = True

    @property
    def should_send_reminder(self):
        stagger = timedelta(minutes=c.TABLETOP_SMS_STAGGER_MINUTES)
        reminder = timedelta(minutes=c.TABLETOP_SMS_REMINDER_MINUTES)
        return not self.confirmed \
            and not self.reminder \
            and localized_now() < self.tournament.event.start_time \
            and localized_now() > self.signed_up + stagger \
            and localized_now() > self.tournament.event.start_time - reminder

    def matches(self, message):
        sent = message.date_sent.replace(tzinfo=UTC)
        start_time_slack = timedelta(minutes=c.TABLETOP_TOURNAMENT_SLACK)
        return normalize_phone(self.attendee.cellphone) == message.from_ \
            and self.reminder and sent > self.reminder.when \
            and sent < self.tournament.event.start_time + start_time_slack

    __table_args__ = (
        UniqueConstraint('tournament_id', 'attendee_id', name='_tournament_entrant_uniq'),
    )


class TabletopSmsReminder(MagModel):
    entrant_id = Column(UUID, ForeignKey('tabletop_entrant.id'), unique=True)
    sid = Column(UnicodeText)
    when = Column(UTCDateTime, default=lambda: datetime.now(UTC))
    text = Column(UnicodeText)


class TabletopSmsReply(MagModel):
    entrant_id = Column(UUID, ForeignKey('tabletop_entrant.id'), nullable=True)
    sid = Column(UnicodeText)
    when = Column(UTCDateTime)
    text = Column(UnicodeText)
