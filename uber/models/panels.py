import re
from datetime import datetime, timedelta

from pytz import UTC
from sqlalchemy.orm import backref
from sqlalchemy.schema import ForeignKey, Table, UniqueConstraint, Index
from sqlalchemy.types import Boolean, Integer, Uuid, String, DateTime
from sqlalchemy.ext.hybrid import hybrid_property

from uber.config import c
from uber.decorators import presave_adjustment
from uber.models import MagModel
from uber.models.types import default_relationship as relationship, utcnow, Choice, DefaultColumn as Column, \
    MultiChoice, UniqueList


__all__ = ['AssignedPanelist', 'Event', 'EventLocation', 'EventFeedback', 'PanelApplicant', 'PanelApplication']


# Many to many association table to tie Panel Applicants with Panel Applications
panel_applicant_application = Table(
    'panel_applicant_application',
    MagModel.metadata,
    Column('panel_applicant_id', Uuid(as_uuid=False), ForeignKey('panel_applicant.id')),
    Column('panel_application_id', Uuid(as_uuid=False), ForeignKey('panel_application.id')),
    UniqueConstraint('panel_applicant_id', 'panel_application_id'),
    Index('ix_admin_panel_application_panel_applicant_id', 'panel_applicant_id'),
    Index('ix_admin_panel_application_panel_application_id', 'panel_application_id'),
)


class EventLocation(MagModel):
    department_id = Column(Uuid(as_uuid=False), ForeignKey('department.id', ondelete='SET NULL'), nullable=True)
    name = Column(String)
    room = Column(String)
    tracks = Column(MultiChoice(c.EVENT_TRACK_OPTS))

    events = relationship('Event', backref=backref('location', lazy='joined', cascade="save-update,merge"),
                          cascade="save-update,merge", single_parent=True)
    attractions = relationship('AttractionEvent', backref=backref('location', lazy='joined', cascade="save-update,merge"),
                          cascade="save-update,merge", single_parent=True)

    @property
    def schedule_name(self):
        if self.room:
            return f"{self.name} ({self.room})"
        return self.name
    
    def update_events(self, session):
        orig_dept_id = self.orig_value_of('department_id')
        orig_tracks = set([int(i) for i in str(self.orig_value_of('tracks')).split(',') if i])
        new_tracks = set(self.tracks_ints)
        
        if self.department_id == orig_dept_id and new_tracks == orig_tracks:
            return
        
        remove_tracks = orig_tracks - new_tracks
        add_tracks = new_tracks - orig_tracks

        for event in self.events:
            event_updated = False

            if event.department_id == orig_dept_id:
                event.department_id = self.department_id
                event_updated = True
            
            event_old_tracks = set(event.tracks_ints)
            if remove_tracks:
                event.tracks = ','.join(map(str, list(set(event.tracks_ints) - remove_tracks)))
            if add_tracks:
                event.tracks = ','.join(map(str, event.tracks_ints + list(add_tracks)))

            if set(event.tracks_ints) != event_old_tracks:
                event_updated = True

            if event_updated:
                event.last_updated = datetime.now(UTC)
                session.add(event)


