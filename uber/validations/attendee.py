import re

from datetime import date
from pockets import classproperty
from wtforms import validators
from wtforms.validators import ValidationError, StopValidation

from uber.badge_funcs import get_real_badge_type
from uber.config import c
from uber.custom_tags import format_currency
from uber.models import Attendee, Session
from uber.model_checks import invalid_zip_code, invalid_phone_number
from uber.utils import get_age_from_birthday, get_age_conf_from_birthday
from uber.decorators import form_validation, new_or_changed_validation, post_form_validation

"""
These should probably be rewritten as automatic changes with a message attached
@post_form_validation.badge_type
def child_badge_over_13(attendee):
    if c.CHILD_BADGE in c.PREREG_BADGE_TYPES and attendee.badge_type == c.CHILD_BADGE \
            and get_age_from_birthday(attendee.birthdate, c.NOW_OR_AT_CON) >= 13:
        raise ValidationError("If you will be 13 or older at the start of {}, " \
                                "please select an Attendee badge instead of a 12 and Under badge.".format(c.EVENT_NAME))

@post_form_validation.badge_type
def attendee_badge_under_13(attendee):
    if c.CHILD_BADGE in c.PREREG_BADGE_TYPES and attendee.badge_type == c.ATTENDEE_BADGE \
        and get_age_from_birthday(attendee.birthdate, c.NOW_OR_AT_CON) < 13:
        raise ValidationError("If you will be 12 or younger at the start of {}, " \
                                "please select the 12 and Under badge instead of an Attendee badge.".format(c.EVENT_NAME))
"""

###### Attendee-Facing Validations ######
def attendee_age_checks(form, field):
    age_group_conf = get_age_conf_from_birthday(field.data, c.NOW_OR_AT_CON) if form.birthdate.data else field.data
    if age_group_conf and not age_group_conf['can_register']:
        raise ValidationError('Attendees {} years of age do not need to register, ' \
            'but MUST be accompanied by a parent at all times!'.format(age_group_conf['desc'].lower()))

@post_form_validation.none
def reasonable_total_cost(attendee):
    if attendee.total_cost >= 999999:
        return 'We cannot charge {}. Please reduce extras so the total is below $9,999.'.format(
            format_currency(attendee.total_cost))

@new_or_changed_validation.amount_extra
def upgrade_sold_out(form, field):
    currently_available_upgrades = [tier['value'] for tier in c.PREREG_DONATION_DESCRIPTIONS]
    if field.data and field.data not in currently_available_upgrades:
        raise ValidationError("The upgrade you have selected is sold out.")

@post_form_validation.badge_type
def child_group_leaders(attendee):
    if attendee.badge_type == c.PSEUDO_GROUP_BADGE and get_age_from_birthday(attendee.birthdate, c.NOW_OR_AT_CON) < 13:
        raise ValidationError("Children under 13 cannot be group leaders.")

@post_form_validation.badge_type
def no_more_child_badges(attendee):
    # TODO: Review business logic here
    if c.CHILD_BADGE in c.PREREG_BADGE_TYPES and get_age_from_birthday(attendee.birthdate, c.NOW_OR_AT_CON) < 18 \
            and not c.CHILD_BADGE_AVAILABLE:
        raise ValidationError("Unfortunately, we are sold out of badges for attendees under 18.")

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

@form_validation.badge_printed_name
def invalid_characters(form, field):
    if field.data and c.PRINTED_BADGE_DEADLINE and c.BEFORE_PRINTED_BADGE_DEADLINE \
            and re.search(c.INVALID_BADGE_PRINTED_CHARS, field.data):
        return 'Your printed badge name has invalid characters. Please use only alphanumeric characters and symbols.'

@new_or_changed_validation.badge_printed_name
def past_printed_deadline(form, field):
    if field.data in c.PREASSIGNED_BADGE_TYPES and c.PRINTED_BADGE_DEADLINE and c.AFTER_PRINTED_BADGE_DEADLINE:
        with Session() as session:
            admin = session.current_admin_account()
            if admin.is_super_admin:
                return
        raise ValidationError('{} badges have already been ordered, so you cannot change your printed badge name.'.format(
            c.BADGES[field.data]))

@form_validation.birthdate
def valid_format(form, field):
    # TODO: Make WTForms use this message instead of the generic DateField invalid value message
    if field.data and not isinstance(field.data, date):
        raise StopValidation('Please use the format YYYY-MM-DD for your date of birth.')

@form_validation.birthdate
def reasonable_dob(form, field):
    if field.data and field.data > date.today():
        raise ValidationError('You cannot be born in the future.')

