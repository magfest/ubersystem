import cherrypy
from datetime import date

from markupsafe import Markup
from wtforms import (BooleanField, URLField, EmailField,
                     HiddenField, SelectField, SelectMultipleField, FileField,
                     StringField, TelField, widgets, TextAreaField)
from wtforms.validators import ValidationError, StopValidation

from uber.config import c
from uber.forms import (AddressForm, MultiCheckbox, MagForm, SelectBooleanField, SwitchInput, NumberInputGroup,
                        HiddenBoolField, IntegerField, SelectDynamicChoices, UniqueList, SelectButtonGroup)
from uber.custom_tags import popup_link
from uber.badge_funcs import get_real_badge_type
from uber.models import Attendee, BadgeInfo, Session, PromoCodeGroup
from uber.model_checks import invalid_phone_number
from uber.utils import get_age_conf_from_birthday


__all__ = ['StudioInfo', 'DeveloperInfo', 'MivsGameInfo', 'MivsDemoInfo', 'MivsConsents', 'MivsCode', 'MivsScreenshot',
           'ArcadeGameInfo', 'ArcadeConsents', 'ArcadeLogistics', 'ArcadePhoto', 'RetroGameInfo', 'RetroGameDetails',
           'RetroLogistics', 'RetroScreenshot', 'MivsJudgeInfo', 'JudgeShowcaseInfo', 'NewJudgeInfo', 'GameReview']


def int_or_empty(val):
    if not val:
        return ''
    return int


class StudioInfo(MagForm):
    name = StringField('Studio Name')
    website = StringField('Website')
    other_links = StringField('Other Links (Social media, Linktree, etc)', widget=UniqueList())


class AdminStudioInfo(StudioInfo):
    status = SelectField('Status', coerce=int, choices=c.MIVS_STUDIO_STATUS_OPTS)
    staff_notes = TextAreaField('Notes')


class DeveloperInfo(MagForm):
    first_name = StringField('First Name', render_kw={'autocomplete': "fname"})
    last_name = StringField('Last Name', render_kw={'autocomplete': "lname"})
    email = EmailField('Email Address', render_kw={'placeholder': 'test@example.com'})
    cellphone = TelField('Phone Number')
    gets_emails = BooleanField('I want to receive emails about my studio\'s showcase submissions.')
    agreed_coc = BooleanField()
    agreed_data_policy = BooleanField()

    def agreed_coc_label(self):
        return Markup(f"""I agree to be bound by the <a href="{c.CODE_OF_CONDUCT_URL}">Code of Conduct</a>.""")
    
    def agreed_data_policy_label(self):
        return f"""I agree that I am submitting my information to MAGFest for the sole purpose of
        determining showcase selections for {c.EVENT_NAME_AND_YEAR}. My information will not be shared with any outside parties."""
    
    def agree_data_policy_desc(self):
        return Markup(f"""For more information on our privacy practices please contact us via <a href='{c.CONTACT_URL}'>{c.CONTACT_URL}</a>.""")


class MivsGameInfo(MagForm):
    title = StringField('Game Title')
    brief_description = StringField('Brief Description')
    description = TextAreaField('Full Description')
    genres = SelectMultipleField('Genres', coerce=int, choices=c.MIVS_GENRE_OPTS,
                                 widget=MultiCheckbox(), description="Please select all that apply.")
    genres_text = StringField('', render_kw={'placeholder': "Other genre(s)"})
    has_multiplayer = BooleanField('This is a multiplayer game.')
    player_count = StringField('Number of Players', render_kw={'placeholder': "E.g., 1-4"})
    platforms = SelectMultipleField('Platforms Used for Demo', coerce=int,
                                    choices=c.MIVS_PLATFORM_OPTS, widget=MultiCheckbox())
    platforms_text = StringField('', render_kw={'placeholder': "Other platform(s)"})
    content_warning = BooleanField('I would like to add a content or trigger warning for this game.')
    warning_desc = TextAreaField('Content/Trigger Warning Description')
    photosensitive_warning = BooleanField('This game may trigger photosensitivity issues.')
    requires_gamepad = BooleanField('This game requires a gamepad.')
    is_alumni = BooleanField('This game has been shown at Super MAGFest before.')


