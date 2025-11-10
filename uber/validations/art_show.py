import re
from wtforms import validators
from wtforms.validators import ValidationError, StopValidation

from uber.config import c
from uber.forms.art_show import (ArtShowInfo, AdminArtShowInfo, ArtistAttendeeInfo, AdminArtistAttendeeInfo,
                                 ArtistMailingInfo, ArtShowPieceInfo, ArtistCheckOutInfo, ArtistCheckInInfo,
                                 PieceCheckInOut, BidderAttendeeInfo, AdminBidderSignup)
from uber.model_checks import validation
from uber.utils import localized_now
from uber.validations import address_required_validators, valid_zip_code, which_required_region


ArtShowInfo.field_validation.required_fields = {
    'delivery_method': "Please tell us how your art will get to the Art Show.",
    'us_only': ("Please confirm your address is within the continental US.",
                'delivery_method',
                lambda x: x == c.BY_MAIL and c.BY_MAIL_US_ONLY),
    'payout_method': ("Please select your preferred payout method.", 'payout_method',
                      lambda x: len(c.ARTIST_PAYOUT_METHOD_OPTS) > 2 or x.form.is_admin),
    'banner_name_ad': ("Please enter the banner name you want displayed in the Mature gallery.",
                       'separate_ad_banner'),
    'description': "Please provide a description of your art.",
    'website': "Please provide a website URL showcasing your art, or enter 'N/A'.",
    'contact_at_con': "Please tell us the best way to get a hold of you at the event, e.g., your mobile number or your hotel and room number.",
}


ArtShowInfo.field_validation.validations['payout_method']['optional'] = validators.Optional()


@ArtShowInfo.new_or_changed('delivery_method')
def cant_ghost_art_show(form, field):
    if c.INDEPENDENT_ART_SHOW:
        return
    if field.data == c.BRINGING_IN and form.not_attending.data:
        raise ValidationError('You cannot bring your own art if you are not attending.')


@ArtShowInfo.new_or_changed('panels')
def num_panels(form, field):
    if field.data > c.MAX_ART_PANELS:
        raise ValidationError(f'You cannot have more than {c.MAX_ART_PANELS} panels.')
    if field.data < 0:
        raise ValidationError('You cannot have fewer than 0 panels.')


@ArtShowInfo.new_or_changed('panels_ad')
def num_panels_ad(form, field):
    if field.data > c.MAX_ART_PANELS:
        raise ValidationError(f'You cannot have more than {c.MAX_ART_PANELS} panels.')
    if field.data < 0:
        raise ValidationError('You cannot have fewer than 0 panels.')


@ArtShowInfo.new_or_changed('tables')
def num_tables(form, field):
    if field.data > c.MAX_ART_TABLES:
        raise ValidationError(f'You cannot have more than {c.MAX_ART_TABLES} table sections.')
    if field.data < 0:
        raise ValidationError('You cannot have fewer than 0 table sections.')


@ArtShowInfo.new_or_changed('tables')
def num_tables_ad(form, field):
    if field.data > c.MAX_ART_TABLES:
        raise ValidationError(f'You cannot have more than {c.MAX_ART_TABLES} table sections.')
    if field.data < 0:
        raise ValidationError('You cannot have fewer than 0 table sections.')


@AdminArtShowInfo.field_validation('overridden_price')
def is_unset_or_number(form, field):
    if not field.data:
        return
    
    try:
        price = int(field.data)
    except ValueError:
        raise ValidationError("Application fee must be a number, or left blank.")
    if price < 0:
        raise ValidationError("Application fee must be a number that is 0 or higher, or left blank.")


ArtistAttendeeInfo.field_validation.required_fields = {
    'first_name': "Please provide your first name.",
    'last_name': "Please provide your last name.",
    'email': "Please enter an email address."
}


for field_name, message in address_required_validators.items():
    AdminArtistAttendeeInfo.field_validation.required_fields[field_name] = (
        message, field_name, lambda x: x.form.model.badge_status != c.NOT_ATTENDING)


for field_name in ['region', 'region_us', 'region_canada']:
    AdminArtistAttendeeInfo.field_validation.validations[field_name][f'required_{field_name}'] = which_required_region(
        field_name, check_placeholder=True)


ArtistMailingInfo.field_validation.required_fields['business_name'] = "Please enter a name or business name for your address."


for field_name, message in address_required_validators.items():
    ArtistMailingInfo.field_validation.required_fields[field_name] = (message, 'copy_address', lambda x: not x or not x.data)


for field_name in ['region', 'region_us', 'region_canada']:
    ArtistMailingInfo.field_validation.validations[field_name][f'required_{field_name}'] = which_required_region(field_name)


ArtistMailingInfo.field_validation.validations['zip_code']['valid'] = valid_zip_code


