from datetime import timedelta

from residue import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy.orm import backref
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import Boolean, Integer
from sqlalchemy.ext.hybrid import hybrid_property

from uber.config import c
from uber.models import MagModel
from uber.models.types import default_relationship as relationship, utcnow, Choice, DefaultColumn as Column, \
    MultiChoice, SocialMediaMixin


__all__ = ['AssignedPanelist', 'Event', 'EventFeedback', 'PanelApplicant', 'PanelApplication']


class Event(MagModel):
    location = Column(Choice(c.EVENT_LOCATION_OPTS))
    start_time = Column(UTCDateTime)
    duration = Column(Integer)  # half-hour increments
    name = Column(UnicodeText, nullable=False)
    description = Column(UnicodeText)

    assigned_panelists = relationship('AssignedPanelist', backref='event')
    applications = relationship('PanelApplication', backref=backref('event', cascade="save-update,merge"), 
                                cascade="save-update,merge")
    panel_feedback = relationship('EventFeedback', backref='event')
    tournaments = relationship('TabletopTournament', backref='event', uselist=False)
    guest = relationship('GuestGroup', backref=backref('event', cascade="save-update,merge"),
                         cascade='save-update,merge')

    @property
    def half_hours(self):
        half_hours = set()
        for i in range(self.duration):
            half_hours.add(self.start_time + timedelta(minutes=30 * i))
        return half_hours

    @property
    def minutes(self):
        return (self.duration or 0) * 30

    @property
    def start_slot(self):
        if self.start_time:
            start_delta = self.start_time_local - c.EPOCH
            return int(start_delta.total_seconds() / (60 * 30))

    @property
    def end_time(self):
        return self.start_time + timedelta(minutes=self.minutes)

    @property
    def guidebook_name(self):
        return self.name

    @property
    def guidebook_subtitle(self):
        # Note: not everything on this list is actually exported
        if self.location in c.PANEL_ROOMS:
            return 'Panel'
        if self.location in c.MUSIC_ROOMS:
            return 'Music'
        if self.location in c.TABLETOP_LOCATIONS:
            return 'Tabletop Event'
        if "Autograph" in self.location_label:
            return 'Autograph Session'

    @property
    def guidebook_desc(self):
        panelists_creds = '<br/><br/>' + '<br/><br/>'.join(
            a.other_credentials for a in self.applications[0].applicants if a.other_credentials
        ) if self.applications else ''
        return self.description + panelists_creds

    @property
    def guidebook_location(self):
        return self.event.location_label


class AssignedPanelist(MagModel):
    attendee_id = Column(UUID, ForeignKey('attendee.id', ondelete='cascade'))
    event_id = Column(UUID, ForeignKey('event.id', ondelete='cascade'))

    def __repr__(self):
        if self.attendee:
            return '<{} panelisting {}>'.format(
                self.attendee.full_name, self.event.name)
        else:
            return super(AssignedPanelist, self).__repr__()


class PanelApplication(MagModel):
    event_id = Column(UUID, ForeignKey('event.id', ondelete='SET NULL'), nullable=True)
    poc_id = Column(UUID, ForeignKey('attendee.id', ondelete='SET NULL'), nullable=True)
    name = Column(UnicodeText)
    length = Column(Choice(c.PANEL_LENGTH_OPTS), default=c.SIXTY_MIN)
    length_text = Column(UnicodeText)
    length_reason = Column(UnicodeText)
    description = Column(UnicodeText)
    unavailable = Column(UnicodeText)
    available = Column(UnicodeText)
    affiliations = Column(UnicodeText)
    past_attendance = Column(UnicodeText)
    presentation = Column(Choice(c.PRESENTATION_OPTS))
    other_presentation = Column(UnicodeText)
    tech_needs = Column(MultiChoice(c.TECH_NEED_OPTS))
    other_tech_needs = Column(UnicodeText)
    need_tables = Column(Boolean, default=False)
    tables_desc = Column(UnicodeText)
    has_cost = Column(Boolean, default=False)
    is_loud = Column(Boolean, default=False)
    cost_desc = Column(UnicodeText)
    livestream = Column(Choice(c.LIVESTREAM_OPTS), default=c.OPT_IN)
    panelist_bringing = Column(UnicodeText)
    extra_info = Column(UnicodeText)
    applied = Column(UTCDateTime, server_default=utcnow())
    status = Column(Choice(c.PANEL_APP_STATUS_OPTS), default=c.PENDING, admin_only=True)
    comments = Column(UnicodeText, admin_only=True)

    applicants = relationship('PanelApplicant', backref='application')

    email_model_name = 'app'

    @property
    def email(self):
        return self.submitter and self.submitter.email

    @property
    def submitter(self):
        for a in self.applicants:
            if a.submitter:
                return a
        return None

    @property
    def other_panelists(self):
        return [a for a in self.applicants if not a.submitter]

    @property
    def matched_attendees(self):
        return [a.attendee for a in self.applicants if a.attendee_id]

    @property
    def unmatched_applicants(self):
        return [a for a in self.applicants if not a.attendee_id]

    @hybrid_property
    def has_been_accepted(self):
        return self.status == c.ACCEPTED


class PanelApplicant(SocialMediaMixin, MagModel):
    app_id = Column(UUID, ForeignKey('panel_application.id', ondelete='cascade'))
    attendee_id = Column(UUID, ForeignKey('attendee.id', ondelete='cascade'), nullable=True)
    submitter = Column(Boolean, default=False)
    first_name = Column(UnicodeText)
    last_name = Column(UnicodeText)
    email = Column(UnicodeText)
    cellphone = Column(UnicodeText)
    communication_pref = Column(MultiChoice(c.COMMUNICATION_PREF_OPTS))
    other_communication_pref = Column(UnicodeText)
    pronouns = Column(MultiChoice(c.PRONOUN_OPTS))
    other_pronouns = Column(UnicodeText)
    occupation = Column(UnicodeText)
    website = Column(UnicodeText)
    other_credentials = Column(UnicodeText)

    @property
    def has_credentials(self):
        return any([self.occupation, self.website, self.other_credentials])

    @property
    def full_name(self):
        return self.first_name + ' ' + self.last_name


class EventFeedback(MagModel):
    event_id = Column(UUID, ForeignKey('event.id'))
    attendee_id = Column(UUID, ForeignKey('attendee.id', ondelete='cascade'))
    headcount_starting = Column(Integer, default=0)
    headcount_during = Column(Integer, default=0)
    comments = Column(UnicodeText)
    rating = Column(Choice(c.PANEL_RATING_OPTS), default=c.UNRATED)
