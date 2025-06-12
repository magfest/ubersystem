from wtforms import validators
from wtforms.validators import ValidationError

from uber.config import c
from uber.forms.panels import PanelistInfo, PanelInfo, PanelOtherInfo, PanelConsents
from uber.model_checks import validation
from uber.utils import localized_now


PanelistInfo.field_validation.required_fields = {
    'first_name': "Please provide a first name.",
    'last_name': "Please provide a last name.",
    'email': "Please enter an email address.",
    'cellphone': "Please provide a phone number.",
}


PanelInfo.field_validation.required_fields = {
    'name': "Please enter a panel name.",
    'length': "Please estimate how long this panel will need to be.",
    'length_text': ('Please specify how long your panel will be.', 'length', lambda x: x == c.OTHER),
    'length_reason': ('Please explain why your panel needs to be longer than sixty minutes.',
                      'length', lambda x: x != c.SIXTY_MIN),
    'description': "Please enter a description of what this panel will be about.",
    'presentation': "Please select a panel type.",
    'other_presentation': ('Since you selected "Other" for your type of panel, please describe it.',
                           'presentation', lambda x: x == c.OTHER),
    'noise_level': "Please select a noise level.",
}


if len(c.LIVESTREAM_OPTS) > 2:
    PanelInfo.field_validation.required_fields['livestream'] = "Please select your preference for recording/livestreaming."
elif c.CAN_LIVESTREAM:
    PanelInfo.field_validation.required_fields['livestream'] = "Please let us know if we can livestream your panel."


if len(c.LIVESTREAM_OPTS) <= 2:
    PanelInfo.field_validation.required_fields['record'] = "Please let us know if we can record your panel."


if len(c.PANEL_CONTENT_OPTS) > 1:
    PanelInfo.field_validation.required_fields['granular_rating'] = "Please select what your panel's content will contain, or None."
elif len(c.PANEL_RATING_OPTS) > 1:
    PanelInfo.field_validation.required_fields['rating'] = "Please select a content rating for your panel."


@PanelInfo.field_validation('department')
def require_if_multi_departments(form, field):
    # This has to be inside a function in order to avoid the system
    # accessing the DB before migrations are run

    if len(c.PANELS_DEPT_OPTS) > 1 and not field.data:
        raise ValidationError("Please select a department.")


@PanelInfo.field_validation('granular_rating')
def none_is_none_granular_rating(form, field):
    if c.NONE in field.data and len(field.data) > 1:
        raise ValidationError("You cannot select mature content for your panel and also 'None'.")


PanelOtherInfo.field_validation.required_fields = {
    'tables_desc': ("Please describe how you need tables set up for your panel.", 'need_tables'),
    'cost_desc': ("Please describe the materials you will provide and how much you will charge attendees for them.", 'has_cost'),
    'affiliations': ("Please list your affiliations.", 'has_affiliations'),
    'past_attendance': ("Please describe past attendance for this panel.", 'held_before'),
    'unavailable': "Please let us know when you are unavailable to run a panel.",
    'verify_unavailable': "Please verify your unavailability.",
}


PanelConsents.field_validation.required_fields = {
    'verify_waiting': f"You must agree to not prematurely email {c.EVENT_NAME} about your panel application.",
    'coc_agreement': "You must agree to the Code of Conduct.",
    'data_agreement': "You must agree to our data policies.",
    'verify_tos': "You must accept our Terms of Accommodation.",
    'verify_poc': ("You must agree to being the point of contact for your group.",
                   'other_panelists', lambda x: int(x) != 0)
}
