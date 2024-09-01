import cherrypy
from datetime import date

from markupsafe import Markup
from wtforms import (BooleanField, DateField, EmailField,
                     HiddenField, SelectField, SelectMultipleField, IntegerField,
                     StringField, TelField, validators, TextAreaField)
from wtforms.validators import ValidationError, StopValidation

from uber.config import c
from uber.forms import (AddressForm, MultiCheckbox, MagForm, SelectAvailableField, SwitchInput, NumberInputGroup,
                        HiddenBoolField, HiddenIntField, CustomValidation, Ranking)
from uber.custom_tags import popup_link
from uber.badge_funcs import get_real_badge_type
from uber.models import Attendee, Session, PromoCodeGroup
from uber.model_checks import invalid_phone_number
from uber.utils import get_age_conf_from_birthday


__all__ = ['LotteryInfo', 'RoomLottery', 'SuiteLottery', 'LotteryRoomGroup']


def html_format_date(dt):
    return dt.astimezone(c.EVENT_TIMEZONE).strftime('%Y-%m-%d')


def date_in_range(field, str, min, max):
    if field.data and field.data < min.date() or field.data > max.date():
        raise ValidationError(f"Your {str} date must be between {html_format_date(min)} and {html_format_date(max)}.")


class LotteryInfo(MagForm):
    terms_accepted = BooleanField('I understand, agree to, and will abide by the lottery policies.', default=False,
                                  validators=[validators.InputRequired("You must agree to the room lottery policies to continue.")])


class LotteryRoomGroup(MagForm):
    field_validation = CustomValidation()
    room_group_name = StringField('Room Group Name',
                                  description='This will be shared with anyone you invite to your room group.',
                                  validators=[validators.DataRequired("Please enter a name for your room group.")])
    invite_code = StringField('Room Group Invite Code',
                              description='Send this code to up to three friends to invite them to your room group.',
                              render_kw={'readonly': "true"})
    
    def get_non_admin_locked_fields(self, app):
        locked_fields = super().get_non_admin_locked_fields(app)
        locked_fields.append('invite_code')
        return locked_fields


