from uber.config import c
from uber.model_checks import invalid_phone_number, invalid_zip_code
from uber.forms import AddressForm
from wtforms import validators
from wtforms.validators import ValidationError, StopValidation
import logging

log = logging.getLogger(__name__)


def placeholder_unassigned_fields(form):
    field_list = Attendee.skip_placeholder_fields

    if form.is_admin and form.model.unassigned_group_reg:
        return ['first_name', 'last_name', 'email'] + field_list

    if form.model.placeholder or form.model.badge_status == c.NOT_ATTENDING:
        return field_list

    return []


def valid_zip_code(form, field):
    if not c.COLLECT_FULL_ADDRESS:
        if getattr(form, 'international', None):
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

    if field.data and not skip_validation and invalid_zip_code(field.data):
        raise ValidationError('Please enter a valid 5 or 9-digit zip code.')


def which_required_region(field_name, check_placeholder=False, check_lambda=lambda x: True):
    def region_validation(form, field):
        if getattr(form, 'copy_address', None) and form.copy_address.data:
            return
        if check_placeholder and 'region' in placeholder_unassigned_fields(form):
            return
        if not check_lambda(form):
            return

        country = form.country.data

        if field_name == 'region_us':
            if country == 'United States' and not field.data:
                raise StopValidation("Please select a state.")
        elif field_name == 'region_canada':
            if country == 'Canada' and not field.data:
                raise StopValidation("Please select a province.")
        else:
            if country not in ['United States', 'Canada'] and not field.data:
                raise StopValidation("Please enter a state, province, or region.")
    return region_validation


address_required_validators = {
    'address1': "Please enter a street address.",
    'city': "Please enter a city.",
    'zip_code': "Please enter a zip code.",
    'country': "Please enter a country.",
}


from uber.validations.artist_marketplace import *
from uber.validations.art_show import *
from uber.validations.attendee import *
from uber.validations.attraction import *
from uber.validations.department import *
from uber.validations.group import *
from uber.validations.hotel_lottery import *
from uber.validations.panels import *
from uber.validations.security import *
from uber.validations.showcase import *