import os
import re

from datetime import datetime, timedelta
from functools import wraps

from pytz import UTC
from residue import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sideboard.lib import on_startup
from sqlalchemy import func
from sqlalchemy.schema import ForeignKey, UniqueConstraint
from sqlalchemy.types import Boolean, Integer
from sqlalchemy.ext.hybrid import hybrid_property

from uber.config import c
from uber.decorators import presave_adjustment
from uber.models import MagModel, Attendee
from uber.models.types import default_relationship as relationship, utcnow, \
    Choice, DefaultColumn as Column, MultiChoice
from uber.utils import localized_now, make_url


__all__ = [
    'IndieJudge', 'IndieStudio', 'IndieDeveloper', 'IndieGame',
    'IndieGameImage', 'IndieGameCode', 'IndieGameReview']


class ReviewMixin:
    @property
    def game_reviews(self):
        return [r for r in self.reviews if r.game_status != c.PENDING]


class IndieJudge(MagModel, ReviewMixin):
    admin_id = Column(UUID, ForeignKey('admin_account.id'))
    status = Column(Choice(c.MIVS_JUDGE_STATUS_OPTS), default=c.UNCONFIRMED)
    no_game_submission = Column(Boolean, nullable=True)
    genres = Column(MultiChoice(c.MIVS_INDIE_JUDGE_GENRE_OPTS))
    platforms = Column(MultiChoice(c.MIVS_INDIE_PLATFORM_OPTS))
    platforms_text = Column(UnicodeText)
    staff_notes = Column(UnicodeText)

    codes = relationship('IndieGameCode', backref='judge')
    reviews = relationship('IndieGameReview', backref='judge')

    email_model_name = 'judge'

    @property
    def judging_complete(self):
        return len(self.reviews) == len(self.game_reviews)

    @property
    def mivs_all_genres(self):
        return c.MIVS_ALL_GENRES in self.genres_ints

    @property
    def attendee(self):
        return self.admin_account.attendee

    @property
    def full_name(self):
        return self.attendee.full_name

    @property
    def email(self):
        return self.attendee.email