class MivsDemoInfo(MagForm):
    link_to_video = URLField('Link to Video',
                             description="Please include a link to a YouTube video, 720p or better, no longer than 2 minutes.")
    link_to_game = URLField('Link to Game')
    no_password = BooleanField('The download link for this game does not require a password.')
    password_to_game = StringField('Game Download Password', render_kw={'autocomplete': "off"})
    code_type = SelectField('Game Activation Code', coerce=int, default=0,
                            choices=[(0, 'Please select an option')] + c.MIVS_CODE_TYPE_OPTS)
    code_instructions = StringField('Instructions for Game Code(s)')
    build_status = SelectField('Game Build Status', coerce=int, default=0,
                               choices=[(0, 'Please select an option')] + c.MIVS_BUILD_STATUS_OPTS)
    how_to_play = TextAreaField(
        'How to Play',
        description="Please include any instructions necessary to play, especially for things which might not be obvious.")
    build_notes = TextAreaField('Build Notes')

    def link_to_game_desc(self):
        return "Allowed game download sites include: self hosted, steam, itch.io, dropbox, google drive, apple app store, and \
            google play store. If putting your demo on Google drive, it must be made public during judging period."
    
    def build_notes_desc(self):
        return 'List any special instructions related specifically to this build to work around a known bug. \
            (Instructions that are relevant to all builds should be included in the "How To Play" section.)'


class MivsConsents(MagForm):
    agreed_liability = BooleanField()
    agreed_showtimes = BooleanField()

    def agreed_liability_label(self):
        return "I understand that I am responsible for all equipment brought to the indie showcase by myself \
            or my team, and we do not hold liable MAGFest, MIVS, or the venue in the event equipment is stolen or damaged."
    
    def agreed_showtimes_label(self):
        return """At least one person from my team will be available to man our booth from 11am to 7pm each full \
            convention day and on the last day from 11am to 2pm. Core hours exist each day to ensure games are setup \
                for attendees to play. Games may be setup past core hours as the MIVS area is open 24 hours and will \
                    have volunteers on hand during this time."""


class MivsCode(MagForm):
    code = StringField("Code")
    unlimited_use = BooleanField("This code can be shared among all judges instead of being assigned to a single judge.")


class MivsScreenshot(MagForm):
    description = TextAreaField("Screenshot Description")
    image = FileField("Image File (max 5MB)", render_kw={'accept': "image/*"})
    is_screenshot = HiddenBoolField('', default=True)


class MivsJudgeInfo(MagForm):
    genres = SelectMultipleField('Genres', coerce=int, widget=MultiCheckbox(), choices=c.MIVS_JUDGE_GENRE_OPTS)
    platforms = SelectMultipleField('Platforms Owned', coerce=int, widget=MultiCheckbox(), choices=c.MIVS_PLATFORM_OPTS)
    platforms_text = TextAreaField('PC Specs and Other Platforms',
                                   render_kw={'placeholder': 'List your PC specs and any other platforms you own.'})
    vr_text = StringField('', render_kw={'placeholder': 'VR/AR platform(s)'})
    no_game_submission = BooleanField('I have not submitted a game to MIVS this year.', default=False)

    def get_non_admin_locked_fields(self, model):
        return ['showcases']


class NewJudgeInfo(MagForm):
    admin_desc = True

    first_name = StringField('First Name', default='')
    last_name = StringField('Last Name', default='')
    email = EmailField('Email Address', default='')


class JudgeShowcaseInfo(MagForm):
    admin_desc = True

    status = SelectField('Judge Status', coerce=int, choices=c.MIVS_JUDGE_STATUS_OPTS)
    email = StringField('Email Address',
                        description="Please note that changing this judge's email address will change the email they must log in with.")
    assignable_showcases = SelectMultipleField('Assignable Showcase(s)', choices=c.SHOWCASE_GAME_TYPE_OPTS, widget=MultiCheckbox(),
        description="This judge will be available to assign games to in the showcase(s) selected above.")
    all_games_showcases = SelectMultipleField(
        'Showcase(s) Reviewing All Games', choices=c.SHOWCASE_GAME_TYPE_OPTS, widget=MultiCheckbox(),
        description="This judge will be assigned to review ALL games submitted to the showcase(s) selected above.")
    staff_notes = TextAreaField('Staff Notes')


