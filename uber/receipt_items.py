"""
When an attendee or group preregisters or changes their registration, we want a way to determine the potential costs and
credits to add to their receipt. These items are defined here. Each cost/credit should return None if there is no applicable 
charge for that model or a tuple of the cost description, the cost price, and (optionally) the number of items. If the cost 
price is 0, the item is printed as "Free" on the receipt. All cost prices should be in cents.

Each model can also have a cost_changes dict, where each entry is a tuple containing two descriptions and the
calculation function on the model. These functions are called through the add_receipt_upgrade_item function on the Charge
class and they return a negative or positive number representing how much we should charge or credit an attendee/group with
an existing receipt. The two descriptions correspond to what the receipt item will say if the number is positive or negative,
e.g.:

    Attendee.cost_changes = {
        'key': ('Label', 'cost_change_func_name', 'extra_formatting_attr')
    }
"""
import re
from collections import defaultdict
from datetime import date
from functools import wraps
from urllib.request import urlopen

import cherrypy
import phonenumbers
from pockets.autolog import log

from uber.config import c
from uber.custom_tags import format_currency
from uber.decorators import cost_calculation, credit_calculation
from uber.models import Attendee, ArtShowApplication, Group, PrintJob, PromoCodeGroup, Session
from uber.utils import localized_now, Charge, valid_email




@cost_calculation.MarketplaceApplication
def app_cost(app):
    if app.status == c.APPROVED:
        return ("Marketplace application", app.overridden_price * 100 or c.MARKETPLACE_FEE * 100 or 0)


@cost_calculation.ArtShowApplication
def overridden_app_cost(app):
    if app.status == c.APPROVED and app.overridden_price != None:
        return ("Art Show application", app.overridden_price * 100)

@cost_calculation.ArtShowApplication
def panel_cost(app):
    return ("General Panel", c.COST_PER_PANEL * 100, app.panels) if app.panels else None

@cost_calculation.ArtShowApplication
def table_cost(app):
    return ("General Table", c.COST_PER_TABLE * 100, app.tables) if app.tables else None

@cost_calculation.ArtShowApplication
def ad_panel_cost(app):
    return ("Mature Panel", c.COST_PER_PANEL * 100, app.panels_ad) if app.panels_ad else None

@cost_calculation.ArtShowApplication
def ad_table_cost(app):
    return ("Mature Table", c.COST_PER_TABLE * 100, app.tables_ad) if app.tables_ad else None

@cost_calculation.ArtShowApplication
def mailing_fee(app):
    return ("Mailing fee", c.ART_MAILING_FEE * 100) if app.delivery_method == c.BY_MAIL else None


Attendee.cost_changes = {
    'overridden_price': ('Custom Badge Price', "calc_badge_cost_change"),
    'badge_type': ('Badge ({})', "calc_badge_cost_change", "badge_type_label"),
    'amount_extra': ('Kickin ({})', None, "amount_extra_label"),
    'extra_donation': ('Extra Donation', None),
}

Attendee.credit_changes = {
    'paid': ('Badge Comp', "calc_badge_comp_change"),
    'birthdate': ('Age Discount', "calc_age_discount_change"),
    'promo_code': ('Promo Code'), # TODO
}

@cost_calculation.Attendee
def badge_cost(attendee):
    return ("{} badge for {}".format(attendee.badge_type_label, attendee.full_name), attendee.calculate_badge_cost() * 100)

@cost_calculation.Attendee
def shipping_fee_cost(attendee):
    if attendee.badge_status == c.DEFERRED_STATUS and attendee.amount_extra:
        return ("Merch Shipping Fee", attendee.calculate_shipping_fee_cost() * 100)

@cost_calculation.Attendee
def donation_cost(attendee):
    return ("Extra Donation", attendee.extra_donation * 100) if attendee.extra_donation else None

@cost_calculation.Attendee
def kickin_cost(attendee):
    return ("Kickin ({})".format(attendee.amount_extra_label), attendee.amount_extra * 100) if attendee.amount_extra else None

@credit_calculation.Attendee
def age_discount(attendee):
    if attendee.qualifies_for_discounts:
        return ("Age Discount", attendee.age_discount * 100) if attendee.age_discount else None

@credit_calculation.Attendee
def group_discount(attendee):
    if attendee.qualifies_for_discounts and not attendee.age_discount and (
                attendee.promo_code_groups or attendee.group and attendee.paid == c.PAID_BY_GROUP):
        return ("Group discount", c.GROUP_DISCOUNT * 100)


@cost_calculation.Group
def table_cost(group):
    table_count = int(float(group.tables))
    if table_count:
        return ("{} Tables".format(table_count), sum(c.TABLE_PRICES[i] for i in range(1, 1 + table_count)) * 100)

@cost_calculation.Group
def badge_cost(group):
    cost_table = defaultdict(int)

    for attendee in group.attendees:
        if attendee.paid == c.PAID_BY_GROUP:
            cost_table[attendee.badge_cost * 100] += 1

    return ("Group badge ({})".format(group.name), cost_table)


@cost_calculation.PrintJob
def badge_reprint_fee(job):
    return ("Badge reprint fee", job.print_fee * 100) if job.print_fee else None


@cost_calculation.PromoCodeGroup
def cost(group):
    cost_table = defaultdict(int)

    for code in group.promo_codes:
        cost_table[code.cost * 100] += 1

    return ("Group badge ({}'s group)".format(), cost_table)

@cost_calculation.PromoCode
def code_cost(code):
    return ("Promo code group badge", code.cost * 100) if code.cost else None