@post_form_validation.birthdate
def age_discount_after_paid(attendee):
    if (attendee.total_cost * 100) < attendee.amount_paid:
        if (not attendee.orig_value_of('birthdate') or attendee.orig_value_of('birthdate') < attendee.birthdate) \
                and attendee.age_group_conf['discount'] > 0:
            return 'The date of birth you entered incurs a discount; ' \
                'please email {} to change your badge and receive a refund'.format(c.REGDESK_EMAIL)

@form_validation.cellphone
def dealer_cellphone_required(form, field):
    if form.badge_type.data == c.PSEUDO_DEALER_BADGE and not field.data:
        raise StopValidation('A phone number is required for {}s.'.format(c.DEALER_TERM))

@form_validation.cellphone
def invalid_format(form, field):
    if field.data and invalid_phone_number(field.data):
        raise ValidationError('Your phone number was not a valid 10-digit US phone number. ' \
                                'Please include a country code (e.g. +44) for international numbers.')

@form_validation.cellphone
def different_ec_phone(form, field):
    if field.data and field.data == form.ec_phone.data:
        raise ValidationError("Your phone number cannot be the same as your emergency contact number.")

@post_form_validation.cellphone
def volunteers_cellphone_or_checkbox(attendee):
    if not attendee.no_cellphone and attendee.staffing_or_will_be and not attendee.cellphone:
        return "Volunteers and staffers must provide a cellphone number or indicate they do not have a cellphone."

@form_validation.ec_phone
def valid_format(form, field):
    if not form.international.data and invalid_phone_number(field.data):
        if c.COLLECT_FULL_ADDRESS:
            raise ValidationError('Please enter a 10-digit US phone number or include a ' \
                                    'country code (e.g. +44) for your emergency contact number.')
        else:
            raise ValidationError('Please enter a 10-digit emergency contact number.')

@form_validation.onsite_contact
def required_or_no_contact(form, field):
    if not field.data and not form.no_onsite_contact.data:
        raise ValidationError('Please enter contact information for at least one trusted friend onsite, ' \
                                'or indicate that we should use your emergency contact information instead.')

@post_form_validation.promo_code
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


@post_form_validation.promo_code
def promo_code_not_is_expired(attendee):
    if attendee.is_new and attendee.promo_code and attendee.promo_code.is_expired:
        return 'That promo code is expired.'


@post_form_validation.promo_code
def promo_code_has_uses_remaining(attendee):
    from uber.utils import Charge
    if attendee.is_new and attendee.promo_code and not attendee.promo_code.is_unlimited:
        unpaid_uses_count = Charge.get_unpaid_promo_code_uses_count(
            attendee.promo_code.id, attendee.id)
        if (attendee.promo_code.uses_remaining - unpaid_uses_count) < 0:
            return 'That promo code has been used too many times.'

@post_form_validation.staffing
def allowed_to_volunteer(attendee):
    if attendee.staffing_or_will_be \
            and not attendee.age_group_conf['can_volunteer'] \
            and attendee.badge_type not in [c.STAFF_BADGE, c.CONTRACTOR_BADGE] \
            and c.PRE_CON:
        return 'Your interest is appreciated, but ' + c.EVENT_NAME + ' volunteers must be 18 or older.'
    
@post_form_validation.staffing
def banned_volunteer(attendee):
    if attendee.staffing_or_will_be and attendee.full_name in c.BANNED_STAFFERS:
        return "We've declined to invite {} back as a volunteer, ".format(attendee.full_name) + (
                    'talk to STOPS to override if necessary' if c.AT_THE_CON else
                    'Please contact us via {} if you believe this is in error'.format(c.CONTACT_URL))


###### Admin-Only Validations ######

@form_validation.badge_num
def not_in_range(form, field):
    if not field.data:
        return
    
    badge_type = get_real_badge_type(form.badge_type.data)
    lower_bound, upper_bound = c.BADGE_RANGES[badge_type]
    if not (lower_bound <= field.data <= upper_bound):
        return 'Badge number {} is out of range for badge type {} ({} - {})'.format(field.data, 
                                                                                    c.BADGES[form.badge_type.data],
                                                                                    lower_bound, 
                                                                                    upper_bound)

@form_validation.badge_num
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

@post_form_validation.group_id
def dealer_needs_group(attendee):
    if attendee.is_dealer and not attendee.badge_type == c.PSEUDO_DEALER_BADGE and not attendee.group_id:
        return '{}s must be associated with a group'.format(c.DEALER_TERM)

@post_form_validation.group_id
def group_leadership(attendee):
    if attendee.session and not attendee.group_id:
        orig_group_id = attendee.orig_value_of('group_id')
        if orig_group_id and attendee.id == attendee.session.group(orig_group_id).leader_id:
            return 'You cannot remove the leader of a group from that group; make someone else the leader first'
