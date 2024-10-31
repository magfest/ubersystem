"""
When an attendee or group preregisters or changes their registration, we want a way to determine the potential costs
and credits to add to their receipt. These functions are defined here.

Each function takes the following parameters:
    - The current model
    - The new or "preview" model if you are processing a receipt change (optional)

Each function returns either None, if there is no applicable charge, or a tuple with:
    - (str) The description of the cost/credit item
    - (int) The cost/credit amount, in cents. Negative costs are processed as credits.
        - This can alternatively be a dictionary where each key is a cost and its value is the count for that cost.
          This is used in cases where the same items might have different costs, like group badges purchased at 
          different times.
    - One of three things:
        - (str) The name of the column that this cost/credit applies to, e.g., 'tables'. This is used
                when building a new receipt to populate 'default' values for the revert_change column on ReceiptItem.
        - (tuple) A tuple of strings representing multiple column names, also used to populate ReceiptItem.revert_change.
        - (enum) The configured category that should be applied to this column. This is used in cases where there
                 is no meaningful default value, OR the item in question might apply to different categories, e.g.,
                 a promo code is either a badge discount or an item comp, based on if the code makes the badge free.
    - (int) Optionally, a quantity. For items with more than one quantity, the cost should be the cost per-item.

Additionally, we define here each model's default receipt_item_dept. Most models have only one department applied
to their items, but if they don't that is processed by the functions in ReceiptManager and not here.

Finally, we define a dictionary of tuples for each model that associates column names with the cost/credit functions
to run for them and their corresponding categories. If a function returns a category, that is always used instead.
"""
import string

from collections import defaultdict
from pockets.autolog import log

from uber.config import c
from uber.decorators import receipt_calculation
from uber.models import Attendee, ArtShowApplication, Group


def calc_simple_cost_change(model, col_name, col_str, new_model=None):
    """
    Takes an instance of a model and attempts to calculate a simple cost change
    based on a column name. Used for columns where the cost is the column, e.g.,
    extra_donation and amount_extra.
    """
    col_val = getattr(model, col_name, 0)
    if not new_model:
        return (col_str, col_val * 100, col_name) if col_val else None
    
    new_val = getattr(new_model, col_name, 0)
    if new_val > col_val:
        label = "Increase"
    else:
        label = "Decrease"
    
    diff = (new_val - col_val) * 100
    if diff:
        return (f"{label} {col_str}", diff, col_name)


def calc_multiplied_cost_change(app, col_name, col_str, price_per, new_app=None):
    col_val = getattr(app, col_name)

    if not new_app:    
        return (col_str, price_per * 100, col_name, col_val) if col_val else None
    
    new_val = getattr(new_app, col_name)

    if new_val > col_val:
        label = "Add"
        cost_mod = 1
    else:
        label = "Remove"
        cost_mod = -1
    diff = new_val - col_val

    if diff:
        return (f"{label} {col_str}", price_per * 100 * cost_mod, col_name, abs(diff))


@receipt_calculation.ArtistMarketplaceApplication
def app_cost(app):
    if app.status == c.APPROVED:
        return ("Marketplace Application Fee", app.overridden_price * 100 or c.MARKETPLACE_FEE * 100 or 0, None)


@receipt_calculation.ArtShowApplication
def overridden_app_cost(app, new_app=None):
    if not new_app and app.overridden_price is None:
        return
    elif not new_app:
        return ("Art Show Application (Custom Fee)", app.overridden_price * 100, 'overridden_price')
    
    if app.overridden_price is None and new_app.overridden_price is None:
        return
    
    if new_app.overridden_price is None:
        new_cost = new_app.panels_and_tables_cost * 100
    else:
        new_cost = new_app.overridden_price * 100

    if app.overridden_price is None:
        diff = new_cost - (app.panels_and_tables_cost * 100)
        label = "Set"
    elif new_app.overridden_price is None:
        diff = new_cost - app.overridden_price * 100
        label = "Unset"
    else:
        diff = new_cost - app.overridden_price * 100
        label = "Update"

    if diff:
        return (f"{label} Custom Fee", diff, 'overridden_price')


@receipt_calculation.ArtShowApplication
def panel_cost(app, new_app=None):
    if app.overridden_price is not None or new_app and new_app.overridden_price is not None:
        return
    
    return calc_multiplied_cost_change(app, 'panels', 'General Panels', c.COST_PER_PANEL, new_app)


