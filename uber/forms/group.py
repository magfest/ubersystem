from markupsafe import Markup
from wtforms import (BooleanField, DecimalField, EmailField, Form, FormField,
                     HiddenField, SelectField, SelectMultipleField, IntegerField,
                     StringField, TelField, validators, TextAreaField)
from wtforms.validators import ValidationError, StopValidation

from uber.config import c
from uber.forms import AddressForm, MultiCheckbox, MagForm, IntSelect, SwitchInput, DollarInput, HiddenIntField
from uber.custom_tags import popup_link, format_currency, pluralize, table_prices
from uber.model_checks import invalid_phone_number

__all__ = ['GroupInfo', 'ContactInfo', 'TableInfo', 'AdminGroupInfo', 'AdminTableInfo']

class GroupInfo(MagForm):
    name = StringField('Group Name', validators=[
        validators.DataRequired("Please enter a group name."),
        validators.Length(max=40, message="Group names cannot be longer than 40 characters.")
        ])
    badges = IntegerField('Badges', widget=IntSelect())

    def badges_label(self):
        return "Badges (" + format_currency(c.GROUP_PRICE) + " each)"
    
    def badges_desc(self):
        if c.GROUP_UPDATE_GRACE_PERIOD > 0:
            return """You have {} hour{} after paying to add badges to your group without quantity restrictions.
            You may continue to add badges to your group after that, but you'll have to add at least {} badges at a time.
            """.format(c.GROUP_UPDATE_GRACE_PERIOD, pluralize(c.GROUP_UPDATE_GRACE_PERIOD), c.MIN_GROUP_ADDITION)
        else:
            return "You may add badges to your group later, but you must add at least {} badges at a time.".format(
                c.MIN_GROUP_ADDITION)


class AdminGroupInfo(GroupInfo):
    guest_group_type = SelectField('Checklist Type', default="", choices=[('', 'N/A')] + c.GROUP_TYPE_OPTS, coerce=int)
    can_add = BooleanField('This group may purchase additional badges.')
    new_badge_type = SelectField('Badge Type', choices=c.BADGE_OPTS, coerce=int)
    cost = IntegerField('Total Group Price', widget=DollarInput())
    auto_recalc = BooleanField('Automatically recalculate this number.')
    amount_paid_repr = StringField('Amount Paid', render_kw={'disabled': "disabled"})
    amount_refunded_repr = StringField('Amount Refunded', render_kw={'disabled': "disabled"})


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
        
        return optional_list
    
    def validate_phone(form, field):
        if field.data and invalid_phone_number(field.data):
            raise ValidationError('Your phone number was not a valid 10-digit US phone number. ' \
                                    'Please include a country code (e.g. +44) for international numbers.')


class TableInfo(GroupInfo):
    name = StringField('Table Name', validators=[
        validators.DataRequired("Please enter a table name."),
        validators.Length(max=40, message="Table names cannot be longer than 40 characters.")
        ])
    description = StringField('Description', validators=[
        validators.DataRequired("Please provide a brief description of your business.")
        ], description="Please keep to one sentence.")
    tables = DecimalField('Tables', widget=IntSelect())
    website = StringField('Website', validators=[
        validators.DataRequired("Please enter your business' website address.")
        ], description="The one you want us to link on our website, or where we can view your work to judge your application.")
    wares = TextAreaField('Wares', validators=[
        validators.DataRequired("You must provide a detailed explanation of what you sell for us to evaluate your submission.")
        ], description="Please be detailed; include a link to view your wares. You must include links to what you sell or a portfolio otherwise you will be automatically waitlisted.")
    categories = SelectMultipleField('Categories', validators=[
        validators.DataRequired("Please select at least one category your wares fall under.")
        ], choices=c.DEALER_WARES_OPTS, coerce=int, widget=MultiCheckbox())
    categories_text = StringField('Other')
    special_needs = TextAreaField('Special Requests', description="No guarantees that we can accommodate any requests.")

    def get_optional_fields(self, group, is_admin=False):
        if not group.is_dealer:
            return ['description', 'website', 'wares', 'categories',
                    'address1', 'city', 'region', 'zip_code', 'country']
        return []

    def get_non_admin_locked_fields(self, group):
        if group.is_new or group.status in c.DEALER_EDITABLE_STATUSES:
            return []
        
        return list(self._fields.keys())

    def badges_label(self):
        return "Badges (" + format_currency(c.DEALER_BADGE_PRICE) + " each)"
    
    def badges_desc(self):
        return "The number of people working your table, including yourself."

    def tables_desc(self):
        return table_prices()
    
    def validate_categories(form, field):
        if field.data and c.OTHER in field.data and not form.categories_text.data:
            raise ValidationError("Please describe what 'other' categories your wares fall under.")

class AdminTableInfo(TableInfo, AdminGroupInfo):
    status = SelectField('Status', choices=c.DEALER_STATUS_OPTS, coerce=int)
    admin_notes = TextAreaField('Admin Notes')

    def can_add_label(self):
        if c.MAX_DEALERS:
            return "This {} can add up to {} badges.".format(c.DEALER_TERM, c.MAX_DEALERS)
        else:
            return "This {} can add badges up to their personal maximum.".format(c.DEALER_TERM)