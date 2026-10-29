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
import logging
from collections import defaultdict
from typing import Any

from uber.config import c
from uber.decorators import receipt_calculation
from uber.money import Money
from uber.models import Attendee, ArtShowApplication, Group, ArtistMarketplaceApplication

log = logging.getLogger(__name__)

ReceiptItemResult = (
    tuple[str, Money | dict[Money, int] | None, str | tuple[str, ...] | int | None]
    | tuple[str, Money | dict[Money, int] | None, str | tuple[str, ...] | int | None, int]
    | None
)


def calc_simple_cost_change(model: Attendee, col_name: str, col_str: str, new_model: Attendee | None = None) -> ReceiptItemResult:
    """
    Takes an instance of a model and attempts to calculate a simple cost change
    based on a column name. Used for columns where the cost is the column, e.g.,
    extra_donation and amount_extra.
    """
    col_val = getattr(model, col_name, 0)
    col_money = col_val if isinstance(col_val, Money) else Money.from_dollars(col_val or 0)
    if not new_model:
        return (col_str, col_money, col_name) if col_money else None
    
    new_val = getattr(new_model, col_name, 0)
    new_money = new_val if isinstance(new_val, Money) else Money.from_dollars(new_val or 0)
    if new_money > col_money:
        label = "Increase"
    else:
        label = "Decrease"
    
    diff = new_money - col_money
    if diff:
        return (f"{label} {col_str}", diff, col_name)
    return None


def calc_multiplied_cost_change(app: ArtShowApplication, col_name: str, col_str: str, price_per: Money, new_app: ArtShowApplication | None = None) -> ReceiptItemResult:
    col_val = getattr(app, col_name)

    if not new_app:    
        return (col_str, price_per, col_name, col_val) if col_val else None
    
    new_val = getattr(new_app, col_name)

    if new_val > col_val:
        label = "Add"
        cost_mod = 1
    else:
        label = "Remove"
        cost_mod = -1
    diff = new_val - col_val

    if diff:
        return (f"{label} {col_str}", price_per * cost_mod, col_name, abs(diff))
    return None


@receipt_calculation.ArtistMarketplaceApplication
def app_cost(app: ArtistMarketplaceApplication) -> ReceiptItemResult:
    if app.status == c.APPROVED:
        fee = app.overridden_price or Money.from_dollars(getattr(c, 'MARKETPLACE_FEE', 0) or getattr(c, 'ARTIST_MARKETPLACE_FEE', 0))
        return ("Marketplace Application Fee", fee, None)
    return None


@receipt_calculation.ArtShowApplication
def overridden_app_cost(app: ArtShowApplication, new_app: ArtShowApplication | None = None) -> ReceiptItemResult:
    if not new_app:
        if app.overridden_price is None:
            return None
        return ("Art Show Application (Custom Fee)", app.overridden_price, 'overridden_price')
    
    if app.overridden_price is None and new_app.overridden_price is None:
        return None
    
    if new_app.overridden_price is None:
        new_cost = Money.from_dollars(new_app.panels_and_tables_cost)
    else:
        new_cost = new_app.overridden_price

    if app.overridden_price is None:
        diff = new_cost - Money.from_dollars(app.panels_and_tables_cost)
        label = "Set"
    elif new_app.overridden_price is None:
        diff = new_cost - app.overridden_price
        label = "Unset"
    else:
        diff = new_cost - app.overridden_price
        label = "Update"

    if diff:
        return (f"{label} Custom Fee", diff, 'overridden_price')
    return None


@receipt_calculation.ArtShowApplication
def panel_cost(app: ArtShowApplication, new_app: ArtShowApplication | None = None) -> ReceiptItemResult:
    if app.overridden_price is not None or new_app and new_app.overridden_price is not None:
        return None

    return calc_multiplied_cost_change(app, 'panels', 'General Panels', Money.from_dollars(c.COST_PER_PANEL), new_app)


@receipt_calculation.ArtShowApplication
def table_cost(app: ArtShowApplication, new_app: ArtShowApplication | None = None) -> ReceiptItemResult:
    if app.overridden_price is not None or new_app and new_app.overridden_price is not None:
        return None
    
    return calc_multiplied_cost_change(app, 'tables', 'General Tables', Money.from_dollars(c.COST_PER_TABLE), new_app)


@receipt_calculation.ArtShowApplication
def mature_panel_cost(app: ArtShowApplication, new_app: ArtShowApplication | None = None) -> ReceiptItemResult:
    if app.overridden_price is not None or new_app and new_app.overridden_price is not None:
        return None
    
    return calc_multiplied_cost_change(app, 'panels_ad', 'Mature Panels', Money.from_dollars(c.COST_PER_PANEL), new_app)