class IndieStudio(MagModel):
    group_id = Column(UUID, ForeignKey('group.id'), nullable=True)
    name = Column(UnicodeText, unique=True)
    address = Column(UnicodeText)
    website = Column(UnicodeText)
    twitter = Column(UnicodeText)
    facebook = Column(UnicodeText)
    status = Column(
        Choice(c.MIVS_STUDIO_STATUS_OPTS), default=c.NEW, admin_only=True)
    staff_notes = Column(UnicodeText, admin_only=True)
    registered = Column(UTCDateTime, server_default=utcnow())

    accepted_core_hours = Column(Boolean, default=False)
    discussion_emails = Column(UnicodeText)
    completed_discussion = Column(Boolean, default=False)
    read_handbook = Column(Boolean, default=False)
    training_password = Column(UnicodeText)
    selling_at_event = Column(Boolean, nullable=True, admin_only=True)  # "Admin only" preserves null default
    needs_hotel_space = Column(Boolean, nullable=True, admin_only=True)  # "Admin only" preserves null default
    name_for_hotel = Column(UnicodeText)
    email_for_hotel = Column(UnicodeText)
    contact_phone = Column(UnicodeText)
    show_info_updated = Column(Boolean, default=False)

    games = relationship(
        'IndieGame', backref='studio', order_by='IndieGame.title')
    developers = relationship(
        'IndieDeveloper',
        backref='studio',
        order_by='IndieDeveloper.last_name')

    email_model_name = 'studio'

    @property
    def primary_contact_first_names(self):
        if len(self.primary_contacts) == 1:
            return self.primary_contacts[0].first_name

        string = self.primary_contacts[0].first_name
        for dev in self.primary_contacts[1:-1]:
            string += ", " + dev.first_name
        if len(self.primary_contacts) > 2:
            string += ","
        string += " and " + self.primary_contacts[-1].first_name
        return string

    @property
    def confirm_deadline(self):
        sorted_games = sorted(
            [g for g in self.games if g.accepted], key=lambda g: g.accepted)
        confirm_deadline = timedelta(days=c.MIVS_CONFIRM_DEADLINE)
        return sorted_games[0].accepted + confirm_deadline if len(sorted_games) else None

    @property
    def after_confirm_deadline(self):
        return self.confirm_deadline < localized_now()

    @property
    def discussion_emails_list(self):
        return list(filter(None, self.discussion_emails.split(',')))
    
    @property
    def discussion_emails_last_updated(self):
        studio_updates = self.get_tracking_by_instance(self, action=c.UPDATED, last_only=False)
        for update in studio_updates:
            if 'discussion_emails' in update.data:
                return update.when

    @property
    def core_hours_status(self):
        return "Accepted" if self.accepted_core_hours else None

    @property
    def discussion_status(self):
        return "Completed" if self.completed_discussion else None

    @property
    def handbook_status(self):
        return "Read" if self.read_handbook else None

    @property
    def training_status(self):
        if self.training_password:
            return "Completed" if self.training_password.lower() == c.MIVS_TRAINING_PASSWORD.lower()\
                else "Entered the wrong phrase!"

    @property
    def selling_at_event_status(self):
        if self.selling_at_event is not None:
            return "Expressed interest in selling" if self.selling_at_event else "Opted out"

    @property
    def hotel_space_status(self):
        if self.needs_hotel_space is not None:
            return "Requested hotel space for {} with email {}".format(self.name_for_hotel, self.email_for_hotel)\
                if self.needs_hotel_space else "Opted out"
                
    @property
    def show_info_status(self):
        return self.show_info_updated

    def checklist_deadline(self, slug):
        default_deadline = c.MIVS_CHECKLIST[slug]['deadline']
        if self.group and self.group.registered >= default_deadline and slug in ['core_hours', 'discussion']:
            return self.group.registered + timedelta(days=7)
        return default_deadline

    def past_checklist_deadline(self, slug):
        """

        Args:
            slug: A standardized name, which should match the checklist's section name in config.
            E.g., the properties above ending in _status

        Returns: A timedelta object representing how far from the deadline this team is for a particular checklist item

        """
        return localized_now() - self.checklist_deadline(slug)

    @property
    def checklist_items_due_soon_grouped(self):
        two_days = []
        one_day = []
        overdue = []
        for key, val in c.MIVS_CHECKLIST.items():
            if localized_now() >= self.checklist_deadline(key):
                overdue.append([val['name'], "mivs_" + key])
            elif (localized_now() - timedelta(days=1)) >= self.checklist_deadline(key):
                one_day.append([val['name'], "mivs_" + key])
            elif (localized_now() - timedelta(days=2)) >= self.checklist_deadline(key):
                two_days.append([val['name'], "mivs_" + key])

        return two_days, one_day, overdue

    @property
    def website_href(self):
        return make_url(self.website)

    @property
    def email(self):
        return [dev.email_to_address for dev in self.developers if dev.primary_contact]

    @property
    def primary_contacts(self):
        return [dev for dev in self.developers if dev.primary_contact]

    @property
    def submitted_games(self):
        return [g for g in self.games if g.submitted]
    
    @property
    def confirmed_games(self):
        return [g for g in self.games if g.confirmed]

    @property
    def comped_badges(self):
        game_count = len([g for g in self.games if g.status == c.ACCEPTED])
        return c.MIVS_INDIE_BADGE_COMPS * game_count

    @property
    def unclaimed_badges(self):
        claimed_count = len(
            [d for d in self.developers if not d.matching_attendee])
        return max(0, self.comped_badges - claimed_count)


class IndieDeveloper(MagModel):
    studio_id = Column(UUID, ForeignKey('indie_studio.id'))

    # primary_contact == True just means they receive emails
    primary_contact = Column(Boolean, default=False)
    first_name = Column(UnicodeText)
    last_name = Column(UnicodeText)
    email = Column(UnicodeText)
    cellphone = Column(UnicodeText)
    agreed_coc = Column(Boolean, default=False)
    agreed_data_policy = Column(Boolean, default=False)

    @property
    def email_to_address(self):
        # Note: this doesn't actually do what we want right now
        # because the IndieDeveloper and attendee are not properly linked
        if self.matching_attendee:
            return self.matching_attendee.email
        return self.email

    @property
    def cellphone_num(self):
        if self.matching_attendee:
            return self.matching_attendee.cellphone
        return self.cellphone

    @property
    def full_name(self):
        return self.first_name + ' ' + self.last_name

    @property
    def matching_attendee(self):
        return self.session.query(Attendee).filter(
            func.lower(Attendee.first_name) == self.first_name.lower(),
            func.lower(Attendee.last_name) == self.last_name.lower(),
            func.lower(Attendee.email) == self.email.lower()
        ).first()


