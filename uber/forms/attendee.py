import cherrypy
from datetime import date

from markupsafe import Markup
from wtforms import (BooleanField, DateField, EmailField,
                     HiddenField, SelectField, SelectMultipleField, IntegerField,
                     StringField, TelField, validators, TextAreaField)
from wtforms.widgets import TextInput

from uber.config import c
from uber.forms import (AddressForm, MultiCheckbox, MagForm, SelectAvailableField, SwitchInput, NumberInputGroup,
                        HiddenBoolField, HiddenIntField, CustomValidation, Ranking)
from uber.custom_tags import popup_link
from uber.badge_funcs import get_real_badge_type
from uber.models import Attendee, BadgeInfo, Session, PromoCodeGroup
from uber.model_checks import invalid_phone_number
from uber.utils import get_age_conf_from_birthday


__all__ = ['AdminBadgeExtras', 'AdminBadgeFlags', 'AdminConsents', 'AdminStaffingInfo', 'BadgeExtras',
           'BadgeFlags', 'BadgeAdminNotes', 'PersonalInfo', 'PreregOtherInfo', 'OtherInfo', 'StaffingInfo',
           'Consents', 'CheckInForm']


class PersonalInfo(AddressForm, MagForm):
    first_name = StringField('First Name', render_kw={'autocomplete': "fname"})
    last_name = StringField('Last Name', render_kw={'autocomplete': "lname"})
    same_legal_name = BooleanField('The above name is exactly what appears on my Legal Photo ID.')
    legal_name = StringField('Name as appears on Legal Photo ID',
                             render_kw={'placeholder': 'First and last name exactly as they appear on Photo ID'})
    badge_printed_name = StringField('Name Printed on Badge', description="Badge names have a maximum of 20 characters.")
    email = EmailField('Email Address', render_kw={'placeholder': 'test@example.com'})
    confirm_email = StringField('Confirm Email Address')
    cellphone = TelField('Phone Number', render_kw={'placeholder': 'A phone number we can use to contact you during the event'})
    birthdate = DateField('Date of Birth')
    age_group = SelectField('Age Group', choices=c.AGE_GROUP_OPTS)
    ec_name = StringField('Emergency Contact Name',
                          render_kw={'placeholder': 'Who we should contact if something happens to you'})
    ec_phone = TelField('Emergency Contact Phone', render_kw={'placeholder': 'A valid phone number for your emergency contact'})
    onsite_contact = TextAreaField('Onsite Contact',
                                   render_kw={'placeholder': 'Contact info for a trusted friend or friends who will be at or near the venue '
                                              'during the event'})

    copy_email = BooleanField('Use my business email for my personal email.', default=False)
    copy_phone = BooleanField('Use my business phone number for my cellphone number.', default=False)
    copy_address = BooleanField('Use my business address for my personal address.', default=False)

    no_cellphone = BooleanField('I won\'t have a phone with me during the event.')
    no_onsite_contact = BooleanField('My emergency contact is also on site with me at the event.')
    international = BooleanField('I\'m coming from outside the US.')

    def placeholder_optional_field_names(self):
        # Note that the fields below must ALWAYS be required if the attendee is not a placeholder
        # Otherwise add them to get_optional_fields instead
        # TODO: Remove after front-end refactor phase 1 is complete
        return ['legal_name', 'birthdate', 'age_group', 'ec_name', 'ec_phone', 'address1', 'city',
                'region', 'region_us', 'region_canada', 'zip_code', 'country', 'onsite_contact']

    def placeholder_optional_fields(self):
        return [getattr(self, name) for name in self.placeholder_optional_field_names()]

    def get_non_admin_locked_fields(self, attendee):
        locked_fields = []

        if attendee.is_new or attendee.badge_status == c.PENDING_STATUS or attendee.paid == c.PENDING:
            return locked_fields
        elif not attendee.is_valid or attendee.badge_status == c.REFUNDED_STATUS:
            return list(self._fields.keys())

        if attendee.valid_placeholder or attendee.unassigned_group_reg:
            return locked_fields

        return locked_fields + ['first_name', 'last_name', 'legal_name', 'same_legal_name']


