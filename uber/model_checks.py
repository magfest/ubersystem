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
from sqlalchemy import and_, func, or_

from uber.badge_funcs import get_real_badge_type
from uber.config import c
from uber.custom_tags import format_currency, full_date_local
from uber.decorators import prereg_validation, validation
from uber.models import (AccessGroup, AdminAccount, ApiToken, Attendee, ArtShowApplication, ArtShowPiece,
                         AttendeeTournament, Attraction, AttractionFeature, Department, DeptRole, Event,
                         GuestDetailedTravelPlan, IndieDeveloper, IndieGame, IndieGameCode, IndieJudge, IndieStudio,
                         Job, MarketplaceApplication, MITSApplicant, MITSDocument, MITSGame, MITSPicture, MITSTeam,
                         PanelApplicant, PanelApplication, PromoCode, PromoCodeGroup, Sale, Session, WatchList)
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


Department.required = [('name', 'Name'), ('description', 'Description')]
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
def room_meets_requirements(app):
    if app.any_room_dates_different:
        latest_checkin, earliest_checkout = app.shortest_room_check_in_out_dates
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
def suite_meets_requirements(app):
    if app.any_suite_dates_different:
        latest_checkin, earliest_checkout = app.shortest_suite_check_in_out_dates
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
# marketplace
# =============================
MarketplaceApplication.required = [('description', 'Description'), ('categories', 'Categories')]


@validation.MarketplaceApplication
def marketplace_other_category(app):
    if app.categories and c.OTHER in app.categories_ints and not app.categories_text:
        return "Please describe what 'other' things you are planning to sell."

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


IndieStudio.required = [
    ('name', 'Studio Name'),
    ('website', 'Website')
]

IndieDeveloper.required = [
    ('first_name', 'First Name'),
    ('last_name', 'Last Name'),
    ('email', 'Email')
]

IndieGame.required = [
    ('title', 'Game Title'),
    ('brief_description', 'Brief Description'),
    ('genres', 'Genres'),
    ('description', 'Full Description')
]


@validation.IndieGame
def mivs_showtime_agreement(game):
    if not game.agreed_showtimes:
        return 'Please check the box to confirm to the showtimes for a MIVS booth.'


@validation.IndieGame
def mivs_liability_agreement(game):
    if not game.agreed_liability:
        return 'Please check the box to confirm to agree to the liability waiver.'


IndieGameCode.required = [
    ('code', 'Game Code')
]


IndieJudge.required = [
    ('platforms', 'Platforms'),
    ('genres', 'Genres'),
]


@validation.IndieJudge
def must_have_pc(judge):
    if c.PC not in judge.platforms_ints and c.PCGAMEPAD not in judge.platforms_ints:
        return 'You must have a PC to judge for MIVS.'


@validation.IndieJudge
def vr_text(judge):
    if c.VR in judge.platforms_ints and not judge.vr_text:
        return 'Please tell us what VR/AR platforms you own.'


@validation.IndieStudio
def mivs_new_studio_deadline(studio):
    if studio.is_new and not c.CAN_SUBMIT_MIVS:
        return 'Sorry, but the deadline has already passed, so no new studios may be registered.'


@validation.IndieStudio
def mivs_valid_url(studio):
    if studio.website and _is_invalid_url(studio.website_href):
        return 'We cannot contact that website; please enter a valid url ' \
            'or leave the website field blank until your website goes online.'


@validation.IndieStudio
def mivs_unique_name(studio):
    with Session() as session:
        if session.query(IndieStudio).filter(IndieStudio.name == studio.name, IndieStudio.id != studio.id).count():
            return "That studio name is already taken; " \
                "are you sure you shouldn't be logged in with that studio's account?"


@validation.IndieStudio
def mivs_studio_contact_phone(studio):
    if studio.contact_phone and invalid_phone_number(studio.contact_phone):
        return 'Please enter a valid phone number'


@validation.IndieDeveloper
def agree_to_coc(dev):
    if not dev.agreed_coc:
        return 'You must agree to be bound by our Code of Conduct.'


@validation.IndieDeveloper
def agree_to_data_policy(dev):
    if not dev.agreed_data_policy:
        return 'You must agree for your information to be used for determining showcase selection.'


@validation.IndieDeveloper
def mivs_dev_email(dev):
    if not re.match(c.EMAIL_RE, dev.email):
        return 'Please enter a valid email address'


@validation.IndieDeveloper
def mivs_dev_cellphone(dev):
    if (dev.primary_contact or dev.cellphone) and invalid_phone_number(dev.cellphone):
        return 'Please enter a valid phone number'


