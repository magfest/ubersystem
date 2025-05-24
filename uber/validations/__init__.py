from uber.model_checks import invalid_phone_number
from uber.utils import get_age_conf_from_birthday
from wtforms import validators
from wtforms.validators import ValidationError, StopValidation

def valid_cellphone(form, field):
    if field.data and invalid_phone_number(field.data):
        raise ValidationError('Please provide a valid 10-digit US phone number or '
                              'include a country code (e.g. +44) for international numbers.')

def email_validators():
    return [
        validators.Length(max=255, message="Email addresses cannot be longer than 255 characters."),
        validators.Email(granular_message=True),
        ]

from uber.validations.panels import *