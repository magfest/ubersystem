"""
When an admin submits a form to create/edit an attendee/group/job/etc we usually want to perform some basic validations
on the data that was entered.  We put those validations here.  To make a validation for the Attendee model, you can
just write a function decorated with the @validation.Attendee decorator.  That function should return None on success
and an error string on failure.

In addition, you can define a set of required fields by setting the .required field like the AdminAccount.required list
below.  This should be a list of tuples where the first tuple element is the name of the field, and the second is the
name that should be displayed in the "XXX is a required field" error message.

To perform these validations, call the "check" method on the instance you're validating.  That method returns None
on success and a string error message on validation failure.
"""
import re
from datetime import datetime, timedelta
from functools import wraps
from urllib.request import urlopen

import cherrypy
import phonenumbers
from pockets.autolog import log
from pockets import sluggify
from sqlalchemy import and_, func, or_

from uber.badge_funcs import get_real_badge_type
from uber.config import c
from uber.custom_tags import format_currency, full_date_local
from uber.decorators import prereg_validation, validation
from uber.models import (AccessGroup, AdminAccount, ApiToken, Attendee, ArtShowApplication, ArtShowPiece,
                         AttendeeTournament, Attraction, AttractionFeature, ArtShowBidder, DeptRole, Event,
                         GuestDetailedTravelPlan, IndieDeveloper, IndieGame, IndieGameCode, IndieJudge, IndieStudio,
                         Job, ArtistMarketplaceApplication, MITSApplicant, MITSDocument, MITSGame, MITSPicture, MITSTeam,
                         PromoCode, PromoCodeGroup, Sale, Session, WatchList)
from uber.utils import localized_now, valid_email, get_age_from_birthday
from uber.payments import PreregCart


AccessGroup.required = [('name', 'Name')]


def _invalid_phone_number(s):
    try:
        # parse input as a US number, unless a leading + is provided,
        # in which case the input will be validated according to the country code
        parsed = phonenumbers.parse(s, 'US')
    except phonenumbers.phonenumberutil.NumberParseException:
        # could not be parsed due to unexpected characters
        return True

    if not phonenumbers.is_possible_number(parsed):
        # could not be a phone number due to length, invalid characters, etc
        return True
    elif parsed.country_code == 1 and phonenumbers.length_of_national_destination_code(parsed) == 0:
        # US number does not contain area code
        return True

    return False


def _invalid_zip_code(s):
    return len(re.findall(r'\d', s)) not in [5, 9]


@validation.AccessGroup
def has_any_access(group):
    if not group.access and not group.read_only_access:
        return 'You must give this access group some sort of access'


@validation.AccessGroup
def read_only_makes_sense(group):
    for access in group.read_only_access:
        if access in group.access and int(group.read_only_access[access]) < int(group.access[access]):
            return 'You cannot set a read-only access level lower than the read-write access'


@validation.AdminAccount
def duplicate_admin(account):
    if account.is_new:
        with Session() as session:
            if session.query(AdminAccount).filter_by(attendee_id=account.attendee_id).all():
                return 'That attendee already has an admin account'


@validation.AdminAccount
def has_email_address(account):
    if account.is_new:
        with Session() as session:
            if session.query(Attendee).filter_by(id=account.attendee_id).first().email == '':
                return "Attendee doesn't have a valid email set"


ApiToken.required = [('name', 'Name'), ('description', 'Intended Usage'), ('access', 'Access Controls')]


@validation.ApiToken
def admin_has_required_api_access(api_token):
    admin_account_id = cherrypy.session.get('account_id')
    if api_token.is_new and admin_account_id != api_token.admin_account_id:
        return 'You may not create an API token for another user'

    with Session() as session:
        admin_account = session.current_admin_account()
        for access_level in set(api_token.access_ints):
            access_name = 'api_' + c.API_ACCESS[access_level].lower()
            if not getattr(admin_account, access_name, None):
                return 'You do not have permission to create a token with {} access'.format(c.API_ACCESS[access_level])