@validation.IndieGame
def mivs_platforms_or_other(game):
    if not game.platforms and not game.platforms_text:
        return 'Please select a platform your game runs on or describe another platform in the box provided.'


@validation.IndieGame
def mivs_new_game_deadline(game):
    if game.is_new and not c.CAN_SUBMIT_MIVS:
        return 'Sorry, but the deadline has already passed, so no new games may be registered'


@validation.IndieGame
def mivs_instructions(game):
    if game.code_type in c.MIVS_CODES_REQUIRING_INSTRUCTIONS and not game.code_instructions:
        return 'You must leave instructions for how the judges are to use the code(s) you provide'


@validation.IndieGame
def mivs_video_link(game):
    if game.link_to_video and _is_invalid_url(game.video_href):
        return 'The link you provided for the intro/instructional video does not appear to work'


@validation.IndieGame
def mivs_submitted(game):
    if (game.submitted and not game.status == c.ACCEPTED) and not c.HAS_MIVS_ADMIN_ACCESS:
        return 'You cannot edit a game after it has been submitted'


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


@validation.IndieGameImage
def mivs_description(image):
    if image.is_screenshot and not image.description:
        return 'Please enter a description of the screenshot.'


@validation.IndieGameImage
def mivs_valid_type(screenshot):
    if screenshot.extension not in c.GUIDEBOOK_ALLOWED_IMAGE_TYPES:
        return 'Our server did not recognize your upload as a valid image'


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


@validation.Event
def overlapping_events(event, other_event_id=None):
    existing = {}
    for e in event.session.query(Event).filter(Event.location == event.location,
                                               Event.id != event.id,
                                               Event.id != other_event_id).all():
        for hh in e.half_hours:
            existing[hh] = e.name

    for hh in event.half_hours:
        if hh in existing:
            return '"{}" overlaps with the time/duration you specified for "{}"'.format(existing[hh], event.name)


PanelApplication.required = [
    ('name', 'Panel Name'),
    ('description', 'Panel Description'),
    ('presentation', 'Panel Type'),
    ('length', 'Panel Length'),
    ('noise_level', 'Noise Level'),
]

if len(c.PANEL_DEPT_OPTS) > 1:
    PanelApplication.required.append(('department', 'Department'))

PanelApplicant.required = [
    ('first_name', 'First Name'),
    ('last_name', 'Last Name'),
    ('email', 'Email'),
]


@validation.PanelApplicant
def pa_email(pa):
    if not pa.email or not re.match(c.EMAIL_RE, pa.email):
        return 'Please enter a valid email address'


@validation.PanelApplicant
def pa_phone(pa):
    if (pa.submitter or pa.cellphone) and invalid_phone_number(pa.cellphone):
        return 'Please enter a valid phone number'


@validation.PanelApplication
def unavailability(app):
    if not app.unavailable:
        return 'Your unavailability is required.'


@validation.PanelApplication
def panel_other(app):
    if app.presentation == c.OTHER and not app.other_presentation:
        return 'Since you selected "Other" for your type of panel, please describe it'


@validation.PanelApplication
def specify_other_time(app):
    if app.length == c.OTHER and not app.length_text:
        return 'Please specify how long your panel will be.'


@validation.PanelApplication
def specify_nonstandard_time(app):
    if app.length != c.SIXTY_MIN and not app.length_reason and not app.poc_id:
        return 'Please explain why your panel needs to be longer than sixty minutes.'


@validation.PanelApplication
def select_livestream_opt(app):
    if not app.livestream:
        return 'Please select your preference for recording/livestreaming.' \
            if len(c.LIVESTREAM_OPTS) > 2 else 'Please tell us if we can livestream your panel.'
    

@validation.PanelApplication
def select_record_opt(app):
    if not app.record and len(c.LIVESTREAM_OPTS) <= 2:
        return 'Please tell us if we can record your panel.'


@validation.PanelApplication
def specify_table_needs(app):
    if app.need_tables and not app.tables_desc:
        return 'Please describe how you need tables set up for your panel.'


@validation.PanelApplication
def specify_cost_details(app):
    if app.has_cost and not app.cost_desc:
        return 'Please describe the materials you will provide and how much you will charge attendees for them.'


@validation.PanelApplication
def specify_rating(app):
    if len(c.PANEL_RATING_OPTS) > 1 and app.rating == c.UNRATED:
        return 'Please select a content rating for your panel.'


@validation.PanelApplication
def specify_granular_rating(app):
    if len(c.PANEL_CONTENT_OPTS) > 1 and not app.granular_rating:
        return "Please select what your panel's content will contain, or None."


