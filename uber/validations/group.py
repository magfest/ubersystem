import cherrypy
from functools import wraps
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
from uber.models import Attendee, Session, PromoCodeGroup, BadgeInfo
from uber.model_checks import invalid_phone_number
from uber.utils import get_age_conf_from_birthday
from uber.forms.group import *
from uber.validations import address_required_validators, valid_zip_code, which_required_region


GroupInfo.field_validation.required_fields = {
    'name': "Please enter a group name."
}


GroupInfo.field_validation.validations['name']['length'] = validators.Length(
    max=40, message="Group names cannot be longer than 40 characters.")


AdminGroupInfo.field_validation.validations['cost']['minimum'] = validators.NumberRange(
    min=0, message="Total Group Price must be a number that is 0 or higher.")


ContactInfo.field_validation.required_fields = {
    'email_address': "Please enter your business email address.",
    'phone': "Please enter your business' phone number."
}

for field_name, message in address_required_validators.items():
    ContactInfo.field_validation.required_fields[field_name] = (message, field_name, lambda x: x.form.model.is_dealer)

for field_name in ['region', 'region_us', 'region_canada']:
    ContactInfo.field_validation.validations[field_name][f'required_{field_name}'] = which_required_region(field_name)


ContactInfo.field_validation.validations['zip_code']['valid'] = valid_zip_code


TableInfo.field_validation.required_fields = {
    'name': "Please enter a table name.",
    'description': ("Please provide a brief description of your business.", 'description',
                    lambda x: x.form.model.is_dealer),
    'website': ("Please enter your business' website address.", 'website',
                lambda x: x.form.model.is_dealer),
    'wares': ("You must provide a detailed explanation of what you sell for us to evaluate your submission.",
              'wares', lambda x: x.form.model.is_dealer),
    'categories': ("Please select at least one category your wares fall under.",
                   'categories', lambda x: x.form.model.is_dealer),
    'categories_text': ("Please describe what 'other' category your wares fall under.",
                        'categories', lambda x: c.OTHER in x)
}


TableInfo.field_validation.validations['name']['length'] = validators.Length(
    max=40, message="Table names cannot be longer than 40 characters.")


def group_requires_leader(form):
    return form.model.is_dealer or form.model.guest or getattr(form.model, 'guest_group_type', None)


LeaderInfo.field_validation.required_fields = {
    'leader_first_name': ("Please provide the group leader's first name.", 'leader_first_name',
                          lambda x: group_requires_leader(x.form)),
    'leader_last_name': ("Please provide the group leader's last name.", 'leader_last_name',
                         lambda x: group_requires_leader(x.form)),
    'leader_email': ("Please enter an email address.", 'leader_email', lambda x: group_requires_leader(x.form)),
    'leader_cellphone': ("Please provide a phone number.", 'leader_cellphone', lambda x: x.form.model.is_dealer),
}


LeaderInfo.field_validation.validations['email']['optional'] = validators.Optional()