class RoomLottery(MagForm):
    field_validation = CustomValidation()

    wants_room = BooleanField('I would like to enter the hotel room lottery.', default=False)
    earliest_room_checkin_date = DateField(
        'Preferred Check-In Date',
        validators=[validators.DataRequired("Please enter your preferred check-in date.")],
        render_kw={'min': html_format_date(c.HOTEL_LOTTERY_CHECKIN_START),
                   'max': html_format_date(c.HOTEL_LOTTERY_CHECKIN_END)})
    latest_room_checkin_date = DateField('Latest Acceptable Check-In Date',
                                         validators=[validators.Optional()],
                                         render_kw={'min': html_format_date(c.HOTEL_LOTTERY_CHECKIN_START),
                                                    'max': html_format_date(c.HOTEL_LOTTERY_CHECKIN_END)})
    earliest_room_checkout_date = DateField('Earliest Acceptable Check-Out Date',
                                            validators=[validators.Optional()],
                                            render_kw={'min': html_format_date(c.HOTEL_LOTTERY_CHECKOUT_START),
                                                       'max': html_format_date(c.HOTEL_LOTTERY_CHECKOUT_END)})
    latest_room_checkout_date = DateField(
        'Preferred Check-Out Date',
        validators=[validators.DataRequired("Please enter your preferred check-out date.")],
        render_kw={'min': html_format_date(c.HOTEL_LOTTERY_CHECKOUT_START),
                   'max': html_format_date(c.HOTEL_LOTTERY_CHECKOUT_END)})
    hotel_preference = SelectMultipleField(
        'Hotels', coerce=int, choices=c.HOTEL_LOTTERY_HOTELS_OPTS,
        widget=Ranking(c.HOTEL_LOTTERY_HOTELS_OPTS),
        validators=[validators.DataRequired("Please select at least one preferred hotel.")])
    room_type_preference = SelectMultipleField(
        'Room Types', coerce=int, choices=c.HOTEL_LOTTERY_ROOM_TYPES_OPTS,
        widget=Ranking(c.HOTEL_LOTTERY_ROOM_TYPES_OPTS),
        validators=[validators.DataRequired("Please select at least one preferred room type.")])
    room_selection_priorities = SelectMultipleField(
        'Preference Priorities', coerce=int, choices=c.HOTEL_LOTTERY_ROOM_PRIORITIES_OPTS,
        widget=Ranking(c.HOTEL_LOTTERY_ROOM_PRIORITIES_OPTS))
    wants_ada = BooleanField('I would like to request an ADA room.', default=False)
    ada_requests = TextAreaField('Requested Accommodations')

    @property
    def shared_fields(self):
        # This help us use the same template logic for both room and suite lotteries
        return {'earliest_checkin_date': self.earliest_room_checkin_date,
                'latest_checkin_date': self.latest_room_checkin_date,
                'earliest_checkout_date': self.earliest_room_checkout_date,
                'latest_checkout_date': self.latest_room_checkout_date,
                'room_or_suite_type_preference': self.room_type_preference,
                'selection_priorities': self.room_selection_priorities}

    @field_validation.earliest_room_checkin_date
    def earliest_checkin_within_range(form, field):
        date_in_range(field, "preferred check-in", c.HOTEL_LOTTERY_CHECKIN_START, c.HOTEL_LOTTERY_CHECKIN_END)

    @field_validation.latest_room_checkin_date
    def latest_checkin_within_range(form, field):
        date_in_range(field, "latest acceptable check-in", c.HOTEL_LOTTERY_CHECKIN_START, c.HOTEL_LOTTERY_CHECKIN_END)

    @field_validation.latest_room_checkin_date
    def after_preferred_checkin(form, field):
        if field.data and field.data < form.earliest_room_checkin_date.data:
            raise ValidationError("It does not make sense to have your latest acceptable check-in date \
                                  earlier than your preferred check-in date.")

    @field_validation.latest_room_checkout_date
    def latest_checkin_within_range(form, field):
        date_in_range(field, "preferred check-out", c.HOTEL_LOTTERY_CHECKOUT_START, c.HOTEL_LOTTERY_CHECKOUT_END)

    @field_validation.earliest_room_checkout_date
    def earliest_checkin_within_range(form, field):
        date_in_range(field, "earliest acceptable check-out", c.HOTEL_LOTTERY_CHECKOUT_START, c.HOTEL_LOTTERY_CHECKOUT_END)

    @field_validation.earliest_room_checkout_date
    def before_preferred_checkout(form, field):
        if field.data and field.data > form.latest_room_checkout_date.data:
            raise ValidationError("It does not make sense to have your earliest acceptable check-out date \
                                  later than your preferred check-out date.")

    @field_validation.room_selection_priorities
    def all_options_ranked(form, field):
        if len(field.data) < len(c.HOTEL_LOTTERY_ROOM_PRIORITIES_OPTS):
            raise ValidationError("Please rank all priorities for selecting a hotel room.")


