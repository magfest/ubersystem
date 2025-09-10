from datetime import date
from wtforms import validators
from wtforms.validators import ValidationError, StopValidation

from uber.config import c
from uber.forms.hotel_lottery import *
from uber.forms.hotel_lottery import html_format_date
from uber.model_checks import validation
from uber.utils import get_age_from_birthday


def get_common_required_fields(check_func):
    return {
        'earliest_checkin_date': ("Please enter your preferred check-in date.", 'earliest_checkin_date', check_func),
        'latest_checkout_date': ("Please enter your preferred check-out date.", 'latest_checkout_date', check_func),
        'selection_priorities': ("Please rank your priorities for selecting a hotel room.", 'selection_priorities', check_func),
    }


def date_in_range(field, str, min, max):
    if field.data and (field.data < min.date() or field.data > max.date()):
        raise ValidationError(f"Your {str} date must be between {html_format_date(min)} and {html_format_date(max)}.")


def get_earliest_checkout_date(form):
    if getattr(form, f"earliest_checkout_date").data:
        return "acceptable check-out date", getattr(form, f"earliest_checkout_date").data
    else:
        return "preferred check-out date", getattr(form, f"latest_checkout_date").data


LotteryInfo.field_validation.required_fields = {
    'legal_first_name': "Please enter your first name as it appears on your photo ID.",
    'legal_last_name': "Please enter your last name as it appears on your photo ID.",
    'cellphone': "Please provide a phone number for the hotel to contact you.",
    'terms_accepted': "You must agree to the room lottery policies to continue.",
    'data_policy_accepted': "You must agree to the data policies to continue.",
}


LotteryConfirm.field_validation.required_fields['guarantee_policy_accepted'] = "You must agree to the payment guarantee policy to continue."


LotteryRoomGroup.field_validation.required_fields['room_group_name'] = f"Please enter a name for your {c.HOTEL_LOTTERY_GROUP_TERM.lower()}."
LotteryRoomGroup.field_validation.validations['room_group_name']['length'] = validators.Length(
    max=40, message=f"{c.HOTEL_LOTTERY_GROUP_TERM.capitalize()} names cannot be longer than 40 characters.")


@LotteryRoomGroup.field_validation('room_group_name')
def no_dashes(form, field):
    if '-' in field.data:
        raise ValidationError(f"Please do not use dashes ('-') in your {c.HOTEL_LOTTERY_GROUP_TERM.lower()} name.")


def check_required_room_steps(form):
    optional_list = ['suite_type_preference', 'suite_terms_accepted']

    room_step = int(form.model.current_step) if form.model.current_step else 0

    if room_step < c.HOTEL_LOTTERY_FORM_STEPS.get('room_selection_pref', 9999):
        optional_list.append('selection_priorities')
    if room_step < c.HOTEL_LOTTERY_FORM_STEPS.get('room_hotel_type', 9999):
        optional_list.extend(['room_type_preference', 'hotel_preference'])
    elif not c.HOTEL_LOTTERY_HOTELS_OPTS:
        optional_list.append('hotel_preference')
    if room_step < c.HOTEL_LOTTERY_FORM_STEPS.get('room_dates', 9999):
        optional_list.extend(['earliest_checkin_date', 'latest_checkout_date'])
    return optional_list


room_steps_check = lambda x: x.name not in check_required_room_steps(x.form)



RoomLottery.field_validation.required_fields = get_common_required_fields(room_steps_check)
RoomLottery.field_validation.required_fields.update({
    'ada_requests': ("Please explain some of the ADA accommodations you will require.", 'wants_ada'),
    'hotel_preference': ("Please select at least one preferred hotel.", 'hotel_preference', room_steps_check),
    'room_type_preference': ("Please select at least one preferred room type.", 'room_type_preference', room_steps_check),
    })


RoomLottery.field_validation.validations['latest_checkin_date']['optional'] = validators.Optional()
RoomLottery.field_validation.validations['earliest_checkout_date']['optional'] = validators.Optional()


@RoomLottery.field_validation('earliest_checkin_date')
def old_enough_to_check_in(form, field):
    if not field.data or not form.model.birthdate:
        return
    
    if get_age_from_birthday(form.model.birthdate, field.data) < 21:
        raise ValidationError("You must be at least 21 years old on your earliest check-in date.")


@RoomLottery.field_validation('earliest_checkin_date')
def preferred_dates_not_swapped(form, field):
    if not field.data:
        return

    checkout_label, earliest_checkout_date = get_earliest_checkout_date(form)

    if earliest_checkout_date and field.data == earliest_checkout_date:
        raise StopValidation(f"You cannot check in and out on the same day.")
    if earliest_checkout_date and field.data > earliest_checkout_date:
        raise StopValidation(f"Your preferred check-in date is after your {checkout_label}.")


@RoomLottery.field_validation('latest_checkin_date')
def acceptable_dates_not_swapped(form, field):
    if not field.data:
        return
    
    checkout_label, earliest_checkout_date = get_earliest_checkout_date(form)
    
    if earliest_checkout_date and field.data == earliest_checkout_date:
        raise StopValidation(f"You cannot check in and out on the same day.")
    if earliest_checkout_date and field.data > earliest_checkout_date:
        raise StopValidation(f"Your acceptable check-in date is after your {checkout_label}.")


