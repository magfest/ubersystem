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
from uber.models import Attendee, Session, PromoCodeGroup
from uber.model_checks import invalid_phone_number
from uber.utils import get_age_conf_from_birthday
from uber.forms.attendee import *
from uber.validations import phone_validators, email_validators, address_required_validators, valid_zip_code


def placeholder_unassigned_fields(form):
    field_list = ['birthdate', 'age_group', 'ec_name', 'ec_phone', 'address1', 'city',
                  'region', 'region_us', 'region_canada', 'zip_code', 'country', 'onsite_contact',
                  'badge_printed_name', 'cellphone', 'confirm_email']

    if form.model.valid_placeholder:
        return field_list

    if form.is_admin and form.model.unassigned_group_reg:
        return ['first_name', 'last_name', 'email'] + field_list
    
    return []


def create_placeholder_check():
    return lambda x: x.name not in placeholder_unassigned_fields(x.form)


def ignore_unassigned_and_placeholders(func):
    @wraps(func)
    def with_skipping(form, field, *args, **kwargs):
        if field.name not in placeholder_unassigned_fields(form):
            return func(form, field, *args, **kwargs)
    return with_skipping


PersonalInfo.field_validation.required_fields = {
    'first_name': ("Please provide your first name.", 'first_name', create_placeholder_check()),
    'last_name': ("Please provide your last name.", 'last_name', create_placeholder_check()),
    'email': ("Please enter an email address.", 'email', create_placeholder_check()),
    'ec_name': ("Please tell us the name of your emergency contact.", 'ec_name', create_placeholder_check()),
    'ec_phone': ("Please give us an emergency contact phone number.", 'ec_phone', create_placeholder_check()),
}


for field_name, message in address_required_validators.items():
    PersonalInfo.field_validation.required_fields[field_name] = (message, field_name, create_placeholder_check())


if c.COLLECT_EXACT_BIRTHDATE:
    PersonalInfo.field_validation.required_fields['birthdate'] = ("Please enter your date of birth.",
                                                                  'birthdate', create_placeholder_check())
else:
    PersonalInfo.field_validation.required_fields['age_group'] = ("Please select your age group.",
                                                                  'age_group', create_placeholder_check())


PersonalInfo.field_validation.validations['badge_printed_name'].update({
    'optional': validators.Optional(),
    'length': validators.Length(max=20,
                                message="Your printed badge name is too long. Please use less than 20 characters."),
    'invalid_chars': validators.Regexp(c.VALID_BADGE_PRINTED_CHARS, message="""Your printed badge name has invalid
                                characters. Please use only alphanumeric characters and symbols."""),
})
PersonalInfo.field_validation.validations['birthdate']['optional'] = validators.Optional()
PersonalInfo.field_validation.validations['email'].update(dict({'optional': validators.Optional()}, **email_validators))
PersonalInfo.field_validation.validations['cellphone'].update(phone_validators)
PersonalInfo.field_validation.validations['ec_phone'].update(phone_validators)
PersonalInfo.field_validation.validations['onsite_contact'].update({
    'length': validators.Length(max=500, message="""You have entered over 500 characters of onsite contact information. 
                                Please provide contact information for fewer friends.""")
})


@PersonalInfo.field_validation('zip_code')
@ignore_unassigned_and_placeholders
def zip_code_required(form, field):
    return valid_zip_code(form, field)


@PersonalInfo.field_validation('cellphone')
@ignore_unassigned_and_placeholders
def cellphone_required(form, field):
    if not form.copy_phone.data and not form.no_cellphone.data and (form.model.is_dealer or 
                                                                    form.model.staffing_or_will_be):
        raise ValidationError("Please provide a phone number.")


@PersonalInfo.new_or_changed('confirm_email')
@ignore_unassigned_and_placeholders
def confirm_email_required(form, field):
    if not c.PREREG_CONFIRM_EMAIL_ENABLED:
        return

    if not form.is_admin and (form.model.needs_pii_consent or form.model.badge_status == c.PENDING_STATUS):
        raise ValidationError("Please confirm your email address.")


@PersonalInfo.field_validation('badge_name')
@ignore_unassigned_and_placeholders
def badge_name_required(form, field):
    if not field.data and form.model.has_personalized_badge or (c.PRINTED_BADGE_DEADLINE and 
                                                                c.AFTER_PRINTED_BADGE_DEADLINE):
        raise ValidationError("Please enter a name to be printed on your badge.")


@PersonalInfo.field_validation('legal_name')
@ignore_unassigned_and_placeholders
def legal_name_required(form, field):
    if not field.data and not form.same_legal_name.data:
        raise ValidationError("Please provide the name on your photo ID or indicate that your first and last name match your ID.")


@PersonalInfo.field_validation('onsite_contact')
@ignore_unassigned_and_placeholders
def require_onsite_contact(form, field):
    if not field.data and not form.no_onsite_contact.data and form.model.badge_type not in [c.STAFF_BADGE,
                                                                                            c.CONTRACTOR_BADGE]:
        raise ValidationError("""Please enter contact information for at least one trusted friend onsite, 
                              or indicate that we should use your emergency contact information instead.""")


@PersonalInfo.new_or_changed('badge_type')
def past_printed_deadline(form, field):
    if field.data in c.PREASSIGNED_BADGE_TYPES and c.PRINTED_BADGE_DEADLINE and c.AFTER_PRINTED_BADGE_DEADLINE:
        with Session() as session:
            admin = session.current_admin_account()
            if admin.is_super_admin:
                return
    raise ValidationError(f'{c.BADGES[field.data]} badges have already been ordered, '
                            'so you cannot change your printed badge name.')


@PersonalInfo.field_validation('confirm_email')
def match_email(form, field):
        if field.data and field.data != form.email.data:
            raise ValidationError("Your email address and email confirmation do not match.")


@PersonalInfo.field_validation('birthdate')
def birthdate_format(form, field):
    # TODO: Make WTForms use this message instead of the generic DateField invalid value message
    if field.data and not isinstance(field.data, date):
        raise StopValidation('Please use the format YYYY-MM-DD for your date of birth.')
    elif field.data and field.data > date.today():
        raise ValidationError('You cannot be born in the future.')


@PersonalInfo.field_validation('birthdate')
def attendee_age_checks(form, field):
    age_group_conf = get_age_conf_from_birthday(field.data, c.NOW_OR_AT_CON) \
        if (hasattr(form, "birthdate") and form.birthdate.data) else field.data
    if age_group_conf and not age_group_conf['can_register']:
        raise ValidationError('Attendees {} years of age do not need to register, but MUST be '
                                'accompanied by a parent at all times!'.format(age_group_conf['desc'].lower()))


@PersonalInfo.field_validation('cellphone')
def not_same_cellphone_ec(form, field):
    if field.data and field.data == form.ec_phone.data:
        raise ValidationError("Your phone number cannot be the same as your emergency contact number.")