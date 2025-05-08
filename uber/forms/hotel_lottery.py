from markupsafe import Markup
from wtforms import (BooleanField, DateField, HiddenField, SelectField, SelectMultipleField,
                     IntegerField, StringField, validators, TextAreaField, TelField)
from wtforms.validators import ValidationError, StopValidation

from uber.config import c
from uber.forms import (MagForm, CustomValidation, Ranking)
from uber.custom_tags import readable_join
from uber.model_checks import invalid_phone_number


__all__ = ['LotteryInfo', 'LotteryConfirm', 'LotteryRoomGroup', 'RoomLottery', 'SuiteLottery', 'LotteryAdminInfo']


def html_format_date(dt):
    return dt.astimezone(c.EVENT_TIMEZONE).strftime('%Y-%m-%d')


def date_in_range(field, str, min, max):
    if field.data and field.data < min.date() or field.data > max.date():
        raise ValidationError(f"Your {str} date must be between {html_format_date(min)} and {html_format_date(max)}.")


def get_earliest_checkout_date(form):
    if getattr(form, f"earliest_checkout_date").data:
        return "acceptable check-out date", getattr(form, f"earliest_checkout_date").data
    else:
        return "preferred check-out date", getattr(form, f"latest_checkout_date").data


def valid_cellphone(form, field):
    if field.data and invalid_phone_number(field.data):
        raise ValidationError('Please provide a valid 10-digit US phone number or '
                              'include a country code (e.g. +44) for international numbers.')


class LotteryInfo(MagForm):
    legal_first_name = StringField('First Name on ID',
                                   validators=[validators.DataRequired("Please enter your first name as it appears on your photo ID.")])
    legal_last_name = StringField('Last Name on ID',
                                  validators=[validators.DataRequired("Please enter your last name as it appears on your photo ID.")])
    cellphone = TelField('Phone Number', validators=[
        validators.DataRequired("Please provide a phone number for the hotel to contact you."),
        valid_cellphone
        ], render_kw={'placeholder': 'A phone number for the hotel to contact you.'})
    terms_accepted = BooleanField('I understand, agree to, and will abide by the lottery policies.', default=False,
                                  validators=[validators.InputRequired("You must agree to the room lottery policies to continue.")])
    data_policy_accepted = BooleanField('I understand and agree that my registration information will be used as part of the hotel lottery.',
                                        default=False,
                                        validators=[validators.InputRequired("You must agree to the data policies to continue.")])
    
    def get_non_admin_locked_fields(self, app):
        locked_fields = super().get_non_admin_locked_fields(app)
        locked_fields.extend(['terms_accepted', 'data_policy_accepted'])
        return locked_fields
    
class LotteryConfirm(MagForm):
    guarantee_policy_accepted = BooleanField('I understand awards are subject to cancellation if no payment guarantee is made.',
                                             default=False,
                                             validators=[validators.InputRequired("You must agree to the payment guarantee policy to continue.")])

class LotteryRoomGroup(MagForm):
    field_validation = CustomValidation()

    room_group_name = StringField('Room Group Name',
                                  description='This will be shared with anyone you invite to your room group.',
                                  validators=[
                                      validators.DataRequired("Please enter a name for your room group."),
                                      validators.Length(max=40, message="Room group names cannot be longer than 40 characters.")])
    invite_code = StringField('Room Group Invite Code',
                              description='Send this code to up to three friends to invite them to your room group.',
                              render_kw={'readonly': "true"})
    
    def get_non_admin_locked_fields(self, app):
        locked_fields = super().get_non_admin_locked_fields(app)
        locked_fields.append('invite_code')
        return locked_fields
    
    @field_validation.room_group_name
    def no_dashes(form, field):
        if '-' in field.data:
            raise ValidationError("Please do not use dashes ('-') in your room group name.")