@receipt_calculation.ArtShowApplication
def table_cost(app, new_app=None):
    if app.overridden_price is not None or new_app and new_app.overridden_price is not None:
        return
    
    return calc_multiplied_cost_change(app, 'tables', 'General Tables', c.COST_PER_TABLE, new_app)


@receipt_calculation.ArtShowApplication
def mature_panel_cost(app, new_app=None):
    if app.overridden_price is not None or new_app and new_app.overridden_price is not None:
        return
    
    return calc_multiplied_cost_change(app, 'panels_ad', 'Mature Panels', c.COST_PER_PANEL, new_app)


@receipt_calculation.ArtShowApplication
def mature_table_cost(app, new_app=None):
    if app.overridden_price is not None or new_app and new_app.overridden_price is not None:
        return
    
    return calc_multiplied_cost_change(app, 'tables_ad', 'Mature Tables', c.COST_PER_TABLE, new_app)


@receipt_calculation.ArtShowApplication
def mailing_fee_cost(app, new_app=None):
    if not new_app and app.delivery_method != c.BY_MAIL:
        return
    elif not new_app:
        return ("Mailing Fee", c.ART_MAILING_FEE * 100, 'delivery_method')

    old_cost = c.ART_MAILING_FEE * 100 if app.delivery_method == c.BY_MAIL else 0
    new_cost = c.ART_MAILING_FEE * 100 if new_app.delivery_method == c.BY_MAIL else 0
    if old_cost == new_cost:
        return

    label = "Add" if not old_cost else "Remove"
    return (f"{label} Mailing Fee", new_cost - old_cost, 'delivery_method')


ArtShowApplication.receipt_changes = {
    'overridden_price': (overridden_app_cost, c.SPACE),
    'panels': (panel_cost, c.SPACE),
    'panels_ad': (mature_panel_cost, c.SPACE),
    'tables': (table_cost, c.SPACE),
    'tables_ad': (mature_table_cost, c.SPACE),
    'delivery_method': (mailing_fee_cost, c.MAIL_IN_FEE),
}


ArtShowApplication.department = c.ART_SHOW_RECEIPT_ITEM


def skip_badge_cost_calc(attendee, new_receipt=False):
    if new_receipt:
        return attendee.promo_code_groups or getattr(attendee, 'badges', None)
    return attendee.paid == c.PAID_BY_GROUP or attendee.promo_code_groups or getattr(attendee, 'badges', None)


def cost_from_base_badge_item(attendee, new_attendee):
    badge_cost_tuple = base_badge_cost(attendee, new_attendee)
    if badge_cost_tuple is None:
        return 0
    x, old_cost, y = badge_cost_tuple
    return old_cost


@receipt_calculation.Attendee
def base_badge_cost(attendee, new_attendee=None):
    """
    Special logic for new receipts only:
    - Skip entirely if this attendee is buying a promo code group, as that is its own item
    - If the badge is upgraded, log the attendee badge type/price, as the upgrade is its own item
    - All badges in c.DEFAULT_COMPED_BADGE_TYPES check for "need not pay" to see if the badge is free,
        otherwise we log their normal cost and add the comp as a separate line-item in another function
    - Finally, if a badge is 'paid by group' it is also logged as a free item
    """
    if new_attendee or skip_badge_cost_calc(attendee, new_receipt=True):
        return
    
    orig_badge_type = attendee.badge_type
    cost = attendee.new_badge_cost * 100
    if attendee.badge_type in c.BADGE_TYPE_PRICES:
        badge_label = c.BADGES[c.ATTENDEE_BADGE]
        orig_badge_type = attendee.orig_value_of('badge_type')

        if orig_badge_type != attendee.badge_type:
            badge_label = c.BADGES[orig_badge_type]

        label = f"{badge_label} Badge for {attendee.full_name}"
    else:
        label = f"{attendee.badge_type_label} Badge for {attendee.full_name}"
    
    if orig_badge_type not in c.DEFAULT_COMPED_BADGE_TYPES and attendee.paid == c.NEED_NOT_PAY:
        cost = 0
    if attendee.paid == c.PAID_BY_GROUP:
        cost = 0
        label = f"{label} (Paid By Group)"
    elif attendee.is_dealer:
        label.replace(c.BADGES[c.ATTENDEE_BADGE], c.DEALER_TERM.title())

    return (label, cost, c.BADGE)


