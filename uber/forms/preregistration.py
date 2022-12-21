from wtforms import Form, BooleanField, DateField, EmailField, StringField, SelectField, validators
from uber.forms import MagForm

class PersonalData(MagForm):
    first_name = StringField('First Name')
    last_name = StringField('Last Name')
    legal_name = StringField('Legal Name')
    email = EmailField('Email Address')
    birthdate = DateField('Date of Birth', format='%m/%d/%y')
    age_group = SelectField('Age Group')
    international = BooleanField('International')
    zip_code = StringField('Zip code')
    address1 = StringField('Address 1')
    address2 = StringField('Address 2')
    city = StringField('City')
    region = StringField('Region')
    country = StringField('Country')
    ec_name = StringField('Emergency Contact')
    ec_phone = StringField('Emergency Contact Phone #')
    onsite_contact = StringField('Onsite Contact')
    no_onsite_contact = BooleanField('No Onsite Contact')
    cellphone = StringField('Cellphone')
    no_cellphone = BooleanField('No Cellphone')