def invalid_phone_number(s):
    try:
        # parse input as a US number, unless a leading + is provided,
        # in which case the input will be validated according to the country code
        parsed = phonenumbers.parse(s, 'US')
    except phonenumbers.phonenumberutil.NumberParseException:
        # could not be parsed due to unexpected characters
        return True

    if not phonenumbers.is_possible_number(parsed):
        # could not be a phone number due to length, invalid characters, etc
        return True
    elif parsed.country_code == 1 and phonenumbers.length_of_national_destination_code(parsed) == 0:
        # US number does not contain area code
        return True

    return False


def invalid_zip_code(s):
    return len(re.findall(r'\d', s)) not in [5, 9]


def ignore_unassigned_and_placeholders(func):
    @wraps(func)
    def with_skipping(attendee):
        unassigned_group_reg = attendee.group_id and not attendee.first_name and not attendee.last_name
        valid_placeholder = attendee.placeholder and attendee.first_name and attendee.last_name
        if not unassigned_group_reg and not valid_placeholder:
            return func(attendee)
    return with_skipping


@validation.WatchList
def include_a_name(entry):
    if not entry.first_names and not entry.last_name:
        return ('', 'A first or last name is required.')


@validation.WatchList
def include_other_details(entry):
    if not entry.birthdate and not entry.email:
        return ('', 'Email or date of birth is required.')


@validation.WatchList
def not_active_after_expiration(entry):
    if entry.active and entry.expiration and localized_now().date() > entry.expiration:
        return ('expiration', 'An entry cannot be active with an expiration date in the past.')


@validation.MPointsForCash
@validation.OldMPointExchange
def money_amount(model):
    if not str(model.amount).isdigit():
        return 'Amount must be a positive number'


Job.required = [
    ('name', 'Job Name'),
    ('description', 'Job Description'),
    ('start_time', 'Start Time'),
    ('duration', 'Hours and/or Minutes')
]


@validation.Job
def slots(job):
    if job.slots < len(job.shifts):
        return 'You cannot reduce the number of slots to below the number of staffers currently signed up for this job'


@validation.Job
def time_conflicts(job):
    if not job.is_new:
        original_minutes = Job(start_time=job.orig_value_of('start_time'),
                               duration=job.orig_value_of('duration')).minutes
        for shift in job.shifts:
            if job.minutes.intersection(shift.attendee.shift_minutes - original_minutes):
                return 'You cannot change this job to this time, because {} is already working a shift then'.format(
                    shift.attendee.full_name)


@validation.Job
def no_negative_hours(job):
    if job.duration < 0:
        return 'You cannot create a job with negative hours.'


DeptRole.required = [('name', 'Name')]


@validation.DeptChecklistItem
def is_checklist_admin(dept_checklist_item):
    with Session() as session:
        attendee = session.admin_attendee()
        department_id = dept_checklist_item.department_id or dept_checklist_item.department.id
        if not attendee.can_admin_checklist_for(department_id):
            return 'Only checklist admins can complete checklist items'


@validation.OldMPointExchange
def oldmpointexchange_numbers(mpe):
    if not str(mpe.amount).isdigit():
        return 'MPoints must be a positive integer'


Sale.required = [
    ('what', "What's being sold")
]


@validation.Sale
def cash_and_mpoints(sale):
    if not str(sale.cash).isdigit() or int(sale.cash) < 0:
        return 'Cash must be a positive integer'
    if not str(sale.mpoints).isdigit() or int(sale.mpoints) < 0:
        return 'MPoints must be a positive integer'


PromoCode.required = [
    ('expiration_date', 'Expiration date')
]


@validation.PromoCode
def valid_discount(promo_code):
    if promo_code.discount:
        try:
            promo_code.discount = int(promo_code.discount)
            if promo_code.discount < 0:
                return 'You cannot give out promo codes that increase badge prices.'
        except Exception:
            return "What you entered for the discount isn't even a number."


@validation.PromoCode
def valid_uses_allowed(promo_code):
    if promo_code.uses_allowed:
        try:
            promo_code.uses_allowed = int(promo_code.uses_allowed)
            if promo_code.uses_allowed < 0 or promo_code.uses_allowed < promo_code.uses_count:
                return 'Promo codes must have at least 0 uses remaining.'
        except Exception:
            return "What you entered for the number of uses allowed isn't even a number."


