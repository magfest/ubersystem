import cherrypy
from datetime import date

from markupsafe import Markup
from wtforms import (BooleanField, DateField, DateTimeField, EmailField,
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


__all__ = ['WatchListEntry']


class WatchListEntry(MagForm):
    field_validation, new_or_changed_validation = CustomValidation(), CustomValidation()

    first_names = StringField('First Names', render_kw={'placeholder': 'Use commas to separate possible first names.'})
    last_name = StringField('Last Name')
    email = EmailField('Email Address', validators=[
        validators.Optional(),
        validators.Length(max=255, message="Email addresses cannot be longer than 255 characters."),
        validators.Email(granular_message=True),
        ],
        render_kw={'placeholder': 'test@example.com'})
    birthdate = DateField('Date of Birth', validators=[validators.Optional()])
    reason = TextAreaField('Reason', validators=[
        validators.DataRequired("Please enter the reason this attendee is on the watchlist."),
        ])
    action = TextAreaField('Action', validators=[
        validators.DataRequired("Please describe what, if anything, an attendee should do before "
                                "they can check in."),
        ])
    expiration = DateField('Expiration Date', validators=[validators.Optional()])
    active = BooleanField('Automatically place matching attendees in the On Hold status.')

    @field_validation.birthdate
    def birthdate_format(form, field):
        # TODO: Make WTForms use this message instead of the generic DateField invalid value message
        if field.data and not isinstance(field.data, date):
            raise StopValidation('Please use the format YYYY-MM-DD for the date of birth.')
        elif field.data and field.data > date.today():
            raise ValidationError('Attendees cannot be born in the future.')
