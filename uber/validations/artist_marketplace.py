from datetime import date
from wtforms import validators
from wtforms.validators import ValidationError, StopValidation

from uber.config import c
from uber.forms.artist_marketplace import *
from uber.model_checks import validation
from uber.utils import localized_now


ArtistMarketplaceForm.field_validation.required_fields = {
    'attendee_id': "There is an issue with the form.",
    'name': "Please enter your business or fandom name.",
    'email_address': ("Please enter an email address.", 'copy_email'),
    'tax_number': "Please enter your Illinois Business Tax number.",
    'terms_accepted': "You must agree to the Artist Marketplace rules to continue.",
}


ArtistMarketplaceForm.field_validation.validations['tax_number']['pattern_match'] = validators.Regexp(
    "^[0-9-]*$", message="Please use only numbers and hyphens for your IBT number.")


AdminArtistMarketplaceForm.field_validation.required_fields['attendee_id'] = "You must select an attendee for this marketplace application."


@AdminArtistMarketplaceForm.field_validation('overridden_price')
def is_unset_or_number(form, field):
    if not field.data:
        return
    
    try:
        price = int(field.data)
    except ValueError:
        raise ValidationError("Application fee must be a number, or left blank.")
    if price < 0:
        raise ValidationError("Application fee must be a number that is 0 or higher, or left blank.")