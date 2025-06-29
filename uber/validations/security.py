from datetime import date, datetime
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
WatchListEntry.field_validation.validations['expiration']['optional'] = validators.Optional()


@WatchListEntry.field_validation('birthdate')
def birthdate_format(form, field):
    if field.data:
        try:
            value = datetime.strptime(field.data, '%m/%d/%Y')
        except ValueError:
            raise StopValidation('Please use the format MM/DD/YYYY for your date of birth.')
    
        if value.date() > date.today():
            raise ValidationError('You cannot be born in the future.')