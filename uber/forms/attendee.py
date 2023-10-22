import re
from datetime import date

from markupsafe import Markup
from pockets.autolog import log
from wtforms import (BooleanField, DateField, EmailField, Form, FormField,
                     HiddenField, SelectField, SelectMultipleField, IntegerField,
                     StringField, TelField, validators, TextAreaField)
from wtforms.widgets import HiddenInput
from wtforms.validators import ValidationError, StopValidation

from uber.config import c
from uber.forms import AddressForm, MultiCheckbox, MagForm, SelectAvailableField, SwitchInput, NumberInputGroup, HiddenIntField, CustomValidation
from uber.custom_tags import popup_link
from uber.model_checks import invalid_phone_number

from uber.badge_funcs import get_real_badge_type
from uber.custom_tags import format_currency
from uber.models import Attendee, Session, PromoCode, PromoCodeGroup
from uber.model_checks import invalid_zip_code, invalid_phone_number
from uber.utils import get_age_from_birthday, get_age_conf_from_birthday

__all__ = ['AdminInfo', 'BadgeExtras', 'PersonalInfo', 'PreregOtherInfo', 'OtherInfo', 'Consents']

# TODO: turn this into a proper validation class
def valid_cellphone(form, field):
    if field.data and invalid_phone_number(field.data):
        raise ValidationError('Please provide a valid 10-digit US phone number or ' \
                                'include a country code (e.g. +44) for international numbers.')