class SuiteLottery(MagForm):
    field_validation = CustomValidation()

    wants_suite = BooleanField('I would like to enter the suite lottery.', default=False)
    earliest_suite_checkin_date = DateField(
        'Preferred Check-In Date',
        validators=[validators.DataRequired("Please enter your preferred check-in date.")],
        render_kw={'min': html_format_date(c.HOTEL_LOTTERY_CHECKIN_START),
                   'max': html_format_date(c.HOTEL_LOTTERY_CHECKIN_END)})
    latest_suite_checkin_date = DateField('Latest Acceptable Check-In Date',
                                         validators=[validators.Optional()],
                                         render_kw={'min': html_format_date(c.HOTEL_LOTTERY_CHECKIN_START),
                                                    'max': html_format_date(c.HOTEL_LOTTERY_CHECKIN_END)})
    earliest_suite_checkout_date = DateField('Earliest Acceptable Check-Out Date',
                                            validators=[validators.Optional()],
                                            render_kw={'min': html_format_date(c.HOTEL_LOTTERY_CHECKOUT_START),
                                                       'max': html_format_date(c.HOTEL_LOTTERY_CHECKOUT_END)})
    latest_suite_checkout_date = DateField(
        'Preferred Check-Out Date',
        validators=[validators.DataRequired("Please enter your preferred check-out date.")],
        render_kw={'min': html_format_date(c.HOTEL_LOTTERY_CHECKOUT_START),
                   'max': html_format_date(c.HOTEL_LOTTERY_CHECKOUT_END)})
    suite_type_preference = SelectMultipleField(
        'Suite Room Types', coerce=int, choices=c.HOTEL_LOTTERY_SUITE_ROOM_TYPES_OPTS,
        widget=Ranking(c.HOTEL_LOTTERY_SUITE_ROOM_TYPES_OPTS),
        validators=[validators.DataRequired("Please select at least one preferred suite type.")])
    suite_selection_priorities = SelectMultipleField(
        'Preference Priorities', coerce=int, choices=c.HOTEL_LOTTERY_SUITE_PRIORITIES_OPTS,
        widget=Ranking(c.HOTEL_LOTTERY_SUITE_PRIORITIES_OPTS))
    suite_terms_accepted = BooleanField(
        f'I agree, understand and will comply with the {c.EVENT_NAME} suite policies.', default=False,
        validators=[validators.InputRequired("You must agree to the suite lottery policies to enter the suite lottery.")])

    @property
    def shared_fields(self):
        # This help us use the same template logic for both room and suite lotteries
        return {'earliest_checkin_date': self.earliest_suite_checkin_date,
                'latest_checkin_date': self.latest_suite_checkin_date,
                'earliest_checkout_date': self.earliest_suite_checkout_date,
                'latest_checkout_date': self.latest_suite_checkout_date,
                'room_or_suite_type_preference': self.suite_type_preference,
                'selection_priorities': self.suite_selection_priorities}
    
    @field_validation.earliest_suite_checkin_date
    def earliest_checkin_within_range(form, field):
        date_in_range(field, "preferred check-in", c.HOTEL_LOTTERY_CHECKIN_START, c.HOTEL_LOTTERY_CHECKIN_END)

    @field_validation.latest_suite_checkin_date
    def latest_checkin_within_range(form, field):
        date_in_range(field, "latest acceptable check-in", c.HOTEL_LOTTERY_CHECKIN_START, c.HOTEL_LOTTERY_CHECKIN_END)

    @field_validation.latest_suite_checkin_date
    def after_preferred_checkin(form, field):
        if field.data and field.data < form.earliest_suite_checkin_date.data:
            raise ValidationError("It does not make sense to have your latest acceptable check-in date \
                                  earlier than your preferred check-in date.")

    @field_validation.latest_suite_checkout_date
    def latest_checkin_within_range(form, field):
        date_in_range(field, "preferred check-out", c.HOTEL_LOTTERY_CHECKOUT_START, c.HOTEL_LOTTERY_CHECKOUT_END)

    @field_validation.earliest_suite_checkout_date
    def earliest_checkin_within_range(form, field):
        date_in_range(field, "earliest acceptable check-out", c.HOTEL_LOTTERY_CHECKOUT_START, c.HOTEL_LOTTERY_CHECKOUT_END)

    @field_validation.earliest_suite_checkout_date
    def before_preferred_checkout(form, field):
        if field.data and field.data > form.latest_suite_checkout_date.data:
            raise ValidationError("It does not make sense to have your earliest acceptable check-out date \
                                  later than your preferred check-out date.")
        
    @field_validation.suite_selection_priorities
    def all_options_ranked(form, field):
        if len(field.data) < len(c.HOTEL_LOTTERY_SUITE_PRIORITIES_OPTS):
            raise ValidationError("Please rank all priorities for selecting a hotel suite.")