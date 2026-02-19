import os
import cherrypy
from functools import wraps
from datetime import datetime

from pytz import UTC
from sqlalchemy import and_
from sqlalchemy.types import Uuid, DateTime
from sqlalchemy.ext.hybrid import hybrid_property
from typing import ClassVar

from uber.config import c
from uber.models import MagModel
from uber.models.types import (Choice, MultiChoice, GuidebookImageMixin, DefaultColumn as Column,
                               DefaultField as Field, DefaultRelationship as Relationship)
from uber.utils import slugify


__all__ = ['MITSTeam', 'MITSApplicant', 'MITSGame', 'MITSPicture', 'MITSDocument', 'MITSTimes']


class MITSTeam(MagModel, table=True):
    """
    MITSGame: selectin
    """

    name: str = ''
    days_available: int | None = Field(nullable=True)
    hours_available: int | None = Field(nullable=True)
    concurrent_attendees: int = 0
    panel_interest: bool | None = Field(nullable=True, admin_only=True)
    showcase_interest: bool | None = Field(nullable=True, admin_only=True)
    want_to_sell: bool = False
    address: str = ''
    submitted: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True)
    waiver_signature: str = ''
    waiver_signed: datetime | None = Field(sa_type=DateTime(timezone=True), nullable=True)

    applied: datetime = Field(sa_type=DateTime(timezone=True), default_factory=lambda: datetime.now(UTC))
    status: int = Field(sa_column=Column(Choice(c.MITS_APP_STATUS), admin_only=True), default=c.PENDING)

    applicants: list['MITSApplicant'] = Relationship(
        back_populates="team", sa_relationship_kwargs={'cascade': 'all,delete-orphan', 'passive_deletes': True})
    games: list['MITSGame'] = Relationship(
        back_populates="team", sa_relationship_kwargs={'cascade': 'all,delete-orphan', 'passive_deletes': True})
    schedule: 'MITSTimes' = Relationship(
        back_populates="team", sa_relationship_kwargs={'cascade': 'all,delete-orphan', 'passive_deletes': True})
    panel_app: 'MITSPanelApplication' = Relationship(
        back_populates="team", sa_relationship_kwargs={'cascade': 'all,delete-orphan', 'passive_deletes': True})

    duplicate_of: str | None = Field(sa_type=Uuid(as_uuid=False), nullable=True)
    deleted: bool = False
    # We've found that a lot of people start filling out an application and
    # then instead of continuing their application just start over fresh and
    # fill out a new one.  In these cases we mark the application as
    # soft-deleted and then set the duplicate_of field so that when an
    # applicant tries to log into the original application, we can redirect
    # them to the correct application.

    email_model_name: ClassVar = 'team'

    @property
    def accepted(self):
        return self.status == c.ACCEPTED

    @property
    def email(self):
        return [applicant.email for applicant in self.primary_contacts]

    @property
    def primary_contacts(self):
        return [a for a in self.applicants if a.primary_contact]

    @property
    def salutation(self):
        return ' and '.join(applicant.first_name for applicant in self.primary_contacts)

    @property
    def comped_badge_count(self):
        return len([
            a for a in self.applicants
            if a.attendee_id and a.attendee.paid in [c.NEED_NOT_PAY, c.REFUNDED]])

    @property
    def total_badge_count(self):
        return len([a for a in self.applicants if a.attendee_id])

    @property
    def can_add_badges(self):
        uncomped_badge_count = len([
            a for a in self.applicants
            if a.attendee_id and a.attendee.paid not in [c.NEED_NOT_PAY, c.REFUNDED]])
        claimed_badges = len(self.applicants) - uncomped_badge_count
        return claimed_badges < c.MITS_BADGES_PER_TEAM

    @property
    def can_save(self):
        return c.HAS_MITS_ADMIN_ACCESS or self.status in [c.ACCEPTED, c.WAITLISTED] or \
            c.BEFORE_MITS_SUBMISSION_DEADLINE or not self.is_new and c.BEFORE_MITS_EDITING_DEADLINE

    @property
    def completed_panel_request(self):
        return self.panel_interest is not None

    @property
    def completed_showcase_request(self):
        return self.showcase_interest is not None

    @property
    def completed_hotel_form(self):
        """
        This is "any" rather than "all" because teams are allowed to
        add and remove members even after their application has been
        submitted. Rather than suddenly downgrade their completion
        percentage, it makes more sense to send such teams an
        automated email indicating that they need to provide their
        remaining hotel info.
        """
        return any(a.declined_hotel_space or a.requested_room_nights for a in self.applicants)

    @property
    def no_hotel_space(self):
        return all(a.declined_hotel_space for a in self.applicants)

    @property
    def steps_completed(self):
        if not self.days_available:
            return 1
        elif not self.games:
            return 2
        elif not self.submitted:
            return 3
        else:
            return 4

    @property
    def completion_percentage(self):
        return 100 * self.steps_completed // c.MITS_APPLICATION_STEPS