class PersonalInfo(AddressForm, MagForm):
    field_validation, new_or_changed_validation = CustomValidation(), CustomValidation()
    
    first_name = StringField('First Name', validators=[
        validators.DataRequired("Please provide your first name.")
        ], render_kw={'autocomplete': "fname"})
    last_name = StringField('Last Name', validators=[
        validators.DataRequired("Please provide your last name.")
        ], render_kw={'autocomplete': "lname"})
    same_legal_name = BooleanField('The above name is exactly what appears on my Legal Photo ID.')
    legal_name = StringField('Name as appears on Legal Photo ID', validators=[
        validators.DataRequired("Please provide the name on your photo ID or indicate that your first and last name match your ID.")
        ], render_kw={'placeholder': 'First and last name exactly as they appear on Photo ID'})
    badge_printed_name = StringField('Name Printed on Badge', validators=[
        validators.DataRequired("Please enter a name to be printed on your badge."),
        validators.Length(max=20, message="Your printed badge name is too long. \
                          Please use less than 20 characters."),
        validators.Regexp(c.VALID_BADGE_PRINTED_CHARS, message="Your printed badge name has invalid characters. \
                          Please use only alphanumeric characters and symbols.")
        ], description="Badge names have a maximum of 20 characters.")
    email = EmailField('Email Address', validators=[
        validators.DataRequired("Please enter an email address."),
        validators.Length(max=255, message="Email addresses cannot be longer than 255 characters."),
        validators.Email(granular_message=True),
        ],
        render_kw={'placeholder': 'test@example.com'})
    cellphone = TelField('Phone Number', validators=[
        validators.DataRequired("Please provide a phone number."),
        valid_cellphone
        ], render_kw={'placeholder': 'A phone number we can use to contact you during the event'})
    birthdate = DateField('Date of Birth', validators=[
        validators.DataRequired("Please enter your date of birth.") if c.COLLECT_EXACT_BIRTHDATE else validators.Optional(),
        ])
    age_group = SelectField('Age Group', validators=[
        validators.DataRequired("Please select your age group.") if not c.COLLECT_EXACT_BIRTHDATE else validators.Optional()
        ], choices=c.AGE_GROUPS)
    ec_name = StringField('Emergency Contact Name', validators=[
        validators.DataRequired("Please tell us the name of your emergency contact.")
        ], render_kw={'placeholder': 'Who we should contact if something happens to you'})
    ec_phone = TelField('Emergency Contact Phone', validators=[
        validators.DataRequired("Please give us an emergency contact phone number."),
        valid_cellphone
        ], render_kw={'placeholder': 'A valid phone number for your emergency contact'})
    onsite_contact = TextAreaField('Onsite Contact', validators=[
        validators.DataRequired("Please enter contact information for at least one trusted friend onsite, \
                                 or indicate that we should use your emergency contact information instead."),
        validators.Length(max=500, message="You have entered over 500 characters of onsite contact information. \
                          Please provide contact information for fewer friends.")
        ], render_kw={'placeholder': 'Contact info for a trusted friend or friends who will be at or near the venue during the event'})

    copy_email = BooleanField('Use my business email for my personal email.', default=False)
    copy_phone = BooleanField('Use my business phone number for my cellphone number.', default=False)
    copy_address = BooleanField('Use my business address for my personal address.', default=False)

    no_cellphone = BooleanField('I won\'t have a phone with me during the event.')
    no_onsite_contact = BooleanField('My emergency contact is also on site with me at the event.')
    international = BooleanField('I\'m coming from outside the US.')

    def get_optional_fields(self, attendee, is_admin=False):
        if is_admin:
            unassigned_group_reg = attendee.group_id and not attendee.first_name and not attendee.last_name
            valid_placeholder = attendee.placeholder and attendee.first_name and attendee.last_name
            if unassigned_group_reg or valid_placeholder:
                return ['first_name', 'last_name', 'legal_name', 'badge_printed_name', 'email', 'birthdate', 'age_group',
                        'ec_name', 'ec_phone', 'address1', 'city', 'region', 'region_us', 'region_canada', 'zip_code', 'country', 
                        'onsite_contact']
        
        optional_list = super().get_optional_fields(attendee, is_admin)

        if attendee.badge_type not in c.PREASSIGNED_BADGE_TYPES:
            optional_list.append('badge_printed_name')

        if self.same_legal_name.data:
            optional_list.append('legal_name')
        if self.copy_email.data:
            optional_list.append('email')
        if self.copy_phone.data or self.no_cellphone.data or not attendee.is_dealer:
            optional_list.append('cellphone')
        if self.copy_address.data:
            optional_list.extend(['address1', 'city', 'region', 'region_us', 'region_canada', 'zip_code', 'country'])
        if self.no_onsite_contact.data:
            optional_list.append('onsite_contact')

        return optional_list
    
    def get_non_admin_locked_fields(self, attendee):
        locked_fields = []

        if attendee.is_new or attendee.badge_status == c.PENDING_STATUS:
            return locked_fields
        elif not attendee.is_valid or attendee.badge_status == c.REFUNDED_STATUS:
            return list(self._fields.keys())

        if attendee.placeholder:
            return locked_fields
        
        return locked_fields + ['first_name', 'last_name', 'legal_name', 'same_legal_name']
    
    @new_or_changed_validation.badge_type
    def past_printed_deadline(form, field):
        if field.data in c.PREASSIGNED_BADGE_TYPES and c.PRINTED_BADGE_DEADLINE and c.AFTER_PRINTED_BADGE_DEADLINE:
            with Session() as session:
                admin = session.current_admin_account()
                if admin.is_super_admin:
                    return
        raise ValidationError('{} badges have already been ordered, so you cannot change your printed badge name.'.format(
                c.BADGES[field.data]))
    
    @field_validation.onsite_contact
    def require_onsite_contact(form, field):
        if not field.data and not form.no_onsite_contact.data:
            raise ValidationError('Please enter contact information for at least one trusted friend onsite, \
                                 or indicate that we should use your emergency contact information instead.')
    
    @field_validation.birthdate
    def birthdate_format(form, field):
        # TODO: Make WTForms use this message instead of the generic DateField invalid value message
        if field.data and not isinstance(field.data, date):
            raise StopValidation('Please use the format YYYY-MM-DD for your date of birth.')
        elif field.data and field.data > date.today():
            raise ValidationError('You cannot be born in the future.')
        
    @field_validation.birthdate
    def attendee_age_checks(form, field):
        age_group_conf = get_age_conf_from_birthday(field.data, c.NOW_OR_AT_CON) \
            if (hasattr(form, "birthdate") and form.birthdate.data) else field.data
        if age_group_conf and not age_group_conf['can_register']:
            raise ValidationError('Attendees {} years of age do not need to register, ' \
                'but MUST be accompanied by a parent at all times!'.format(age_group_conf['desc'].lower()))

    @field_validation.cellphone
    def not_same_cellphone_ec(form, field):
        if field.data and field.data == form.ec_phone.data:
            raise ValidationError("Your phone number cannot be the same as your emergency contact number.")