@receipt_calculation.ArtShowApplication
def mature_table_cost(app: ArtShowApplication, new_app: ArtShowApplication | None = None) -> ReceiptItemResult:
    if app.overridden_price is not None or new_app and new_app.overridden_price is not None:
        return None
    
    return calc_multiplied_cost_change(app, 'tables_ad', 'Mature Tables', Money.from_dollars(c.COST_PER_TABLE), new_app)


@receipt_calculation.ArtShowApplication
def mailing_fee_cost(app: ArtShowApplication, new_app: ArtShowApplication | None = None) -> ReceiptItemResult:
    if not new_app and app.delivery_method != c.BY_MAIL:
        return None
    elif not new_app:
        return ("Mailing Fee", Money.from_dollars(app.mailing_fee), 'delivery_method')

    old_cost = Money.from_dollars(app.mailing_fee) if app.delivery_method == c.BY_MAIL else Money.zero()
    new_cost = Money.from_dollars(new_app.mailing_fee) if new_app.delivery_method == c.BY_MAIL else Money.zero()
    if old_cost == new_cost:
        return None

    if not old_cost:
        label = "Add"
    elif not new_cost:
        label = "Remove"
    elif new_cost > old_cost:
        label = "Increase"
    else:
        label = "Decrease"

    return (f"{label} Mailing Fee", new_cost - old_cost, 'delivery_method')


ArtShowApplication.receipt_changes = {
    'overridden_price': (overridden_app_cost, c.SPACE),
    'panels': (panel_cost, c.SPACE),
    'panels_ad': (mature_panel_cost, c.SPACE),
    'tables': (table_cost, c.SPACE),
    'tables_ad': (mature_table_cost, c.SPACE),
    'delivery_method': (mailing_fee_cost, c.MAIL_IN_FEE),
    'mailing_fee_update': (mailing_fee_cost, c.MAIL_IN_FEE),
}


ArtShowApplication.department = c.ART_SHOW_RECEIPT_ITEM


def skip_badge_cost_calc(attendee: Attendee, new_receipt: bool = False) -> bool:
    if new_receipt:
        return bool(attendee.promo_code_groups or getattr(attendee, 'badges', None))
    return bool(attendee.paid == c.PAID_BY_GROUP or attendee.promo_code_groups or getattr(attendee, 'badges', None))


def cost_from_base_badge_item(attendee: Attendee, new_attendee: Attendee | None = None) -> Money:
    badge_cost_tuple = base_badge_cost(attendee, new_attendee)
    if badge_cost_tuple is None:
        return Money.zero()
    old_cost = badge_cost_tuple[1]
    return old_cost if isinstance(old_cost, Money) else Money.zero()


@receipt_calculation.Attendee
def base_badge_cost(attendee: Attendee, new_attendee: Attendee | None = None) -> ReceiptItemResult:
    """
    Special logic for new receipts only:
    - Skip entirely if this attendee is buying a promo code group, as that is its own item
    - If the badge is upgraded, log the attendee badge type/price, as the upgrade is its own item
    - All badges in c.DEFAULT_COMPED_BADGE_TYPES are free if they're prereg badges or marked NEED_NOT_PAY,
        otherwise we log their normal cost and add the comp as a separate line-item in another function
    - Finally, if a badge is 'paid by group' it is also logged as a free item
    """
    if new_attendee or skip_badge_cost_calc(attendee, new_receipt=True):
        return None

    orig_badge_type = attendee.badge_type
    cost = Money.from_dollars(attendee.new_badge_cost)
    if attendee.badge_type in c.BADGE_TYPE_PRICES:
        badge_label = c.BADGES[c.ATTENDEE_BADGE]
        orig_badge_type = attendee.orig_value_of('badge_type') or attendee.badge_type

        if orig_badge_type != attendee.badge_type:
            badge_label = c.BADGES[orig_badge_type]

        label = f"{badge_label} Badge for {attendee.full_name}"
    else:
        label = f"{attendee.badge_type_label} Badge for {attendee.full_name}"

    if orig_badge_type in c.DEFAULT_COMPED_BADGE_TYPES and (attendee.paid == c.NEED_NOT_PAY or
                                                            attendee.creator is None):
        cost = Money.zero()
    if attendee.paid == c.PAID_BY_GROUP:
        cost = Money.zero()
        label = f"{label} (Paid By Group)"
    elif attendee.is_dealer:
        label.replace(c.BADGES[c.ATTENDEE_BADGE], c.DEALER_TERM.title())

    return (label, cost, c.BADGE)