@validation.PromoCode
def no_unlimited_free_badges(promo_code):
    if promo_code.is_new \
            or promo_code.uses_allowed != promo_code.orig_value_of('uses_allowed') \
            or promo_code.discount != promo_code.orig_value_of('discount') \
            or promo_code.discount_type != promo_code.orig_value_of('discount_type'):
        if promo_code.is_unlimited and promo_code.is_free:
            return 'Unlimited-use, free-badge promo codes are not allowed.'


@validation.PromoCode
def no_dupe_code(promo_code):
    if promo_code.code and (promo_code.is_new or promo_code.code != promo_code.orig_value_of('code')):
        with Session() as session:
            if session.lookup_promo_code(promo_code.code):
                return 'The code you entered already belongs to another ' \
                    'promo code. Note that promo codes are not case sensitive.'


PromoCodeGroup.required = [
    ('name', 'Name')
]

# =============================
# tournaments
# =============================

AttendeeTournament.required = [
    ('first_name', 'First Name'),
    ('last_name', 'Last Name'),
    ('email', 'Email Address'),
    ('game', 'Game Title'),
    ('availability', 'Your Availability'),
    ('format', 'Tournament Format'),
    ('experience', 'Past Experience'),
    ('needs', 'Your Needs'),
    ('why', '"Why?"'),
]


@validation.AttendeeTournament
def attendee_tournament_email(app):
    if not re.match(c.EMAIL_RE, app.email):
        return 'You did not enter a valid email address'


@validation.AttendeeTournament
def attendee_tournament_cellphone(app):
    if app.cellphone and invalid_phone_number(app.cellphone):
        return 'You did not enter a valid cellphone number'


@validation.LotteryApplication
def room_meets_night_requirements(app):
    if app.any_dates_different and (app.entry_type == c.ROOM_ENTRY or 
            app.entry_type == c.SUITE_ENTRY and not app.room_opt_out) and app.earliest_checkin_date and app.latest_checkout_date:
        latest_checkin, earliest_checkout = app.shortest_check_in_out_dates
        nights = app.build_nights_map(latest_checkin, earliest_checkout)
        if not nights:
            # Suppress this error since other validations will tell them their dates are bad
            return
        if len(nights) > 2:
            for night in nights:
                if 'Friday' in night or 'Saturday' in night:
                    return
        return ('', "Standard rooms require a two-night minimum with at least one night on Friday or Saturday.")


@validation.LotteryApplication
def suite_meets_night_requirements(app):
    if app.any_dates_different and app.entry_type == c.SUITE_ENTRY and app.earliest_checkin_date and app.latest_checkout_date:
        latest_checkin, earliest_checkout = app.shortest_check_in_out_dates
        nights = app.build_nights_map(latest_checkin, earliest_checkout)
        night_counter = 0
        if len(nights) > 3:
            for night in nights:
                if 'Friday' in night or 'Saturday' in night:
                    night_counter += 1
                if night_counter == 2:
                    return
        return ('', "Suites require a three-night minimum with both Friday night and Saturday night.")


# =============================
# mivs
# =============================


def _is_invalid_url(url):
    if c.MIVS_SKIP_URL_VALIDATION:
        return False

    try:
        log.debug("_is_invalid_url() is fetching '%s' to check if it's reachable." % url)
        with urlopen(url, timeout=30) as f:
            f.read()
    except Exception:
        return True


@validation.IndieStudio
def showcase_new_studio_deadline(studio):
    if studio.is_new and not c.INDIE_SHOWCASE_OPEN:
        return 'Sorry, but the deadline has already passed, so no new studios may be registered.'


@validation.IndieStudio
def showcase_valid_url(studio):
    if studio.website and _is_invalid_url(studio.website_href):
        return 'We cannot contact that website; please enter a valid url ' \
            'or leave the website field blank until your website goes online.'


@validation.IndieStudio
def showcase_unique_name(studio):
    with Session() as session:
        if session.query(IndieStudio).filter(IndieStudio.name == studio.name, IndieStudio.id != studio.id).count():
            return "That studio name is already taken."


@validation.IndieStudio
def showcase_studio_contact_phone(studio):
    if studio.contact_phone and invalid_phone_number(studio.contact_phone):
        return 'Please enter a valid phone number.'