@RoomLottery.field_validation('earliest_checkin_date')
def earliest_checkin_within_range(form, field):
    date_in_range(field, "preferred check-in", c.HOTEL_LOTTERY_CHECKIN_START, c.HOTEL_LOTTERY_CHECKIN_END)


@RoomLottery.field_validation('latest_checkin_date')
def latest_checkin_within_range(form, field):
    date_in_range(field, "latest acceptable check-in", c.HOTEL_LOTTERY_CHECKIN_START, c.HOTEL_LOTTERY_CHECKIN_END)


@RoomLottery.field_validation('latest_checkin_date')
def after_preferred_checkin(form, field):
    if field.data and field.data < form.earliest_checkin_date.data:
        raise StopValidation("Please make sure your latest acceptable check-in date "
                             "is later than your preferred check-in date.")


@RoomLottery.field_validation('latest_checkout_date')
def latest_checkin_within_range(form, field):
    date_in_range(field, "preferred check-out", c.HOTEL_LOTTERY_CHECKOUT_START, c.HOTEL_LOTTERY_CHECKOUT_END)


@RoomLottery.field_validation('earliest_checkout_date')
def earliest_checkin_within_range(form, field):
    date_in_range(field, "earliest acceptable check-out", c.HOTEL_LOTTERY_CHECKOUT_START, c.HOTEL_LOTTERY_CHECKOUT_END)


@RoomLottery.field_validation('earliest_checkout_date')
def before_preferred_checkout(form, field):
    if field.data and field.data > form.latest_checkout_date.data:
        raise ValidationError("Please make sure your earliest acceptable check-out date \
                                is earlier than your preferred check-out date.")


@RoomLottery.field_validation('selection_priorities')
def all_options_ranked(form, field):
    if field.data and len(field.data) < len(c.HOTEL_LOTTERY_PRIORITIES_OPTS):
        raise ValidationError("Please rank all priorities for selecting a hotel room.")


def check_required_suite_steps(form):
    optional_list = []

    suite_step = int(form.model.current_step) if form.model.current_step else 0

    if suite_step < c.HOTEL_LOTTERY_FORM_STEPS.get('suite_selection_pref', 9999):
        optional_list.append('selection_priorities')
    if suite_step < c.HOTEL_LOTTERY_FORM_STEPS.get('suite_hotel_type', 9999) or form.room_opt_out.data:
        optional_list.extend(['room_type_preference', 'hotel_preference'])
    if suite_step < c.HOTEL_LOTTERY_FORM_STEPS.get('suite_type', 9999):
        optional_list.append('suite_type_preference')
    if suite_step < c.HOTEL_LOTTERY_FORM_STEPS.get('suite_dates', 9999):
        optional_list.extend(['earliest_checkin_date', 'latest_checkout_date'])

    return optional_list


suite_steps_check = lambda x: x.name not in check_required_suite_steps(x.form)


SuiteLottery.field_validation.required_fields = get_common_required_fields(suite_steps_check)
SuiteLottery.field_validation.required_fields.update({
    'hotel_preference': ("Please select at least one preferred hotel for a room, or opt out of the room lottery.",
                         'hotel_preference', suite_steps_check),
    'room_type_preference': ("Please select at least one preferred standard room type, or opt out of the room lottery.",
                             'room_type_preference', suite_steps_check),
    'suite_terms_accepted': ("You must agree to the suite lottery policies to enter the suite lottery.",
                             'suite_terms_accepted', lambda x: True),  # Allow LotteryAdminInfo to override
    'suite_type_preference': ("Please select at least one preferred suite type.",
                              'suite_type_preference', suite_steps_check),
})


SuiteLottery.field_validation.validations['earliest_checkin_date']['optional'] = validators.Optional()
SuiteLottery.field_validation.validations['latest_checkout_date']['optional'] = validators.Optional()


lottery_form_fields = ['earliest_checkin_date', 'latest_checkin_date', 'earliest_checkout_date', 'latest_checkout_date',
                      'room_type_preference', 'hotel_preference', 'selection_priorities', 'suite_terms_accepted',
                      'suite_type_preference']


def check_required_admin_steps(form):
    if not form.model.entry_type or form.model.entry_type == c.GROUP_ENTRY or form.model.status != c.COMPLETE:
        return lottery_form_fields
    elif form.model.entry_type == c.SUITE_ENTRY:
        return check_required_suite_steps(form)
    else:
        return check_required_room_steps(form)


admin_steps_check = lambda x: x.name not in check_required_admin_steps(x.form)


LotteryAdminInfo.field_validation.required_fields = get_common_required_fields(admin_steps_check)
LotteryAdminInfo.field_validation.required_fields.update({
    'hotel_preference': (
        "Please select at least one preferred hotel for a room, or check the room lottery opt-out checkbox if this is a suite entry.",
        'hotel_preference', admin_steps_check),
    'room_type_preference': (
        "Please select at least one preferred standard room type, or check the room lottery opt-out checkbox if this is a suite entry.",
        'room_type_preference', admin_steps_check),
    'suite_terms_accepted': ("You must agree to the suite lottery policies to enter the suite lottery.",
                             'suite_terms_accepted', admin_steps_check),
    'suite_type_preference': ("Please select at least one preferred suite type.",
                              'suite_type_preference', admin_steps_check),
})


LotteryAdminInfo.field_validation.validations['current_step']['optional'] = validators.Optional()
LotteryAdminInfo.field_validation.validations['current_step']['minimum'] = validators.NumberRange(
    min=0, message="A lottery entry cannot be on a step below 0.")