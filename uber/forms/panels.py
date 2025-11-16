import cherrypy
from datetime import date

from markupsafe import Markup
from wtforms import (BooleanField, DateField, EmailField,
                     HiddenField, SelectField, SelectMultipleField, IntegerField,
                     StringField, TelField, validators, TextAreaField)
from wtforms.validators import ValidationError, StopValidation

from uber.config import c
from uber.forms import (UniqueList, MultiCheckbox, MagForm, DateTimePicker, SwitchInput, HourMinuteDuration,
                        HiddenBoolField, HiddenIntField, CustomValidation, Ranking)
from uber.custom_tags import popup_link
from uber.badge_funcs import get_real_badge_type
from uber.models import Attendee, BadgeInfo, Session, PromoCodeGroup
from uber.model_checks import invalid_phone_number
from uber.utils import get_age_conf_from_birthday


__all__ = ['PanelistInfo', 'PanelistCredentials', 'PanelInfo', 'PanelOtherInfo', 'PanelConsents', 'EventLocationInfo', 'EventInfo']


class PanelistInfo(MagForm):
    first_name = StringField('First Name', render_kw={'autocomplete': "fname"})
    last_name = StringField('Last Name', render_kw={'autocomplete': "lname"})
    email = EmailField('Email Address',
                       description="This should be the e-mail address associated with your badge.",
                       render_kw={'placeholder': 'test@example.com'})
    cellphone = TelField('Phone Number', description='The phone number at which we can most easily reach you before the event.')
    pronouns = SelectMultipleField('Pronouns', coerce=int, choices=c.PRONOUN_OPTS, widget=MultiCheckbox(),
                                   description="We will have both pre-printed and blank pronoun ribbons at the registration desk.")
    display_name = StringField(
        "Public Display Name",
        description=("The personal or group name to show on the schedule to let people know who is hosting the panel. Leave this field blank if you do not want a name displayed on the schedule."))
    other_pronouns = StringField("Other Pronouns", render_kw={'placeholder': 'e.g., Xe/Xir'})
    communication_pref = SelectMultipleField('Communication Preference', coerce=int,
                                             choices=c.COMMUNICATION_PREF_OPTS,
                                             widget=MultiCheckbox())
    other_communication_pref = StringField("Other Communication Preference",
                                           render_kw={'placeholder': "What other way should we contact you?"})
    requested_accessibility_services = BooleanField(
        f'I would like to be contacted by the {c.EVENT_NAME} Accessibility Services department if my panel is accepted '
        'and I understand my contact information will be shared with Accessibility Services for this purpose.',
        widget=SwitchInput())


class PanelistCredentials(MagForm):
    occupation = StringField("Occupation (if relevant)", render_kw={'placeholder': "What do you do?"})
    website = StringField("Website", render_kw={'placeholder': "www.example.com"})
    other_credentials = TextAreaField("Other Experience",
                                      render_kw={'placeholder': "What else qualifies you to conduct this panel?"})
    guidebook_bio = TextAreaField(
        "Schedule Bio",
        render_kw={'placeholder': "Please write a short bio to be displayed on our public-facing schedule."})
    social_media_info = TextAreaField(
        "Social Media Info",
        render_kw={'placeholder': "List social media sites you use and include a link to your page, or your username."})


class PanelInfo(MagForm):
    dynamic_choices_fields = {'department': lambda: [("", 'Please select an option')] + c.PANELS_DEPT_OPTS}

    is_guest = HiddenBoolField()
    name = StringField("Panel Name", description="The title that will appear on the event schedule. Max 120 characters.")
    department = SelectField("Department")
    presentation = SelectField("Type of Panel", coerce=int, default=0,
                               choices=[(0, 'Please select an option')] + c.PRESENTATION_OPTS)
    other_presentation = StringField("Other Panel Type")
    is_loud = BooleanField("I require an environment to have a large volume presentation.")
    length = SelectField("Expected Panel Length", default=0, coerce=int,
                         choices=[(0, 'Please select an option')] + c.PANEL_LENGTH_OPTS,
                             description="An hour is typical, including time for Q&A.")
    length_text = StringField("Other Panel Length")
    length_reason = TextAreaField("Why do you need the extra time?",
                                  description="Panels longer than 60 minutes are allowed, but discouraged unless you really need the extra time.")
    description = TextAreaField("Panel Description")
    public_description = TextAreaField("Schedule Description", description=(
        "To be shown on the public facing schedule. 200 words max. "
        "Leave blank if this is the same as the Panel Description."))
    noise_level = SelectField("Panel Noise Level", coerce=int, default=0,
                              choices=[(0, 'Please select an option')] + c.NOISE_LEVEL_OPTS)
    livestream = SelectField("Is it okay to livestream your panel?", default=0,
                             coerce=int, choices=[(0, 'Please select an option')] + c.LIVESTREAM_OPTS)
    record = SelectField("Is it okay to record your panel?", default=0,
                         coerce=int, choices=[(0, 'Please select an option')] + c.LIVESTREAM_OPTS,
                         description="While we don't record every panel, we attempt to record and post most panels to our YouTube channel after the event.")
    rating = SelectField(coerce=int, default=0, choices=[(0, 'Please select an option')] + c.PANEL_RATING_OPTS)
    granular_rating = SelectMultipleField("Panel Content", coerce=int, choices=c.PANEL_CONTENT_OPTS, widget=MultiCheckbox(),
                                          description='Please select the checkboxes above to let us know what your panel content may contain, or select "None" if you are sure your panel will be for all ages.')

    def description_desc(self):
        return Markup("This is to explain your pitch to us - this can be different from what you want to show the public. <strong>18+ panels will not be accepted.</strong>")

    def livestream_label(self):
        if len(c.LIVESTREAM_OPTS) > 2:
            return "Is it okay to record or livestream your panel?"
        return "Is it okay to livestream your panel?"
    
    def livestream_desc(self):
        if len(c.LIVESTREAM_OPTS) > 2:
            return "While we don't record/live stream every panel, we attempt to record and post most panels to our YouTube channel after the event."
        else:
            return "If you answered Yes to being livestreamed, please ensure that you're not presenting anything that could be considered copyright infringement."