@validation.IndieGame
def mivs_new_game_deadline(game):
    with Session() as session:
        if session.current_admin_account():
            return

    if game.is_new and game.showcase_type == c.MIVS and not c.MIVS_SUBMISSIONS_OPEN:
        return 'Sorry, but the deadline has already passed, so no new MIVS games may be registered.'


@validation.IndieGame
def arcade_new_game_deadline(game):
    with Session() as session:
        if session.current_admin_account():
            return

    if game.is_new and game.showcase_type == c.INDIE_ARCADE and not c.INDIE_ARCADE_SUBMISSIONS_OPEN:
        return 'Sorry, but the deadline has already passed, so no new Indie Arcade games may be registered.'


@validation.IndieGame
def retro_new_game_deadline(game):
    with Session() as session:
        if session.current_admin_account():
            return

    if game.is_new and game.showcase_type == c.INDIE_RETRO and not c.INDIE_RETRO_SUBMISSIONS_OPEN:
        return 'Sorry, but the deadline has already passed, so no new Indie Retro games may be registered.'


@validation.IndieGame
def mivs_video_link(game):
    if game.link_to_video and _is_invalid_url(game.video_href):
        return 'The link you provided for the intro/instructional video does not appear to work'


@validation.IndieGame
def mivs_show_info_required_fields(game):
    if game.confirmed:
        if len(game.brief_description) > 80:
            return 'Please make sure your game has a brief description under 80 characters.'
        if not game.link_to_promo_video:
            return 'Please include a link to a 30-second promo video.'
        if game.has_multiplayer and not game.player_count:
            return 'Please tell us how many players your game supports.'
        if game.has_multiplayer and not game.multiplayer_game_length:
            return 'Please enter the average length for a multiplayer game or match.'


# =============================
# mits
# =============================

MITSTeam.required = [
    ('name', 'Production Team Name')
]


MITSApplicant.required = [
    ('first_name', 'First Name'),
    ('last_name', 'Last Name'),
    ('email', 'Email Address'),
    ('cellphone', 'Cellphone Number')
]


MITSGame.required = [
    ('name', 'Name'),
    ('description', 'Description')
]


MITSDocument.required = [
    ('description', 'Description')
]


@validation.MITSTeam
@validation.MITSApplicant
@validation.MITSGame
@validation.MITSPicture
@validation.MITSTimes
def is_saveable(inst):
    team = inst if isinstance(inst, MITSTeam) else inst.team
    if not team.can_save:
        if team.is_new:
            return 'New applications may not be submitted past the deadline'
        else:
            return 'We are now past the deadline and your application may no longer be edited'


@validation.MITSTeam
def address_required_for_sellers(team):
    if team.want_to_sell and not team.address.strip():
        return 'You must provide a business address if you wish to sell your merchandise'


@validation.MITSTeam
def min_num_days_hours(team):
    if team.days_available is not None and team.days_available < 3:
        return 'You must be available at least 3 days to present at MITS.'
    if team.hours_available is not None and team.hours_available < 8:
        return 'You must be able to show at least 8 hours per day to present at MITS.'


@validation.MITSTeam
def min_concurrent_attendees(team):
    if team.days_available and not team.concurrent_attendees:
        return 'Please enter the number of attendees you can show to at a time.'


@validation.MITSGame
def must_select_copyright(game):
    if not game.copyrighted:
        return 'Please tell us if your game contains copyrighted materials.'


@validation.MITSApplicant
def mits_applicant_email_valid(applicant):
    return valid_email(applicant.email)


@validation.MITSApplicant
def valid_phone_number(applicant):
    if invalid_phone_number(applicant.cellphone):
        return 'Your cellphone number was not a valid 10-digit US phone number. ' \
            'Please include a country code (e.g. +44) for international numbers.'


# =============================
# panels
# =============================

Event.required = [
    ('name', 'Event Name')
]


@validation.PanelApplication
def app_deadline(app):
    if localized_now() > c.PANELS_DEADLINE and not c.HAS_PANELS_ADMIN_ACCESS and (not app.group or not app.group.guest):
        return "We are now past the deadline and are no longer accepting panel applications."