class Event(MagModel):
    """
    EventLocation: joined
    """

    event_location_id = Column(Uuid(as_uuid=False), ForeignKey('event_location.id', ondelete='SET NULL'), nullable=True)
    department_id = Column(Uuid(as_uuid=False), ForeignKey('department.id', ondelete='SET NULL'), nullable=True)
    attraction_event_id = Column(Uuid(as_uuid=False), ForeignKey('attraction_event.id', ondelete='SET NULL'), nullable=True)
    start_time = Column(DateTime(timezone=True))
    duration = Column(Integer, default=60)
    name = Column(String, nullable=False)
    description = Column(String)
    public_description = Column(String)
    tracks = Column(MultiChoice(c.EVENT_TRACK_OPTS))

    assigned_panelists = relationship('AssignedPanelist', backref=backref('event', lazy='joined'))
    applications = relationship('PanelApplication', backref=backref('event', lazy='joined', cascade="save-update,merge"),
                                cascade="save-update,merge")
    panel_feedback = relationship('EventFeedback', backref='event')
    guest = relationship('GuestGroup', backref=backref('event', cascade="save-update,merge"),
                         cascade='save-update,merge')
    attraction = relationship('AttractionEvent', backref=backref(
        'schedule_item', lazy='joined', cascade="save-update,merge", uselist=False
        ), cascade='save-update,merge')

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
    def location_name(self):
        if self.location:
            return self.location.schedule_name
        return "No Location"

    @property
    def guidebook_data(self):
        # This is for a Guidebook Sessions export, so it's not the same as a custom list
        from uber.utils import normalize_newlines

        description = self.public_description or self.description
        tracks = self.tracks_labels
        panel_tracks = set()
        for app in self.applications:
            potential_tracks = app.granular_rating_ints + [app.noise_level] + [app.presentation]
            for track in potential_tracks:
                label = c.EVENT_TRACKS.get(track, None)
                if label:
                    panel_tracks.add(label)
        
        tracks = list(set(tracks) | panel_tracks)

        return {
            'name': self.name,
            'start_date': self.start_time_local.strftime('%m/%d/%Y'),
            'start_time': self.start_time_local.strftime('%I:%M %p'),
            'end_date': self.end_time_local.strftime('%m/%d/%Y'),
            'end_time': self.end_time_local.strftime('%I:%M %p'),
            'location': self.location_name,
            'track': '; '.join(tracks),
            'description': normalize_newlines(description),
            }

    @property
    def guidebook_name(self):
        return self.name

    @property
    def guidebook_desc(self):
        return self.public_description or self.description


class AssignedPanelist(MagModel):
    """
    Attendee: joined
    Event: joined
    """

    attendee_id = Column(Uuid(as_uuid=False), ForeignKey('attendee.id', ondelete='cascade'))
    event_id = Column(Uuid(as_uuid=False), ForeignKey('event.id', ondelete='cascade'))

    def __repr__(self):
        if self.attendee:
            return '<{} panelisting {}>'.format(
                self.attendee.full_name, self.event.name)
        else:
            return super(AssignedPanelist, self).__repr__()


