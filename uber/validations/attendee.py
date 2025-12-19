import cherrypy
from functools import wraps
from datetime import date, datetime, timedelta

from markupsafe import Markup
from dateutil.relativedelta import relativedelta
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
from uber.utils import get_age_conf_from_birthday, normalize_email_legacy
from uber.forms.attendee import *
from uber.validations import address_required_validators, valid_zip_code, placeholder_unassigned_fields, which_required_region


def ignore_unassigned_and_placeholders(func):
    @wraps(func)
    def with_skipping(form, field, *args, **kwargs):
        if field.name not in placeholder_unassigned_fields(form):
            return func(form, field, *args, **kwargs)
    return with_skipping


placeholder_check = lambda x: x.name not in placeholder_unassigned_fields(x.form)


# =============================
# PersonalInfo
# =============================

def prereg_must_confirm_email(form):
    if c.PREREG_CONFIRM_EMAIL_ENABLED and (
            not hasattr(form, 'copy_email') or not form.copy_email.data
            ) and not form.is_admin and (
                form.model.needs_pii_consent or form.model.badge_status == c.PENDING_STATUS):
        return True


PersonalInfo.field_validation.required_fields = {
    'first_name': ("Please provide your first name.", 'first_name', placeholder_check),
    'last_name': ("Please provide your last name.", 'last_name', placeholder_check),
    'badge_printed_name': (
        "Please enter a name for your custom-printed badge.", 'badge_printed_name',
        lambda x: x.form.model.has_personalized_badge and 'badge_printed_name' not in placeholder_unassigned_fields(x.form)),
    'email': ("Please enter an email address.", 'copy_email', lambda x: not x.data and 'email' not in placeholder_unassigned_fields(x.form)),
    'confirm_email': ("Please confirm your email address.", 'confirm_email', lambda x: prereg_must_confirm_email(x.form)),
    'ec_name': ("Please tell us the name of your emergency contact.", 'ec_name', placeholder_check),
    'ec_phone': ("Please give us an emergency contact phone number.", 'ec_phone', placeholder_check),
}


if c.COLLECT_EXACT_BIRTHDATE:
    PersonalInfo.field_validation.required_fields['birthdate'] = ("Please enter your date of birth.",
                                                                  'birthdate', placeholder_check)
else:
    PersonalInfo.field_validation.required_fields['age_group'] = ("Please select your age group.",
                                                                  'age_group', placeholder_check)


if c.COLLECT_FULL_ADDRESS:
    for field_name, message in address_required_validators.items():
        PersonalInfo.field_validation.required_fields[field_name] = (
            message, 'copy_address',
            lambda x: (not x or not x.data) and field_name not in placeholder_unassigned_fields(x.form))

    for field_name in ['region', 'region_us', 'region_canada']:
        PersonalInfo.field_validation.validations[field_name][f'required_{field_name}'] = which_required_region(
            field_name, check_placeholder=True)


PersonalInfo.field_validation.validations['zip_code']['valid'] = valid_zip_code
PersonalInfo.field_validation.validations['badge_printed_name'].update({
    'optional': validators.Optional(),
    'length': validators.Length(max=20,
                                message="Your printed badge name cannot be more than 20 characters long."),
    'invalid_chars': validators.Regexp(c.VALID_BADGE_PRINTED_CHARS, message="""Your printed badge name has invalid
                                characters. Please use only alphanumeric characters and symbols."""),
})
PersonalInfo.field_validation.validations['email']['optional'] = validators.Optional()
PersonalInfo.field_validation.validations['confirm_email']['optional'] = validators.Optional()
PersonalInfo.field_validation.validations['onsite_contact'].update({
    'length': validators.Length(max=500, message="""You have entered over 500 characters of onsite contact information. 
                                Please provide contact information for fewer friends.""")
})

if not c.COLLECT_FULL_ADDRESS:
    PersonalInfo.field_validation.required_fields['zip_code'] = (
        "Please enter a valid 5 or 9-digit zip code.", 'international',
        lambda x: not x.data and 'zip_code' not in placeholder_unassigned_fields(x.form))


