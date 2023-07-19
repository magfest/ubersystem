from markupsafe import Markup
from wtforms import (BooleanField, DecimalField, EmailField, Form, FormField,
                     HiddenField, SelectField, SelectMultipleField, IntegerField,
                     StringField, TelField, validators, TextAreaField)
from wtforms.validators import ValidationError, StopValidation

from uber.config import c
from uber.forms import AddressForm, MultiCheckbox, MagForm, IntSelect, SwitchInput, DollarInput, HiddenIntField
from uber.custom_tags import popup_link, format_currency, pluralize, table_prices
from uber.validations import attendee as attendee_validators

__all__ = ['GroupInfo', 'ContactInfo', 'TableInfo']

class GroupInfo(MagForm):
    name = StringField('Group Name', validators=[
        validators.Length(max=40, message="Group names cannot be longer than 40 characters.")
        ])
    badges = IntegerField('Badges')

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


class ContactInfo(AddressForm, MagForm):
    email_address = EmailField('Email Address', validators=[
        validators.InputRequired("Please enter your business email address."),
        validators.Length(max=255, message="Email addresses cannot be longer than 255 characters."),
        validators.Email(granular_message=True),
        ],
        render_kw={'placeholder': 'test@example.com'})
    phone = TelField('Phone Number', validators=[
        validators.InputRequired("Please enter your business' phone number."),
        ],
        render_kw={'placeholder': 'A phone number we can use to contact you during the event'})


class TableInfo(MagForm):
    name = StringField('Table Name', validators=[
        validators.InputRequired(message="Please enter a table name."),
        validators.Length(max=40, message="Table names cannot be longer than 40 characters.")
        ])
    description = StringField('Description', validators=[
        validators.InputRequired("Please provide a brief description of your business.")
        ], description="Please keep to one sentence.")
    badges = IntegerField('Badges', widget=IntSelect(), description="The number of people working your table, including yourself.")
    tables = DecimalField('Tables', widget=IntSelect())
    website = StringField('Website', validators=[
        validators.InputRequired("Please enter your business' website address.")
        ], description="The one you want us to link on our website, or where we can view your work to judge your application.")
    wares = TextAreaField('Wares', validators=[
        validators.InputRequired("You must provide a detailed explanation of what you sell for us to evaluate your submission.")
        ], description="Please be detailed; include a link to view your wares. You must include links to what you sell or a portfolio otherwise you will be automatically waitlisted.")
    categories = SelectMultipleField('Categories', validators=[
        validators.InputRequired("Please select at least one category your wares fall under.")
        ], choices=c.DEALER_WARES_OPTS, coerce=int, widget=MultiCheckbox())
    categories_text = StringField('Other')
    special_needs = TextAreaField('Special Needs', description="No guarantees that we can accommodate any requests.")

    def badges_label(self):
        return "Badges (" + format_currency(c.DEALER_BADGE_PRICE) + " each)"

    def tables_desc(self):
        return table_prices()
    
    def get_optional_fields(self, group):
        if not group.is_dealer:
            return ['description', 'website', 'wares', 'categories',
                    'address1', 'city', 'region', 'zip_code', 'country']
        return []