class BadgeExtras(MagForm):
    field_validation, new_or_changed_validation = CustomValidation(), CustomValidation()
    dynamic_choices_fields = {'shirt': lambda: c.SHIRT_OPTS, 'staff_shirt': lambda: c.STAFF_SHIRT_OPTS}

    badge_type = HiddenIntField('Badge Type')
    amount_extra = HiddenIntField('Pre-order Merch', validators=[
        validators.NumberRange(min=0, message="Amount extra must be a number that is 0 or higher.")
        ])
    extra_donation = IntegerField('Extra Donation', validators=[
        validators.NumberRange(min=0, message="Extra donation must be a number that is 0 or higher.")
        ], widget=NumberInputGroup(), description=popup_link("../static_views/givingExtra.html", "Learn more"))
    shirt = SelectAvailableField('Shirt Size', coerce=int,
                                 sold_out_list_func=lambda: list(c.REDIS_STORE.smembers(c.REDIS_PREFIX + 'sold_out_shirt_sizes')))
    staff_shirt = SelectField('Staff Shirt Size', coerce=int)
    
    def get_non_admin_locked_fields(self, attendee):
        locked_fields = []

        if attendee.is_new:
            return locked_fields

        if not attendee.is_valid or attendee.badge_status == c.REFUNDED_STATUS:
            return list(self._fields.keys())
        
        if attendee.active_receipt or attendee.badge_status == c.DEFERRED_STATUS:
            locked_fields.extend(['badge_type', 'amount_extra', 'extra_donation'])
        elif not c.BADGE_TYPE_PRICES:
            locked_fields.append('badge_type')
        
        return locked_fields
        
    def get_optional_fields(self, attendee, is_admin=False):        
        optional_list = super().get_optional_fields(attendee, is_admin)

        return optional_list
    
    @field_validation.shirt
    def require_shirt(form, field):
        if (form.amount_extra.data and form.amount_extra.data > 0 or form.badge_type.data in c.BADGE_TYPE_PRICES) \
            and (field.data == c.NO_SHIRT or not field.data):
            raise ValidationError("Please select a shirt size.")
        
    @new_or_changed_validation.shirt
    def shirt_size_sold_out(form, field):
        if field.data in field.get_sold_out_list():
            raise ValidationError(f"Sorry, we're sold out of {c.PREREG_SHIRTS[field.data]} shirts!")
    
    @new_or_changed_validation.amount_extra
    def upgrade_sold_out(form, field):
        if field.data and field.data in c.SOLD_OUT_MERCH_TIERS:
            raise ValidationError("The upgrade you have selected is sold out.")
        elif field.data and getattr(c.kickin_availability_matrix, str(field.data), True) == False:
            raise ValidationError("The upgrade you have selected is no longer available.")

    @new_or_changed_validation.badge_type
    def no_more_custom_badges(form, field):
        if field.data in c.PREASSIGNED_BADGE_TYPES and c.AFTER_PRINTED_BADGE_DEADLINE:
            with Session() as session:
                admin = session.current_admin_account()
                if admin.is_super_admin:
                    return
            raise ValidationError('Custom badges have already been ordered, please choose a different badge type.')

    @new_or_changed_validation.badge_type
    def out_of_badge_type(form, field):
        badge_type = get_real_badge_type(field.data)
        with Session() as session:
            try:
                session.get_next_badge_num(badge_type)
            except AssertionError:
                raise ValidationError('We are sold out of {} badges.'.format(c.BADGES[badge_type]))


class OtherInfo(MagForm):
    field_validation = CustomValidation()
    dynamic_choices_fields = {'requested_depts_ids': lambda: [(v[0], v[1]) for v in c.PUBLIC_DEPARTMENT_OPTS_WITH_DESC]}

    placeholder = BooleanField(widget=HiddenInput())
    staffing = BooleanField('I am interested in volunteering!', widget=SwitchInput(), description=popup_link(c.VOLUNTEER_PERKS_URL, "What do I get for volunteering?"))
    requested_depts_ids = SelectMultipleField('Where do you want to help?', widget=MultiCheckbox()) # TODO: Show attendees department descriptions
    requested_accessibility_services = BooleanField(f'I would like to be contacted by the {c.EVENT_NAME} Accessibility Services department prior to the event and I understand my contact information will be shared with Accessibility Services for this purpose.', widget=SwitchInput())
    interests = SelectMultipleField('What interests you?', choices=c.INTEREST_OPTS, coerce=int, validators=[validators.Optional()], widget=MultiCheckbox())

    def get_non_admin_locked_fields(self, attendee):
        locked_fields = [] 

        if not attendee.placeholder:
            # This is an admin field, but we need it on the confirmation page for placeholder attendees
            locked_fields.append('placeholder')

        if attendee.is_new:
            return locked_fields
        
        if not attendee.is_valid or attendee.badge_status == c.REFUNDED_STATUS:
            return list(self._fields.keys())
        
        if attendee.badge_type in [c.STAFF_BADGE, c.CONTRACTOR_BADGE] or attendee.shifts:
            locked_fields.append('staffing')

        return locked_fields