Attraction.required = [
    ('name', 'Name'),
    ('description', 'Description')
]

@validation.Attraction
def slug_not_existing(attraction):
    with Session() as session:
        slug = sluggify(attraction.name)
        if session.query(Attraction).filter(Attraction.id != attraction.id,
                                            Attraction.slug == slug).first():
            return f"Another attraction has an identical URL to this one ({slug}). \
                Please make sure this attraction's name is different from others, not including punctuation."

AttractionFeature.required = [
    ('name', 'Name'),
    ('description', 'Description')
]


@validation.AttractionFeature
def slug_not_existing(feature):
    with Session() as session:
        slug = sluggify(feature.name)
        if session.query(AttractionFeature).filter(AttractionFeature.id != feature.id,
                                                   AttractionFeature.slug == slug).first():
            return f"Another attraction feature has an identical URL to this one ({slug}). \
                Please make sure this feature's name is different from others, not including punctuation."


@validation.AttractionEvent
def at_least_one_slot(event):
    if event.slots < 1:
        return 'Events must have at least one slot.'


# =============================
# guests
# =============================

@validation.GuestGroup
def payment_nan(guest_group):
    try:
        int(float(guest_group.payment if guest_group.payment else 0))
    except Exception:
        return "What you entered for Payment ({}) isn't even a number".format(guest_group.payment)


@validation.GuestGroup
def vehicles_nan(guest_group):
    if not str(guest_group.vehicles).isdigit():
        return "Please enter a whole number of comped parking spaces for vehicles."


@validation.GuestGroup
def hotel_rooms_nan(guest_group):
    if not str(guest_group.num_hotel_rooms).isdigit():
        return "Please enter a whole number of comped hotel rooms."


@validation.GuestMerch
def is_merch_checklist_complete(guest_merch):
    if not guest_merch.selling_merch:
        return 'You need to tell us whether and how you want to sell merchandise'

    elif guest_merch.selling_merch == c.ROCK_ISLAND:
        if not guest_merch.poc_is_group_leader and not (
                guest_merch.poc_first_name
                and guest_merch.poc_last_name
                and guest_merch.poc_phone
                and guest_merch.poc_email):
            return 'You must tell us about your merch point of contact'

        elif not (
                guest_merch.poc_zip_code
                and guest_merch.poc_address1
                and guest_merch.poc_city
                and guest_merch.poc_region
                and guest_merch.poc_country):
            return 'You must tell us your complete mailing address'
        
        elif not guest_merch.delivery_method:
            return 'Please tell us how you will bring us your inventory'
        elif not guest_merch.payout_method:
            return 'Please tell us how you would like to be paid for your merch'
        elif guest_merch.payout_method == c.PAYPAL and not guest_merch.paypal_email:
            return 'We need your PayPal email address to pay you via PayPal'
        elif guest_merch.payout_method == c.CHECK:
            if not guest_merch.check_payable:
                return 'Please include the name that should go on your check'
            if not (
                guest_merch.check_zip_code
                and guest_merch.check_address1
                and guest_merch.check_city
                and guest_merch.check_region
                and guest_merch.check_country
            ):
                return 'Please include the mailing address to send a check to.'


@validation.GuestTravelPlans
def has_modes(guest_travel_plans):
    if not guest_travel_plans.modes:
        return 'Please tell us how you will arrive at MAGFest.'


@validation.GuestTravelPlans
def has_modes_text(guest_travel_plans):
    if c.OTHER in guest_travel_plans.modes_ints and not guest_travel_plans.modes_text:
        return 'You need to tell us what "other" travel modes you are using.'


@validation.GuestTravelPlans
def has_details(guest_travel_plans):
    if not guest_travel_plans.details:
        return 'Please provide details of your arrival and departure plans.'


GuestDetailedTravelPlan.required = [
    ('mode', 'Mode of Travel'),
    ('traveller', 'Traveller Name'),
    ('contact_email', 'Contact Email'),
    ('contact_phone', 'Contact Phone #'),
    ('arrival_time', 'Arrival Time'),
    ('departure_time', 'Departure Time')
]


