import cherrypy
from datetime import date

from markupsafe import Markup
from wtforms import (BooleanField, URLField, EmailField,
                     HiddenField, SelectField, SelectMultipleField, FileField,
                     StringField, TelField, widgets, TextAreaField)
from wtforms.validators import ValidationError, StopValidation

from uber.config import c
from uber.forms import (AddressForm, MultiCheckbox, MagForm, SelectAvailableField, SwitchInput, NumberInputGroup,
                        HiddenBoolField, HiddenIntField, CustomValidation, UniqueList)
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