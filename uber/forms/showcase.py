import cherrypy
from datetime import date

from markupsafe import Markup
from wtforms import (BooleanField, URLField, EmailField,
                     HiddenField, SelectField, SelectMultipleField, FileField,
                     StringField, TelField, widgets, TextAreaField)
from wtforms.validators import ValidationError, StopValidation

from uber.config import c
from uber.forms import (AddressForm, MultiCheckbox, MagForm, SelectAvailableField, SwitchInput, NumberInputGroup,
                        HiddenBoolField, HiddenIntField, SelectDynamicChoices, UniqueList, SelectButtonGroup)
from uber.custom_tags import popup_link
from uber.badge_funcs import get_real_badge_type
from uber.models import Attendee, BadgeInfo, Session, PromoCodeGroup
from uber.model_checks import invalid_phone_number
from uber.utils import get_age_conf_from_birthday


__all__ = ['StudioInfo', 'DeveloperInfo']


class StudioInfo(MagForm):
    name = StringField('Studio Name')
    website = StringField('Website')
    other_links = StringField('Other Links (Social media, Linktree, etc)', widget=UniqueList())


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
    genres = SelectMultipleField('Genres', coerce=int, choices=c.MIVS_INDIE_GENRE_OPTS,
                                 widget=MultiCheckbox(), description="Please select all that apply.")
    genres_text = StringField('', render_kw={'placeholder': "Other genre(s)"})
    has_multiplayer = BooleanField('This is a multiplayer game.')
    player_count = StringField('Number of Players', render_kw={'placeholder': "E.g., 1-4"})
    platforms = SelectMultipleField('Platforms Used for Demo', coerce=int,
                                    choices=c.MIVS_INDIE_PLATFORM_OPTS, widget=MultiCheckbox())
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
    password_to_game = StringField('Game Download Password')
    code_type = SelectField('Game Activation Code', coerce=int, choices=c.MIVS_CODE_TYPE_OPTS)
    code_instructions = StringField('Instructions for Game Code(s)')
    build_status = SelectField('Game Build Status', coerce=int, choices=c.MIVS_BUILD_STATUS_OPTS)
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
    judge_notes = TextAreaField("Judge Notes")


class MivsScreenshot(MagForm):
    description = TextAreaField("Screenshot Description")
    image = FileField("Image File (max 5MB)", render_kw={'accept': "image/*"})
    is_screenshot = HiddenBoolField('', default=True)


class ArcadeGameInfo(MagForm):
    title = StringField('Submission Name')
    primary_contact = SelectField('Primary Contact',
                                  description="This is who we will reach out to with information about this submission.",
                                  widget=SelectDynamicChoices())
    description = TextAreaField('Brief Description', description="Just a few sentences, no more than two paragraphs.")
    link_to_video = URLField('Link to Video')

    def link_to_video_desc(self):
        return "Please provide footage of people playing your arcade game. \
            Cellphone video is fine, so long as we can see the action. \
            Please do not only send us a gameplay trailer that does not show the physical setup. \
            If the video is private, please provide a password."


class ArcadeConsents(MagForm):
    agreed_showtimes = BooleanField(
        f'At least one person from our team will be present at {c.EVENT_NAME} to set up our game on Jan 22nd (or early Jan 23rd) and remain all weekend to run the game.',
        description="The Indie Arcade staff can assist with a few games each year, but we do not have the resources to set up more than one or two games on our own.")
    agreed_equipment = BooleanField(
        'I understand that I will be responsible for supplying ALL equipment required to run my game.',
        description="It will be up to you and your team to provide all equipment for your game (including power strips, screens & speakers if necessary). We highly recommend bringing a spare extension cord & labeling all of your equipment."
    )
    agreed_liability = BooleanField(
        f'I understand that I will be responsible for the safety and security of my own equipment during {c.EVENT_NAME}.',
        description="We do not have a locked space and the show-floor will be open to the public for the entire event. Some devs feel comfortable leaving their equipment on the show-floor overnight. If you do not, you will need to have a plan to secure it or bring it back to your room."
    )


class ArcadeLogistics(MagForm):
    game_hours = SelectField(
        f"{c.EVENT_NAME} runs for 72 hours straight. It's a lot of fun but it can be taxing for physical installations. Will your game be able to run uninterrupted for this time?",
        choices=['Yes','Other'], widget=SelectButtonGroup())
    game_hours_text = StringField('Let us know what your plans are for keeping your game up running for our prime hours.')
    game_end_time = SelectField(
        'The Indie Arcade is open until 2PM EST on Sunday January 26th. Will your submission be able to stay live until this time?',
        description="We're committed to keeping our space active and safe for attendees until 2pm, but if you need to pack up your submission early on Sunday for travel, that is an option that we can discuss on a team-by-team basis.",
        choices=['Yes','No'], widget=SelectButtonGroup())
    player_count = SelectField('How many players is your submission designed for?',
                               choices=['1', '2', '3+'], widget=SelectButtonGroup())
    floorspace = SelectField('How much floorspace is needed to install and play your game?',
                             description="If possible, provide approximate width/depth measurements for the space your players will need.",
                             coerce=int, choices=c.INDIE_ARCADE_FLOORSPACE_OPTS)
    floorspace_text = StringField('Other')
    cabinet_type = SelectField(
        'What general physical description best represents your game?',
        description='We provide floorspace and optional standard height folding tables.',
        coerce=int, choices=c.INDIE_ARCADE_CABINET_OPTS)
    cabinet_type_text = TextAreaField('Other', description="Please be extremely descriptive and provide exact measurements.")
    sanitation = TextAreaField(
        'What special considerations does your game have with regard to sanitation?',
        description="We understand that standard safety precautions such as masking, social distancing, and surface cleaning can be difficult for innovative and custom-made games. The Indie Arcade is committed to creating a safe environment for both players and games - if these precautions seriously impact the ways in which players interact with your game let us know and we'll see what we can do.")
    needs_transit = TextAreaField(
        'Will you need any assistance to get your game to MAGFest?',
        description="We have a limited budget to assist devs with transit. Be aware, this budget is small and you have a better chance of being accepted if you can get your game here yourself. That being said, we do not want to close the door on devs with fewer resources. Please let us know exactly what you would need/if you would be comfortable carpooling etc.")
    also_mivs = BooleanField(
        'Are you also submitting this game to MIVS?',
        description="Indie Arcade is home to games and digital experiences with custom hardware components, such as alt control games and arcade cabinets. If you're looking to submit a more traditional game to the Indie Videogames Showcase, tune in to super.magfest.org/mivs for information on when and where to submit in the near future. If you have any questions, email mivs@magfest.org."
    )
    mailing_list = BooleanField(
        'Would you like to join our new mailing list?',
        description="We're starting a mailing list for Indie Arcade announcements and PR! We'll add your primary email as above and you'll be able to opt out at any time (via MailChimp)."
    )
    found_how = StringField('How did you learn about the Indie Arcade?')
    read_faq = StringField('FAQ')

    def read_faq_desc(self):
        return Markup("Did you read the FAQ? Prove it. <a href='https://super.magfest.org/indie-arcade' target='_blank'>You can find it right here</a>.")


class ArcadePhoto(MagForm):
    image = FileField("Image File (max 5MB)", render_kw={'accept': "image/*"})