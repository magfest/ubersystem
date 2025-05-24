import cherrypy
from datetime import date

from markupsafe import Markup
from wtforms import (BooleanField, DateField, EmailField,
                     HiddenField, SelectField, SelectMultipleField, IntegerField,
                     StringField, TelField, validators, TextAreaField)
from wtforms.validators import ValidationError, StopValidation

from uber.config import c
from uber.forms import (AddressForm, MultiCheckbox, MagForm, SelectAvailableField, SwitchInput, NumberInputGroup,
                        HiddenBoolField, HiddenIntField, CustomValidation)
from uber.custom_tags import popup_link
from uber.badge_funcs import get_real_badge_type
from uber.models import Attendee, Session, PromoCodeGroup
from uber.model_checks import invalid_phone_number
from uber.utils import get_age_conf_from_birthday
from uber.forms.panels import *
from uber.validations import valid_cellphone


PanelistInfo.field_validation.required_fields = {
    'first_name': "Please provide your first name.",
    'last_name': "Please provide your last name.",
    'email': "Please enter an email address.",
    'cellphone': "Please provide a phone number.",
}


PanelistInfo.field_validation.validations['email']['length'] = validators.Length(max=255, message="Email addresses cannot be longer than 255 characters.")
PanelistInfo.field_validation.validations['email']['valid'] = validators.Email(granular_message=True)
PanelistInfo.field_validation.validations['cellphone']['valid'] = valid_cellphone


PanelistInfo.field_validation.update_required_validations()


PanelInfo.field_validation.required_fields = {
    'name': "Please enter a panel name.",
    'length': "Please estimate how long this panel will need to be.",
    'description': "Please enter a description of what this panel will be about.",
}


if len(c.PANEL_DEPT_OPTS) > 1:
    PanelInfo.field_validation.required_fields['department'] = "Please select a department."


if len(c.LIVESTREAM_OPTS) > 2:
    PanelInfo.field_validation.required_fields['livestream'] = "Please let us know if we can record or livestream your panel."
elif c.CAN_LIVESTREAM:
    PanelInfo.field_validation.required_fields['livestream'] = "Please let us know if we can livestream your panel."


if len(c.LIVESTREAM_OPTS) <= 2:
    PanelInfo.field_validation.required_fields['record'] = "Please let us know if we can record your panel."


if len(c.PANEL_CONTENT_OPTS) > 1:
    PanelInfo.field_validation.required_fields['granular_rating'] = "Please tell us about the content in your panel, or select None."
elif len(c.PANEL_RATING_OPTS) > 1:
    PanelInfo.field_validation.required_fields['rating'] = "Please select a content rating."


PanelInfo.field_validation.update_required_validations()


@PanelInfo.field_validation('other_presentation')
def required_if_other(form, field):
    if form.presentation.data == c.OTHER and not field.data:
        raise ValidationError("Please described your panel type.")


@PanelInfo.field_validation('length_text')
def required_if_other(form, field):
    if form.length.data == c.OTHER and not field.data:
        raise ValidationError("Please estimate your panel length.")


@PanelInfo.field_validation('length_reason')
def required_if_too_long(form, field):
    if form.length.data != c.SIXTY_MIN and not field.data:
        raise ValidationError("Please explain why your panel needs to be longer than 60 minutes.")


PanelOtherInfo.field_validation.required_fields = {
    'unavailable': "Please let us know when you are unavailable to run a panel.",
    'verify_unavailable': "Please verify your unavailability.",
}


PanelOtherInfo.field_validation.update_required_validations()


@PanelOtherInfo.field_validation('tables_desc')
def required_if_need_tables(form, field):
    if form.need_tables.data and not field.data:
        raise ValidationError("Please describe your table needs.")


@PanelOtherInfo.field_validation('cost_desc')
def required_if_has_cost(form, field):
    if form.has_cost.data and not field.data:
        raise ValidationError("Please describe your material costs.")


@PanelOtherInfo.field_validation('affiliations')
def required_if_has_affiliations(form, field):
    if form.has_affiliations.data and not field.data:
        raise ValidationError("Please list your affiliations.")


@PanelOtherInfo.field_validation('past_attendance')
def required_if_held_before(form, field):
    if form.held_before.data and not field.data:
        raise ValidationError("Please describe past attendance for this panel.")


PanelConsents.field_validation.required_fields = {
    'verify_waiting': f"You must agree to not prematurely email {c.EVENT_NAME} about your panel application.",
    'coc_agreement': "You must agree to the Code of Conduct.",
    'data_agreement': "You must agree to our data policies.",
    'verify_tos': "You must agree to our policies for Panelists.",
}


PanelConsents.field_validation.update_required_validations()


@PanelConsents.field_validation('verify_poc')
def sign_poc_if_others(form, field):
    pass