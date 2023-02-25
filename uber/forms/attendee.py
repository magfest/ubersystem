from markupsafe import Markup
from wtforms import (BooleanField, DateField, EmailField, Form, FormField,
                     HiddenField, SelectField, SelectMultipleField, IntegerField,
                     StringField, TelField, validators, TextAreaField)

from uber.config import c
from uber.forms import Address, MultiCheckbox, MagForm, SwitchInput, DollarInput, HiddenIntField
from uber.custom_tags import popup_link

__all__ = ['BadgeExtras', 'PersonalInfo', 'OtherInfo']

class PersonalInfo(MagForm):
    first_name = StringField('First Name', render_kw={'autocomplete': "fname"})
    last_name = StringField('Last Name', render_kw={'autocomplete': "lname"})
    same_legal_name = BooleanField('The above name is exactly what appears on my Legal Photo ID.')
    legal_name = StringField('Name as appears on Legal Photo ID', render_kw={'placeholder': 'First and last name exactly as they appear on Photo ID'})
    email = EmailField('Email Address', render_kw={'placeholder': 'test@example.com'})
    cellphone = TelField('Phone Number', description="A cellphone number is required for volunteers.", render_kw={'placeholder': 'A phone number we can use to contact you during the event'})
    birthdate = DateField('Date of Birth')
    
    zip_code = StringField('Zip/Postal Code', default='')
    ec_name = StringField('Emergency Contact Name', render_kw={'placeholder': 'Who we should contact if something happens to you'})
    ec_phone = TelField('Emergency Contact Phone', render_kw={'placeholder': 'A valid phone number for your emergency contact'})
    onsite_contact = TextAreaField('Onsite Contact', render_kw={'placeholder': 'Contact info for a trusted friend or friends who will be at or near the venue during the event'})

    copy_email = BooleanField('Use my business email for my personal email.', default=False)
    copy_phone = BooleanField('Use my business phone number for my cellphone number.', default=False)
    copy_address = BooleanField('Use my business address for my personal address.', default=False)

    no_cellphone = BooleanField('I won\'t have a phone with me during the event.')
    no_onsite_contact = BooleanField('Use my emergency contact information.')
    international = BooleanField('I\'m coming from outside the US.')


class BadgeExtras(MagForm):
    badge_type = HiddenIntField('Badge Type')
    amount_extra = HiddenIntField('Pre-order Merch')
    extra_donation = IntegerField('Extra Donation', widget=DollarInput(), description=popup_link("../static_views/givingExtra.html", "Learn more"))


class OtherInfo(MagForm):
    staffing = BooleanField('I am interested in volunteering!', widget=SwitchInput(), description=popup_link(c.VOLUNTEER_PERKS_URL, "What do I get for volunteering?"))
    requested_dept_ids = SelectMultipleField('Where do you want to help?', choices=c.JOB_INTEREST_OPTS, widget=MultiCheckbox())
    requested_accessibility_services = BooleanField('I would like to be contacted by the {EVENT_NAME} Accessibility Services department prior to the event and I understand my contact information will be shared with Accessibility Services for this purpose.', widget=SwitchInput())
    interests = SelectMultipleField('What interests you?', choices=c.INTEREST_OPTS, widget=MultiCheckbox())
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