class BadgeExtras(MagForm):
    field_validation, new_or_changed_validation = CustomValidation(), CustomValidation()
    dynamic_choices_fields = {'shirt': lambda: c.SHIRT_OPTS, 'staff_shirt': lambda: c.STAFF_SHIRT_OPTS}

    badge_type = HiddenIntField('Badge Type')
    amount_extra = HiddenIntField('Pre-order Merch')
    extra_donation = IntegerField('Extra Donation', widget=NumberInputGroup(),
                                  description=popup_link("../static_views/givingExtra.html", "Learn more"))
    shirt = SelectAvailableField('Shirt Size', coerce=int,
                                 sold_out_list_func=lambda: list(
                                     c.REDIS_STORE.smembers(c.REDIS_PREFIX + 'sold_out_shirt_sizes')))
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


class AdminBadgeExtras(BadgeExtras):
    amount_extra = SelectField('Pre-ordered Merch', coerce=int, choices=c.DONATION_TIER_OPTS)
    extra_merch = StringField('Extra Merch')
    got_merch = BooleanField('This attendee has picked up their merch.')


class OtherInfo(MagForm):
    field_validation, new_or_changed_validation = CustomValidation(), CustomValidation()

    promo_code_code = StringField('Promo Code')
    interests = SelectMultipleField('What interests you?', choices=c.INTEREST_OPTS, widget=MultiCheckbox())
    requested_accessibility_services = BooleanField(
        f'I would like to be contacted by the {c.EVENT_NAME} Accessibility Services department prior to the event '
        'and I understand my contact information will be shared with Accessibility Services for this purpose.',
        widget=SwitchInput())

    def get_non_admin_locked_fields(self, attendee):
        locked_fields = []

        if attendee.is_new:
            return locked_fields

        if not attendee.is_valid or attendee.badge_status == c.REFUNDED_STATUS:
            return list(self._fields.keys())

        return locked_fields
    
    def promo_code_code_label(self):
        if c.GROUPS_ENABLED:
            return 'Group or Promo Code'
        else:
            return 'Promo Code'


class StaffingInfo(MagForm):
    dynamic_choices_fields = {'requested_depts_ids': lambda: [(v[0], v[1]) for v in c.PUBLIC_DEPARTMENT_OPTS_WITH_DESC]}

    staffing = BooleanField('I am interested in volunteering!', widget=SwitchInput(),
                            description=popup_link(c.VOLUNTEER_PERKS_URL, "What do I get for volunteering?"))
    requested_depts_ids = SelectMultipleField('Where do you want to help?',
                                              widget=MultiCheckbox())  # TODO: Show attendees department descriptions

    def get_non_admin_locked_fields(self, attendee):
        locked_fields = []

        if attendee.is_new:
            return locked_fields

        if not attendee.is_valid or attendee.badge_status == c.REFUNDED_STATUS:
            return list(self._fields.keys())

        if attendee.badge_type in [c.STAFF_BADGE, c.CONTRACTOR_BADGE] or attendee.shifts:
            locked_fields.append('staffing')

        return locked_fields


class AdminStaffingInfo(StaffingInfo):
    dynamic_choices_fields = StaffingInfo.dynamic_choices_fields
    dynamic_choices_fields['assigned_depts_ids'] = lambda: c.DEPARTMENT_OPTS

    assigned_depts_ids = SelectMultipleField('Assigned Departments', widget=MultiCheckbox())
    walk_on_volunteer = BooleanField('This person signed up to volunteer at the event.')
    got_staff_merch = BooleanField('This staffer has picked up their merch.')
    agreed_to_volunteer_agreement = HiddenBoolField('Agreed to Volunteer Agreement')
    reviewed_emergency_procedures = HiddenBoolField('Reviewed Safety and Security Information')
    hotel_eligible = BooleanField('This staffer is eligible for staff crash space.')

    def staffing_label(self):
        return "This attendee is volunteering or staffing."

    def requested_depts_ids_label(self):
        return "Requested Departments"


class PreregOtherInfo(OtherInfo, StaffingInfo):
    dynamic_choices_fields = {'requested_depts_ids': lambda: [(v[0], v[1]) for v in c.PUBLIC_DEPARTMENT_OPTS_WITH_DESC]}

    staffing = BooleanField('I am interested in volunteering!', widget=SwitchInput(),
                            description=popup_link(c.VOLUNTEER_PERKS_URL, "What do I get for volunteering?"))
    requested_depts_ids = SelectMultipleField('Where do you want to help?',
                                              widget=MultiCheckbox())  # TODO: Show attendees department descriptions
    cellphone = TelField('Phone Number', description="A cellphone number is required for volunteers.", 
        render_kw={'placeholder': 'A phone number we can use to contact you during the event'})
    no_cellphone = BooleanField('I won\'t have a phone with me during the event.')

    def get_non_admin_locked_fields(self, attendee):
        return super().get_non_admin_locked_fields(attendee)