class MITSApplicant(MagModel, table=True):
    """
    MITSTeam: joined
    """

    team_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='mits_team.id', ondelete='CASCADE')
    team: 'MITSTeam' = Relationship(back_populates="applicants", sa_relationship_kwargs={'lazy': 'joined'})

    attendee_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='attendee.id', nullable=True)
    attendee: 'Attendee' = Relationship(back_populates="mits_applicants")

    primary_contact: bool = False
    first_name: str = ''
    last_name: str = ''
    email: str = ''
    cellphone: str = ''
    contact_method: int = Field(sa_column=Column(Choice(c.MITS_CONTACT_OPTS)), default=c.TEXTING)

    declined_hotel_space: bool = False
    requested_room_nights: str = Field(sa_type=MultiChoice(c.MITS_ROOM_NIGHT_OPTS), default='')

    email_model_name: ClassVar = 'applicant'

    @property
    def email_to_address(self):
        if self.attendee:
            return self.attendee.email
        return self.email

    @property
    def full_name(self):
        return self.first_name + ' ' + self.last_name

    def has_requested(self, night):
        return night in self.requested_room_nights_ints


class MITSGame(MagModel, table=True):
    """
    MITSTeam: joined
    MITSPicture: selectin
    MITSDocument: selectin
    """

    team_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='mits_team.id', ondelete='CASCADE')
    team: 'MITSTeam' = Relationship(back_populates="games", sa_relationship_kwargs={'lazy': 'joined'})

    name: str = ''
    promo_blurb: str = ''
    description: str = ''
    genre: str = ''
    phase: int = Field(sa_column=Column(Choice(c.MITS_PHASE_OPTS)), default=c.DEVELOPMENT)
    min_age: int = Field(sa_column=Column(Choice(c.MITS_AGE_OPTS)), default=c.CHILD)
    age_explanation: str = ''
    min_players: int = 2
    max_players: int = 4
    copyrighted: int | None = Field(sa_column=Column(Choice(c.MITS_COPYRIGHT_OPTS), nullable=True))
    personally_own: bool = False
    unlicensed: bool = False
    professional: bool = False
    tournament: bool = False

    pictures: list['MITSPicture'] = Relationship(
        back_populates="game", sa_relationship_kwargs={'cascade': 'all,delete-orphan', 'passive_deletes': True})
    documents: list['MITSDocument'] = Relationship(
        back_populates="game", sa_relationship_kwargs={'cascade': 'all,delete-orphan', 'passive_deletes': True})

    @hybrid_property
    def has_been_accepted(self):
        return self.team.status == c.ACCEPTED

    @has_been_accepted.expression
    def has_been_accepted(cls):
        return and_(MITSTeam.id == cls.team_id, MITSTeam.status == c.ACCEPTED)

    @property
    def guidebook_header(self):
        for image in self.pictures:
            if image.is_header:
                return image
        return ''

    @property
    def guidebook_thumbnail(self):
        for image in self.pictures:
            if image.is_thumbnail:
                return image
        return ''

    @property
    def guidebook_edit_link(self):
        return f"../mits_admin/team?id={self.team.id}"

    @property
    def guidebook_data(self):
        return {
            'guidebook_name': self.name,
            'guidebook_subtitle': self.team.name,
            'guidebook_desc': self.description,
            'guidebook_location': '',
            'guidebook_header': self.guidebook_images[0][0],
            'guidebook_thumbnail': self.guidebook_images[0][1],
        }

    @property
    def guidebook_images(self):
        if not self.pictures:
            return ['', ''], ['', '']

        header = self.guidebook_header
        thumbnail = self.guidebook_thumbnail
        prepend = slugify(self.name) + '_'

        header_name = (prepend + header.filename) if header else ''
        thumbnail_name = (prepend + thumbnail.filename) if thumbnail else ''
        
        return [header_name, thumbnail_name], [header, thumbnail]