ArtShowPieceInfo.field_validation.required_fields = {
    'name': "Please enter a title for this piece.",
    'opening_bid': ("Please enter an opening bid for this piece.", 'for_sale', lambda x: x and x != 0),
    'gallery': "Please select a gallery for this piece.",
    'type': "Please select whether this piece is an original or a print.",
    'media': ("Please describe what medium your original art is on.", 'type', lambda x: x and x == c.ORIGINAL),
    'print_run_num': ("Please enter this piece's print edition number.", 'type', lambda x: x and x == c.PRINT),
    'print_run_total': ("Please enter the total number of prints for this piece's print run.", 'type', lambda x: x and x == c.PRINT),
}


ArtShowPieceInfo.field_validation.validations['for_sale']['required'] = validators.InputRequired(
    "Please select whether or not this piece is for sale.")


ArtShowPieceInfo.field_validation.validations['name']['length'] = validators.Length(
    max=c.MAX_PIECE_NAME_LENGTH, message=f"Piece names must be {c.MAX_PIECE_NAME_LENGTH} characters or fewer.")


@ArtShowPieceInfo.field_validation('quick_sale_price')
def required_if_for_sale_not_qs_disabled(form, field):
    if not field.data and form.for_sale.data and not form.no_quick_sale.data:
        raise StopValidation(f"Please enter a {c.QS_PRICE_TERM} for this piece.")
    

@ArtShowPieceInfo.field_validation('opening_bid')
def blank_or_minimum(form, field):
    if not field.data:
        return
    
    if field.data < 1:
        raise ValidationError(f"Opening bid must be at least $1.")


@ArtShowPieceInfo.field_validation('quick_sale_price')
def blank_or_minimum(form, field):
    if not field.data:
        return
    
    if field.data < 1:
        raise ValidationError(f"{c.QS_PRICE_TERM} must be at least $1.")


ArtShowPieceInfo.field_validation.validations['media']['length'] = validators.Length(
    max=15, message=f"The description of this piece's media must be 15 characters or fewer.")


@ArtShowPieceInfo.field_validation('print_run_num')
def blank_or_minimum(form, field):
    if not field.data:
        return

    if field.data < 0:
        raise ValidationError("Print edition must be a number that is 1 or higher.")


@ArtShowPieceInfo.field_validation('print_run_total')
def blank_or_minimum_maximum(form, field):
    if not field.data:
        return

    if field.data < 0:
        raise ValidationError("Print run total must be a number that is 1 or higher.")
    elif field.data > 1000:
        raise ValidationError("Print run total cannot be higher than 1000.")


@ArtShowPieceInfo.field_validation('print_run_num')
def lower_than_run(form, field):
    if not field.data or not form.print_run_total.data:
        return

    if field.data > form.print_run_total.data:
        raise ValidationError(f"Print edition cannot be a higher number than print run total.")


ArtistCheckOutInfo.field_validation.required_fields = {
    'artist_id': "Please enter a valid artist ID.",
    'artist_id_ad': ("Please enter a valid mature artist ID.", 'artist_id_ad',
                     lambda x: x.form.model.banner_name_ad and x.form.model.has_mature_space),
    'payout_method': "Please select a preferred payout method.",
}


ArtistCheckInInfo.field_validation.required_fields = {
    'artist_id_ad': ("Please enter a valid mature artist ID.", 'artist_id_ad',
                     lambda x: x.form.banner_name_ad and x.form.banner_name_ad.data and x.form.model.has_mature_space),
    'delivery_method': "Please select a delivery method.",
}


PieceCheckInOut.field_validation.required_fields = {
    'status': "Please select a status for this piece.",
    'name': "Please enter a title for this piece.",
    'gallery': "Please select a gallery for this piece.",
}


BidderAttendeeInfo.field_validation.required_fields = {
    'badge_num': "Please enter your badge number.",
    'first_name': "Please provide your first name.",
    'last_name': "Please provide your last name.",
    'email': "Please provide your email address.",
    'cellphone': "Please enter a phone number.",
}


if not c.INDEPENDENT_ART_SHOW:
    for field_name, message in address_required_validators.items():
        BidderAttendeeInfo.field_validation.required_fields[field_name] = message

    for field_name in ['region', 'region_us', 'region_canada']:
        BidderAttendeeInfo.field_validation.validations[field_name][f'required_{field_name}'] = which_required_region(field_name)


AdminBidderSignup.field_validation.required_fields = {
    'bidder_num': "Please enter a bidder number.",
}


@AdminBidderSignup.field_validation('bidder_num')
def bidder_num_formatting(form, field):
    if field.data and not re.match("^[a-zA-Z]-[0-9]+", field.data):
        raise ValidationError("Bidder numbers must be in the format X-000 (e.g., A-100).")