class PreregOtherInfo(OtherInfo):
    new_or_changed_validation = CustomValidation()

    promo_code_code = StringField('Promo Code')
    cellphone = TelField('Phone Number', description="A cellphone number is required for volunteers.", validators=[
        # Required in model_checks because the staffing property is too complex to rely on per-form logic
        valid_cellphone
        ], render_kw={'placeholder': 'A phone number we can use to contact you during the event'})
    no_cellphone = BooleanField('I won\'t have a phone with me during the event.')

    def get_non_admin_locked_fields(self, attendee):
        return super().get_non_admin_locked_fields(attendee)
    
    @new_or_changed_validation.promo_code_code
    def promo_code_valid(form, field):
        if field.data:
            with Session() as session:
                code = session.lookup_promo_code(field.data)
                if not code:
                    group = session.lookup_promo_or_group_code(field.data, PromoCodeGroup)
                    if not group:
                        raise ValidationError("The promo code you entered is invalid.")
                    elif not group.valid_codes:
                        raise ValidationError(f"There are no more badges left in the group {group.name}.")
                else:
                    if code.is_expired:
                        raise ValidationError("That promo code has expired.")
                    elif code.uses_remaining <= 0 and not code.is_unlimited:
                        raise ValidationError("That promo code has been used already.")


class Consents(MagForm):
    can_spam = BooleanField(f'Please send me emails relating to {c.EVENT_NAME} and {c.ORGANIZATION_NAME} in future years.', description=popup_link("../static_views/privacy.html", "View Our Spam Policy"))
    pii_consent = BooleanField(Markup(f'<strong>Yes</strong>, I understand and agree that {c.ORGANIZATION_NAME} will store the personal information I provided above for the limited purposes of contacting me about my registration'),
                               validators=[validators.InputRequired("You must agree to allow us to store your personal information in order to register.")
                                           ], description=Markup('For more information please check out our <a href="{}" target="_blank">Privacy Policy</a>.'.format(c.PRIVACY_POLICY_URL)))

    def get_non_admin_locked_fields(self, attendee):
        if attendee.needs_pii_consent:
            return []
        
        return ['pii_consent']

    def pii_consent_label(self):
        base_label = f"<strong>Yes</strong>, I understand and agree that {c.ORGANIZATION_NAME} will store the personal information I provided above for the limited purposes of contacting me about my registration"
        label = base_label
        if c.HOTELS_ENABLED:
            label += ', hotel accommodations'
        if c.DONATIONS_ENABLED:
            label += ', donations'
        if c.ACCESSIBILITY_SERVICES_ENABLED:
            label += ', accessibility needs'
        if label != base_label:
            label += ','
        label += ' or volunteer opportunities selected at sign-up.'
        return Markup(label)


class AdminInfo(MagForm):
    field_validation, new_or_changed_validation = CustomValidation(), CustomValidation()
    placeholder = BooleanField('Placeholder')
    group_id = StringField('Group')

    @new_or_changed_validation.badge_num
    def dupe_badge_num(form, field):
        existing_name = ''
        if c.NUMBERED_BADGES and field.data \
                and (not c.SHIFT_CUSTOM_BADGES or c.AFTER_PRINTED_BADGE_DEADLINE or c.AT_THE_CON):
            with Session() as session:
                existing = session.query(Attendee).filter_by(badge_num=field.data)
                if not existing.count():
                    return
                else:
                    existing_name = existing.first().full_name
            raise ValidationError('That badge number already belongs to {!r}'.format(existing_name))