@receipt_calculation.Attendee
def overridden_badge_cost(attendee, new_attendee=None):
    if not new_attendee and (attendee.overridden_price is None or attendee.paid == c.PAID_BY_GROUP):
        return
    elif not new_attendee:
        old_cost = cost_from_base_badge_item(attendee, new_attendee)
        if old_cost == 0:
            if skip_badge_cost_calc(attendee, new_receipt=True):
                old_cost = attendee.calculate_badge_price(include_price_override=False) * 100
            else:
                return
        return ("Custom Badge Price", (attendee.overridden_price * 100) - old_cost, 'overridden_price')

    if attendee.overridden_price is None and new_attendee.overridden_price is None:
        return
    if attendee.paid == c.PAID_BY_GROUP and new_attendee.paid == c.PAID_BY_GROUP:
        return

    old_cost = attendee.calculate_badge_cost() * 100
    new_cost = new_attendee.calculate_badge_cost() * 100

    if old_cost == new_cost:
        return

    label = "Update"

    if attendee.overridden_price is None:
        label = "Set"
    elif new_attendee.overridden_price is None:
        label = "Unset"

    return (f"{label} Custom Badge Price", new_cost - old_cost, 'overridden_price')


@receipt_calculation.Attendee
def badge_upgrade_cost(attendee, new_attendee=None):
    if not new_attendee and attendee.badge_type not in c.BADGE_TYPE_PRICES:
        return
    elif not new_attendee:
        old_cost = attendee.new_badge_cost if attendee.overridden_price is None else attendee.overridden_price
        diff = (c.BADGE_TYPE_PRICES[attendee.badge_type] - old_cost) * 100
        return (f"{attendee.badge_type_label} Badge Upgrade", diff, 'badge_type')
    
    if attendee.badge_type not in c.BADGE_TYPE_PRICES and new_attendee.badge_type not in c.BADGE_TYPE_PRICES:
        return

    old_cost = attendee.base_badge_prices_cost * 100
    new_cost = new_attendee.base_badge_prices_cost * 100

    if attendee.badge_type in c.BADGE_TYPE_PRICES and new_attendee.badge_type in c.BADGE_TYPE_PRICES:
        old_cost = c.BADGE_TYPE_PRICES[attendee.badge_type] * 100
        new_cost = c.BADGE_TYPE_PRICES[new_attendee.badge_type] * 100
        label = "Upgrade" if new_cost > old_cost else "Downgrade"
    elif attendee.badge_type in c.BADGE_TYPE_PRICES:
        old_cost = c.BADGE_TYPE_PRICES[attendee.badge_type] * 100
        label = "Downgrade"
    elif new_attendee.badge_type in c.BADGE_TYPE_PRICES:
        new_cost = c.BADGE_TYPE_PRICES[new_attendee.badge_type] * 100
        label = "Upgrade"
    
    if old_cost == new_cost:
        return
    
    return (f"{label} to {new_attendee.badge_type_label} Badge", new_cost - old_cost, 'badge_type')


@receipt_calculation.Attendee
def extra_donation_cost(attendee, new_attendee=None):
    return calc_simple_cost_change(attendee, 'extra_donation', "Extra Donation", new_attendee)


@receipt_calculation.Attendee
def amount_extra_cost(attendee, new_attendee=None):
    cost_change_tuple = calc_simple_cost_change(attendee, 'amount_extra', "Preordered Merch", new_attendee)
    if not cost_change_tuple:
        return
    prefix, diff, col_name = cost_change_tuple

    prefix.replace("Increase", "Upgrade")
    prefix.replace("Decrease", "Downgrade")
    label = c.DONATION_TIERS[getattr(new_attendee, col_name, getattr(attendee, col_name, 0))]
    return (f"{prefix} to {label}", diff, col_name)


@receipt_calculation.Attendee
def promo_code_group_cost(attendee, new_attendee=None):
    if new_attendee:
        return

    cost_table = defaultdict(int)

    if getattr(attendee, 'badges', None):
        # During prereg we set the number of promo code badges on the attendee model
        cost_table[c.get_group_price() * 100] = int(attendee.badges)
    elif attendee.promo_code_groups:
        for code in attendee.promo_code_groups[0].promo_codes:
            cost_table[code.cost * 100] += 1
    else:
        return

    return ("Group Badge ({})".format(attendee.promo_code_groups[0].name if attendee.promo_code_groups
                                      else getattr(attendee, 'name', 'Unknown')), cost_table, c.GROUP_BADGE)


