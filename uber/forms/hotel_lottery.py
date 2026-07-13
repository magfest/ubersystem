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


def _hotel_ranking_choices(is_suite=False):
    from uber.models import Session
    from uber.models.hotel import LotteryHotel, HotelRoomInventory
    with Session() as session:
        hotels = session.query(LotteryHotel).filter_by(active=True).order_by(LotteryHotel.name).all()
        choices = []
        for hotel in hotels:
            price, staff_price = HotelRoomInventory.price_range_for_hotel(session, hotel.id, is_suite=is_suite)
            choices.append((str(hotel.id), {
                "name": hotel.name,
                "price": price,
                "staff_price": staff_price,
                "description": hotel.description,
                "description_right": hotel.description_right,
                "footnote": hotel.footnote,
            }))
        return choices


def _room_type_ranking_choices(is_suite=False):
    from uber.models import Session
    from uber.models.hotel import LotteryRoomType, HotelRoomInventory
    with Session() as session:
        room_types = session.query(LotteryRoomType).filter_by(
            active=True, is_suite=is_suite
        ).order_by(LotteryRoomType.name).all()
        choices = []
        for rt in room_types:
            price, staff_price = HotelRoomInventory.price_range_for_room_type(
                session, rt.id, is_suite=is_suite)
            choices.append((str(rt.id), {
                "name": rt.name,
                "price": price,
                "staff_price": staff_price,
                "description": rt.description,
                "description_right": rt.description_right,
                "footnote": rt.footnote,
            }))
        return choices


def _priority_ranking_choices():
    # Priorities are config-defined (not DB-backed), so the options come
    # straight from HOTEL_LOTTERY_PRIORITIES_OPTS.
    return list(c.HOTEL_LOTTERY_PRIORITIES_OPTS)


class LotteryInfo(MagForm):
    # `hotel_first_name` / `hotel_last_name` live on the Attendee: one
    # legal name per attendee, applied to every room they book or occupy.
    # The form fields are named to match so WTForms can bind them;
    # `populate_obj` / `process_obj` below read/write the linked attendee.
    hotel_first_name = StringField('First Name on ID')
    hotel_last_name = StringField('Last Name on ID')
    cellphone = TelField('Phone Number', render_kw={'placeholder': 'A phone number for the hotel to contact you.'})
    terms_accepted = BooleanField('I understand, agree to, and will abide by the lottery policies.', default=False)
    data_policy_accepted = BooleanField(
        'I understand and agree that my registration information will be used as part of the hotel lottery.',
        default=False)

    def process(self, formdata=None, obj=None, data=None, extra_filters=None, **kwargs):
        # Pre-fill from the attendee's hotel-name override (or the
        # legal-name fallback) so existing rows that never explicitly
        # set the new fields still show a value.
        if obj is not None and getattr(obj, 'attendee', None):
            a = obj.attendee
            kwargs.setdefault('hotel_first_name', a.effective_hotel_first_name)
            kwargs.setdefault('hotel_last_name', a.effective_hotel_last_name)
        super().process(formdata=formdata, obj=obj, data=data,
                        extra_filters=extra_filters, **kwargs)

    def populate_obj(self, app, is_admin=False):
        # Write `hotel_first_name` / `hotel_last_name` straight onto the
        # attendee; everything else lands on the lottery application as
        # usual.
        first = self.hotel_first_name.data
        last = self.hotel_last_name.data
        # Strip our two fields off the WTForms iteration so MagForm's
        # default populate_obj doesn't try to set them on the app.
        skip = {'hotel_first_name', 'hotel_last_name'}
        for name, field in self._fields.items():
            if name in skip:
                continue
            field.populate_obj(app, name)
        if app.attendee is not None:
            app.attendee.hotel_first_name = (first or '').strip()
            app.attendee.hotel_last_name = (last or '').strip()

    def get_non_admin_locked_fields(self, app):
        locked_fields = super().get_non_admin_locked_fields(app)
        locked_fields.extend(['terms_accepted', 'data_policy_accepted'])
        if not app.is_new:
            locked_fields.extend(['hotel_first_name', 'hotel_last_name'])
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
    dynamic_choices_fields = {
        'hotel_preference': lambda: _hotel_ranking_choices(is_suite=False),
        'room_type_preference': lambda: _room_type_ranking_choices(is_suite=False),
        'selection_priorities': _priority_ranking_choices,
    }

    current_step = HiddenField('Current Step')
    entry_type = HiddenField('Entry Type')
    hotel_preference = SelectMultipleField(
        'Hotels', coerce=str, choices=[],
        widget=Ranking([]))
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
        'Room Types', coerce=str, choices=[],
        widget=Ranking([]))
    selection_priorities = SelectMultipleField(
        'Selection Priorities', coerce=str, choices=[],
        widget=Ranking([]))
    wants_ada = BooleanField('I would like to request an ADA room.', default=False)
    ada_requests = TextAreaField('Requested Accommodations')


class SuiteLottery(RoomLottery):
    dynamic_choices_fields = {
        'hotel_preference': lambda: _hotel_ranking_choices(is_suite=True),
        'room_type_preference': lambda: _room_type_ranking_choices(is_suite=False),
        'suite_type_preference': lambda: _room_type_ranking_choices(is_suite=True),
        'selection_priorities': _priority_ranking_choices,
    }

    suite_type_preference = SelectMultipleField(
        'Suite Room Types', coerce=str, choices=[],
        widget=Ranking([]))
    suite_terms_accepted = BooleanField(
        f'I agree, understand and will comply with the {c.EVENT_NAME} suite policies.', default=False)
    hotel_preference = SelectMultipleField(
        'Hotels', coerce=str, choices=[], widget=Ranking([]))
    room_type_preference = SelectMultipleField(
        'Room Types', coerce=str, choices=[], widget=Ranking([]))
    room_opt_out = BooleanField('I do NOT want to enter the room lottery.')
    
    def room_opt_out_label(self):
        return Markup('I do NOT want to enter the room lottery. <strong>I understand that this means I will not be eligible for a room award if my entry is not chosen for the suite lottery.</strong>')

def _partition_choices():
    from uber.models import Session
    from uber.models.hotel import InventoryPartition
    with Session() as session:
        partitions = session.query(InventoryPartition).filter_by(active=True).order_by(InventoryPartition.name).all()
        choices = [('', "None")]
        for p in partitions:
            choices.append((str(p.id), p.name))
        return choices


class LotteryAdminInfo(SuiteLottery):
    # Per-room admin fields (assigned_inventory_id, assigned_check_in_date,
    # assigned_check_out_date, booking_url, etc.) are not on this form; the
    # hotel-lottery admin form has a separate Rooms section backed directly
    # by RoomAssignment rows.
    dynamic_choices_fields = {
        **SuiteLottery.dynamic_choices_fields,
        'partition_id': _partition_choices,
    }

    response_id = IntegerField('Response ID', render_kw={'readonly': "true"})
    current_step = IntegerField('Current Step')
    confirmation_num = StringField('Confirmation Number', render_kw={'readonly': "true"})
    can_edit = BooleanField(f'Make this application editable even after its lottery is closed.')
    is_staff_entry = BooleanField(f'This application is entered into the staff lottery.')
    hotel_first_name = LotteryInfo.hotel_first_name
    hotel_last_name = LotteryInfo.hotel_last_name
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
    partition_id = SelectField('Partition', coerce=str, choices=[('', "None")])
    hotel_rewards_number = StringField('Hotel Rewards Number')