class Consents(MagForm):
    can_spam = BooleanField(
        f'Please send me emails relating to {c.EVENT_NAME} and {c.ORGANIZATION_NAME} in future years.',
        description=popup_link("../static_views/privacy.html", "View Our Spam Policy"))
    pii_consent = BooleanField(
        Markup(f'<strong>Yes</strong>, I understand and agree that {c.ORGANIZATION_NAME} will store '
               'the personal information I provided above for the limited purposes '
               'of contacting me about my registration'),
        description=Markup(f'For more information please check out our <a href="{c.PRIVACY_POLICY_URL}" '
                           'target="_blank">Privacy Policy</a>.'))

    def get_non_admin_locked_fields(self, attendee):
        if attendee.needs_pii_consent:
            return []

        return ['pii_consent']

    def pii_consent_label(self):
        base_label = f"<strong>Yes</strong>, I understand and agree that {c.ORGANIZATION_NAME} will store "\
            "the personal information I provided above for the limited purposes of contacting me about my registration"
        label = base_label
        if c.HOTELS_ENABLED:
            label += ', hotel accommodations'
        if c.ADDONS_ENABLED:
            label += ', donations'
        if c.ACCESSIBILITY_SERVICES_ENABLED:
            label += ', accessibility needs'
        if label != base_label:
            label += ','
        label += ' or volunteer opportunities selected at sign-up.'
        return Markup(label)


class AdminConsents(Consents):
    attractions_opt_out = HiddenBoolField('Attractions Signups Locked')
    pii_consent = HiddenBoolField()

    def can_spam_label(self):
        return "This attendee has opted in to marketing emails."


class BadgeFlags(MagForm):
    placeholder = BooleanField('Email this person to fill out their details.',
                               description="You will only need to fill out their name and email address.")

    def get_non_admin_locked_fields(self, attendee):
        locked_fields = []

        if not attendee.valid_placeholder and not attendee.unassigned_group_reg:
            # This field is locked to False except on register_group_member
            locked_fields.append('placeholder')

        return locked_fields


class AdminBadgeFlags(BadgeFlags):
    new_or_changed_validation = CustomValidation()
    dynamic_choices_fields = {'group_id': lambda: AdminBadgeFlags.get_valid_groups()}

    can_transfer = BooleanField('Make this attendee\'s badge always transferable.')
    badge_status = SelectField('Badge Status', coerce=int, choices=c.BADGE_STATUS_OPTS)
    badge_type = SelectField('Badge Type', coerce=int, choices=c.BADGE_OPTS)
    badge_num = IntegerField('Badge #', default='', widget=TextInput())
    no_badge_num = BooleanField('Omit badge #')
    ribbon = SelectMultipleField('Ribbons', coerce=int, choices=c.RIBBON_OPTS, widget=MultiCheckbox())
    group_id = SelectField('Group')
    paid = SelectField('Paid Status', coerce=int, choices=c.PAYMENT_OPTS)
    overridden_price = IntegerField('Base Badge Price', widget=NumberInputGroup())
    no_override = BooleanField('Let the system determine base badge price. (uncheck to override badge price)')

    def get_valid_groups():
        from uber.models import Group
        with Session() as session:
            groups_list = [(g.id, g.name + (f" ({g.status_label})" if g.is_dealer else ""))
                           for g in session.query(Group).filter(Group.status != c.IMPORTED).order_by(Group.name).all()]
            return [('', "No Group")] + groups_list


class BadgeAdminNotes(MagForm):
    regdesk_info = TextAreaField('Special Regdesk Instructions')
    for_review = TextAreaField('Notes for Later Review')
    admin_notes = TextAreaField('Admin Notes')


class CheckInForm(MagForm):
    field_validation, new_or_changed_validation = CustomValidation(), CustomValidation()

    full_name = HiddenField('Name')
    legal_name = HiddenField('Name on ID')
    email = HiddenField('Email')
    zip_code = HiddenField('Zipcode')
    birthdate = PersonalInfo.birthdate
    age_group = HiddenField('Age Group')
    badge_type = HiddenIntField('Badge Type')
    badge_num = StringField('Badge Number', id="checkin_badge_num", default='')
    badge_printed_name = PersonalInfo.badge_printed_name
    got_merch = AdminBadgeExtras.got_merch
    got_staff_merch = AdminStaffingInfo.got_staff_merch
