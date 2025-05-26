from datetime import date
from wtforms import validators
from wtforms.validators import ValidationError, StopValidation

from uber.config import c
from uber.forms.security import WatchListEntry
from uber.model_checks import validation
from uber.utils import localized_now


WatchListEntry.field_validation.required_fields = {
    'reason': "Please enter the reason this attendee is on the watchlist.",
    'action': "Please describe what, if anything, an attendee should do before they can check in."
}


WatchListEntry.field_validation.validations['email']['optional'] = validators.Optional()
WatchListEntry.field_validation.validations['birthdate']['optional'] = validators.Optional()
WatchListEntry.field_validation.validations['expiration']['optional'] = validators.Optional()


@WatchListEntry.field_validation('birthdate')
def birthdate_format(form, field):
    # TODO: Make WTForms use this message instead of the generic DateField invalid value message
    if field.data and not isinstance(field.data, date):
        raise StopValidation('Please use the format YYYY-MM-DD for the date of birth.')
    elif field.data and field.data > date.today():
        raise ValidationError('Attendees cannot be born in the future.')