class IndieGame(MagModel, ReviewMixin):
    studio_id = Column(UUID, ForeignKey('indie_studio.id'))
    title = Column(UnicodeText)
    brief_description = Column(UnicodeText)       # 140 max
    genres = Column(MultiChoice(c.MIVS_INDIE_GENRE_OPTS))
    platforms = Column(MultiChoice(c.MIVS_INDIE_PLATFORM_OPTS))
    platforms_text = Column(UnicodeText)
    description = Column(UnicodeText)  # 500 max
    how_to_play = Column(UnicodeText)  # 1000 max
    link_to_video = Column(UnicodeText)
    link_to_game = Column(UnicodeText)
    password_to_game = Column(UnicodeText)
    code_type = Column(Choice(c.MIVS_CODE_TYPE_OPTS), default=c.NO_CODE)
    code_instructions = Column(UnicodeText)
    build_status = Column(
        Choice(c.MIVS_BUILD_STATUS_OPTS), default=c.PRE_ALPHA)
    build_notes = Column(UnicodeText)  # 500 max
    shown_events = Column(UnicodeText)
    submitted = Column(Boolean, default=False)
    agreed_liability = Column(Boolean, default=False)
    agreed_showtimes = Column(Boolean, default=False)
    agreed_reminder1 = Column(Boolean, default=False)
    agreed_reminder2 = Column(Boolean, default=False)
    alumni_years = Column(MultiChoice(c.PREV_MIVS_YEAR_OPTS))
    alumni_update = Column(UnicodeText)

    link_to_promo_video = Column(UnicodeText)
    link_to_webpage = Column(UnicodeText)
    twitter = Column(UnicodeText)
    facebook = Column(UnicodeText)
    other_social_media = Column(UnicodeText)

    tournament_at_event = Column(Boolean, default=False)
    tournament_prizes = Column(UnicodeText)
    has_multiplayer = Column(Boolean, default=False)
    player_count = Column(UnicodeText)

    # Length in minutes
    multiplayer_game_length = Column(Integer, nullable=True)
    leaderboard_challenge = Column(Boolean, default=False)

    status = Column(
        Choice(c.MIVS_GAME_STATUS_OPTS), default=c.NEW, admin_only=True)
    judge_notes = Column(UnicodeText, admin_only=True)
    registered = Column(UTCDateTime, server_default=utcnow())
    waitlisted = Column(UTCDateTime, nullable=True)
    accepted = Column(UTCDateTime, nullable=True)

    codes = relationship('IndieGameCode', backref='game')
    reviews = relationship('IndieGameReview', backref='game')
    images = relationship(
        'IndieGameImage', backref='game', order_by='IndieGameImage.id')

    email_model_name = 'game'

    @presave_adjustment
    def accepted_time(self):
        if self.status == c.ACCEPTED and not self.accepted:
            self.accepted = datetime.now(UTC)

    @presave_adjustment
    def waitlisted_time(self):
        if self.status == c.WAITLISTED and not self.waitlisted:
            self.waitlisted = datetime.now(UTC)

    @property
    def email(self):
        return self.studio.email

    @property
    def reviews_to_email(self):
        return [review for review in self.reviews if review.send_to_studio]

    @property
    def video_href(self):
        return make_url(self.link_to_video)

    @property
    def href(self):
        return make_url(self.link_to_game)

    @property
    def screenshots(self):
        return [img for img in self.images if img.is_screenshot]

    @property
    def best_screenshots(self):
        return [
            img for img in self.images
            if img.is_screenshot and img.use_in_promo]

    def best_screenshot_downloads(self, count=2):
        all_images = reversed(sorted(
            self.images,
            key=lambda img: (
                img.is_screenshot and img.use_in_promo,
                img.is_screenshot,
                img.use_in_promo)))

        screenshots = []
        for i, screenshot in enumerate(all_images):
            if os.path.exists(screenshot.filepath):
                screenshots.append(screenshot)
                if len(screenshots) >= count:
                    break
        return screenshots

    def best_screenshot_download_filenames(self, count=2):
        nonchars = re.compile(r'[\W]+')
        best_screenshots = self.best_screenshot_downloads(count)
        screenshots = []
        for i, screenshot in enumerate(best_screenshots):
            if os.path.exists(screenshot.filepath):
                name = '_'.join([s for s in self.title.lower().split() if s])
                name = nonchars.sub('', name)
                filename = '{}_{}.{}'.format(
                    name, len(screenshots) + 1, screenshot.extension.lower())
                screenshots.append(filename)
                if len(screenshots) >= count:
                    break
        return screenshots + ([''] * (count - len(screenshots)))

    @property
    def promo_image(self):
        return next(
            iter([img for img in self.images if not img.is_screenshot]), None)

    @property
    def missing_steps(self):
        steps = []
        if not self.link_to_video:
            steps.append(
                'You have not yet included a link to a video showcasing '
                'at least 30 seconds of gameplay'
            )
        if not self.link_to_game:
            steps.append(
                'You have not yet included a link to where the judges can '
                'access your game')
        if self.code_type != c.NO_CODE and self.link_to_game:
            if not self.codes:
                steps.append(
                    'You have not yet attached any codes to this game for '
                    'our judges to use')
            elif not self.unlimited_code \
                    and len(self.codes) < c.MIVS_CODES_REQUIRED:
                steps.append(
                    'You have not attached the {} codes you must provide '
                    'for our judges'.format(c.MIVS_CODES_REQUIRED))
        if not self.agreed_showtimes:
            steps.append(
                'You must agree to the showtimes detailed on the game form')
        if not self.agreed_liability:
            steps.append(
                'You must check the box that agrees to our liability waiver')

        return steps

    @property
    def video_broken(self):
        for r in self.reviews:
            if r.video_status == c.BAD_LINK:
                return True

    @property
    def unlimited_code(self):
        for code in self.codes:
            if code.unlimited_use:
                return code

    @property
    def submittable(self):
        return not self.missing_steps

    @property
    def scores(self):
        return [r.game_score for r in self.reviews if r.game_score]

    @property
    def score_sum(self):
        return sum(self.scores, 0)

    @property
    def average_score(self):
        return (self.score_sum / len(self.scores)) if self.scores else 0

    @property
    def has_issues(self):
        return any(r.has_issues for r in self.reviews)

    @property
    def confirmed(self):
        return self.status == c.ACCEPTED \
            and self.studio \
            and self.studio.group_id

    @hybrid_property
    def has_been_accepted(self):
        return self.status == c.ACCEPTED

    @property
    def guidebook_name(self):
        return self.studio.name

    @property
    def guidebook_subtitle(self):
        return self.title

    @property
    def guidebook_desc(self):
        return self.description

    @property
    def guidebook_location(self):
        return ''

    @property
    def guidebook_image(self):
        return self.best_screenshot_download_filenames()[0]

    @property
    def guidebook_thumbnail(self):
        return self.best_screenshot_download_filenames()[1] \
            if len(self.best_screenshot_download_filenames()) > 1 else self.best_screenshot_download_filenames()[0]

    @property
    def guidebook_images(self):
        image_filenames = [self.best_screenshot_download_filenames()[0]]
        images = [self.best_screenshot_downloads()[0]]
        if self.guidebook_image != self.guidebook_thumbnail:
            image_filenames.append(self.guidebook_thumbnail)
            images.append(self.best_screenshot_downloads()[1])

        return image_filenames, images


