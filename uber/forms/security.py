import cherrypy

from markupsafe import Markup
from wtforms import (BooleanField, DateField, DateTimeField, EmailField,
                     HiddenField, SelectField, SelectMultipleField, IntegerField,
                     StringField, TelField, validators, TextAreaField)
from uber.forms import MagForm


__all__ = ['WatchListEntry']


class WatchListEntry(MagForm):
    first_names = StringField('First Names', render_kw={'placeholder': 'Use commas to separate possible first names.'})
    last_name = StringField('Last Name')
    email = EmailField('Email Address', render_kw={'placeholder': 'test@example.com'})
    birthdate = DateField('Date of Birth')
    reason = TextAreaField('Reason')
    action = TextAreaField('Action')
    expiration = DateField('Expiration Date')
    active = BooleanField('Automatically place matching attendees in the On Hold status.')
