from wtforms import (BooleanField, IntegerField, EmailField, HiddenField, SelectField,
                     StringField, validators, TextAreaField)
from wtforms.validators import ValidationError, StopValidation

from uber.config import c
from uber.forms import (MagForm, CustomValidation, NumberInputGroup)
from uber.custom_tags import readable_join


__all__ = ['ArtistMarketplaceForm', 'AdminArtistMarketplaceForm']


class ArtistMarketplaceForm(MagForm):
    attendee_id = HiddenField('Confirmation ID')
    name = StringField('Business Name')
    display_name = StringField('Display Name', description="The name to display for your table, if different from your business name.")
    email_address = EmailField('Email Address', render_kw={'placeholder': 'test@example.com'})
    website = StringField('Gallery Link')
    tax_number = StringField('Illinois Business Tax Number',
                             description="""
                             If you have an Illinois Business license please provide the number here. Note that this 
                             number is in the format 1234-5678; it is not your Federal Tax ID or any other Tax ID number 
                             you may have.""", render_kw={'pattern': "[0-9]{4}-[0-9]{4}", 'title': "1234-5678"})
    seating_requests = TextAreaField('Seating Requests', description="Let us know where you would like to be sat in the marketplace, e.g., seated next to someone specific.")
    accessibility_requests = TextAreaField('Accessibility Requests', description="Let us know any accessibility needs, e.g., if you need space for a wheelchair.")
    terms_accepted = BooleanField(
        f'I have read the Artist Marketplace rules and understand the requirements, including the ${c.ARTIST_MARKETPLACE_FEE} fee for the marketplace.',
        default=False)
    
    copy_email = BooleanField('Use my registration email for my marketplace application email.', default=False)


class AdminArtistMarketplaceForm(ArtistMarketplaceForm):
    field_validation = CustomValidation()

    attendee_id = HiddenField('Attendee ID')
    status = SelectField('Entry Status', coerce=int, choices=c.MARKETPLACE_STATUS_OPTS)
    overridden_price = StringField('Application Fee',
                                   widget=NumberInputGroup(), render_kw={'placeholder': c.ARTIST_MARKETPLACE_FEE})
    admin_notes = TextAreaField('Admin Notes')