class IndieGameImage(MagModel):
    game_id = Column(UUID, ForeignKey('indie_game.id'))
    filename = Column(UnicodeText)
    content_type = Column(UnicodeText)
    extension = Column(UnicodeText)
    description = Column(UnicodeText)
    use_in_promo = Column(Boolean, default=False)
    is_screenshot = Column(Boolean, default=True)

    @property
    def url(self):
        return 'view_image?id={}'.format(self.id)

    @property
    def filepath(self):
        return os.path.join(c.MIVS_GAME_IMAGE_DIR, str(self.id))


class IndieGameCode(MagModel):
    game_id = Column(UUID, ForeignKey('indie_game.id'))
    judge_id = Column(UUID, ForeignKey('indie_judge.id'), nullable=True)
    code = Column(UnicodeText)
    unlimited_use = Column(Boolean, default=False)
    judge_notes = Column(UnicodeText, admin_only=True)

    @property
    def type_label(self):
        return 'Unlimited-Use' if self.unlimited_use else 'Single-Person'


class IndieGameReview(MagModel):
    game_id = Column(UUID, ForeignKey('indie_game.id'))
    judge_id = Column(UUID, ForeignKey('indie_judge.id'))
    video_status = Column(
        Choice(c.MIVS_VIDEO_REVIEW_STATUS_OPTS), default=c.PENDING)
    game_status = Column(
        Choice(c.MIVS_GAME_REVIEW_STATUS_OPTS), default=c.PENDING)
    game_content_bad = Column(Boolean, default=False)

    # 0 = not reviewed, 1-10 score (10 is best)
    readiness_score = Column(Integer, default=0)
    design_score = Column(Integer, default=0)
    enjoyment_score = Column(Integer, default=0)
    game_review = Column(UnicodeText)
    developer_response = Column(UnicodeText)
    staff_notes = Column(UnicodeText)
    send_to_studio = Column(Boolean, default=False)

    __table_args__ = (
        UniqueConstraint('game_id', 'judge_id', name='review_game_judge_uniq'),
    )

    @property
    def game_score(self):
        if self.has_game_issues or not (self.readiness_score and self.design_score and self.enjoyment_score):
            return 0
        return sum([self.readiness_score, self.design_score, self.enjoyment_score]) / float(3)

    @property
    def has_video_issues(self):
        return self.video_status in c.MIVS_PROBLEM_STATUSES

    @property
    def has_game_issues(self):
        if self.game_status != c.COULD_NOT_PLAY:
            return self.game_status in c.MIVS_PROBLEM_STATUSES

    @property
    def has_issues(self):
        return self.has_video_issues or self.has_game_issues