@receipt_calculation.Attendee
def dealer_badge_credit(attendee, new_attendee=None):
    if not new_attendee:
        # This is rolled into base_badge_cost, since it's just what dealer badges cost
        return
    
    if not attendee.is_dealer and not new_attendee.is_dealer:
        return
    if attendee.overridden_price and new_attendee.overridden_price:
        return
    
    old_cost = attendee.calculate_badge_cost() * 100
    new_cost = new_attendee.calculate_badge_cost() * 100

    if old_cost == new_cost:
        return
    if attendee.paid != new_attendee.paid and new_attendee.paid == c.NOT_PAID:
        return # This cost change will be in the paid status receipt item
    
    if attendee.is_dealer and new_attendee.is_dealer:
        return
    elif attendee.is_dealer:
        return (f"Remove {c.DEALER_TERM.title()} Status", new_cost - old_cost, 'ribbon')
    elif new_attendee.is_dealer:
        return (f"Add {c.DEALER_TERM.title()} Status", new_cost - old_cost, 'ribbon')


@receipt_calculation.Attendee
def badge_comp_credit(attendee, new_attendee=None):
    if not new_attendee:
        old_cost = cost_from_base_badge_item(attendee, new_attendee)
        if old_cost != 0 and attendee.paid == c.NEED_NOT_PAY and not attendee.promo_code:
            return ("Badge Comp", old_cost * -1, 'paid')
        return

    comp_statuses = [c.PAID_BY_GROUP, c.NEED_NOT_PAY]
    if attendee.paid not in comp_statuses and new_attendee.paid not in comp_statuses:
        return

    if attendee.paid in comp_statuses and new_attendee.paid in comp_statuses:
        return
    elif attendee.paid in comp_statuses and new_attendee.paid != c.REFUNDED:
        diff = new_attendee.calculate_badge_cost() * 100
        label = f'Remove Paid Status "{string.capwords(attendee.paid_label)}"'
    elif new_attendee.paid in comp_statuses:
        diff = attendee.badge_cost * 100 * -1
        label = f'Add Paid Status "{string.capwords(new_attendee.paid_label)}"'
    else:
        return

    return (label, diff, 'paid')


@receipt_calculation.Attendee
def age_discount_credit(attendee, new_attendee=None):
    if not new_attendee and (not attendee.qualifies_for_discounts or not attendee.age_discount):
        return
    elif not new_attendee:
        old_cost = cost_from_base_badge_item(attendee, new_attendee)
        if not old_cost:
            return
        
        if abs(attendee.age_discount * 100) > old_cost:
            diff = old_cost * -1
        else:
            diff = attendee.age_discount * 100
        return ("Age Discount", diff, c.BADGE_DISCOUNT)
    
    old_credit = attendee.age_discount if attendee.qualifies_for_discounts else 0
    new_credit = new_attendee.age_discount if new_attendee.qualifies_for_discounts else 0

    if old_credit == new_credit:
        return
    
    if abs(old_credit) > attendee.calculate_badge_cost():
        old_credit = attendee.calculate_badge_cost() * -1
    if abs(new_credit) > new_attendee.calculate_badge_cost():
        new_credit = new_attendee.calculate_badge_cost() * -1

    if old_credit and new_credit:
        return ("Update Age Discount", (new_credit - old_credit) * 100, c.BADGE_DISCOUNT)
    elif old_credit:
        return ("Remove Age Discount", old_credit * 100 * -1, c.BADGE_DISCOUNT)
    elif new_credit:
        return ("Add Age Discount", new_credit * 100, c.BADGE_DISCOUNT)


@receipt_calculation.Attendee
def promo_code_credit(attendee, new_attendee=None):
    if not new_attendee and not attendee.promo_code:
        return
    elif not new_attendee:
        default_cost = attendee.calculate_badge_cost()
        if not default_cost:
            return
        discount = default_cost - attendee.badge_cost_with_promo_code
        if attendee.badge_cost_with_promo_code == 0:
            return ("Badge Comp (Promo Code)", discount * 100 * -1, c.ITEM_COMP)
        else:
            return ("Promo Code Discount", discount * 100 * -1, c.BADGE_DISCOUNT)

    old_cost = attendee.badge_cost_with_promo_code * 100
    new_cost = new_attendee.badge_cost_with_promo_code * 100

    if old_cost == new_cost:
        return

    if attendee.promo_code and new_attendee.promo_code:
        return ("Update Promo Code", new_cost - old_cost, c.BADGE_DISCOUNT)
    elif attendee.promo_code:
        if not old_cost:
            return ("Remove Badge Comp (Promo Code)", new_cost, c.ITEM_COMP)
        return ("Remove Promo Code", new_cost - old_cost, c.BADGE_DISCOUNT)
    elif new_attendee.promo_code:
        if not new_cost:
            return ("Add Badge Comp (Promo Code)", old_cost * -1, c.ITEM_COMP)
        return ("Add Promo Code", new_cost - old_cost, c.BADGE_DISCOUNT)