class MITSPicture(MagModel, GuidebookImageMixin, table=True):
    """
    MITSGame: joined
    """

    game_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='mits_game.id', ondelete='CASCADE')
    game: 'MITSGame' = Relationship(back_populates="pictures", sa_relationship_kwargs={'lazy': 'joined'})

    description: str = ''

    @property
    def url(self):
        return '../mits/view_picture?id={}'.format(self.id)

    @property
    def filepath(self):
        return os.path.join(c.MITS_PICTURE_DIR, str(self.id))


class MITSDocument(MagModel, table=True):
    """
    MITSGame: joined
    """
    
    game_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='mits_game.id', ondelete='CASCADE')
    game: 'MITSGame' = Relationship(back_populates="documents", sa_relationship_kwargs={'lazy': 'joined'})

    filename: str = ''
    description: str = ''

    @property
    def url(self):
        return '../mits/download_doc?id={}'.format(self.id)

    @property
    def filepath(self):
        return os.path.join(c.MITS_PICTURE_DIR, str(self.id))


class MITSTimes(MagModel, table=True):
    """
    MITSTeam: joined
    """

    team_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='mits_team.id', ondelete='CASCADE', unique=True)
    team: 'MITSTeam' = Relationship(back_populates="schedule", sa_relationship_kwargs={'lazy': 'joined', 'single_parent': True})

    showcase_availability: str = Field(sa_type=MultiChoice(c.MITS_SHOWCASE_SCHEDULE_OPTS), default='')
    availability: str = Field(sa_type=MultiChoice(c.MITS_SCHEDULE_OPTS), default='')


class MITSPanelApplication(MagModel, table=True):
    """
    MITSTeam: joined
    """

    team_id: str | None = Field(sa_type=Uuid(as_uuid=False), foreign_key='mits_team.id', ondelete='CASCADE', unique=True)
    team: 'MITSTeam' = Relationship(back_populates="panel_app", sa_relationship_kwargs={'lazy': 'joined', 'single_parent': True})

    name: str = ''
    description: str = ''
    length: int = Field(sa_column=Column(Choice(c.PANEL_STRICT_LENGTH_OPTS)), default=c.SIXTY_MIN)
    participation_interest: bool = False


def add_applicant_restriction():
    """
    We use convenience functions for our form handling, e.g. to
    instantiate an attendee from an id or from form data we use the
    session.attendee() method. This method runs on startup and overrides
    the methods which are used for the game application forms to add a
    new "applicant" parameter.  If truthy, this triggers three
    additional behaviors:

    1) We check that there is currently a logged in team, and redirect
       to the initial application form if there is not.
    2) We check that the item being edited belongs to the
       currently-logged-in team and raise an exception if it does not.
       This check is bypassed for new things which have not yet been
       saved to the database.
    3) We set the "team" relationship on the model to the
       logged-in team.
    """
    from uber.models import Session

    def override_getter(method_name):
        orig_getter = getattr(Session.SessionMixin, method_name)

        @wraps(orig_getter)
        def with_applicant(self, *args, **kwargs):
            applicant = kwargs.pop('applicant', False)
            instance = orig_getter(self, *args, **kwargs)
            if applicant:
                team = self.logged_in_mits_team()
                assert instance.is_new or team == instance.team
                instance.team = team
            return instance
        setattr(Session.SessionMixin, method_name, with_applicant)

    for name in [
        'mits_applicant', 'mits_game', 'mits_times', 'mits_picture', 'mits_document', 'mits_panel_application'
    ]:
        override_getter(name)
cherrypy.engine.subscribe('start', add_applicant_restriction, priority=98)