@validation.PanelApplication
def none_is_none_granular_rating(app):
    if c.NONE in app.granular_rating_ints and len(app.granular_rating_ints) > 1:
        return "You cannot select mature content for your panel and also 'None'."


Attraction.required = [
    ('name', 'Name'),
    ('description', 'Description')
]

AttractionFeature.required = [
    ('name', 'Name'),
    ('description', 'Description')
]


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
ArtShowApplication.required = [('description', 'Description'), ('website', 'Website URL')]


@prereg_validation.ArtShowApplication
def max_panels(app):
    if app.panels > c.MAX_ART_PANELS and app.panels != app.orig_value_of('panels') or \
        app.panels_ad > c.MAX_ART_PANELS and app.panels_ad != app.orig_value_of('panels_ad'):
        return 'You cannot have more than {} panels.'.format(c.MAX_ART_PANELS)


@prereg_validation.ArtShowApplication
def min_panels(app):
    if app.panels < 0 or app.panels_ad < 0:
        return 'You cannot have fewer than 0 panels.'


@prereg_validation.ArtShowApplication
def max_tables(app):
    if app.tables > c.MAX_ART_TABLES and app.tables != app.orig_value_of('tables') or \
        app.tables_ad > c.MAX_ART_TABLES and app.tables_ad != app.orig_value_of('tables_ad'):
        return 'You cannot have more than {} tables.'.format(c.MAX_ART_TABLES)


@prereg_validation.ArtShowApplication
def min_tables(app):
    if app.tables < 0 or app.tables_ad < 0:
        return 'You cannot have fewer than 0 tables.'


@prereg_validation.ArtShowApplication
def invalid_mature_banner(app):
    if app.banner_name_ad and not app.has_mature_space:
        return "You cannot enter a banner name for the mature gallery without any space in the mature gallery."


@prereg_validation.ArtShowApplication
def contact_at_con(app):
    if not app.contact_at_con:
        return "Please tell us the best way to get a hold of you at the event, e.g., " \
        "your mobile number or your hotel and room number."


@validation.ArtShowApplication
def artist_id_dupe(app):
    if app.artist_id and (app.is_new or app.artist_id != app.orig_value_of('artist_id')):
        with Session() as session:
            dupe = session.query(ArtShowApplication).filter(or_(ArtShowApplication.artist_id == app.artist_id,
                                                                ArtShowApplication.artist_id_ad == app.artist_id),
                                                            ArtShowApplication.id != app.id).first()
            if dupe:
                return f"{dupe.display_name}'s {c.ART_SHOW_APP_TERM} already has the code {app.artist_id}!"


@validation.ArtShowApplication
def artist_id_ad_dupe(app):
    if app.artist_id and (app.is_new or app.artist_id_ad != app.orig_value_of('artist_id_ad')):
        with Session() as session:
            dupe = session.query(ArtShowApplication).filter(or_(ArtShowApplication.artist_id == app.artist_id_ad,
                                                                ArtShowApplication.artist_id_ad == app.artist_id_ad),
                                                            ArtShowApplication.id != app.id).first()
            if dupe:
                return f"{dupe.display_name}'s {c.ART_SHOW_APP_TERM} already has the mature code {app.artist_id_ad}!"


@validation.ArtShowApplication
def us_only(app):
    if app.delivery_method == c.BY_MAIL and not app.us_only:
        return 'Please confirm your address is within the continental US if you are mailing your art in.'


@validation.ArtShowApplication
def cant_ghost_art_show(app):
    if not c.INDEPENDENT_ART_SHOW and app.attendee and app.delivery_method == c.BRINGING_IN \
            and app.attendee.badge_status == c.NOT_ATTENDING:
        return 'You cannot bring your own art if you are not attending.'


@validation.ArtShowApplication
def need_some_space(app):
    if not app.panels and not app.tables \
            and not app.panels_ad and not app.tables_ad:
        return 'Please select how many panels and/or tables to include' \
               ' on this application.'


@prereg_validation.ArtShowApplication
def too_late_now(app):
    if app.status != c.UNAPPROVED:
        for field in ['artist_name',
                      'panels',
                      'panels_ad',
                      'tables',
                      'tables_ad',
                      'description',
                      'website',
                      'special_needs',
                      'status',
                      'delivery_method',
                      'admin_notes']:
            if app.orig_value_of(field) != getattr(app, field):
                return 'Your application has been {} and may no longer be updated'\
                    .format(app.status_label)


@validation.ArtShowApplication
def discounted_price(app):
    try:
        cost = int(float(app.overridden_price if app.overridden_price else 0))
        if cost < 0:
            return 'Overridden Price must be a number that is 0 or higher.'
    except Exception:
        return "What you entered for Overridden Price ({}) " \
               "isn't even a number".format(app.overridden_price)


