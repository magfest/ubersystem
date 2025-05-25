from uber.config import c
from uber.model_checks import invalid_phone_number, invalid_zip_code
from uber.forms import AddressForm
from wtforms import validators
from wtforms.validators import ValidationError, StopValidation
from pockets.autolog import log

def valid_cellphone(form, field):
    if field.data and invalid_phone_number(field.data):
        raise ValidationError('Please provide a valid 10-digit US phone number or '
                              'include a country code (e.g. +44) for international numbers.')


phone_validators = {'valid': valid_cellphone}


email_validators = {
    'length': validators.Length(max=255, message="Email addresses cannot be longer than 255 characters."),
    'valid': validators.Email(granular_message=True),
    }


def valid_zip_code(form, field):
    if not c.COLLECT_FULL_ADDRESS:
        if getattr(form, 'international', None):
            log.error(form.international.data)
            skip_validation = form.international.data
        elif getattr(form, 'country', None):
            skip_validation = form.country.data != 'United States'
        else:
            skip_validation = False
    else:
        if getattr(form, 'country', None):
            skip_validation = form.country.data != 'United States'
        else:
            skip_validation = False

    if field.data and invalid_zip_code(field.data) and not skip_validation:
        raise ValidationError('Please enter a valid 5 or 9-digit zip code.')


address_required_validators = {
    'address1': "Please enter a street address.",
    'city': "Please enter a city.",
    'region': "Please enter a state, province, or region.",
    'region_us': "Please select a state.",
    'region_canada': "Please select a province.",
    'zip_code': "Please enter a zip code." if c.COLLECT_FULL_ADDRESS else "Please enter a valid 5 or 9-digit zip code.",
    'country': "Please enter a country.",
}


zip_code_validators = {
    'valid': valid_zip_code
}


from uber.validations.attendee import *
from uber.validations.panels import *