class RoomLottery(MagForm):
    field_validation = CustomValidation()

    current_step = HiddenField('Current Step')
    entry_type = HiddenField('Entry Type')
    hotel_preference = SelectMultipleField(
        'Hotels', coerce=int, choices=c.HOTEL_LOTTERY_HOTELS_OPTS,
        widget=Ranking(c.HOTEL_LOTTERY_HOTELS_OPTS),
        validators=[validators.DataRequired("Please select at least one preferred hotel.")])
    earliest_checkin_date = DateField(
        'Preferred Check-In Date',
        validators=[validators.DataRequired("Please enter your preferred check-in date.")],
        render_kw={'min': html_format_date(c.HOTEL_LOTTERY_CHECKIN_START),
                   'max': html_format_date(c.HOTEL_LOTTERY_CHECKIN_END)})
    latest_checkin_date = DateField('Latest Acceptable Check-In Date',
                                         validators=[validators.Optional()],
                                         render_kw={'min': html_format_date(c.HOTEL_LOTTERY_CHECKIN_START),
                                                    'max': html_format_date(c.HOTEL_LOTTERY_CHECKIN_END)})
    earliest_checkout_date = DateField('Earliest Acceptable Check-Out Date',
                                            validators=[validators.Optional()],
                                            render_kw={'min': html_format_date(c.HOTEL_LOTTERY_CHECKOUT_START),
                                                       'max': html_format_date(c.HOTEL_LOTTERY_CHECKOUT_END)})
    latest_checkout_date = DateField(
        'Preferred Check-Out Date',
        validators=[validators.DataRequired("Please enter your preferred check-out date.")],
        render_kw={'min': html_format_date(c.HOTEL_LOTTERY_CHECKOUT_START),
                   'max': html_format_date(c.HOTEL_LOTTERY_CHECKOUT_END)})
    room_type_preference = SelectMultipleField(
        'Room Types', coerce=int, choices=c.HOTEL_LOTTERY_ROOM_TYPES_OPTS,
        widget=Ranking(c.HOTEL_LOTTERY_ROOM_TYPES_OPTS),
        validators=[validators.DataRequired("Please select at least one preferred room type.")])
    selection_priorities = SelectMultipleField(
        'Preference Priorities', coerce=int, choices=c.HOTEL_LOTTERY_PRIORITIES_OPTS,
        widget=Ranking(c.HOTEL_LOTTERY_PRIORITIES_OPTS))
    wants_ada = BooleanField('I would like to request an ADA room.', default=False)
    ada_requests = TextAreaField('Requested Accommodations',
                                 validators=[validators.DataRequired("Please explain some of the ADA accommodations you will require.")])
    
    def get_optional_fields(self, application, is_admin=False):
        optional_list = super().get_optional_fields(application, is_admin)

        if not application.wants_ada:
            optional_list.append('ada_requests')

        room_step = int(application.current_step) if application.current_step else 0

        if not c.HOTEL_LOTTERY_PREF_RANKING or room_step <= c.HOTEL_LOTTERY_FORM_STEPS['room_selection_pref']:
            optional_list.append('selection_priorities')
        if room_step <= c.HOTEL_LOTTERY_FORM_STEPS['room_hotel_type']:
            optional_list.extend(['room_type_preference', 'hotel_preference'])
        elif not c.HOTEL_LOTTERY_HOTELS_OPTS:
            optional_list.append('hotel_preference')
        if not c.SHOW_HOTEL_LOTTERY_DATE_OPTS or room_step < c.HOTEL_LOTTERY_FORM_STEPS['room_dates']:
            optional_list.extend(['earliest_checkin_date', 'latest_checkout_date'])

        return optional_list

    @field_validation.earliest_checkin_date
    def preferred_dates_not_swapped(form, field):
        checkout_label, earliest_checkout_date = get_earliest_checkout_date(form)

        if earliest_checkout_date and field.data == earliest_checkout_date:
            raise StopValidation(f"You cannot check in and out on the same day.")
        if earliest_checkout_date and field.data > earliest_checkout_date:
            raise StopValidation(f"Your preferred check-in date is after your {checkout_label}.")
    
    @field_validation.latest_checkin_date
    def acceptable_dates_not_swapped(form, field):
        if not field.data:
            return
        
        checkout_label, earliest_checkout_date = get_earliest_checkout_date(form)
        
        if earliest_checkout_date and field.data == earliest_checkout_date:
            raise StopValidation(f"You cannot check in and out on the same day.")
        if earliest_checkout_date and field.data > earliest_checkout_date:
            raise StopValidation(f"Your acceptable check-in date is after your {checkout_label}.")

    @field_validation.earliest_checkin_date
    def earliest_checkin_within_range(form, field):
        date_in_range(field, "preferred check-in", c.HOTEL_LOTTERY_CHECKIN_START, c.HOTEL_LOTTERY_CHECKIN_END)

    @field_validation.latest_checkin_date
    def latest_checkin_within_range(form, field):
        date_in_range(field, "latest acceptable check-in", c.HOTEL_LOTTERY_CHECKIN_START, c.HOTEL_LOTTERY_CHECKIN_END)

    @field_validation.latest_checkin_date
    def after_preferred_checkin(form, field):
        if field.data and field.data < form.earliest_checkin_date.data:
            raise StopValidation("It does not make sense to have your latest acceptable check-in date \
                                  earlier than your preferred check-in date.")

    @field_validation.latest_checkout_date
    def latest_checkin_within_range(form, field):
        date_in_range(field, "preferred check-out", c.HOTEL_LOTTERY_CHECKOUT_START, c.HOTEL_LOTTERY_CHECKOUT_END)

    @field_validation.earliest_checkout_date
    def earliest_checkin_within_range(form, field):
        date_in_range(field, "earliest acceptable check-out", c.HOTEL_LOTTERY_CHECKOUT_START, c.HOTEL_LOTTERY_CHECKOUT_END)

    @field_validation.earliest_checkout_date
    def before_preferred_checkout(form, field):
        if field.data and field.data > form.latest_checkout_date.data:
            raise ValidationError("It does not make sense to have your earliest acceptable check-out date \
                                  later than your preferred check-out date.")

    @field_validation.selection_priorities
    def all_options_ranked(form, field):
        if form.current_step.data and int(form.current_step.data) < 4:
            return
        if len(field.data) < len(c.HOTEL_LOTTERY_PRIORITIES_OPTS):
            raise ValidationError("Please rank all priorities for selecting a hotel room.")