@PersonalInfo.field_validation('cellphone')
@ignore_unassigned_and_placeholders
def cellphone_required(form, field):
    if not field.data and (not hasattr(form, 'copy_phone') or not form.copy_phone.data
            ) and not form.no_cellphone.data and (form.model.is_dealer or form.model.staffing_or_will_be):
        raise ValidationError("Please provide a phone number.")


@PersonalInfo.field_validation('confirm_email')
@ignore_unassigned_and_placeholders
def match_email(form, field):
    if c.PREREG_CONFIRM_EMAIL_ENABLED and field.data and \
            normalize_email_legacy(field.data) != normalize_email_legacy(form.email.data):
        raise ValidationError("Your email address and email confirmation do not match.")


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
        raise ValidationError("Please enter contact information for at least one trusted friend onsite, "
                              "or indicate that we should use your emergency contact information instead.")


@PersonalInfo.new_or_changed('badge_type')
def past_printed_deadline(form, field):
    if field.data in c.PREASSIGNED_BADGE_TYPES and c.PRINTED_BADGE_DEADLINE and c.AFTER_PRINTED_BADGE_DEADLINE:
        with Session() as session:
            admin = session.current_admin_account()
            if admin.is_super_admin:
                return
    raise ValidationError(f'{c.BADGES[field.data]} badges have already been ordered, '
                            'so you cannot change your printed badge name.')


@PersonalInfo.field_validation('birthdate')
def birthdate_format(form, field):
    if not field.data:
        return

    if isinstance(field.data, str):
        try:
            value = datetime.strptime(field.data, '%m/%d/%Y').date()
        except ValueError:
            raise StopValidation('Please use the format MM/DD/YYYY for your date of birth.')
    else:
        value = field.data

    if value > date.today():
        raise StopValidation('You cannot be born in the future.')
    
    if value < (date.today() - relativedelta(years=120)):
        raise StopValidation('You cannot be more than 120 years old.')


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

# =============================
# BadgeExtras
# =============================

BadgeExtras.field_validation.validations['amount_extra']['minimum'] = validators.NumberRange(
    min=0, message="Amount extra must be a number that is 0 or higher.")
BadgeExtras.field_validation.validations['extra_donation']['minimum'] = validators.NumberRange(
    min=0, message="Extra donation must be a number that is 0 or higher.")


@BadgeExtras.field_validation('shirt')
def require_shirt(form, field):
    if form.is_admin:
        return

    if (form.amount_extra.data and form.amount_extra.data > 0
            or form.badge_type.data in c.BADGE_TYPE_PRICES) and (field.data == c.NO_SHIRT or not field.data):
        raise ValidationError("Please select a shirt size.")


@BadgeExtras.new_or_changed('shirt')
def shirt_size_sold_out(form, field):
    if form.is_admin:
        return

    if field.data in field.get_sold_out_list():
        raise ValidationError(f"Sorry, we're sold out of {c.PREREG_SHIRTS[field.data]} shirts!")


@BadgeExtras.new_or_changed('amount_extra')
def upgrade_sold_out(form, field):
    if form.is_admin and not c.AT_THE_CON: # Temp
        return

    if field.data and field.data in c.SOLD_OUT_MERCH_TIERS:
        raise ValidationError("The upgrade you have selected is sold out.")
    elif field.data and getattr(c.kickin_availability_matrix, str(field.data), True) is False:
        raise ValidationError("The upgrade you have selected is no longer available.")


@BadgeExtras.field_validation('badge_type_single')
def must_select_day(form, field):
    if form.is_admin or (form.model.attendance_type == form.attendance_type.data and not form.model.is_new):
        return

    if hasattr(c, 'SINGLE_DAY') and form.attendance_type.data and \
            form.attendance_type.data == c.SINGLE_DAY and c.BADGES[field.data] not in c.DAYS_OF_WEEK:
        raise ValidationError("Please select which day you would like to attend.")


@BadgeExtras.field_validation('badge_type')
def must_select_type(form, field):
    if not c.BADGE_TYPE_PRICES or form.is_admin or (form.model.attendance_type == form.attendance_type.data and not form.model.is_new):
        return

    if form.attendance_type.data and form.attendance_type.data == c.WEEKEND and \
            field.data not in [c.ATTENDEE_BADGE, c.PSEUDO_DEALER_BADGE, c.PSEUDO_GROUP_BADGE] + list(c.BADGE_TYPE_PRICES.keys()):
        raise ValidationError("Please select what type of badge you want.")


