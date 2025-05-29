from datetime import datetime, timedelta

from pytz import UTC
from residue import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy.orm import backref
from sqlalchemy.schema import ForeignKey, Table, UniqueConstraint, Index
from sqlalchemy.types import Boolean, Integer
from sqlalchemy.ext.hybrid import hybrid_property

from uber.config import c
from uber.decorators import presave_adjustment
from uber.models import MagModel
from uber.models.types import default_relationship as relationship, utcnow, Choice, DefaultColumn as Column, \
    MultiChoice, SocialMediaMixin, UniqueList


__all__ = ['AssignedPanelist', 'Event', 'EventFeedback', 'PanelApplicant', 'PanelApplication']


# Many to many association table to tie Panel Applicants with Panel Applications
panel_applicant_application = Table(
    'panel_applicant_application',
    MagModel.metadata,
    Column('panel_applicant_id', UUID, ForeignKey('panel_applicant.id')),
    Column('panel_application_id', UUID, ForeignKey('panel_application.id')),
    UniqueConstraint('panel_applicant_id', 'panel_application_id'),
    Index('ix_admin_panel_application_panel_applicant_id', 'panel_applicant_id'),
    Index('ix_admin_panel_application_panel_application_id', 'panel_application_id'),
)


class Event(MagModel):
    location = Column(Choice(c.EVENT_LOCATION_OPTS))
    start_time = Column(UTCDateTime)
    duration = Column(Integer, default=60)
    name = Column(UnicodeText, nullable=False)
    description = Column(UnicodeText)
    public_description = Column(UnicodeText)
    track = Column(UnicodeText)

    assigned_panelists = relationship('AssignedPanelist', backref='event')
    applications = relationship('PanelApplication', backref=backref('event', cascade="save-update,merge"),
                                cascade="save-update,merge")
    panel_feedback = relationship('EventFeedback', backref='event')
    guest = relationship('GuestGroup', backref=backref('event', cascade="save-update,merge"),
                         cascade='save-update,merge')

    @property
    def minutes(self):
        minutes = set()
        for i in range(int(self.duration)):
            minutes.add(self.start_time + timedelta(minutes=i))
        return minutes

    @property
    def end_time(self):
        return self.start_time + timedelta(minutes=self.duration)

    @property
    def guidebook_data(self):
        # This is for a Guidebook Sessions export, so it's not the same as a custom list
        from uber.utils import normalize_newlines

        description = self.public_description or self.description

        return {
            'name': self.name,
            'start_date': self.start_time_local.strftime('%m/%d/%Y'),
            'start_time': self.start_time_local.strftime('%I:%M %p'),
            'end_date': self.end_time_local.strftime('%m/%d/%Y'),
            'end_time': self.end_time_local.strftime('%I:%M %p'),
            'location': self.location_label,
            'track': self.track,
            'description': description,
            }

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
        return self.public_description or self.description


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
    submitter_id = Column(UUID, ForeignKey('panel_applicant.id', ondelete='SET NULL'), nullable=True)
    name = Column(UnicodeText)
    length = Column(Choice(c.PANEL_LENGTH_OPTS), default=c.SIXTY_MIN)
    length_text = Column(UnicodeText)
    length_reason = Column(UnicodeText)
    description = Column(UnicodeText)
    public_description = Column(UnicodeText)
    unavailable = Column(UnicodeText)
    available = Column(UnicodeText)
    affiliations = Column(UnicodeText)
    past_attendance = Column(UnicodeText)
    department = Column(UniqueList)
    department_name = Column(UnicodeText)
    rating = Column(Choice(c.PANEL_RATING_OPTS), default=c.UNRATED)
    granular_rating = Column(MultiChoice(c.PANEL_CONTENT_OPTS))
    presentation = Column(Choice(c.PRESENTATION_OPTS))
    other_presentation = Column(UnicodeText)
    noise_level = Column(Choice(c.NOISE_LEVEL_OPTS))
    tech_needs = Column(MultiChoice(c.TECH_NEED_OPTS))
    other_tech_needs = Column(UnicodeText)
    need_tables = Column(Boolean, default=False)
    tables_desc = Column(UnicodeText)
    has_cost = Column(Boolean, default=False)
    is_loud = Column(Boolean, default=False)
    tabletop = Column(Boolean, default=False)
    cost_desc = Column(UnicodeText)
    livestream = Column(Choice(c.LIVESTREAM_OPTS), default=c.OPT_IN)
    record = Column(Choice(c.LIVESTREAM_OPTS), default=c.OPT_IN)
    panelist_bringing = Column(UnicodeText)
    extra_info = Column(UnicodeText)
    applied = Column(UTCDateTime, server_default=utcnow(), default=lambda: datetime.now(UTC))
    accepted = Column(UTCDateTime, nullable=True)
    confirmed = Column(UTCDateTime, nullable=True)
    status = Column(Choice(c.PANEL_APP_STATUS_OPTS), default=c.PENDING, admin_only=True)
    comments = Column(UnicodeText, admin_only=True)
    track = Column(UnicodeText, admin_only=True)
    tags = Column(UniqueList, admin_only=True)

    applicants = relationship('PanelApplicant', backref='applications',
                              cascade='save-update,merge,refresh-expire,expunge',
                              secondary='panel_applicant_application')

    email_model_name = 'app'

    @presave_adjustment
    def update_event_info(self):
        if self.event and any([getattr(self.event, key, '') != getattr(self, key, '') for key in [
                'name', 'description', 'public_description', 'track']]):
            self.event.name = self.name
            self.event.description = self.description
            self.event.public_description = self.public_description
            self.event.track = self.track
            self.event.last_updated = self.last_updated
    
    @presave_adjustment
    def set_default_dept(self):
        if len(c.PANELS_DEPT_OPTS) <= 1 and not self.department:
            self.department = c.get_panels_id()

    @presave_adjustment
    def set_record(self):
        if len(c.LIVESTREAM_OPTS) > 2 and not self.record:
            self.record = c.OPT_OUT
    
    def add_credentials_to_desc(self):
        description = self.description or self.public_description
        panelist_creds = []

        def generate_creds(p):
            text = p.display_name
            if p.occupation or p.website:
                text += " ["
                if p.occupation:
                    text += p.occupation + (', ' if p.website else '')
                if p.website:
                    text += p.website
                text += "]"
            return text

        if self.submitter.display_name:
            panelist_creds.append(generate_creds(self.submitter))
        for panelist in [a for a in self.other_panelists if a.display_name]:
            panelist_creds.append(generate_creds(panelist))
        
        description += f"\n\nPanelists: {' '.join(panelist_creds)}"
        self.public_description = description
    
    @presave_adjustment
    def set_dept_name(self):
        from uber.models import Session

        if not self.department:
            dept_name = 'N/A'
        elif self.department == str(c.PANELS):
            dept_name = 'Panels'
        else:
            with Session() as session:
                dept_name = session.department(self.department).name

        self.department_name = dept_name

    @property
    def email(self):
        return self.submitter and self.submitter.email

    @property
    def submitter(self):
        for a in self.applicants:
            if a.id == self.submitter_id:
                return a
        return None

    @property
    def group(self):
        if self.submitter and self.submitter.attendee:
            return self.submitter.attendee.group

    @property
    def other_panelists(self):
        return [a for a in self.applicants if a.id != self.submitter_id]

    @property
    def matched_attendees(self):
        return [a.attendee for a in self.applicants if a.attendee_id]

    @property
    def unmatched_applicants(self):
        return [a for a in self.applicants if not a.attendee_id]

    @property
    def confirm_deadline(self):
        if c.PANELS_CONFIRM_DEADLINE and self.has_been_accepted and not self.confirmed and not (self.group and self.group.guest):
            confirm_deadline = timedelta(days=c.PANELS_CONFIRM_DEADLINE)
            return self.accepted + confirm_deadline

    @property
    def after_confirm_deadline(self):
        return self.confirm_deadline and self.confirm_deadline < datetime.now(UTC)

    @hybrid_property
    def has_been_accepted(self):
        return self.status == c.ACCEPTED


