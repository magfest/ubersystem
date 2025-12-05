from markupsafe import Markup
from wtforms import (BooleanField, IntegerField, EmailField, HiddenField, SelectField,
                     StringField, validators, TextAreaField)
from wtforms.validators import ValidationError, StopValidation
from wtforms.widgets import TextInput

from uber.config import c
from uber.forms import (BlankOrIntegerField, MagForm, HiddenBoolField, IntSelect, AddressForm, NumberInputGroup,
                        SelectDynamicChoices, SelectButtonGroup)
from uber.forms.attendee import PersonalInfo, AdminBadgeFlags
from uber.custom_tags import email_only, email_to_link, format_currency


__all__ = ['ArtShowInfo', 'AdminArtShowInfo', 'ArtistAttendeeInfo', 'AdminArtistAttendeeInfo',
           'ArtistMailingInfo', 'ArtShowPieceInfo', 'ArtistCheckOutInfo', 'ArtistCheckInInfo', 'PieceCheckInOut']


class ArtShowInfo(MagForm):
    not_attending = HiddenBoolField()
    artist_name = StringField('Artist Name',
                              description=f"The name you want to use on your {c.ART_SHOW_APP_TERM}, if different from your first and last name.")
    delivery_method = SelectField('Art Delivery', default=0,
                                  coerce=int, choices=[(0, 'Please select an option')] + c.ART_SHOW_DELIVERY_OPTS)
    us_only = BooleanField('I verify that my mailing address will be in the continental US.')
    
    banner_name = StringField('Banner Name',
                              description=f"The name you want to display with your artwork, if different from your artist name.")
    separate_ad_banner = BooleanField('I want a different banner name for my pieces in the mature gallery.')
    banner_name_ad = StringField('Mature Banner Name')
    payout_method = SelectField('Preferred Payout Method', coerce=int, choices=[(0, 'Please select an option')] + c.ARTIST_PAYOUT_METHOD_OPTS)
    check_payable = StringField('Name on Check/Bank Account',
                                description="The name to use for payment, if different from your first and last name.")
    panels = IntegerField('General Panels', widget=IntSelect(),
                          description=(f"({format_currency(c.COST_PER_PANEL)} per panel)") if c.COST_PER_PANEL else "")
    tables = IntegerField('General Table Sections', widget=IntSelect(),
                          description=(f"({format_currency(c.COST_PER_TABLE)} per table section)") if c.COST_PER_TABLE else "")
    panels_ad = IntegerField('Mature Panels', widget=IntSelect(),
                             description=(f"({format_currency(c.COST_PER_PANEL)} per panel)") if c.COST_PER_PANEL else "")
    tables_ad = IntegerField('Mature Table Sections', widget=IntSelect(),
                             description=(f"({format_currency(c.COST_PER_TABLE)} per table section)") if c.COST_PER_TABLE else "")
    description = TextAreaField('Description', description="A short description of your artwork.")
    website = StringField(
        'Website',
        description=Markup(f"If you do not have a website showing your work, please enter 'N/A' and contact {email_to_link(email_only(c.ART_SHOW_EMAIL))} after submitting your {c.ART_SHOW_APP_TERM}."))
    contact_at_con = TextAreaField('How should we contact you at-con?',
                                   description="Please tell us the best way to get a hold of you during the event.")
    special_needs = TextAreaField('Special Requests',
                                  description="We cannot guarantee that we will accommodate all requests.")
    
    def get_non_admin_locked_fields(self, app):
        if app.status != c.UNAPPROVED:
            return ['artist_name', 'panels', 'panels_ad', 'tables', 'tables_ad', 'description',
                    'website', 'special_needs', 'delivery_method']
        return []


class AdminArtShowInfo(ArtShowInfo):
    attendee_id = SelectField("Attendee", widget=SelectDynamicChoices(), validate_choice=False)
    badge_status = AdminBadgeFlags.badge_status
    email = StringField("Attendee Email", render_kw={'readonly': "true"})
    status = SelectField(f"{c.ART_SHOW_APP_TERM.title()} Status", coerce=int, choices=c.ART_SHOW_STATUS_OPTS)
    decline_reason = StringField("Decline Reason")
    locations = StringField("Locations", render_kw={'placeholder': "Space assignments for this artist."})
    artist_id = StringField("Artist ID")
    artist_id_ad = StringField("Mature Artist ID")
    overridden_price = StringField('Custom Fee', widget=NumberInputGroup())
    check_in_notes = TextAreaField("Check-In Notes")
    admin_notes = TextAreaField("Admin Notes")

    def badge_status_label(self):
        return "Attendee Badge Status"
    
    def panels_label(self):
        return Markup(f'General Panels <a href="../art_show_admin/assignment_map?gallery={c.GENERAL}&surface_type={c.PANEL}" target="_blank">Map <i class="fa fa-external-link"></i></a>')
    
    def tables_label(self):
        return Markup(f'General Table Sections <a href="../art_show_admin/assignment_map?gallery={c.GENERAL}&surface_type={c.TABLE}" target="_blank">Map <i class="fa fa-external-link"></i></a>')
    
    def panels_ad_label(self):
        return Markup(f'Mature Panels <a href="../art_show_admin/assignment_map?gallery={c.MATURE}&surface_type={c.PANEL}" target="_blank">Map <i class="fa fa-external-link"></i></a>')
    
    def tables_ad_label(self):
        return Markup(f'Mature Table Sections <a href="../art_show_admin/assignment_map?gallery={c.MATURE}&surface_type={c.TABLE}" target="_blank">Map <i class="fa fa-external-link"></i></a>')


