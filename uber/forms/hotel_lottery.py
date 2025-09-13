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


class LotteryInfo(MagForm):
    legal_first_name = StringField('First Name on ID')
    legal_last_name = StringField('Last Name on ID')
    cellphone = TelField('Phone Number', render_kw={'placeholder': 'A phone number for the hotel to contact you.'})
    terms_accepted = BooleanField('I understand, agree to, and will abide by the lottery policies.', default=False)
    data_policy_accepted = BooleanField(
        'I understand and agree that my registration information will be used as part of the hotel lottery.',
        default=False)
    
    def get_non_admin_locked_fields(self, app):
        locked_fields = super().get_non_admin_locked_fields(app)
        locked_fields.extend(['terms_accepted', 'data_policy_accepted'])
        if not app.is_new:
            locked_fields.extend(['legal_first_name', 'legal_last_name'])
        return locked_fields

class LotteryConfirm(MagForm):
    guarantee_policy_accepted = BooleanField(
        'I understand awards are subject to cancellation if no payment guarantee is made.', default=False)

class LotteryRoomGroup(MagForm):
    field_validation = CustomValidation()

    room_group_name = StringField(f'{c.HOTEL_LOTTERY_GROUP_TERM} Name',
                                  description=f'This will be shared with anyone you invite to your {c.HOTEL_LOTTERY_GROUP_TERM.lower()}.')
    invite_code = StringField(f'{c.HOTEL_LOTTERY_GROUP_TERM} Invite Code',
                              description=f'Send this code to up to three friends to invite them to your {c.HOTEL_LOTTERY_GROUP_TERM.lower()}.',
                              render_kw={'readonly': "true"})
    
    def get_non_admin_locked_fields(self, app):
        locked_fields = super().get_non_admin_locked_fields(app)
        locked_fields.append('invite_code')
        return locked_fields


class RoomLottery(MagForm):
    field_validation = CustomValidation()

    current_step = HiddenField('Current Step')
    entry_type = HiddenField('Entry Type')
    hotel_preference = SelectMultipleField(
        'Hotels', coerce=int, choices=c.HOTEL_LOTTERY_HOTELS_OPTS,
        widget=Ranking(c.HOTEL_LOTTERY_HOTELS_OPTS))
    earliest_checkin_date = DateField(
        'Preferred Check-In Date',
        render_kw={'min': html_format_date(c.HOTEL_LOTTERY_CHECKIN_START),
                   'max': html_format_date(c.HOTEL_LOTTERY_CHECKIN_END)})
    latest_checkin_date = DateField('Latest Acceptable Check-In Date',
                                         render_kw={'min': html_format_date(c.HOTEL_LOTTERY_CHECKIN_START),
                                                    'max': html_format_date(c.HOTEL_LOTTERY_CHECKIN_END)})
    earliest_checkout_date = DateField('Earliest Acceptable Check-Out Date',
                                            render_kw={'min': html_format_date(c.HOTEL_LOTTERY_CHECKOUT_START),
                                                       'max': html_format_date(c.HOTEL_LOTTERY_CHECKOUT_END)})
    latest_checkout_date = DateField(
        'Preferred Check-Out Date',
        render_kw={'min': html_format_date(c.HOTEL_LOTTERY_CHECKOUT_START),
                   'max': html_format_date(c.HOTEL_LOTTERY_CHECKOUT_END)})
    room_type_preference = SelectMultipleField(
        'Room Types', coerce=int, choices=c.HOTEL_LOTTERY_ROOM_TYPES_OPTS,
        widget=Ranking(c.HOTEL_LOTTERY_ROOM_TYPES_OPTS))
    selection_priorities = SelectMultipleField(
        'Preference Priorities', coerce=int, choices=c.HOTEL_LOTTERY_PRIORITIES_OPTS,
        widget=Ranking(c.HOTEL_LOTTERY_PRIORITIES_OPTS))
    wants_ada = BooleanField('I would like to request an ADA room.', default=False)
    ada_requests = TextAreaField('Requested Accommodations')


class SuiteLottery(RoomLottery):
    suite_type_preference = SelectMultipleField(
        'Suite Room Types', coerce=int, choices=c.HOTEL_LOTTERY_SUITE_ROOM_TYPES_OPTS,
        widget=Ranking(c.HOTEL_LOTTERY_SUITE_ROOM_TYPES_OPTS))
    suite_terms_accepted = BooleanField(
        f'I agree, understand and will comply with the {c.EVENT_NAME} suite policies.', default=False)
    hotel_preference = SelectMultipleField(
        'Hotels', coerce=int, choices=c.HOTEL_LOTTERY_HOTELS_OPTS, widget=Ranking(c.HOTEL_LOTTERY_HOTELS_OPTS))
    room_type_preference = SelectMultipleField(
        'Room Types', coerce=int, choices=c.HOTEL_LOTTERY_ROOM_TYPES_OPTS, widget=Ranking(c.HOTEL_LOTTERY_ROOM_TYPES_OPTS))
    room_opt_out = BooleanField('I do NOT want to enter the room lottery.')
    
    def room_opt_out_label(self):
        return Markup('I do NOT want to enter the room lottery. <strong>I understand that this means I will not be eligible for a room award if my entry is not chosen for the suite lottery.</strong>')

def nullable_int(val):
    val = int(val)
    if val <= 0:
        return None
    return val

class LotteryAdminInfo(SuiteLottery):
    response_id = IntegerField('Response ID', render_kw={'readonly': "true"})
    current_step = IntegerField('Current Step')
    confirmation_num = StringField('Confirmation Number', render_kw={'readonly': "true"})
    can_edit = BooleanField(f'Make this application editable even after its lottery is closed.')
    legal_first_name = LotteryInfo.legal_first_name
    legal_last_name = LotteryInfo.legal_last_name
    cellphone = LotteryInfo.cellphone
    status = SelectField('Entry Status', coerce=int, choices=c.HOTEL_LOTTERY_STATUS_OPTS)
    entry_type = SelectField('Entry Type', coerce=int, choices=[(0, "N/A")] + c.HOTEL_LOTTERY_ENTRY_TYPE_OPTS)
    room_group_name = StringField(f'{c.HOTEL_LOTTERY_GROUP_TERM} Name')
    invite_code = StringField(f'{c.HOTEL_LOTTERY_GROUP_TERM} Invite Code', render_kw={'readonly': "true"})
    admin_notes = TextAreaField('Admin Notes')
    terms_accepted = BooleanField('Agreed to Lottery Policies', render_kw={'readonly': "true"})
    data_policy_accepted = BooleanField('Agreed to Data Policies', render_kw={'readonly': "true"})
    guarantee_policy_accepted = BooleanField('Acknowledged Payment Guarantee Policy', render_kw={'readonly': "true"})
    suite_terms_accepted = BooleanField(f'Agreed to Suite Policies', render_kw={'readonly': "true"})
    assigned_hotel = SelectField('Assigned Hotel', coerce=nullable_int, choices=[(0, "N/A")] + [(x[0],x[1]['name']) for x in c.HOTEL_LOTTERY_HOTELS_OPTS])
    assigned_room_type = SelectField('Assigned Hotel Room Type', coerce=nullable_int, choices=[(0, "N/A")] + [(x[0],x[1]['name']) for x in c.HOTEL_LOTTERY_ROOM_TYPES_OPTS])
    assigned_suite_type = SelectField('Assigned Suite Room Type', coerce=nullable_int, choices=[(0, "N/A")] + [(x[0],x[1]['name']) for x in c.HOTEL_LOTTERY_SUITE_ROOM_TYPES_OPTS])