class PanelOtherInfo(MagForm):
    need_tables = BooleanField("Would your panel benefit from a different setup from our normal panel rooms - for instance, an open space or tables for people to work on?")
    tables_desc = TextAreaField("Describe your table needs",
                                description="Our ability to reconfigure main panel rooms is very limited, but we have some alternative spaces that might be better suited for specific needs.")
    has_cost = BooleanField("Does your event require attendees to pay an upfront cost of materials for hands-on activities?")
    cost_desc = TextAreaField("Describe your material costs",
                              description="Please describe what materials you'll be providing and how much you'll need to charge attendees to participate.")

    tech_needs = SelectMultipleField(coerce=int, choices=c.TECH_NEED_OPTS)
    other_tech_needs = TextAreaField("Technical Needs")
    panelist_bringing = TextAreaField()
    has_affiliations = BooleanField("Do you have any group or website affiliations?")
    affiliations = TextAreaField("What are they?")
    held_before = BooleanField("Have you held this panel before?")
    past_attendance = TextAreaField("Where and how many people attended?")
    unavailable = TextAreaField("When are you NOT available?")
    verify_unavailable = BooleanField("I verify I am available at any time during the event EXCEPT for the times listed above.")
    available = TextAreaField()
    extra_info = TextAreaField("Is there anything else you would like to provide regarding your submission?",
                               description="This can include information not for public consumption, but merely things the event needs to know.")


class PanelConsents(MagForm):
    verify_waiting = BooleanField()
    coc_agreement = BooleanField()
    data_agreement = BooleanField()
    verify_poc = BooleanField("I have read and agree to the terms above.")
    verify_tos = BooleanField("I have read and agree to the terms above.")
    other_panelists = HiddenField()

    def verify_waiting_label(self):
        return Markup(f"""<strong>I will not prematurely e-mail {c.EVENT_NAME} to check my panel status</strong>,
                with the understanding that {c.EVENT_NAME} will send final determinations by the end of {c.EXPECTED_RESPONSE}.""")
    
    def coc_agreement_label(self):
        return Markup(f"""I agree to be bound by the <a href="{c.CODE_OF_CONDUCT_URL}">Code of Conduct</a>.""")
    
    def data_agreement_label(self):
        return f"""I agree that I am submitting my information to the panels department for the sole purpose of determining the panels
                selections for {c.EVENT_NAME_AND_YEAR}. My information will not be shared with any outside parties."""
    
    def data_agreement_desc(self):
        return Markup(f"""For more information on our privacy practices please contact us via <a href='{c.CONTACT_URL}'>{c.CONTACT_URL}</a>.""")
    

class EventLocationInfo(MagForm):
    admin_desc = True
    dynamic_choices_fields = {'department_id': lambda: [("", 'No Department')] + c.EVENT_DEPTS_OPTS}

    department_id = SelectField('Department',
                                description="The default department for events in this location, if any.")
    tracks = SelectMultipleField('Track(s)', description="The default tracks for events in this location.",
                                 coerce=int, choices=c.EVENT_TRACK_OPTS, widget=UniqueList())
    name = StringField('Location Name')
    room = StringField('Room Name',
                       description="If set, this is appended to the location name on the schedule, e.g., Location Name (Room Name)")


class EventInfo(MagForm):
    admin_desc = True
    dynamic_choices_fields = {'event_location_id': lambda: [("", 'No Location')] + c.SCHEDULE_LOCATION_OPTS,
                              'department_id': lambda: [("", 'No Department')] + c.EVENT_DEPTS_OPTS}

    event_location_id = SelectField(
        'Location',
        description="If no location is set, this event is not shown on or exported as part of the schedule.")
    department_id = SelectField('Department',
                                description="What department is in charge of this event, if any.")
    name = StringField('Event Name')
    description = TextAreaField('Description')
    public_description = TextAreaField('Public Description')
    tracks = SelectMultipleField('Track(s)', coerce=int, choices=c.EVENT_TRACK_OPTS, widget=UniqueList())
    start_time = StringField('Start Time', widget=DateTimePicker())
    duration = IntegerField('Duration', widget=HourMinuteDuration())
