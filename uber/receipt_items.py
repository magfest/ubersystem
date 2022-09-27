"""
When an attendee or group preregisters or changes their registration, we want a way to determine the potential costs and
credits to add to their receipt. These items are defined here. Each cost/credit should return None if there is no applicable 
charge for that model or a tuple of the cost description, the cost price, and (optionally) the number of items. If the cost 
price is 0, the item is printed as "Free" on the receipt. All cost prices should be in cents.
"""
from collections import defaultdict

from uber.config import c
from uber.decorators import cost_calculation, credit_calculation
from uber.models import Attendee


@cost_calculation.MarketplaceApplication
def app_cost(app):
    if app.status == c.APPROVED:
        return ("Marketplace Application Fee", app.overridden_price * 100 or c.MARKETPLACE_FEE * 100 or 0)


@cost_calculation.ArtShowApplication
def overridden_app_cost(app):
    if app.status == c.APPROVED and app.overridden_price != None:
        return ("Art Show Application (Custom Price)", app.overridden_price * 100)

@cost_calculation.ArtShowApplication
def panel_cost(app):
    return ("General Panel", c.COST_PER_PANEL * 100, app.panels) if app.panels else None

@cost_calculation.ArtShowApplication
def table_cost(app):
    return ("General Table", c.COST_PER_TABLE * 100, app.tables) if app.tables else None

@cost_calculation.ArtShowApplication
def mature_panel_cost(app):
    return ("Mature Panel", c.COST_PER_PANEL * 100, app.panels_ad) if app.panels_ad else None

@cost_calculation.ArtShowApplication
def mature_table_cost(app):
    return ("Mature Table", c.COST_PER_TABLE * 100, app.tables_ad) if app.tables_ad else None

@cost_calculation.ArtShowApplication
def mailing_fee_cost(app):
    return ("Mailing fee", c.ART_MAILING_FEE * 100) if app.delivery_method == c.BY_MAIL else None


Attendee.cost_changes = {
    'overridden_price': ('Custom Badge Price', "calc_badge_cost_change"),
    'badge_type': ('Badge ({})', "calc_badge_cost_change", c.BADGES),
    'amount_extra': ('Kickin ({})', None, c.DONATION_TIERS),
    'extra_donation': ('Extra Donation', None),
}

Attendee.credit_changes = {
    'paid': ('Badge Comp', "calc_badge_comp_change"),
    'birthdate': ('Age Discount', "calc_age_discount_change"),
    'promo_code': ('Promo Code'), # TODO
}

@cost_calculation.Attendee
def badge_cost(attendee):
    if attendee.paid == c.PAID_BY_GROUP or attendee.promo_code_groups:
        cost = 0
    else:
        cost = attendee.calculate_badge_cost() * 100

    if cost or attendee.badge_type in c.BADGE_TYPE_PRICES:
        if attendee.badge_type in c.BADGE_TYPE_PRICES or not attendee.badge_type_label:
            label = "Attendee badge for {}{}".format(attendee.full_name, "" if cost else " (paid by group)")
        else:
            label = "{} badge for {}".format(attendee.badge_type_label, attendee.full_name)

        return (label, cost)

@cost_calculation.Attendee
def badge_upgrade_cost(attendee):
    if attendee.badge_type in c.BADGE_TYPE_PRICES:
        return ("{} badge upgrade for {}".format(attendee.badge_type_label, attendee.full_name), attendee.calculate_badge_prices_cost() * 100)

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
    if attendee.qualifies_for_discounts and attendee.age_discount:
        if abs(attendee.age_discount) > attendee.calculate_badge_cost():
            age_discount = attendee.calculate_badge_cost() * 100 * -1
        else:
            age_discount = attendee.age_discount * 100

        return ("Age Discount", age_discount)

@credit_calculation.Attendee
def group_discount(attendee):
    if c.GROUP_DISCOUNT and attendee.qualifies_for_discounts and not attendee.age_discount and (
                attendee.promo_code_groups or attendee.group):
        return ("Group Discount", c.GROUP_DISCOUNT * 100 * -1)


@cost_calculation.Group
def table_cost(group):
    table_count = int(float(group.tables))
    if table_count:
        return ("{} Tables".format(table_count), sum(c.TABLE_PRICES[i] for i in range(1, 1 + table_count)) * 100)

@cost_calculation.Group
def badge_cost(group):
    cost_table = defaultdict(int)

    for attendee in group.attendees:
        if attendee.paid == c.PAID_BY_GROUP and attendee.badge_cost:
            cost_table[attendee.badge_cost * 100] += 1

    return ("Group badge ({})".format(group.name), cost_table)


@cost_calculation.PrintJob
def badge_reprint_fee_cost(job):
    return ("Badge reprint fee", job.print_fee * 100) if job.print_fee else None

@cost_calculation.Attendee
def promo_code_group_cost(attendee):
    cost_table = defaultdict(int)

    if getattr(attendee, 'badges', None):
        # During prereg we set the number of promo code badges on the attendee model
        cost_table[c.get_group_price() * 100] = int(attendee.badges)
    elif attendee.promo_code_groups:
        for code in attendee.promo_code_groups[0].promo_codes:
            cost_table[code.cost * 100] += 1
    else:
        return

    return ("Group badge ({})".format(attendee.promo_code_groups[0].name if attendee.promo_code_groups
                                      else getattr(attendee, 'name', 'Unknown')), cost_table)