class ArcadeGameInfo(MagForm):
    title = StringField('Submission Name')
    primary_contact_id = SelectField('Primary Contact',
                                     description="This is who we will reach out to with information about this submission.",
                                     widget=SelectDynamicChoices(),
                                     validate_choice=False)
    description = TextAreaField('Brief Description', description="Just a few sentences, no more than two paragraphs.")
    link_to_video = URLField('Link to Video')

    def link_to_video_desc(self):
        return "Please provide footage of people playing your arcade game. \
            Cellphone video is fine, so long as we can see the action. \
            Please do not only send us a gameplay trailer that does not show the physical setup. \
            If the video is private, please provide a password."


class ArcadeConsents(MagForm):
    agreed_showtimes = BooleanField(
        f'At least one person from our team will be present at {c.EVENT_NAME} to set up our game on {c.INDIE_ARCADE_SETUP_TEXT} and remain all weekend to run the game.',
        description="The Indie Arcade staff can assist with a few games each year, but we do not have the resources to set up more than one or two games on our own.")
    agreed_equipment = BooleanField(
        'I understand that I will be responsible for supplying ALL equipment required to run my game, including power strips, screens, and speakers if necessary.',
        description="We highly recommend bringing a spare extension cord & labeling all of your equipment."
    )
    agreed_liability = BooleanField(
        f'I understand that I will be responsible for the safety and security of my own equipment during {c.EVENT_NAME}, which has a show floor open to the public for the entire event.',
        description="Some devs feel comfortable leaving their equipment on the show-floor overnight. If you do not, you will need to have a plan to secure it or bring it back to your room as we do not have a locked space."
    )


class ArcadeLogistics(MagForm):
    game_hours = SelectField(
        "Can Run 72 Hours",
        choices=['Yes','Other'], widget=SelectButtonGroup())
    game_hours_text = StringField('Let us know what your plans are for keeping your game up running for our prime hours.')
    game_end_time = SelectBooleanField(
        'Online Until 2pm Sunday', default='',
        description="We're committed to keeping our space active and safe for attendees until 2pm, but if you need to pack up your submission early on Sunday for travel, that is an option that we can discuss on a team-by-team basis.")
    player_count = SelectField('How many players is your submission designed for?',
                               choices=['1', '2', '3 or more'], widget=SelectButtonGroup())
    floorspace = SelectField('Required Floorspace', default=0,
                             description="If possible, provide approximate width/depth measurements for the space your players will need.",
                             coerce=int, choices=[(0, 'Please select an option')] + c.INDIE_ARCADE_FLOORSPACE_OPTS)
    floorspace_text = StringField('Width/Depth Measurements')
    cabinet_type = SelectField(
        'Cabinet/Installation Type', default=0,
        description='We provide floorspace and optional standard height folding tables.',
        coerce=int, choices=[(0, 'Please select an option')] + c.INDIE_ARCADE_CABINET_OPTS)
    cabinet_type_text = TextAreaField('Installation Description', description="Please be extremely descriptive and provide exact measurements.")
    sanitation = BooleanField('This game has special considerations with regard to sanitation.')
    sanitation_requests = TextAreaField('Sanitation Considerations')
    needs_transit = BooleanField(f'We will or may need assistance to get this game to {c.EVENT_NAME}.')
    transit_needs = TextAreaField('Transit Needs')
    found_how = StringField('How did you learn about the Indie Arcade?')
    read_faq = StringField(Markup("Did you read the FAQ?"))
    mailing_list = BooleanField(
        Markup("I would like to sign up this game's primary contact for the Indie Arcade mailing list."),
        description="We're starting a mailing list for Indie Arcade announcements and PR! You'll be able to opt out at any time via MailChimp."
    )

    def read_faq_desc(self):
        return Markup("Prove it. <a href='https://super.magfest.org/indie-arcade' target='_blank'>You can find it right here</a>.")


class ArcadePhoto(MagForm):
    image = FileField("Image File (max 5MB)", render_kw={'accept': "image/*"})


class RetroGameInfo(MagForm):
    title = StringField('Game Name')
    primary_contact_id = SelectField('Primary Contact',
                                     description="This is who we will reach out to with information about this submission.",
                                     widget=SelectDynamicChoices(),
                                     validate_choice=False)
    publisher_name = StringField('Publisher Name', description="If there is none, please write N/A.")
    brief_description = TextAreaField(
        'Short Description of Game',
        description="There are no specific restrictions on what this must include, but please keep it to no more than 300 characters.")


