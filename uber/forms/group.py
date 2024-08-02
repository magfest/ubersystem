from markupsafe import Markup
from wtforms import (BooleanField, DecimalField, EmailField,
                     SelectField, SelectMultipleField, IntegerField,
                     StringField, TelField, validators, TextAreaField)
from wtforms.validators import ValidationError

from uber.config import c
from uber.forms import AddressForm, CustomValidation, MultiCheckbox, MagForm, IntSelect, NumberInputGroup, Ranking
from uber.forms.attendee import valid_cellphone
from uber.custom_tags import format_currency, pluralize
from uber.model_checks import invalid_phone_number

__all__ = ['HotelLotteryApplication', 'GroupInfo', 'ContactInfo', 'TableInfo', 'AdminGroupInfo', 'AdminTableInfo']


class HotelLotteryApplication(MagForm):
    ranked_hotels = Ranking(c.HOTEL_LOTTERY.keys())


class GroupInfo(MagForm):
    name = StringField('Group Name', validators=[
        validators.DataRequired("Please enter a group name."),
        validators.Length(max=40, message="Group names cannot be longer than 40 characters.")
        ])
    badges = IntegerField('Badges', widget=IntSelect())
    tables = DecimalField('Tables', widget=IntSelect())

    def badges_label(self):
        return "Badges (" + format_currency(c.GROUP_PRICE) + " each)"

    def badges_desc(self):
        if c.GROUP_UPDATE_GRACE_PERIOD > 0:
            return f"You have {c.GROUP_UPDATE_GRACE_PERIOD} hour{pluralize(c.GROUP_UPDATE_GRACE_PERIOD)} "\
                   "after paying to add badges to your group without quantity restrictions. You may continue to add "\
                   "badges to your group after that, but you'll have to add at least "\
                   f"{c.MIN_GROUP_ADDITION} badges at a time."
        else:
            return "You may add badges to your group later, but you must add at least {} badges at a time.".format(
                c.MIN_GROUP_ADDITION)


class AdminGroupInfo(GroupInfo):
    guest_group_type = SelectField('Checklist Type', default=0, choices=[(0, 'N/A')] + c.GROUP_TYPE_OPTS, coerce=int)
    can_add = BooleanField('This group may purchase additional badges.')
    is_dealer = BooleanField(f'This group should be treated as {c.DEALER_INDEFINITE_TERM}.',
                             description=f"{c.DEALER_TERM.title()}s are prevented from paying until they are approved,"
                             "but may assign and purchase add-ons for badges.")
    new_badge_type = SelectField('Badge Type', choices=c.BADGE_OPTS, coerce=int)
    new_ribbons = SelectMultipleField('Badge Ribbons', choices=c.RIBBON_OPTS, coerce=int, widget=MultiCheckbox())
    cost = IntegerField('Total Group Price', validators=[
        validators.NumberRange(min=0, message="Total Group Price must be a number that is 0 or higher.")
    ], widget=NumberInputGroup())
    auto_recalc = BooleanField('Automatically recalculate this number.')
    amount_paid_repr = StringField('Amount Paid', render_kw={'disabled': "disabled"})
    amount_refunded_repr = StringField('Amount Refunded', render_kw={'disabled': "disabled"})
    admin_notes = TextAreaField('Admin Notes')


class ContactInfo(AddressForm, MagForm):
    email_address = EmailField('Email Address', validators=[
        validators.DataRequired("Please enter your business email address."),
        validators.Length(max=255, message="Email addresses cannot be longer than 255 characters."),
        validators.Email(granular_message=True),
        ],
        render_kw={'placeholder': 'test@example.com'})
    phone = TelField('Phone Number', validators=[
        validators.DataRequired("Please enter your business' phone number."),
        ],
        render_kw={'placeholder': 'A phone number we can use to contact you during the event'})

    def get_optional_fields(self, group, is_admin=False):
        optional_list = super().get_optional_fields(group, is_admin)

        if not group.is_dealer:
            optional_list.extend(['address1', 'city', 'region', 'zip_code', 'country'])

        return optional_list

    def validate_phone(form, field):
        if field.data and invalid_phone_number(field.data):
            raise ValidationError('Your phone number was not a valid 10-digit US phone number. '
                                  'Please include a country code (e.g. +44) for international numbers.')


