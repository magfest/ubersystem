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
from uber.models import Attraction, BadgeInfo, Session, PromoCodeGroup
from uber.model_checks import invalid_phone_number
from uber.utils import get_age_conf_from_birthday


__all__ = ['BaseAttractionInfo', 'AttractionInfo', 'AttractionFeatureInfo', 'AttractionEventInfo']


class BaseAttractionInfo(MagForm):
    admin_desc = True

    slots = IntegerField('Minimum # Slots')
    populate_schedule = BooleanField('These events should also appear on the event schedule.')
    no_notifications = BooleanField(
        'These events should NOT send notifications to attendees.',
        description="Check this box if you plan on sending reminders and information to attendees through other means.")
    waitlist_available = BooleanField('These events should open a waitlist when slots are filled.')
    waitlist_slots = IntegerField('Waitlist Slots', description="Set to 0 for an unlimited waitlist.")
    signups_open_type = SelectField(
        f'When do signups open?',
        choices=[('relative', 'A set time before the event starts'),
                 ('absolute', 'A specific day and time'),
                 ('not_open', 'Signups should not open automatically')])
    signups_open_relative = IntegerField('Time Before Event', widget=HourMinuteDuration())
    signups_open_time = StringField('Opening Time', widget=DateTimePicker())


class AttractionInfo(BaseAttractionInfo):
    dynamic_choices_fields = {'department_id': lambda: [("", 'No Department')] + c.EVENT_DEPTS_OPTS}

    name = StringField('Name')
    description = TextAreaField('Listing Description',
                                description="This description will be displayed to attendees on list of attractions.")
    full_description = TextAreaField(
        'Full Description',
        description="This description will be displayed to attendees when they are viewing this attraction's features. \
            Leave blank to use the listing description.")
    department_id = SelectField('Department',
                                description="What department is in charge of this attraction, if any.")
    is_public = BooleanField(
        'This attraction is visible on the public Attractions portal.',
        description="No events or features in this attraction will be visible or available for signups until this option is checked.")
    badge_num_required = BooleanField('The features in this attraction require a badge number to sign up by default.')
    restriction = SelectField('Signup Limits', coerce=int, choices=Attraction._RESTRICTION_OPTS,
                              description="How many events in this attraction a single attendee can sign up for.")
    advance_checkin = SelectField('Check-in Start Time', coerce=int, choices=Attraction._ADVANCE_CHECKIN_OPTS,
                                  description="How soon before an event attendees are told they must check in.")
    checkin_reminder = SelectField('Check-in Reminder', choices=Attraction._ADVANCE_NOTICES_OPTS, validate_choice=False,
                                  description="These reminders are sent via email or text according to attendees' preferences.")
    
    def slots_desc(self):
        return 'The minimum number of slots for events in this attraction. \
            Updating this will increase slots for all events in this attraction up to the minimum value.'


class AttractionFeatureInfo(BaseAttractionInfo):
    name = StringField('Name', description="Updating this will update any synced events on the schedule.")
    description = TextAreaField('Feature Description', description="Updating this will update any synced events on the schedule.")
    is_public = BooleanField(
        'This feature is visible on the public Attractions portal.',
        description="No events in this feature will be visible or available for signups until this option is checked.")
    badge_num_required = BooleanField('The events in this feature require a badge number to sign up.')

    def slots_desc(self):
        return 'The minimum number of slots for events in this feature. \
            Updating this will increase slots for all events in this feature up to the minimum value.'


class AttractionEventInfo(BaseAttractionInfo):
    dynamic_choices_fields = {'event_location_id': lambda: c.SCHEDULE_LOCATION_OPTS}

    attraction_id = HiddenField('')
    attraction_feature_id = HiddenField('')
    event_location_id = SelectField('Location', widget=SelectDynamicChoices())
    start_time = StringField('Start Time', widget=DateTimePicker())
    duration = IntegerField('Duration', widget=HourMinuteDuration())

    def slots_label(self):
        return 'Slots'

    def populate_schedule_label(self):
        return "This event should also appear on the event schedule."
    
    def no_notifications_label(self):
        return "This event should NOT send notifications to attendees."
    
    def waitlist_available_label(self):
        return "This event should open a waitlist when slots are filled."