class RetroGameDetails(MagForm):
    genres = SelectMultipleField('Game Genre(s)', coerce=int, choices=c.MIVS_GENRE_OPTS,
                                 widget=MultiCheckbox(), description="Please select all that apply.")
    genres_text = StringField('Other Genre(s)', render_kw={'placeholder': "Other genre(s)"})
    platforms = SelectMultipleField('Release Platform(s)', coerce=int,
                                    choices=c.INDIE_RETRO_PLATFORM_OPTS, widget=MultiCheckbox())
    platforms_text = StringField('Other Platform(s)', render_kw={'placeholder': "Other platform(s)"})
    release_date = StringField('Availability or Expected Release Date',
                               description="Let us know if your game is already available or when it will be releasing.")
    description = TextAreaField('Full Description',
                                description="There are no specific restrictions on what this must include, but please keep it to no more than 4000 characters.")
    game_logo = FileField("Game Logo (max 5MB)",
                          description="Please ensure your game logo is a PNG with a transparent background.",
                          render_kw={'accept': "image/png"})
    other_assets = TextAreaField(
        'Link to Additional Promotional Assets',
        description="Feel free to share any additional screenshots, GIFs, or other promotional assets that you'd like us to take into consideration.")
    link_to_video = TextAreaField(
        'Link to Gameplay Video and/or Trailer',
        description="It must be a combined 2-5 minutes of footage and can be raw captured gameplay or trailers.")
    link_to_game = TextAreaField('Link to Rom File for Review')
    how_to_play = TextAreaField(
        'Instructions to Play',
        description="Please describe the process of setting up your game into a playable state, as well as listing the basic controls for the game so it can be reviewed. ")

    def link_to_game_desc(self):
        return "Review of the Rom is a mandatory step in the showcase process so we can guarantee a certain level of quality control \
            for the games that are accepted into the showcase. These files will remain secure and will not be shared outside of the review team."


class RetroLogistics(MagForm):
    link_to_webpage = TextAreaField('Link to Available Game Pages', description="e.g., a website, itch.io, Steam")
    in_person = SelectBooleanField(
        f'Are you able to attend {c.EVENT_NAME_AND_YEAR} in person to represent your game?', default='',
        description="Two tickets are included for the show, as well as space within the Indie Retro area. Hotels and travel are not included.",
        yes_label='In Person / Physical Participant', no_label='Remote /  Digital Participant')
    delivery_method = SelectField(
        'How do you plan to have your game physically available at the event?', default=0,
        description="Games that require Cartridge Assistance will be evaluated on a case-by case basis and the service is not guaranteed.",
        coerce=int, choices=[(0, 'Please select an option')] + c.INDIE_RETRO_DELIVERY_OPTS)
    found_how = TextAreaField('How did you learn about Indie Retro?')


class RetroScreenshot(MagForm):
    image = FileField("Image File (max 5MB)", render_kw={'accept': "image/*"})
    is_screenshot = HiddenBoolField('', default=True)


def generate_score_list():
    choices_list = []
    for num in range(0,11):
        if num == 0:
            choices_list.append((num, 'Unscored'))
        else:
            choices_list.append((num, str(num)))
    return choices_list


class GameReview(MagForm):
    read_how_to_play = BooleanField('I have reviewed the instructions on how to play.')
    video_status = SelectField('Video Reviewed?', coerce=int, choices=c.MIVS_VIDEO_REVIEW_STATUS_OPTS)
    game_status = SelectField('Game Reviewed?', coerce=int, choices=c.MIVS_GAME_REVIEW_STATUS_OPTS)
    game_status_text = StringField('Why could you not play the game?')
    readiness_score = SelectField('Show Readiness', coerce=int, choices=generate_score_list(), widget=SelectButtonGroup())
    design_score = SelectField('Overall Design', coerce=int, choices=generate_score_list(), widget=SelectButtonGroup())
    enjoyment_score = SelectField('Overall Enjoyment', coerce=int, choices=generate_score_list(), widget=SelectButtonGroup())
    game_content_bad = BooleanField('This game contains inappropriate content.')
    game_review = TextAreaField('Comments for the Devs (Optional)')

    def game_review_desc(self):
        return "Here is where you can leave notes and feedback about the game for the developers - what impressed you, what didn't, etc. \
            Please be mindful that your comments will be shared directly with the developers. Do not include judging categories \
                or scores and be respectful in your feedback."