@on_startup
def add_applicant_restriction():
    """
    We use convenience functions for our form handling, e.g. to
    instantiate an attendee from an id or from form data we use the
    session.attendee() method. This method runs on startup and overrides
    the methods which are used for the game application forms to add a
    new "applicant" parameter.  If truthy, this triggers three
    additional behaviors:
    1) We check that there is currently a logged in studio, and redirect
       to the initial application form if there is not.
    2) We check that the item being edited belongs to the
       currently-logged-in studio and raise an exception if it does not.
       This check is bypassed for new things which have not yet been
       saved to the database.
    3) If the model is one with a "studio" relationship, we set that to
       the currently-logged-in studio.

    We do not perform these kinds of checks for indie judges, for two
    reasons:
    1) We're less concerned about judges abusively editing each other's
       reviews.
    2) There are probably some legitimate use cases for one judge to be
       able to edit another's reviews, e.g. to correct typos or reset a
       review's status after a link has been fixed, etc.
    """
    from uber.models import Session

    def override_getter(method_name):
        orig_getter = getattr(Session.SessionMixin, method_name)

        @wraps(orig_getter)
        def with_applicant(self, *args, **kwargs):
            applicant = kwargs.pop('applicant', False)
            instance = orig_getter(self, *args, **kwargs)
            if applicant:
                studio = self.logged_in_studio()
                if hasattr(instance.__class__, 'game'):
                    assert instance.is_new or studio == instance.game.studio
                else:
                    assert instance.is_new or studio == instance.studio
                    instance.studio = studio
            return instance
        setattr(Session.SessionMixin, method_name, with_applicant)

    names = [
        'indie_developer',
        'indie_game',
        'indie_game_code',
        'indie_game_image']
    for name in names:
        override_getter(name)