class PanelApplicant(SocialMediaMixin, MagModel):
    attendee_id = Column(UUID, ForeignKey('attendee.id', ondelete='SET NULL'), nullable=True)
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
    guidebook_bio = Column(UnicodeText)
    display_name = Column(UnicodeText)

    @property
    def has_credentials(self):
        return any([self.occupation, self.website, self.other_credentials])

    @property
    def full_name(self):
        return self.first_name + ' ' + self.last_name
    
    @property
    def confirmed_application_names(self):
        return [app.name for app in self.applications if app.submitter_id == self.id and app.confirmed]
    
    @property
    def accepted_applications(self):
        return [app for app in self.applications if app.submitter_id == self.id and app.status == c.ACCEPTED]
    
    def check_if_still_submitter(self, app_id):
        for app in self.applications:
            if app_id != app.id and app.submitter_id == self.id:
                return
        self.submitter = False


class EventFeedback(MagModel):
    event_id = Column(UUID, ForeignKey('event.id'))
    attendee_id = Column(UUID, ForeignKey('attendee.id', ondelete='cascade'))
    headcount_starting = Column(Integer, default=0)
    headcount_during = Column(Integer, default=0)
    comments = Column(UnicodeText)
    rating = Column(Choice(c.PANEL_FEEDBACK_OPTS), default=c.UNRATED)