ArtShowPiece.required = [('name', 'Name'),
                         ('gallery', 'Gallery'),
                         ('type', 'Type')]


@validation.ArtShowPiece
def no_duplicate_piece_names(piece):
    with Session() as session:
        if session.query(ArtShowPiece).iexact(name=piece.name).filter(ArtShowPiece.id != piece.id,
                                                                      ArtShowPiece.app_id == piece.app_id).all():
            return "You already have a piece with that name."


@validation.ArtShowPiece
def print_run_if_print(piece):
    if piece.type == c.PRINT:
        if not piece.print_run_num:
            return "Please enter the piece's edition number"
        if not piece.print_run_total:
            return "Please enter the total number of prints for this piece's print run"

        try:
            num = int(piece.print_run_num)
            total = int(piece.print_run_total)
            if total > 1000:
                return "Print runs can only be 1000 prints or fewer"
            if total <= 0:
                return "Print runs must have at least 1 print"
            if num <= 0:
                return "A piece must be at least edition 1 of {}".format(total)
            if total < num:
                return "A piece's edition number cannot be higher than the total print run"
        except Exception:
            return ("What you entered for the print edition or run total "
                    f"({piece.print_run_num}/{piece.print_run_total}) isn't even a number")


@validation.ArtShowPiece
def media_if_original(piece):
    if piece.type == c.ORIGINAL and not piece.media:
        return "Please describe what medium your original art is on."


@validation.ArtShowPiece
def price_checks_if_for_sale(piece):
    if piece.for_sale:
        if not piece.opening_bid:
            return "Please enter an opening bid for this piece"

        try:
            price = int(piece.opening_bid)
            if price <= 0:
                return "A piece must cost more than $0"
        except Exception:
            return f"What you entered for the opening bid ({piece.opening_bid}) isn't even a number"

        if not piece.no_quick_sale:
            if not piece.quick_sale_price:
                "Please enter a " + c.QS_PRICE_TERM

            try:
                price = int(piece.quick_sale_price)
                if price <= 0:
                    return "A piece must cost more than $0, even after bidding ends"
            except Exception:
                return f"What you entered for the {c.QS_PRICE_TERM} ({piece.quick_sale_price}) isn't even a number"


@validation.ArtShowPiece
def name_max_length(piece):
    if len(piece.name) > c.PIECE_NAME_LENGTH:
        return "Piece names must be {} characters or fewer.".format(c.PIECE_NAME_LENGTH)


@validation.ArtShowPiece
def check_in_gallery(piece):
    if piece.gallery == c.GENERAL and not piece.app.has_general_space:
        return "You cannot put a piece in the General gallery because you do not have any space there."
    if piece.gallery == c.MATURE and not piece.app.has_mature_space:
        return "You cannot put a piece in the Mature gallery because you do not have any space there."


@validation.ArtShowPiece
def media_max_length(piece):
    if len(piece.media) > 15:
        return "The description of the piece's media must be 15 characters or fewer."


# New validations, which return a tuple with the field name (or an empty string) and the message
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
    if not attendee.is_new and attendee.badge_status not in [c.PENDING_STATUS, c.AT_DOOR_PENDING_STATUS] \
            or attendee.unassigned_group_reg or attendee.valid_placeholder:
        return

    if c.CHILD_BADGE in c.PREREG_BADGE_TYPES and attendee.birthdate and attendee.badge_type == c.CHILD_BADGE \
            and get_age_from_birthday(attendee.birthdate, c.NOW_OR_AT_CON) >= 13:
        return ('badge_type',
                f"If you will be 13 or older at the start of {c.EVENT_NAME}, "
                "please select an Attendee badge instead of a 12 and Under badge.")


@prereg_validation.Attendee
def attendee_badge_under_13(attendee):
    if not attendee.is_new and attendee.badge_status not in [c.PENDING_STATUS, c.AT_DOOR_PENDING_STATUS] \
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
    if attendee.gets_staff_shirt and not attendee.shirt_size_marked:
        return ('staff_shirt', "Please select a shirt size for your staff shirt.")


@validation.Attendee
def volunteers_cellphone_or_checkbox(attendee):
    if not attendee.placeholder and not attendee.no_cellphone \
            and attendee.staffing_or_will_be and not attendee.cellphone:
        return ('cellphone',
                "Volunteers and staffers must provide a cellphone number or indicate they do not have a cellphone.")


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
        return ('group_id', '{}s must be associated with a group'.format(c.DEALER_TERM.title()))


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