class SuiteLottery(RoomLottery):
    suite_type_preference = SelectMultipleField(
        'Suite Room Types', coerce=int, choices=c.HOTEL_LOTTERY_SUITE_ROOM_TYPES_OPTS,
        widget=Ranking(c.HOTEL_LOTTERY_SUITE_ROOM_TYPES_OPTS),
        validators=[validators.DataRequired("Please select at least one preferred suite type.")])
    suite_terms_accepted = BooleanField(
        f'I agree, understand and will comply with the {c.EVENT_NAME} suite policies.', default=False,
        validators=[validators.InputRequired("You must agree to the suite lottery policies to enter the suite lottery.")])
    hotel_preference = SelectMultipleField(
        'Hotels', coerce=int, choices=c.HOTEL_LOTTERY_HOTELS_OPTS,
        widget=Ranking(c.HOTEL_LOTTERY_HOTELS_OPTS),
        validators=[validators.DataRequired("Please select at least one preferred hotel OR opt out of entering the room lottery.")])
    room_type_preference = SelectMultipleField(
        'Room Types', coerce=int, choices=c.HOTEL_LOTTERY_ROOM_TYPES_OPTS,
        widget=Ranking(c.HOTEL_LOTTERY_ROOM_TYPES_OPTS),
        validators=[validators.DataRequired("Please select at least one preferred room type OR opt out of entering the room lottery.")])
    room_opt_out = BooleanField('I do NOT want to enter the room lottery.')

    def get_optional_fields(self, application, is_admin=False):
        optional_list = ['ada_requests'] # steps are different for room lottery so we start from scratch

        suite_step = int(application.current_step) if application.current_step else 0

        if not c.HOTEL_LOTTERY_PREF_RANKING or suite_step <= c.HOTEL_LOTTERY_FORM_STEPS['suite_selection_pref']:
            optional_list.append('selection_priorities')
        if suite_step <= c.HOTEL_LOTTERY_FORM_STEPS['suite_hotel_type'] or application.room_opt_out:
            optional_list.extend(['room_type_preference', 'hotel_preference'])
        if suite_step <= c.HOTEL_LOTTERY_FORM_STEPS['suite_type']:
            optional_list.append('suite_type_preference')
        if not c.SHOW_HOTEL_LOTTERY_DATE_OPTS or suite_step < c.HOTEL_LOTTERY_FORM_STEPS['suite_dates']:
            optional_list.extend(['earliest_checkin_date', 'latest_checkout_date'])

        return optional_list
    
    def room_opt_out_label(self):
        return Markup('I do NOT want to enter the room lottery. <strong>I understand that this means I will not be eligible for a room award if my entry is not chosen for the suite lottery.</strong>')

class LotteryAdminInfo(SuiteLottery):
    response_id = IntegerField('Response ID', render_kw={'readonly': "true"})
    confirmation_num = StringField('Confirmation Number', render_kw={'readonly': "true"})
    legal_first_name = LotteryInfo.legal_first_name
    legal_last_name = LotteryInfo.legal_last_name
    cellphone = LotteryInfo.cellphone
    status = SelectField('Entry Status', coerce=int, choices=c.HOTEL_LOTTERY_STATUS_OPTS)
    entry_type = SelectField('Entry Type', coerce=int, choices=[(0, "N/A")] + c.HOTEL_LOTTERY_ENTRY_TYPE_OPTS)
    current_step = IntegerField('Current Step', validators=[
        validators.NumberRange(min=0, message="A lottery entry cannot be on a step below 0.")
    ])
    room_group_name = StringField('Room Group Name')
    invite_code = StringField('Room Group Invite Code', render_kw={'readonly': "true"})
    admin_notes = TextAreaField('Admin Notes')
    terms_accepted = BooleanField('Agreed to Lottery Policies', render_kw={'readonly': "true"})
    data_policy_accepted = BooleanField('Agreed to Data Policies', render_kw={'readonly': "true"})
    guarantee_policy_accepted = BooleanField('Acknowledged Payment Guarantee Policy', render_kw={'readonly': "true"})
    suite_terms_accepted = BooleanField(f'Agreed to Suite Policies', render_kw={'readonly': "true"})

    def get_optional_fields(self, application, is_admin=False):
        if not application.entry_type or application.entry_type == c.GROUP_ENTRY:
            return ['selection_priorities', 'room_type_preference', 'hotel_preference',
                    'suite_type_preference', 'earliest_checkin_date', 'latest_checkout_date',
                    'ada_requests']

        if application.entry_type == c.ROOM_ENTRY:
            optional_list = RoomLottery.get_optional_fields(self, application, is_admin)
            optional_list.append('suite_type_preference')
        elif application.entry_type == c.SUITE_ENTRY:
            optional_list = SuiteLottery.get_optional_fields(self, application, is_admin)
        return optional_list