@validation.GuestDetailedTravelPlan
def arrival_departure_details(travel_plan):
    if travel_plan.mode not in [c.CAR, c.TAXI]:
        if not travel_plan.arrival_details:
            return 'Please provide arrival details, such as the bus or train or plane identifier.'
        if not travel_plan.departure_details:
            return 'Please provide departure details, such as the bus or train or plane identifier.'


@validation.GuestDetailedTravelPlan
def time_checks(travel_plan):
    if travel_plan.arrival_time < travel_plan.min_arrival_time:
        return ('If you are arriving over a week before the event, please select the earliest date and make a note '
                'in the arrival details.')
    if travel_plan.arrival_time > travel_plan.max_arrival_time:
        return 'You cannot arrive after the event is over.'
    if travel_plan.departure_time < travel_plan.min_departure_time:
        return 'You cannot leave before the event starts.'
    if travel_plan.departure_time > travel_plan.max_departure_time:
        return ('If you are leaving over a week after the event, please select the latest date and make a note '
                'in the departure details.')


@validation.GuestDetailedTravelPlan
def has_detailed_modes_text(travel_plan):
    if travel_plan.mode == c.OTHER and not travel_plan.mode_text:
        return 'You need to tell us what "other" travel mode you are using.'


@validation.GuestDetailedTravelPlan
def validate_email(travel_plan):
    return valid_email(travel_plan.contact_email)


@validation.GuestDetailedTravelPlan
def validate_phone(travel_plan):
    if invalid_phone_number(travel_plan.contact_phone):
        return 'Your phone number was not a valid 10-digit US phone number. ' \
            'Please include a country code (e.g. +44) for international numbers.'


# =============================
# art show
# =============================

@prereg_validation.ArtShowApplication
def invalid_mature_banner(app):
    if app.banner_name_ad and not app.has_mature_space:
        return ('banner_name_ad',
                "You cannot enter a banner name for the mature gallery without any space in the mature gallery.")


@validation.ArtShowApplication
def artist_id_dupe(app):
    if app.artist_id and (app.is_new or app.artist_id != app.orig_value_of('artist_id')):
        with Session() as session:
            dupe = session.query(ArtShowApplication).filter(or_(
                ArtShowApplication.artist_id == app.artist_id,
                ArtShowApplication.artist_id_ad == app.artist_id),
                ArtShowApplication.id != app.id).first()
            if dupe:
                return ('artist_id',
                        f"{dupe.display_name}'s {c.ART_SHOW_APP_TERM} already has the code {app.artist_id}!")


@validation.ArtShowApplication
def artist_id_ad_dupe(app):
    if app.artist_id_ad and (app.is_new or app.artist_id_ad != app.orig_value_of('artist_id_ad')):
        with Session() as session:
            dupe = session.query(ArtShowApplication).filter(or_(
                ArtShowApplication.artist_id == app.artist_id_ad,
                ArtShowApplication.artist_id_ad == app.artist_id_ad),
                ArtShowApplication.id != app.id).first()
            if dupe:
                return ('artist_id_ad',
                        f"{dupe.display_name}'s {c.ART_SHOW_APP_TERM} already has the mature code {app.artist_id_ad}!")


@validation.ArtShowApplication
def need_some_space(app):
    if not app.panels and not app.tables \
            and not app.panels_ad and not app.tables_ad:
        return ('', 'Please select how many panels and/or tables to include on this application.')


@validation.ArtShowPiece
def no_duplicate_piece_names(piece):
    with Session() as session:
        if session.query(ArtShowPiece).iexact(name=piece.name).filter(
            ArtShowPiece.id != piece.id, ArtShowPiece.app_id == piece.app_id).all():
            return ('name', "You already have a piece with that name.")


@validation.ArtShowPiece
def check_in_gallery(piece):
    with Session() as session:
        app = session.art_show_application(piece.app_id, ignore_csrf=True)
        if piece.gallery == c.GENERAL and not app.has_general_space:
            return ('gallery', "You cannot put a piece in the General gallery because you do not have any space there.")
        if piece.gallery == c.MATURE and not app.has_mature_space:
            return ('mature', "You cannot put a piece in the Mature gallery because you do not have any space there.")


