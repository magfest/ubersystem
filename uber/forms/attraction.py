import cherrypy
from datetime import date

from markupsafe import Markup
from wtforms import (BooleanField, DateField, EmailField,
                     HiddenField, SelectField, SelectMultipleField, IntegerField,
                     StringField, TelField, validators, TextAreaField)
from wtforms.validators import ValidationError, StopValidation

from uber.config import c
from uber.forms import (SelectDynamicChoices, MultiCheckbox, MagForm, DateTimePicker, BlankOrIntegerField, HourMinuteDuration,
                        HiddenBoolField, HiddenIntField, CustomValidation, Ranking)
from uber.custom_tags import popup_link
from uber.badge_funcs import get_real_badge_type
from uber.models import Attendee, BadgeInfo, Session, PromoCodeGroup
from uber.model_checks import invalid_phone_number
from uber.utils import get_age_conf_from_birthday


__all__ = ['AttractionEventInfo']


class BaseAttractionInfo(MagForm):
    admin_desc = True

    #name = StringField('Name')
    #description = TextAreaField('Description')
    slots = IntegerField('Slots')
    populate_schedule = BooleanField('These events should also appear on the event schedule.')
    send_emails = BooleanField('These events should send emails to attendees.')
    waitlist_available = BooleanField('These events should open a waitlist when slots are filled.')
    waitlist_slots = IntegerField('Waitlist Slots', description="Set to 0 for an unlimited waitlist.")
    #warn_overlap = BooleanField('Show a warning if events in this feature overlap in the same location.')
    signups_open_type = SelectField(
        f'When do signups open?',
        choices=[('relative', 'A set time before the event starts'),
                 ('absolute', 'A specific day and time'),
                 ('not_open', 'Signups should not open automatically')])
    signups_open_relative = IntegerField('Time Before Event', widget=HourMinuteDuration())
    signups_open_time = StringField('Opening Time', widget=DateTimePicker())


class AttractionEventInfo(BaseAttractionInfo):
    dynamic_choices_fields = {'event_location_id': lambda: c.SCHEDULE_LOCATION_OPTS}

    attraction_id = HiddenField('')
    attraction_feature_id = HiddenField('')
    event_location_id = SelectField('Location', widget=SelectDynamicChoices())
    start_time = StringField('Start Time', widget=DateTimePicker())
    duration = IntegerField('Duration', widget=HourMinuteDuration())

    def populate_schedule_label(self):
        return "This event should also appear on the event schedule."
    
    def send_emails_label(self):
        return "This event should send emails to attendees."
    
    def waitlist_available_label(self):
        return "This event should open a waitlist when slots are filled."