@receipt_calculation.Attendee
def overridden_badge_cost(attendee: Attendee, new_attendee: Attendee | None = None) -> ReceiptItemResult:
    if not new_attendee and (attendee.overridden_price is None or attendee.paid == c.PAID_BY_GROUP):
        return None
    elif not new_attendee:
        old_cost = cost_from_base_badge_item(attendee, new_attendee)
        if old_cost == 0:
            if skip_badge_cost_calc(attendee, new_receipt=True):
                old_cost = attendee.calculate_badge_cost(include_price_override=False)
        return ("Custom Badge Price", attendee.overridden_price - old_cost, 'overridden_price')

    if attendee.overridden_price is None and new_attendee.overridden_price is None:
        return None
    if attendee.paid == c.PAID_BY_GROUP and new_attendee.paid == c.PAID_BY_GROUP:
        return None

    # Check paid by group for converting dealer badges
    old_cost = Money.zero() if attendee.paid == c.PAID_BY_GROUP else (
        attendee.overridden_price if attendee.overridden_price is not None
        else attendee.calculate_badge_cost()
    )
    new_cost = Money.zero() if new_attendee.paid == c.PAID_BY_GROUP else (
        new_attendee.overridden_price if new_attendee.overridden_price is not None
        else new_attendee.calculate_badge_cost()
    )

    if old_cost == new_cost:
        return None

    label = "Update"

    if attendee.overridden_price is None:
        label = "Set"
    elif new_attendee.overridden_price is None:
        label = "Unset"

    return (f"{label} Custom Badge Price", new_cost - old_cost, 'overridden_price')


def needs_badge_change_calc(attendee: Attendee) -> bool:
    return attendee.is_presold_oneday or attendee.badge_type == c.ONE_DAY_BADGE or attendee.badge_type in c.BADGE_TYPE_PRICES


def one_day_or_upgraded_badge_cost(attendee: Attendee) -> int:
    if attendee.badge_type in c.BADGE_TYPE_PRICES:
        return c.BADGE_TYPE_PRICES[attendee.badge_type]
    return attendee.new_badge_cost


@receipt_calculation.Attendee
def badge_upgrade_cost(attendee: Attendee, new_attendee: Attendee | None = None) -> ReceiptItemResult:
    if not new_attendee and attendee.badge_type in c.BADGE_TYPE_PRICES:
        new_cost = Money.from_dollars(c.BADGE_TYPE_PRICES[attendee.badge_type])
        old_cost = cost_from_base_badge_item(attendee, new_attendee)
        if old_cost == 0:
            if skip_badge_cost_calc(attendee, new_receipt=True):
                old_cost = attendee.calculate_badge_cost(include_price_override=False)
        return (f"Upgrade to {attendee.badge_type_label} Badge", new_cost - old_cost, 'badge_type')
    elif not new_attendee:
        return None

    if not needs_badge_change_calc(attendee) and not needs_badge_change_calc(new_attendee):
        return None

    old_cost = attendee.base_badge_prices_cost
    new_cost = new_attendee.base_badge_prices_cost

    if needs_badge_change_calc(attendee) and needs_badge_change_calc(new_attendee):
        old_cost = Money.from_dollars(one_day_or_upgraded_badge_cost(attendee))
        new_cost = Money.from_dollars(one_day_or_upgraded_badge_cost(new_attendee))
    elif needs_badge_change_calc(attendee):
        old_cost = Money.from_dollars(one_day_or_upgraded_badge_cost(attendee))
    elif needs_badge_change_calc(new_attendee):
        new_cost = Money.from_dollars(one_day_or_upgraded_badge_cost(new_attendee))
    label = "Upgrade" if new_cost > old_cost else "Downgrade"

    if old_cost == new_cost:
        return None
    
    return (f"{label} to {new_attendee.badge_type_label} Badge", new_cost - old_cost, 'badge_type')


@receipt_calculation.Attendee
def extra_donation_cost(attendee: Attendee, new_attendee: Attendee | None = None) -> ReceiptItemResult:
    return calc_simple_cost_change(attendee, 'extra_donation', "Extra Donation", new_attendee)


