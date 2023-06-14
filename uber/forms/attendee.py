from markupsafe import Markup
from wtforms import (BooleanField, DateField, EmailField, Form, FormField,
                     HiddenField, SelectField, SelectMultipleField, IntegerField,
                     StringField, TelField, validators, TextAreaField)
from wtforms.validators import ValidationError, StopValidation

from uber.config import c
from uber.forms import AddressForm, MultiCheckbox, MagForm, SwitchInput, DollarInput, HiddenIntField
from uber.custom_tags import popup_link
from uber.validations import attendee as attendee_validators

__all__ = ['AdminInfo', 'BadgeExtras', 'PersonalInfo', 'OtherInfo']

class PersonalInfo(AddressForm, MagForm):
    badge_type = HiddenIntField('Badge Type')
    first_name = StringField('First Name', render_kw={'autocomplete': "fname"})
    last_name = StringField('Last Name', render_kw={'autocomplete': "lname"})
    same_legal_name = BooleanField('The above name is exactly what appears on my Legal Photo ID.')
    legal_name = StringField('Name as appears on Legal Photo ID', render_kw={'placeholder': 'First and last name exactly as they appear on Photo ID'})
    email = EmailField('Email Address', validators=[
        validators.Length(max=255, message="Email addresses cannot be longer than 255 characters."),
        validators.Email(granular_message=True),
        ],
        render_kw={'placeholder': 'test@example.com'})
    cellphone = TelField('Phone Number', description="A cellphone number is required for volunteers.", render_kw={'placeholder': 'A phone number we can use to contact you during the event'})
    birthdate = DateField('Date of Birth', validators=[attendee_validators.attendee_age_checks])
    age_group = SelectField('Age Group', choices=c.AGE_GROUPS)

    ec_name = StringField('Emergency Contact Name', render_kw={'placeholder': 'Who we should contact if something happens to you'})
    ec_phone = TelField('Emergency Contact Phone', render_kw={'placeholder': 'A valid phone number for your emergency contact'})
    onsite_contact = TextAreaField('Onsite Contact', validators=[validators.Length(max=500, message="You have entered over 500 characters of onsite contact information. Please provide contact information for fewer friends.")], render_kw={'placeholder': 'Contact info for a trusted friend or friends who will be at or near the venue during the event'})

    copy_email = BooleanField('Use my business email for my personal email.', default=False)
    copy_phone = BooleanField('Use my business phone number for my cellphone number.', default=False)
    copy_address = BooleanField('Use my business address for my personal address.', default=False)

    no_cellphone = BooleanField('I won\'t have a phone with me during the event.')
    no_onsite_contact = BooleanField('Use my emergency contact information.')
    international = BooleanField('I\'m coming from outside the US.')

    skip_unassigned_placeholder_validators = {
        'first_name': [validators.InputRequired(message="Please provide your first name.")],
        'last_name': [validators.InputRequired(message="Please provide your last name.")],
        'email': [validators.InputRequired(message="Please enter an email address.")],
        'birthdate': [validators.InputRequired("Please enter your date of birth.")] if c.COLLECT_EXACT_BIRTHDATE else [validators.Optional()],
        'age_group': [validators.InputRequired("Please select your age group.")] if not c.COLLECT_EXACT_BIRTHDATE else [validators.Optional()],
        'ec_name': [validators.InputRequired(message="Please tell us the name of your emergency contact.")],
        'ec_phone': [validators.InputRequired(message="Please give us an emergency contact phone number.")],
    }
            

class BadgeExtras(MagForm):
    badge_type = HiddenIntField('Badge Type')
    amount_extra = HiddenIntField('Pre-order Merch', validators=[validators.NumberRange(min=0, message="Amount extra must be a number that is 0 or higher.")])
    extra_donation = IntegerField('Extra Donation', validators=[validators.NumberRange(min=0, message="Extra donation must be a number that is 0 or higher.")], widget=DollarInput(), description=popup_link("../static_views/givingExtra.html", "Learn more"))
    shirt = SelectField('Shirt Size', choices=c.SHIRT_OPTS, coerce=int)
    badge_printed_name = StringField('Name Printed on Badge')

    def validate_shirt(form, field):
        if form.amount_extra.data > 0 and field.data == c.NO_SHIRT:
            raise ValidationError("Your shirt size is required.")


class OtherInfo(MagForm):
    staffing = BooleanField('I am interested in volunteering!', widget=SwitchInput(), description=popup_link(c.VOLUNTEER_PERKS_URL, "What do I get for volunteering?"))
    requested_dept_ids = SelectMultipleField('Where do you want to help?', choices=c.JOB_INTEREST_OPTS, coerce=int, widget=MultiCheckbox())
    requested_accessibility_services = BooleanField('I would like to be contacted by the {EVENT_NAME} Accessibility Services department prior to the event and I understand my contact information will be shared with Accessibility Services for this purpose.', widget=SwitchInput())
    interests = SelectMultipleField('What interests you?', choices=c.INTEREST_OPTS, coerce=int, validators=[validators.Optional()], widget=MultiCheckbox())
    can_spam = BooleanField('Please send me emails relating to {EVENT_NAME} and {ORGANIZATION_NAME} in future years.', widget=SwitchInput(), description=popup_link("../static_views/privacy.html", "View Our Spam Policy"))
    pii_consent = BooleanField(Markup('<strong>Yes</strong>, I understand and agree that {ORGANIZATION_NAME} will store the personal information I provided above for the limited purposes of contacting me about my registration'), widget=SwitchInput())

    def pii_consent_label(self):
        base_label = "<strong>Yes</strong>, I understand and agree that {ORGANIZATION_NAME} will store the personal information I provided above for the limited purposes of contacting me about my registration"
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
    placeholder = BooleanField('Placeholder')
    group_id = StringField('Group')