class ArtistAttendeeInfo(MagForm):
    first_name = PersonalInfo.first_name
    last_name = PersonalInfo.last_name
    legal_name = PersonalInfo.legal_name
    email = PersonalInfo.email
    not_attending = BooleanField(f"I don't plan on attending {c.EVENT_NAME}.")


class AdminArtistAttendeeInfo(ArtistAttendeeInfo, AddressForm):
    pass


class ArtistMailingInfo(AddressForm):
    business_name = StringField('Mailing Business Name')
    copy_address = BooleanField('Use my personal address for my mailing address.', default=False)


class ArtShowPieceInfo(MagForm):
    name = StringField("Piece Name", render_kw={'placeholder': "The title of this piece."})
    for_sale = SelectField("Is This Piece For Sale?", coerce=int,
                           default='', choices=[(1, 'Yes'),(0, 'No')], widget=SelectButtonGroup())
    opening_bid = BlankOrIntegerField("Opening Bid", default='', widget=NumberInputGroup())
    quick_sale_price = BlankOrIntegerField(c.QS_PRICE_TERM.title(), default='', widget=NumberInputGroup())
    no_quick_sale = BooleanField("I don't want my piece to be for sale after bidding ends.")
    gallery = SelectField("Gallery", coerce=int, default='',
                          choices=c.ART_PIECE_GALLERY_OPTS, widget=SelectButtonGroup())
    type = SelectField("Piece Type", coerce=int, default='',
                          choices=c.ART_PIECE_TYPE_OPTS, widget=SelectButtonGroup())
    media = StringField("Original Media")
    print_run_num = BlankOrIntegerField("Print Edition", default='', render_kw={'placeholder': "X"})
    print_run_total = BlankOrIntegerField("Print Run Total", default='', render_kw={'placeholder': "Y"})


class ArtistCheckOutInfo(MagForm):
    artist_name = AdminArtShowInfo.artist_name
    artist_id = AdminArtShowInfo.artist_id
    artist_id_ad = AdminArtShowInfo.artist_id_ad
    payout_method = AdminArtShowInfo.payout_method
    check_payable = AdminArtShowInfo.check_payable


class ArtistCheckInInfo(ArtistCheckOutInfo):
    locations = AdminArtShowInfo.locations
    banner_name = AdminArtShowInfo.banner_name
    banner_name_ad = AdminArtShowInfo.banner_name_ad
    delivery_method = AdminArtShowInfo.delivery_method
    check_in_notes = AdminArtShowInfo.check_in_notes
    panels = AdminArtShowInfo.panels
    panels_ad = AdminArtShowInfo.panels_ad
    tables = AdminArtShowInfo.tables
    tables_ad = AdminArtShowInfo.tables_ad

    def panels_label(self):
        return Markup(f'General Panels <a href="../art_show_admin/assignment_map?gallery={c.GENERAL}&surface_type={c.PANEL}" target="_blank">Map <i class="fa fa-external-link"></i></a>')
    
    def tables_label(self):
        return Markup(f'General Table Sections <a href="../art_show_admin/assignment_map?gallery={c.GENERAL}&surface_type={c.TABLE}" target="_blank">Map <i class="fa fa-external-link"></i></a>')
    
    def panels_ad_label(self):
        return Markup(f'Mature Panels <a href="../art_show_admin/assignment_map?gallery={c.MATURE}&surface_type={c.PANEL}" target="_blank">Map <i class="fa fa-external-link"></i></a>')
    
    def tables_ad_label(self):
        return Markup(f'Mature Table Sections <a href="../art_show_admin/assignment_map?gallery={c.MATURE}&surface_type={c.TABLE}" target="_blank">Map <i class="fa fa-external-link"></i></a>')


class PieceCheckInOut(MagForm):
    status = SelectField("Status", coerce=int, choices=c.ART_PIECE_STATUS_OPTS)
    gallery = ArtShowPieceInfo.gallery
    name = ArtShowPieceInfo.name
    for_sale = HiddenField()
    no_quick_sale = ArtShowPieceInfo.no_quick_sale
    opening_bid = StringField("Opening Bid", default='', render_kw={'placeholder': "N/A"})
    quick_sale_price = StringField(c.QS_PRICE_TERM.title(), default='', render_kw={'placeholder': "N/A"})


class BidderAttendeeInfo(AddressForm):
    badge_num = IntegerField('Badge Number', default='')
    first_name = PersonalInfo.first_name
    last_name = PersonalInfo.last_name
    legal_name = PersonalInfo.legal_name
    email = PersonalInfo.email
    cellphone = PersonalInfo.cellphone


class BidderSignup(MagForm):
    contact_type = SelectField('Best Way to Contact?', coerce=int,
                               choices=c.ART_SHOW_CONTACT_TYPE_OPTS, widget=SelectButtonGroup())
    email_won_bids = BooleanField('Yes, please email me about pieces I won in the art show.')


class AdminBidderSignup(BidderSignup):
    bidder_num = StringField('Bidder Number', default='')
    admin_notes = TextAreaField('Notes')