class TableInfo(GroupInfo):
    name = StringField('Table Name', validators=[
        validators.DataRequired("Please enter a table name."),
        validators.Length(max=40, message="Table names cannot be longer than 40 characters.")
        ])
    description = StringField('Description', validators=[
        validators.DataRequired("Please provide a brief description of your business.")
        ], description="Please keep to one sentence.")
    website = StringField('Website', validators=[
        validators.DataRequired("Please enter your business' website address.")
        ], description="The one you want us to link on our website, or where we can view your work "
        "to judge your application.")
    wares = TextAreaField('What do you sell?', validators=[
        validators.DataRequired("You must provide a detailed explanation of what you sell "
                                "for us to evaluate your submission.")
        ], description="Please be detailed; include a link to view your wares. "
        "You must include links to what you sell or a portfolio otherwise you will be automatically waitlisted.")
    categories = SelectMultipleField('Categories', validators=[
        validators.DataRequired("Please select at least one category your wares fall under.")
        ], choices=c.DEALER_WARES_OPTS, coerce=int, widget=MultiCheckbox())
    categories_text = StringField('Other')
    special_needs = TextAreaField('Special Requests', description="No guarantees that we can accommodate any requests.")

    def get_optional_fields(self, group, is_admin=False):
        optional_list = super().get_optional_fields(group, is_admin)
        if not group.is_dealer:
            optional_list.extend(['description', 'website', 'wares', 'categories'])
        return optional_list

    def get_non_admin_locked_fields(self, group):
        if group.is_new:
            return []
        elif group.status in c.DEALER_EDITABLE_STATUSES:
            return ['tables']

        return list(self._fields.keys())

    def badges_label(self):
        return "Badges (" + format_currency(c.DEALER_BADGE_PRICE) + " each)"

    def badges_desc(self):
        return "The number of people working your table, including yourself."

    def validate_categories(form, field):
        if field.data and c.OTHER in field.data and not form.categories_text.data:
            raise ValidationError("Please describe what 'other' categories your wares fall under.")


class AdminTableInfo(TableInfo, AdminGroupInfo):
    status = SelectField('Status', choices=c.DEALER_STATUS_OPTS, coerce=int)
    shared_with_name = StringField(
        'Shared With', description=f"The {c.DEALER_APP_TERM} this {c.DEALER_APP_TERM} is sharing a table with.")
    convert_badges = BooleanField("Convert this group's badges to individual badges.")

    def can_add_label(self):
        if c.MAX_DEALERS:
            return "This {} can add up to {} badges.".format(c.DEALER_TERM, c.MAX_DEALERS)
        else:
            return "This {} can add badges up to their personal maximum.".format(c.DEALER_TERM)


class LeaderInfo(MagForm):
    field_validation = CustomValidation()

    leader_first_name = StringField('First Name', validators=[
        validators.InputRequired("Please provide the group leader's first name.")
        ])
    leader_last_name = StringField('Last Name', validators=[
        validators.InputRequired("Please provide the group leader's last name.")
        ])
    leader_email = EmailField('Email Address', validators=[
        validators.InputRequired("Please enter an email address."),
        validators.Length(max=255, message="Email addresses cannot be longer than 255 characters."),
        validators.Email(granular_message=True),
        ],
        render_kw={'placeholder': 'test@example.com'})
    leader_cellphone = TelField('Phone Number', validators=[
        valid_cellphone
        ])

    def get_optional_fields(self, group, is_admin=False):
        optional_list = super().get_optional_fields(group, is_admin)

        if not group.is_dealer and not group.guest and not getattr(group, 'guest_group_type', None):
            optional_list.append('leader_email')

            # This mess is required because including a field in this list prevents
            # all validations from running if the field is not present
            if not getattr(group, 'leader_cellphone', None) and not getattr(group, 'leader_email', None):
                if not getattr(group, 'leader_first_name', None):
                    optional_list.append('leader_last_name')
                if not getattr(group, 'leader_last_name', None):
                    optional_list.append('leader_first_name')
        return optional_list