Attendee.receipt_changes = {
    'overridden_price': (overridden_badge_cost, c.BADGE),
    'badge_type': (badge_upgrade_cost, c.BADGE_UPGRADE),
    'ribbon': (dealer_badge_credit, c.OTHER),
    'paid': (badge_comp_credit, c.ITEM_COMP),
    'extra_donation': (extra_donation_cost, c.DONATION),
    'amount_extra': (amount_extra_cost, c.MERCH),
    'birthdate': (age_discount_credit, c.BADGE_DISCOUNT),
    'promo_code_code': (promo_code_credit, c.BADGE_DISCOUNT), # category changes inside the function
}


Attendee.department = c.REG_RECEIPT_ITEM


@receipt_calculation.Group  # noqa: F811
def table_cost(group, new_group=None):
    if not group.auto_recalc or new_group and not new_group.auto_recalc:
        return
    
    if not new_group:
        table_count = int(float(group.tables))
        if table_count:
            return (f"{table_count} Tables", c.get_table_price(table_count) * 100, 'tables')
        return
    
    old_tables = int(float(group.tables))
    new_tables = int(float(new_group.tables))

    if old_tables == new_tables:
        return
    
    if new_tables > old_tables:
        label = "Add"
    else:
        label = "Remove"
    
    diff = (c.get_table_price(new_tables) - c.get_table_price(old_tables)) * 100
    
    return (f"{label} {abs(new_tables - old_tables)} Tables", diff, 'tables')


@receipt_calculation.Group  # noqa: F811
def badge_cost(group, new_group=None):
    if not group.auto_recalc or new_group and not new_group.auto_recalc:
        return

    if not new_group:
        cost_table = defaultdict(int)

        for attendee in group.attendees:
            if attendee.paid == c.PAID_BY_GROUP and attendee.badge_cost:
                cost_table[attendee.badge_cost * 100] += 1
        return ("Badge", cost_table, c.BADGE)

    old_badges = group.badges
    new_badges = getattr(new_group, 'badges_update', None) # "badges" is a property, so we use a temp variable instead

    if new_badges == old_badges:
        return

    badge_diff = abs(new_badges - old_badges)
    label = c.DEALER_TERM.title() if new_group.is_dealer else "Group"
    category = c.BADGE if new_group.is_dealer else c.GROUP_BADGE

    if new_badges > old_badges:
        return (f"Add {label} Badge", new_group.new_badge_cost * 100, category, badge_diff)
    else:
        cost_table = defaultdict(int)
        ordered_badges = sorted(group.floating, key=lambda a: a.badge_cost, reverse=True)

        if len(ordered_badges) < badge_diff:
            log.error("We tried to compute a group reducing its badges to below its floating badges, "
                      "but that shouldn't be possible!")
            return

        for count in range(badge_diff):
            attendee = ordered_badges[count]
            cost_table[attendee.badge_cost * 100 * -1] += 1
            count += 1
        return (f"Remove {label} Badge", cost_table, category)


@receipt_calculation.Group
def custom_group_cost(group, new_group=None):
    if not new_group and group.auto_recalc:
        return
    elif not new_group:
        group_name = c.DEALER_TERM.title() if group.is_dealer else "Group"
        return (f"{group_name} (Custom Fee)".format(group.name), group.cost * 100, ('auto_recalc', 'cost'))
    
    if group.auto_recalc and new_group.auto_recalc:
        return
    
    if not group.auto_recalc and not new_group.auto_recalc:
        diff = (new_group.cost - group.cost) * 100
        label = "Update"
    elif not group.auto_recalc:
        diff = (new_group.calc_default_cost() - group.cost) * 100
        label = "Unset"
    elif not new_group.auto_recalc:
        diff = (new_group.cost - group.cost) * 100
        label = "Set"
    
    if not diff:
        return
    
    return (f"{label} Custom Fee", diff, ('auto_recalc', 'cost'))


Group.receipt_changes = {
    'tables': (table_cost, c.TABLE),
    'badges': (badge_cost, c.BADGE),
    'cost': (custom_group_cost, c.CUSTOM_FEE),
    'auto_recalc': (custom_group_cost, c.CUSTOM_FEE),
}


Group.department = c.REG_RECEIPT_ITEM # set to c.DEALER_RECEIPT_ITEM in ReceiptManager functions if group is dealer