"""


@prereg_validation.Attendee
def shirt_size(attendee):
    if attendee.amount_extra >= c.SHIRT_LEVEL and attendee.shirt == c.NO_SHIRT:
        return 'Your shirt size is required'


@prereg_validation.Attendee
def group_leader_under_13(attendee):
    if attendee.badge_type == c.PSEUDO_GROUP_BADGE and attendee.age_group_conf['val'] in [c.UNDER_6, c.UNDER_13]:
        return "Children under 13 cannot be group leaders."


@prereg_validation.Attendee
def child_badge_over_13(attendee):
    if c.CHILD_BADGE in c.PREREG_BADGE_TYPES and attendee.is_new and attendee.badge_type == c.CHILD_BADGE \
            and attendee.age_now_or_at_con and attendee.age_now_or_at_con >= 13:
        return "If you will be 13 or older at the start of {}, " \
            "please select an Attendee badge instead of a 12 and Under badge.".format(c.EVENT_NAME)


@prereg_validation.Attendee
def attendee_badge_under_13(attendee):
    if c.CHILD_BADGE in c.PREREG_BADGE_TYPES and attendee.is_new and attendee.badge_type == c.ATTENDEE_BADGE \
            and attendee.age_now_or_at_con and attendee.age_now_or_at_con < 13:
        return "If you will be 12 or younger at the start of {}, " \
            "please select the 12 and Under badge instead of an Attendee badge.".format(c.EVENT_NAME)

           
@validation.Attendee
def no_more_child_badges(attendee):
    if c.CHILD_BADGE in c.PREREG_BADGE_TYPES and attendee.is_new and attendee.age_now_or_at_con and attendee.age_now_or_at_con < 18 \
            and not c.CHILD_BADGE_AVAILABLE:
        return "Unfortunately, we are sold out of badges for attendees under 18."


@prereg_validation.Attendee
def upgrade_sold_out(attendee):
    currently_available_upgrades = [tier['value'] for tier in c.PREREG_DONATION_DESCRIPTIONS]
    if (attendee.is_new or attendee.orig_value_of('amount_extra') != attendee.amount_extra) \
        and attendee.amount_extra and attendee.amount_extra not in currently_available_upgrades:
        return "The upgrade you have selected is sold out."


@validation.Attendee
def extra_donation_valid(attendee):
    try:
        extra_donation = int(float(attendee.extra_donation or 0))
        if extra_donation < 0:
            return 'Extra Donation must be a number that is 0 or higher.'
    except Exception:
        return "What you entered for Extra Donation ({}) isn't even a number".format(attendee.extra_donation)


@prereg_validation.Attendee
def total_cost_over_paid(attendee):
    return
    if (attendee.total_cost * 100) < attendee.amount_paid:
        if (not attendee.orig_value_of('birthdate') or attendee.orig_value_of('birthdate') < attendee.birthdate) \
                and attendee.age_group_conf['val'] in [c.UNDER_6, c.UNDER_13]:
            return 'The date of birth you entered incurs a discount; ' \
                'please email {} to change your badge and receive a refund'.format(c.REGDESK_EMAIL)
        return 'You have already paid {}, you cannot reduce your extras below that.'.format(
            format_currency(attendee.amount_paid / 100))


@validation.Attendee
def reasonable_total_cost(attendee):
    if attendee.total_cost >= 999999:
        return 'We cannot charge {}. Please reduce extras so the total is below $999,999.'.format(
            format_currency(attendee.total_cost))


@prereg_validation.Attendee
def promo_code_is_useful(attendee):
    if attendee.promo_code:
        with Session() as session:
            if session.lookup_agent_code(attendee.promo_code.code):
                return
            code = session.lookup_promo_or_group_code(attendee.promo_code.code, PromoCode)
            group = code.group if code and code.group else session.lookup_promo_or_group_code(attendee.promo_code.code, PromoCodeGroup)
            if group and group.total_cost == 0:
                return

    if attendee.is_new and attendee.promo_code:
        if not attendee.is_unpaid:
            return "You can't apply a promo code after you've paid or if you're in a group."
        elif attendee.is_dealer:
            return "You can't apply a promo code to a {}.".format(c.DEALER_REG_TERM)
        elif attendee.age_discount != 0:
            return "You are already receiving an age based discount, you can't use a promo code on top of that."
        elif attendee.badge_type == c.ONE_DAY_BADGE or attendee.is_presold_oneday:
            return "You can't apply a promo code to a one day badge."
        elif attendee.overridden_price:
            return "You already have a special badge price, you can't use a promo code on top of that."
        elif attendee.default_badge_cost >= attendee.badge_cost_without_promo_code:
            return "That promo code doesn't make your badge any cheaper. You may already have other discounts."


import re
from datetime import date
from functools import wraps
from uber.custom_tags import format_currency
from uber.decorators import prereg_validation, validation

def _invalid_zip_code(s):
    return len(re.findall(r'\d', s)) not in [5, 9]


def ignore_unassigned_and_placeholders(func):
    @wraps(func)
    def with_skipping(attendee):
        unassigned_group_reg = attendee.group_id and not attendee.first_name and not attendee.last_name
        valid_placeholder = attendee.placeholder and attendee.first_name and attendee.last_name
        if not unassigned_group_reg and not valid_placeholder:
            return func(attendee)
    return with_skipping


@prereg_validation.Attendee
def promo_code_not_is_expired(attendee):
    if attendee.is_new and attendee.promo_code and attendee.promo_code.is_expired:
        return 'That promo code is expired.'


@prereg_validation.Attendee
def promo_code_has_uses_remaining(attendee):
    if attendee.is_new and attendee.promo_code and not attendee.promo_code.is_unlimited:
        unpaid_uses_count = Charge.get_unpaid_promo_code_uses_count(
            attendee.promo_code.id, attendee.id)
        if (attendee.promo_code.uses_remaining - unpaid_uses_count) < 0:
            return 'That promo code has been used too many times.'


@validation.Attendee
@ignore_unassigned_and_placeholders
def full_name(attendee):
    if not attendee.first_name:
        return 'First Name is a required field'
    elif not attendee.last_name:
        return 'Last Name is a required field'


@validation.Attendee
def allowed_to_volunteer(attendee):
    if attendee.staffing_or_will_be \
            and not attendee.age_group_conf['can_volunteer'] \
            and attendee.badge_type not in [c.STAFF_BADGE, c.CONTRACTOR_BADGE] \
            and c.PRE_CON:

        return 'Your interest is appreciated, but ' + c.EVENT_NAME + ' volunteers must be 18 or older.'


@validation.Attendee
@ignore_unassigned_and_placeholders
def age(attendee):
    if c.COLLECT_EXACT_BIRTHDATE:
        if not attendee.birthdate:
            return 'Please enter a date of birth.'
        elif not isinstance(attendee.birthdate, date):
            attendee.birthdate = ''
            return 'Please use the format YYYY-MM-DD for your date of birth.'
        elif attendee.birthdate > date.today():
            return 'You cannot be born in the future.'
    elif not attendee.age_group:
        return 'Please enter your age group'


@validation.Attendee
def allowed_to_register(attendee):
    if not attendee.age_group_conf['can_register']:
        return 'Attendees {} years of age do not need to register, ' \
            'but MUST be accompanied by a parent at all times!'.format(attendee.age_group_conf['desc'].lower())


@validation.Attendee
@ignore_unassigned_and_placeholders
def has_email(attendee):
    if not attendee.email:
        return 'Please enter an email address.'


@validation.Attendee
def attendee_email_valid(attendee):
    if attendee.email and attendee.orig_value_of('email') != attendee.email:
        return valid_email(attendee.email)


@validation.Attendee
@ignore_unassigned_and_placeholders
def address(attendee):
    if c.COLLECT_FULL_ADDRESS:
        if not attendee.address1:
            return 'Please enter a street address.'
        if not attendee.city:
            return 'Please enter a city.'
        if not attendee.region and attendee.country in ['United States', 'Canada']:
            return 'Please enter a state, province, or region.'
        if not attendee.country:
            return 'Please enter a country.'


@validation.Attendee
@ignore_unassigned_and_placeholders
def zip_code(attendee):
    if not attendee.international and not c.AT_OR_POST_CON and (not c.COLLECT_FULL_ADDRESS or attendee.country == 'United States'):
        if _invalid_zip_code(attendee.zip_code):
            return 'Enter a valid zip code'


@validation.Attendee
@ignore_unassigned_and_placeholders
def emergency_contact(attendee):
    if not attendee.ec_name:
        return 'Please tell us the name of your emergency contact.'
    if not attendee.ec_phone:
        return 'Please give us an emergency contact phone number.'
    if not attendee.international and _invalid_phone_number(attendee.ec_phone):
        if c.COLLECT_FULL_ADDRESS:
            return 'Enter a 10-digit US phone number or include a ' \
                'country code (e.g. +44) for your emergency contact number.'
        else:
            return 'Enter a 10-digit emergency contact number.'


@validation.Attendee
@ignore_unassigned_and_placeholders
def cellphone(attendee):
    if attendee.cellphone and _invalid_phone_number(attendee.cellphone):
        # phone number was inputted incorrectly
        return 'Your phone number was not a valid 10-digit US phone number. ' \
            'Please include a country code (e.g. +44) for international numbers.'

    if not attendee.no_cellphone and attendee.staffing_or_will_be and not attendee.cellphone:
        return "Phone number is required for volunteers (unless you don't own a cellphone)"


@prereg_validation.Attendee
def dealer_cellphone(attendee):
    if attendee.badge_type == c.PSEUDO_DEALER_BADGE and not attendee.cellphone:
        return 'Your phone number is required'


@validation.Attendee
@ignore_unassigned_and_placeholders
def emergency_contact_not_cellphone(attendee):
    if not attendee.international and attendee.cellphone and attendee.cellphone == attendee.ec_phone:
        return "Your phone number cannot be the same as your emergency contact number"


@validation.Attendee
@ignore_unassigned_and_placeholders
def onsite_contact(attendee):
    if not attendee.onsite_contact and not attendee.no_onsite_contact and attendee.badge_type not in [c.STAFF_BADGE, c.CONTRACTOR_BADGE]:
        return 'Please enter contact information for at least one trusted friend onsite, or indicate ' \
               'that we should use your emergency contact information instead.'


@validation.Attendee
@ignore_unassigned_and_placeholders
def onsite_contact_length(attendee):
    if attendee.onsite_contact and len(attendee.onsite_contact) > 500:
        return 'You have entered over 500 characters of onsite contact information.' \
                'Please provide contact information for fewer friends.'


@validation.Attendee
def printed_badge_change(attendee):
    if attendee.badge_printed_name != attendee.orig_value_of('badge_printed_name') \
            and c.PRINTED_BADGE_DEADLINE \
            and localized_now() > c.get_printed_badge_deadline_by_type(attendee.badge_type_real):
        with Session() as session:
            admin = session.current_admin_account()
            if not admin.is_admin:
                return '{} badges have already been ordered, so you cannot change the badge printed name.'.format(
                    attendee.badge_type_label if attendee.badge_type in c.PREASSIGNED_BADGE_TYPES else "Supporter")


@validation.Attendee
def group_leadership(attendee):
    if attendee.session and not attendee.group_id:
        orig_group_id = attendee.orig_value_of('group_id')
        if orig_group_id and attendee.id == attendee.session.group(orig_group_id).leader_id:
            return 'You cannot remove the leader of a group from that group; make someone else the leader first'


@validation.Attendee
def banned_volunteer(attendee):
    if attendee.staffing_or_will_be and attendee.full_name in c.BANNED_STAFFERS:
        return "We've declined to invite {} back as a volunteer, ".format(attendee.full_name) + (
                    'talk to Stops to override if necessary' if c.AT_THE_CON else
                    'Please contact us via {} if you believe this is in error'.format(c.CONTACT_URL))


@validation.Attendee
def attendee_money(attendee):
    try:
        amount_extra = int(float(attendee.amount_extra or 0))
        if amount_extra < 0:
            return 'Amount extra must be a positive integer'
    except Exception:
        return 'Invalid amount extra ({})'.format(attendee.amount_extra)

    if attendee.overridden_price is not None:
        try:
            overridden_price = int(float(attendee.overridden_price))
            if overridden_price < 0:
                return 'Overridden price must be a positive integer'
        except Exception:
            return 'Invalid overridden price ({})'.format(attendee.overridden_price)


@validation.Attendee
def dealer_needs_group(attendee):
    if attendee.is_dealer and not attendee.badge_type == c.PSEUDO_DEALER_BADGE and not attendee.group_id:
        return '{}s must be associated with a group'.format(c.DEALER_TERM)


@validation.Attendee
def dupe_badge_num(attendee):
    if (attendee.badge_num != attendee.orig_value_of('badge_num') or attendee.is_new) \
            and c.NUMBERED_BADGES and attendee.badge_num \
            and (not c.SHIFT_CUSTOM_BADGES or c.AFTER_PRINTED_BADGE_DEADLINE or c.AT_THE_CON):
        with Session() as session:
            existing = session.query(Attendee).filter_by(badge_num=attendee.badge_num)
            if existing.count():
                return 'That badge number already belongs to {!r}'.format(existing.first().full_name)


@validation.Attendee
def invalid_badge_num(attendee):
    if c.NUMBERED_BADGES and attendee.badge_num:
        try:
            assert int(attendee.badge_num) is not None
        except Exception:
            return '{!r} is not a valid badge number'.format(attendee.badge_num)


@validation.Attendee
def no_more_custom_badges(attendee):
    if (attendee.badge_type != attendee.orig_value_of('badge_type') or attendee.is_new) \
            and attendee.has_personalized_badge and c.AFTER_PRINTED_BADGE_DEADLINE:
        with Session() as session:
            admin = session.current_admin_account()
            if not admin.is_admin:
                return 'Custom badges have already been ordered so you cannot use this badge type'


@validation.Attendee
def out_of_badge_type(attendee):
    if attendee.badge_type != attendee.orig_value_of('badge_type'):
        with Session() as session:
            try:
                session.get_next_badge_num(attendee.badge_type_real)
            except AssertionError:
                return 'There are no more badges available for that type'


@validation.Attendee
def not_in_range(attendee):
    lower_bound, upper_bound = c.BADGE_RANGES[attendee.badge_type_real]
    if attendee.badge_num and not (lower_bound <= attendee.badge_num <= upper_bound):
        return 'Badge number {} is out of range for badge type {} ({} - {})'.format(attendee.badge_num, 
                                                                                    c.BADGES[attendee.badge_type_real], 
                                                                                    lower_bound, 
                                                                                    upper_bound)


@validation.Attendee
def invalid_badge_name(attendee):
    if attendee.badge_printed_name and c.PRINTED_BADGE_DEADLINE \
            and localized_now() <= c.get_printed_badge_deadline_by_type(attendee.badge_type_real) \
            and re.search(c.INVALID_BADGE_PRINTED_CHARS, attendee.badge_printed_name):
        return 'Your printed badge name has invalid characters. Please use only alphanumeric characters and symbols.'
"""