@receipt_calculation.Attendee
def amount_extra_cost(attendee: Attendee, new_attendee: Attendee | None = None) -> ReceiptItemResult:
    from uber.custom_tags import format_currency

    if c.MERCH_TAX:
        amount_extra = attendee.amount_extra
        if not new_attendee:
            if not amount_extra:
                return None
            tax = c.get_amount_extra_tax(amount_extra)
            total = Money.from_dollars(amount_extra + tax)
            label = c.DONATION_TIERS[amount_extra] + f" (Includes {format_currency(amount_extra)} base price + {format_currency(tax)} Sales Tax)"
            return (f"Upgrade to {label}", total, 'amount_extra')
        
        new_amount_extra = new_attendee.amount_extra
        if new_amount_extra > amount_extra:
            prefix = "Upgrade"
        else:
            prefix = "Downgrade"
        
        diff = (new_amount_extra - amount_extra)
        if diff:
            old_total = amount_extra + c.get_amount_extra_tax(amount_extra)
            new_tax = c.get_amount_extra_tax(new_amount_extra)
            new_total = new_amount_extra + new_tax
            label = c.DONATION_TIERS[new_amount_extra]
            if diff > 0:
                label += f" (Includes {format_currency(new_amount_extra)} base price + {format_currency(new_tax)} Sales Tax)"
            real_diff = Money.from_dollars(new_total - old_total)
            return (f"{prefix} to {label}", real_diff, 'amount_extra')
        return None

    cost_change_tuple = calc_simple_cost_change(attendee, 'amount_extra', "Preordered Merch", new_attendee)
    if not cost_change_tuple:
        return None
    prefix, cost_diff, col_name = cost_change_tuple[0], cost_change_tuple[1], cost_change_tuple[2]

    prefix = prefix.replace("Increase", "Upgrade").replace("Decrease", "Downgrade")
    label = c.DONATION_TIERS[getattr(new_attendee, str(col_name), getattr(attendee, str(col_name), 0))]
    return (f"{prefix} to {label}", cost_diff, col_name)


@receipt_calculation.Attendee
def promo_code_group_cost(attendee: Attendee, new_attendee: Attendee | None = None) -> ReceiptItemResult:
    if new_attendee:
        return None

    cost_table: dict[Money, int] = defaultdict(int)

    if getattr(attendee, 'badges', None):
        # During prereg we set the number of promo code badges on the attendee model
        cost_table[Money.from_dollars(c.get_group_price())] = int(attendee.badges)
    elif attendee.promo_code_groups:
        for code in attendee.promo_code_groups[0].promo_codes:
            code_cost = code.cost if isinstance(code.cost, Money) else Money.from_dollars(code.cost or 0)
            cost_table[code_cost] += 1
    else:
        return None

    return ("Group Badge ({})".format(attendee.promo_code_groups[0].name if attendee.promo_code_groups
                                      else getattr(attendee, 'name', 'Unknown')), cost_table, c.GROUP_BADGE)


@receipt_calculation.Attendee
def dealer_badge_credit(attendee: Attendee, new_attendee: Attendee | None = None) -> ReceiptItemResult:
    if not new_attendee:
        # This is rolled into base_badge_cost, since it's just what dealer badges cost
        return None
    
    if not attendee.is_dealer and not new_attendee.is_dealer:
        return None
    if attendee.overridden_price and new_attendee.overridden_price:
        return None
    
    old_cost = attendee.calculate_badge_cost()
    new_cost = new_attendee.calculate_badge_cost()

    if old_cost == new_cost:
        return None
    if attendee.paid != new_attendee.paid and new_attendee.paid == c.NOT_PAID:
        return None # This cost change will be in the paid status receipt item
    
    if attendee.is_dealer and new_attendee.is_dealer:
        return None
    elif attendee.is_dealer:
        return (f"Remove {c.DEALER_TERM.title()} Status", new_cost - old_cost, 'ribbon')
    elif new_attendee.is_dealer:
        return (f"Add {c.DEALER_TERM.title()} Status", new_cost - old_cost, 'ribbon')
    return None


@receipt_calculation.Attendee
def badge_comp_credit(attendee: Attendee, new_attendee: Attendee | None = None) -> ReceiptItemResult:
    if not new_attendee:
        old_cost = cost_from_base_badge_item(attendee, new_attendee)
        if old_cost != 0 and attendee.paid == c.NEED_NOT_PAY and not attendee.promo_code:
            return ("Badge Comp", -old_cost, 'paid')
        return None

    comp_statuses = [c.PAID_BY_GROUP, c.NEED_NOT_PAY]
    if attendee.paid not in comp_statuses and new_attendee.paid not in comp_statuses:
        return None

    if attendee.paid in comp_statuses and new_attendee.paid in comp_statuses:
        return None
    elif attendee.paid in comp_statuses and new_attendee.paid != c.REFUNDED:
        diff = new_attendee.calculate_badge_cost()
        label = f'Remove Paid Status "{string.capwords(attendee.paid_label)}"'
    elif new_attendee.paid in comp_statuses:
        diff = -attendee.badge_cost if attendee.badge_cost else Money.zero()
        label = f'Add Paid Status "{string.capwords(new_attendee.paid_label)}"'
    else:
        return None

    return (label, diff, 'paid')