@validation.ArtShowBidder
def bidder_num_dupe(bidder):
    if bidder.bidder_num and (bidder.is_new or bidder.bidder_num != bidder.orig_value_of('bidder_num')):
        with Session() as session:
            bidder_num_dupe = session.query(ArtShowBidder).filter(
                ArtShowBidder.id != bidder.id,
                ArtShowBidder.bidder_num_stripped == ArtShowBidder.strip_bidder_num(bidder.bidder_num)).first()
            if bidder_num_dupe:
                return ('bidder_num',
                        f"The bidder number {bidder_num_dupe.bidder_num[2:]} already belongs to bidder {bidder_num_dupe.bidder_num}.")


# This is still required for creating an attendee from an art show app, will need to refactor later
Attendee.required = [('first_name', 'First Name'),
                     ('last_name', 'Last Name'),
                     ('email', 'Email')]


@prereg_validation.Attendee
def reasonable_total_cost(attendee):
    if attendee.total_cost >= 999999:
        return ('', 'We cannot charge {}. Please reduce extras so the total is below $9,999.'.format(
            format_currency(attendee.total_cost)))


@prereg_validation.Attendee
def child_group_leaders(attendee):
    if attendee.badge_type == c.PSEUDO_GROUP_BADGE and attendee.birthdate and \
            get_age_from_birthday(attendee.birthdate, c.NOW_OR_AT_CON) < 13:
        return ('badge_type', "Children under 13 cannot be group leaders.")


@prereg_validation.Attendee
def no_more_child_badges(attendee):
    if not attendee.is_new and not attendee.badge_status == c.PENDING_STATUS:
        return

    if c.CHILD_BADGE in c.PREREG_BADGE_TYPES and attendee.birthdate and \
            get_age_from_birthday(attendee.birthdate, c.NOW_OR_AT_CON) < 18 and not c.CHILD_BADGE_AVAILABLE:
        return ('badge_type', "Unfortunately, we are sold out of badges for attendees under 18.")


@prereg_validation.Attendee
def child_badge_over_13(attendee):
    if not attendee.is_new and attendee.badge_status != c.PENDING_STATUS \
            or attendee.unassigned_group_reg or attendee.valid_placeholder:
        return

    if c.CHILD_BADGE in c.PREREG_BADGE_TYPES and attendee.birthdate and attendee.badge_type == c.CHILD_BADGE \
            and get_age_from_birthday(attendee.birthdate, c.NOW_OR_AT_CON) >= 13:
        return ('badge_type',
                f"If you will be 13 or older at the start of {c.EVENT_NAME}, "
                "please select an Attendee badge instead of a 12 and Under badge.")


@prereg_validation.Attendee
def attendee_badge_under_13(attendee):
    if not attendee.is_new and attendee.badge_status != c.PENDING_STATUS \
            or attendee.unassigned_group_reg or attendee.valid_placeholder:
        return

    if c.CHILD_BADGE in c.PREREG_BADGE_TYPES and attendee.birthdate and attendee.badge_type == c.ATTENDEE_BADGE and (
            get_age_from_birthday(attendee.birthdate, c.NOW_OR_AT_CON) < 13):
        return ('badge_type', "If you will be 12 or younger at the start of {}, "
                "please select the 12 and Under badge instead of an Attendee badge.".format(c.EVENT_NAME))


@prereg_validation.Attendee
def age_discount_after_paid(attendee):
    if (attendee.total_cost * 100) < attendee.amount_paid:
        if (not attendee.orig_value_of('birthdate') or attendee.orig_value_of('birthdate') < attendee.birthdate) \
                and attendee.age_group_conf['discount'] > 0:
            return ('birthdate', 'The date of birth you entered incurs a discount; \
                                please email {} to change your badge and receive a refund'.format(c.REGDESK_EMAIL))


@prereg_validation.Attendee
def require_staff_shirt_size(attendee):
    if attendee.gets_staff_shirt and not attendee.shirt_size_marked and not c.STAFF_SHIRTS_OPTIONAL:
        return ('staff_shirt', "Please select a shirt size for your staff shirt.")