class PanelApplication(MagModel):
    """
    Event: joined
    PanelApplicant: selectin
    """

    event_id = Column(Uuid(as_uuid=False), ForeignKey('event.id', ondelete='SET NULL'), nullable=True)
    poc_id = Column(Uuid(as_uuid=False), ForeignKey('attendee.id', ondelete='SET NULL'), nullable=True)
    submitter_id = Column(Uuid(as_uuid=False), ForeignKey('panel_applicant.id', ondelete='SET NULL'), nullable=True)
    name = Column(String)
    length = Column(Choice(c.PANEL_LENGTH_OPTS), default=c.SIXTY_MIN)
    length_text = Column(String)
    length_reason = Column(String)
    description = Column(String)
    public_description = Column(String)
    unavailable = Column(String)
    available = Column(String)
    affiliations = Column(String)
    past_attendance = Column(String)
    department = Column(UniqueList)
    department_name = Column(String)
    rating = Column(Choice(c.PANEL_RATING_OPTS), default=c.UNRATED)
    granular_rating = Column(MultiChoice(c.PANEL_CONTENT_OPTS))
    presentation = Column(Choice(c.PRESENTATION_OPTS))
    other_presentation = Column(String)
    noise_level = Column(Choice(c.NOISE_LEVEL_OPTS))
    tech_needs = Column(MultiChoice(c.TECH_NEED_OPTS))
    other_tech_needs = Column(String)
    need_tables = Column(Boolean, default=False)
    tables_desc = Column(String)
    has_cost = Column(Boolean, default=False)
    is_loud = Column(Boolean, default=False)
    tabletop = Column(Boolean, default=False)
    cost_desc = Column(String)
    livestream = Column(Choice(c.LIVESTREAM_OPTS), default=c.OPT_IN)
    record = Column(Choice(c.LIVESTREAM_OPTS), default=c.OPT_IN)
    panelist_bringing = Column(String)
    extra_info = Column(String)
    applied = Column(DateTime(timezone=True), server_default=utcnow(), default=lambda: datetime.now(UTC))
    accepted = Column(DateTime(timezone=True), nullable=True)
    confirmed = Column(DateTime(timezone=True), nullable=True)
    status = Column(Choice(c.PANEL_APP_STATUS_OPTS), default=c.PENDING, admin_only=True)
    comments = Column(String, admin_only=True)
    tags = Column(UniqueList, admin_only=True)

    applicants = relationship('PanelApplicant', lazy='selectin', backref=backref('applications', lazy='selectin'),
                              cascade='save-update,merge,refresh-expire,expunge',
                              secondary='panel_applicant_application')

    email_model_name = 'app'

    @presave_adjustment
    def update_event_info(self):
        updated = False
        if self.event:
            for key in ['name', 'description', 'public_description']:
                if getattr(self.event, key, '') != getattr(self, key, ''):
                    updated = True
                    setattr(self.event, key, getattr(self, key, ''))
        if updated:
            self.event.last_updated = datetime.now(UTC)
    
    @presave_adjustment
    def set_default_dept(self):
        if len(c.PANELS_DEPT_OPTS) <= 1 and not self.department:
            self.department = c.get_panels_id()

    @presave_adjustment
    def set_record(self):
        if len(c.LIVESTREAM_OPTS) > 2 and not self.record:
            self.record = c.OPT_OUT
    
    def add_credentials_to_desc(self):
        description = self.public_description or self.description
        panelist_creds = []

        existing_panelist_creds = re.search('\\nPanelists: .*$', description)
        if existing_panelist_creds:
            return

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
        
        if panelist_creds:
            description += f"\n\nPanelists: {' | '.join(panelist_creds)}"
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


class PanelApplicant(MagModel):
    """
    Attendee: joined
    PanelApplicant: selectin
    """

    attendee_id = Column(Uuid(as_uuid=False), ForeignKey('attendee.id', ondelete='SET NULL'), nullable=True)
    submitter = Column(Boolean, default=False)
    first_name = Column(String)
    last_name = Column(String)
    email = Column(String)
    cellphone = Column(String)
    communication_pref = Column(MultiChoice(c.COMMUNICATION_PREF_OPTS))
    other_communication_pref = Column(String)
    requested_accessibility_services = Column(Boolean, default=False)
    pronouns = Column(MultiChoice(c.PRONOUN_OPTS))
    other_pronouns = Column(String)
    occupation = Column(String)
    website = Column(String)
    other_credentials = Column(String)
    guidebook_bio = Column(String)
    display_name = Column(String)
    social_media_info = Column(String)

    @property
    def has_credentials(self):
        return any([self.occupation, self.website, self.other_credentials])

    @property
    def full_name(self):
        return self.first_name + ' ' + self.last_name

    @property
    def confirmed_application_names(self):
        return [app.name for app in self.applications if app.confirmed]
    
    @property
    def accepted_applications(self):
        return [app for app in self.applications if app.status == c.ACCEPTED]
    
    def check_if_still_submitter(self, app_id):
        for app in self.applications:
            if app_id != app.id and app.submitter_id == self.id:
                return
        self.submitter = False


class EventFeedback(MagModel):
    event_id = Column(Uuid(as_uuid=False), ForeignKey('event.id'))
    attendee_id = Column(Uuid(as_uuid=False), ForeignKey('attendee.id', ondelete='cascade'))
    headcount_starting = Column(Integer, default=0)
    headcount_during = Column(Integer, default=0)
    comments = Column(String)
    rating = Column(Choice(c.PANEL_FEEDBACK_OPTS), default=c.UNRATED)
