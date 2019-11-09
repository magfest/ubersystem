import os
from functools import wraps

from PIL import Image
from residue import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sqlalchemy import and_
from sideboard.lib import on_startup
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import Boolean, Integer
from sqlalchemy.ext.hybrid import hybrid_property

from uber.config import c
from uber.models import MagModel
from uber.models.types import default_relationship as relationship, utcnow, Choice, DefaultColumn as Column, MultiChoice


__all__ = ['MITSTeam', 'MITSApplicant', 'MITSGame', 'MITSPicture', 'MITSDocument', 'MITSTimes']


class MITSTeam(MagModel):
    name = Column(UnicodeText)
    panel_interest = Column(Boolean, nullable=True, admin_only=True)
    showcase_interest = Column(Boolean, nullable=True, admin_only=True)
    want_to_sell = Column(Boolean, default=False)
    address = Column(UnicodeText)
    submitted = Column(UTCDateTime, nullable=True)
    waiver_signature = Column(UnicodeText)
    waiver_signed = Column(UTCDateTime, nullable=True)

    applied = Column(UTCDateTime, server_default=utcnow())
    status = Column(Choice(c.MITS_APP_STATUS), default=c.PENDING, admin_only=True)

    applicants = relationship('MITSApplicant', backref='team')
    games = relationship('MITSGame', backref='team')
    pictures = relationship('MITSPicture', backref='team')
    documents = relationship('MITSDocument', backref='team')
    schedule = relationship('MITSTimes', uselist=False, backref='team')
    panel_app = relationship('MITSPanelApplication', uselist=False, backref='team')

    duplicate_of = Column(UUID, nullable=True)
    deleted = Column(Boolean, default=False)
    # We've found that a lot of people start filling out an application and
    # then instead of continuing their application just start over fresh and
    # fill out a new one.  In these cases we mark the application as
    # soft-deleted and then set the duplicate_of field so that when an
    # applicant tries to log into the original application, we can redirect
    # them to the correct application.

    email_model_name = 'team'

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
        return c.HAS_MITS_ADMIN_ACCESS or self.status in [c.ACCEPTED, c.WAITLISTED] or (
            self.is_new
            and c.BEFORE_MITS_SUBMISSION_DEADLINE
            or c.BEFORE_MITS_EDITING_DEADLINE)

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
        if not self.games:
            return 1
        elif not self.pictures:
            return 2
        elif not self.completed_panel_request:
            return 3
        elif not self.completed_showcase_request:
            return 4
        elif not self.completed_hotel_form:
            return 5
        elif not self.submitted:
            return 6
        else:
            return 7

    @property
    def completion_percentage(self):
        return 100 * self.steps_completed // c.MITS_APPLICATION_STEPS


class MITSApplicant(MagModel):
    team_id = Column(ForeignKey('mits_team.id'))
    attendee_id = Column(ForeignKey('attendee.id'), nullable=True)
    primary_contact = Column(Boolean, default=False)
    first_name = Column(UnicodeText)
    last_name = Column(UnicodeText)
    email = Column(UnicodeText)
    cellphone = Column(UnicodeText)
    contact_method = Column(Choice(c.MITS_CONTACT_OPTS), default=c.TEXTING)

    declined_hotel_space = Column(Boolean, default=False)
    requested_room_nights = Column(MultiChoice(c.MITS_ROOM_NIGHT_OPTS), default='')

    email_model_name = 'applicant'

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


class MITSGame(MagModel):
    team_id = Column(ForeignKey('mits_team.id'))
    name = Column(UnicodeText)
    promo_blurb = Column(UnicodeText)
    description = Column(UnicodeText)
    genre = Column(UnicodeText)
    phase = Column(Choice(c.MITS_PHASE_OPTS))
    min_age = Column(Integer)
    min_players = Column(Integer, default=2)
    max_players = Column(Integer, default=4)
    personally_own = Column(Boolean, default=False)
    unlicensed = Column(Boolean, default=False)
    professional = Column(Boolean, default=False)

    @hybrid_property
    def has_been_accepted(self):
        return self.team.status == c.ACCEPTED

    @has_been_accepted.expression
    def has_been_accepted(cls):
        return and_(MITSTeam.id == cls.team_id, MITSTeam.status == c.ACCEPTED)

    @property
    def guidebook_name(self):
        return self.team.name

    @property
    def guidebook_subtitle(self):
        return self.name

    @property
    def guidebook_desc(self):
        return self.description

    @property
    def guidebook_location(self):
        return ''

    @property
    def guidebook_image(self):
        if not self.team.pictures:
            return ''
        for image in self.team.pictures:
            if image.is_header:
                return image.filename
        return self.team.pictures[0].filename

    @property
    def guidebook_thumbnail(self):
        if not self.team.pictures:
            return ''
        for image in self.team.pictures:
            if image.is_thumbnail:
                return image.filename
        return self.team.pictures[1].filename if len(self.team.pictures) > 1 else self.team.pictures[0].filename

    @property
    def guidebook_images(self):
        if not self.team.pictures:
            return ['', '']

        header = None
        thumbnail = None
        for image in self.team.pictures:
            if image.is_header and not header:
                header = image
            if image.is_thumbnail and not thumbnail:
                thumbnail = image

        if not header:
            header = self.team.pictures[0]
        if not thumbnail:
            thumbnail = self.team.pictures[1] if len(self.team.pictures) > 1 else self.team.pictures[0]

        if header == thumbnail:
            return [header.filename], [header]
        else:
            return [header.filename, thumbnail.filename], [header, thumbnail]


class MITSPicture(MagModel):
    team_id = Column(UUID, ForeignKey('mits_team.id'))
    filename = Column(UnicodeText)
    content_type = Column(UnicodeText)
    extension = Column(UnicodeText)
    description = Column(UnicodeText)

    @property
    def url(self):
        return '../mits/view_picture?id={}'.format(self.id)

    @property
    def filepath(self):
        return os.path.join(c.MITS_PICTURE_DIR, str(self.id))

    @property
    def is_header(self):
        try:
            return Image.open(self.filepath).size == tuple(map(int, c.MITS_HEADER_SIZE))
        except OSError:
            # This probably isn't an image, so it's not a header image
            return

    @property
    def is_thumbnail(self):
        try:
            return Image.open(self.filepath).size == tuple(map(int, c.MITS_THUMBNAIL_SIZE))
        except OSError:
            # This probably isn't an image, so it's not a thumbnail image
            return


class MITSDocument(MagModel):
    team_id = Column(UUID, ForeignKey('mits_team.id'))
    filename = Column(UnicodeText)
    description = Column(UnicodeText)

    @property
    def url(self):
        return '../mits/download_doc?id={}'.format(self.id)

    @property
    def filepath(self):
        return os.path.join(c.MITS_PICTURE_DIR, str(self.id))


class MITSTimes(MagModel):
    team_id = Column(ForeignKey('mits_team.id'))
    showcase_availability = Column(MultiChoice(c.MITS_SHOWCASE_SCHEDULE_OPTS))
    availability = Column(MultiChoice(c.MITS_SCHEDULE_OPTS))


class MITSPanelApplication(MagModel):
    team_id = Column(ForeignKey('mits_team.id'))
    name = Column(UnicodeText)
    description = Column(UnicodeText)
    length = Column(Choice(c.PANEL_STRICT_LENGTH_OPTS), default=c.SIXTY_MIN)
    participation_interest = Column(Boolean, default=False)


@on_startup
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