Attendee.receipt_changes = {
    'overridden_price': (overridden_badge_cost, c.BADGE),
    'badge_type': (badge_upgrade_cost, c.BADGE_UPGRADE),
    'ribbon': (dealer_badge_credit, c.OTHER),
    'paid': (badge_comp_credit, c.ITEM_COMP),
    'extra_donation': (extra_donation_cost, c.DONATION),
    'amount_extra': (amount_extra_cost, c.MERCH),
}


Attendee.department = c.REG_RECEIPT_ITEM


@receipt_calculation.Group  # type: ignore[no-redef]  # noqa: F811
def table_cost(group: Group, new_group: Group | None = None) -> ReceiptItemResult:
    if not group.auto_recalc or new_group and not new_group.auto_recalc:
        return None
    
    if not new_group:
        table_count = int(float(group.tables))
        if table_count:
            return (f"{table_count} Tables", Money.from_dollars(c.get_table_price(table_count)), 'tables')
        return None
    
    old_tables = int(float(group.tables))
    new_tables = int(float(new_group.tables))

    if old_tables == new_tables:
        return None
    
    if new_tables > old_tables:
        label = "Add"
    else:
        label = "Remove"
    
    diff = Money.from_dollars(c.get_table_price(new_tables) - c.get_table_price(old_tables))
    
    return (f"{label} {abs(new_tables - old_tables)} Tables", diff, 'tables')


@receipt_calculation.Group  # noqa: F811
def badge_cost(group: Group, new_group: Group | None = None) -> ReceiptItemResult:
    if not group.auto_recalc or new_group and not new_group.auto_recalc:
        return None

    if not new_group:
        cost_table: dict[Money, int] = defaultdict(int)

        for attendee in group.attendees:
            if attendee.paid == c.PAID_BY_GROUP and attendee.badge_cost:
                cost_table[attendee.badge_cost] += 1
        return ("Badge", cost_table, c.BADGE)

    old_badges = group.badges
    new_badges = getattr(new_group, 'badges_update', None) # "badges" is a property, so we use a temp variable instead

    if new_badges == old_badges:
        return None

    badge_diff = abs(new_badges - old_badges)
    label = c.DEALER_TERM.title() if new_group.is_dealer else "Group"
    category = c.BADGE if new_group.is_dealer else c.GROUP_BADGE

    if new_badges > old_badges:
        return (f"Add {label} Badge", Money.from_dollars(new_group.new_badge_cost), category, badge_diff)
    else:
        cost_table = defaultdict(int)
        ordered_badges = sorted(group.floating, key=lambda a: a.badge_cost or Money.zero(), reverse=True)

        if len(ordered_badges) < badge_diff:
            log.error("We tried to compute a group reducing its badges to below its floating badges, "
                      "but that shouldn't be possible!")
            return None

        for count in range(badge_diff):
            attendee = ordered_badges[count]
            cost_table[-(attendee.badge_cost or Money.zero())] += 1
            count += 1
        return (f"Remove {label} Badge", cost_table, category)


@receipt_calculation.Group
def custom_group_cost(group: Group, new_group: Group | None = None) -> ReceiptItemResult:
    if not new_group and group.auto_recalc:
        return None
    elif not new_group:
        group_name = c.DEALER_TERM.title() if group.is_dealer else "Group"
        return (f"{group_name} (Custom Fee)".format(group.name), group.cost, ('auto_recalc', 'cost'))
    
    if group.auto_recalc and new_group.auto_recalc:
        return None
    
    if not group.auto_recalc and not new_group.auto_recalc:
        diff = new_group.cost - group.cost
        label = "Update"
    elif not group.auto_recalc:
        diff = new_group.calc_default_cost() - group.cost
        label = "Unset"
    elif not new_group.auto_recalc:
        diff = new_group.cost - group.cost
        label = "Set"
    
    if not diff:
        return None
    
    return (f"{label} Custom Fee", diff, ('auto_recalc', 'cost'))


Group.receipt_changes = {
    'tables': (table_cost, c.TABLE),
    'badges': (badge_cost, c.BADGE),
    'cost': (custom_group_cost, c.CUSTOM_FEE),
    'auto_recalc': (custom_group_cost, c.CUSTOM_FEE),
}


Group.department = c.REG_RECEIPT_ITEM # set to c.DEALER_RECEIPT_ITEM in ReceiptManager functions if group is dealer