@prereg_validation.Attendee
def promo_code_is_useful(attendee):
    if attendee.promo_code:
        with Session() as session:
            code = session.lookup_registration_code(attendee.promo_code.code, PromoCode)
            group = code.group if code and code.group else session.lookup_registration_code(attendee.promo_code.code,
                                                                                            PromoCodeGroup)
            if group and group.total_cost == 0:
                return

    if attendee.is_new and attendee.promo_code:
        if not attendee.is_unpaid:
            return ('promo_code', "You can't apply a promo code after you've paid or if you're in a group.")
        elif attendee.is_dealer:
            return ('promo_code', "You can't apply a promo code to a {}.".format(c.DEALER_REG_TERM))
        elif attendee.age_discount != 0:
            return ('promo_code',
                    "You are already receiving an age based discount, you can't use a promo code on top of that.")
        elif attendee.badge_type == c.ONE_DAY_BADGE or attendee.is_presold_oneday:
            return ('promo_code', "You can't apply a promo code to a one day badge.")
        elif attendee.overridden_price:
            return ('promo_code',
                    "You already have a special badge price, you can't use a promo code on top of that.")
        elif attendee.badge_cost_with_promo_code >= attendee.calculate_badge_cost():
            return ('promo_code',
                    "That promo code doesn't make your badge any cheaper. You may already have other discounts.")


@prereg_validation.Attendee
def promo_code_not_is_expired(attendee):
    if attendee.is_new and attendee.promo_code and attendee.promo_code.is_expired:
        return ('promo_code', 'That promo code is expired.')


@validation.Attendee
def promo_code_has_uses_remaining(attendee):
    if attendee.is_new and attendee.promo_code and not attendee.promo_code.is_unlimited:
        unpaid_uses_count = PreregCart.get_unpaid_promo_code_uses_count(
            attendee.promo_code.id, attendee.id)
        if (attendee.promo_code.uses_remaining - unpaid_uses_count) < 0:
            return ('promo_code', 'That promo code has been used too many times.')


@validation.Attendee
def allowed_to_volunteer(attendee):
    if attendee.staffing_or_will_be \
            and not attendee.age_group_conf['can_volunteer'] \
            and attendee.badge_type not in [c.STAFF_BADGE, c.CONTRACTOR_BADGE] \
            and c.PRE_CON:
        return ('staffing', 'Your interest is appreciated, but ' + c.EVENT_NAME + ' volunteers must be 18 or older.')


@validation.Attendee
def banned_volunteer(attendee):
    if attendee.staffing_or_will_be and attendee.full_name in c.BANNED_STAFFERS:
        return ('staffing', "We've declined to invite {} back as a volunteer, ".format(attendee.full_name) + (
                    'talk to STOPS to override if necessary' if c.AT_THE_CON else
                    'Please contact us via {} if you believe this is in error'.format(c.CONTACT_URL)))


@validation.Attendee
def not_in_range(attendee):
    if not attendee.badge_num:
        return

    badge_type = get_real_badge_type(attendee.badge_type)
    lower_bound, upper_bound = c.BADGE_RANGES[badge_type]
    if not (lower_bound <= int(attendee.badge_num) <= upper_bound):
        return ('badge_num',
                f'Badge number {attendee.badge_num} is out of range for badge type '
                f'{c.BADGES[attendee.badge_type]} ({lower_bound} - {upper_bound})')


@validation.Attendee
def dealer_needs_group(attendee):
    if attendee.is_dealer and not attendee.group_id and attendee.badge_type != c.PSEUDO_DEALER_BADGE:
        return ('group_id', '{}s must be associated with a group.'.format(c.DEALER_TERM.title()))


@validation.Attendee
def group_leadership(attendee):
    if attendee.session and not attendee.group_id:
        orig_group_id = attendee.orig_value_of('group_id')
        if orig_group_id and attendee.id == attendee.session.group(orig_group_id).leader_id:
            return ('group_id',
                    'You cannot remove the leader of a group from that group; make someone else the leader first')


@prereg_validation.Group
def edit_only_correct_statuses(group):
    if group.status not in c.DEALER_EDITABLE_STATUSES:
        return "You cannot change your {} after it has been {}.".format(c.DEALER_APP_TERM, group.status_label)