@BadgeExtras.new_or_changed('badge_type')
def no_more_custom_badges(form, field):
    if field.data in c.PREASSIGNED_BADGE_TYPES and c.AFTER_PRINTED_BADGE_DEADLINE:
        with Session() as session:
            admin = session.current_admin_account()
            if admin.is_super_admin:
                return
        raise ValidationError('Custom badges have already been ordered, please choose a different badge type.')


@BadgeExtras.new_or_changed('badge_type')
def out_of_badge_type(form, field):
    badge_type = get_real_badge_type(field.data)
    with Session() as session:
        try:
            session.get_next_badge_num(badge_type)
        except AssertionError:
            raise ValidationError('We are sold out of {} badges.'.format(c.BADGES[badge_type]))

# =============================
# OtherInfo
# =============================

@OtherInfo.new_or_changed('promo_code_code')
def promo_code_valid(form, field):
    if field.data:
        with Session() as session:
            code = session.lookup_promo_code(field.data)
            if not code:
                group = session.lookup_registration_code(field.data, PromoCodeGroup)
                if not group:
                    raise ValidationError("The promo code you entered is invalid.")
                elif not group.valid_codes:
                    raise ValidationError(f"There are no more badges left in the group {group.name}.")
            else:
                if code.is_expired:
                    raise ValidationError("That promo code has expired.")
                elif not code.is_unlimited and code.uses_remaining <= 0:
                    raise ValidationError("That promo code has been used already.")

PreregOtherInfo.field_validation.required_fields = {
    'requested_depts_ids': ('Please select at least one department to volunteer for, or check "Anywhere".',
                            'staffing', lambda x: x and len(c.PUBLIC_DEPARTMENT_OPTS_WITH_DESC) > 1)
    }

# =============================
# Consents
# =============================

Consents.field_validation.required_fields = {
    'pii_consent': ("You must agree to allow us to store your personal information in order to register.",
                    'pii_consent', placeholder_check)
}

# =============================
# AdminBadgeFlags
# =============================

AdminBadgeFlags.field_validation.validations['overridden_price']['minimum'] = validators.NumberRange(
    min=0, message="Base badge price must be a number that is 0 or higher.")


@AdminBadgeFlags.new_or_changed('badge_num')
def dupe_badge_num(form, field):
    existing_name = ''
    if c.NUMBERED_BADGES and field.data:
        with Session() as session:
            existing = session.query(BadgeInfo).filter(BadgeInfo.ident == field.data,
                                                       BadgeInfo.attendee_id != None)
            if not existing.count():
                return
            else:
                existing_name = existing.first().attendee.full_name
        raise ValidationError('That badge number already belongs to {!r}'.format(existing_name))


@AdminBadgeFlags.field_validation('badge_num')
def not_in_range(form, field):
    if not field.data or form.no_badge_num and form.no_badge_num.data:
        return

    badge_type = get_real_badge_type(form.model.badge_type)
    lower_bound, upper_bound = c.BADGE_RANGES[badge_type]
    if not (lower_bound <= int(field.data) <= upper_bound):
        raise ValidationError(f'Badge number {field.data} is out of range for badge type \
                              {c.BADGES[form.model.badge_type]} ({lower_bound} - {upper_bound})')

# =============================
# CheckInForm
# =============================

CheckInForm.field_validation.validations['badge_printed_name'].update(PersonalInfo.field_validation.validations['badge_printed_name'])
CheckInForm.field_validation.validations['birthdate'].update(PersonalInfo.field_validation.validations['birthdate'])
CheckInForm.new_or_changed.validations['badge_num']['dupe_badge_num'] = dupe_badge_num


@CheckInForm.field_validation('instructions_followed')
def instructions_were_followed(form, field):
    if form.model.check_in_notes and not field.data:
        raise ValidationError(f"Please confirm that you've reviewed and followed the check-in instructions for this attendee.")


if c.NUMBERED_BADGES:
    CheckInForm.field_validation.required_fields['badge_num'] = "Badge number is required."
else:
    CheckInForm.field_validation.validations['badge_num']['optional'] = validators.Optional()
