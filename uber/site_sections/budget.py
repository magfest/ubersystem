import math
import re
import logging

from collections import defaultdict
from residue import CoerceUTF8 as UnicodeText
from sqlalchemy.orm import joinedload
from sqlalchemy import or_, func, not_, and_

from uber.config import c
from uber.decorators import all_renderable, log_pageview
from uber.models import ArbitraryCharge, Attendee, Group, ModelReceipt, MPointsForCash, ReceiptItem, Sale, PromoCodeGroup
from uber.server import redirect_site_section
from uber.utils import localized_now, Order

log = logging.getLogger(__name__)


def _build_item_subquery(session):
    return session.query(ModelReceipt.owner_id, ModelReceipt.item_total_sql.label('item_total')
                         ).join(ModelReceipt.receipt_items).group_by(ModelReceipt.owner_id).subquery()

def _build_txn_subquery(session):
    return session.query(ModelReceipt.owner_id, ModelReceipt.payment_total_sql.label('payment_total'),
                         ModelReceipt.refund_total_sql.label('refund_total')
                         ).join(ModelReceipt.receipt_txns).group_by(ModelReceipt.owner_id).subquery()

def get_grouped_costs(session, filters=[], joins=[], selector=Attendee.badge_cost):
    # Returns a defaultdict with the {int(cost): count} of badges
    query = session.query(selector, func.count(selector))
    for join in joins:
        query = query.join(join)
    if filters:
        query = query.filter(*filters)
    return defaultdict(int, query.group_by(selector).order_by(selector).all())


def get_dict_sum(dict_to_sum):
    return sum([dict_to_sum[key] * key for key in dict_to_sum])


@all_renderable()
class Root:
    @log_pageview
    def index(self, session):
        receipt_items = session.query(ReceiptItem)
        receipt_total = sum([item.amount for item in receipt_items.filter_by(txn_type=c.PAYMENT).all()]
                            ) - sum([item.amount for item in receipt_items.filter_by(txn_type=c.REFUND).all()])
        sales_total = sum([sale.cash * 100 for sale in session.query(Sale).all()])
        arbitrary_charge_total = sum([charge.amount * 100 for charge in session.query(ArbitraryCharge).all()])
        return {
            'receipt_items': receipt_items.filter_by(txn_type=c.REFUND),
            'arbitrary_charges': session.query(ArbitraryCharge),
            'sales': session.query(Sale),
            'total': receipt_total + sales_total + arbitrary_charge_total,
        }

    def badge_cost_summary(self, session):
        attendees = session.query(Attendee)
        item_subquery = _build_item_subquery(session)
        txn_subquery = _build_txn_subquery(session)

        base_filter = [Attendee.has_or_will_have_badge]

        group_filter = base_filter + [Attendee.group_id != None, Attendee.paid == c.PAID_BY_GROUP]  # noqa: E711
        badge_cost_matters_filter = [Group.cost > 0, Group.auto_recalc == True]  # noqa: E712

        group_counts = {}

        group_counts['free_groups'] = session.query(Attendee).filter(
            *group_filter).join(Attendee.group).filter(Group.cost <= 0).count()
        group_counts['custom_price'] = session.query(Attendee).filter(
            *group_filter).join(Attendee.group).filter(Group.cost > 0, Group.auto_recalc == False).count()  # noqa: E712

        group_subquery_base = session.query(Attendee.id).filter(*group_filter).outerjoin(
            Attendee.group).filter(*badge_cost_matters_filter).outerjoin(
                item_subquery, Group.id == item_subquery.c.owner_id
                ).outerjoin(txn_subquery, Group.id == txn_subquery.c.owner_id).group_by(Attendee.id).group_by(
                    item_subquery.c.item_total).group_by(txn_subquery.c.payment_total).group_by(
                        txn_subquery.c.refund_total)

        paid_group_subquery = group_subquery_base.having(
            (txn_subquery.c.payment_total - txn_subquery.c.refund_total) >= item_subquery.c.item_total).subquery()
        unpaid_group_subquery = group_subquery_base.having(
            (txn_subquery.c.payment_total - txn_subquery.c.refund_total) < item_subquery.c.item_total).subquery()
        paid_group_badges = get_grouped_costs(
            session, joins=[(paid_group_subquery, Attendee.id == paid_group_subquery.c.id)])
        unpaid_group_badges = get_grouped_costs(
            session, joins=[(unpaid_group_subquery, Attendee.id == unpaid_group_subquery.c.id)])
        no_receipt_group_badges = get_grouped_costs(session,
                                                    filters=group_filter + badge_cost_matters_filter + [
                                                        Attendee.default_cost > 0, ~Attendee.active_receipt.has()],
                                                    joins=[Attendee.group])
        for key, val in no_receipt_group_badges.items():
            unpaid_group_badges[key] += val

        group_total = session.query(Attendee).filter(*group_filter).count()

        pc_group_filter = base_filter + [Attendee.promo_code_group_name != None]  # noqa: E711
        paid_pc_group_filter = pc_group_filter + [PromoCodeGroup.total_cost > 0]

        pc_comped_badges = 0
        pc_unused_badges = defaultdict(int)
        pc_group_total = session.query(Attendee).filter(*pc_group_filter).count()

        pc_group_leaders = session.query(Attendee).filter(Attendee.promo_code_groups != None).count()  # noqa: E711
        pc_group_badges = get_grouped_costs(session, paid_pc_group_filter)

        for group in session.query(PromoCodeGroup).filter(PromoCodeGroup.total_cost <= 0):
            pc_comped_badges += len(group.used_promo_codes)

        for group in session.query(PromoCodeGroup).filter(PromoCodeGroup.total_cost > 0):
            for code in group.unused_codes:
                pc_unused_badges[code.cost] += 1
                pc_group_total += 1

        individual_filter = base_filter + [not_(Attendee.paid.in_([c.PAID_BY_GROUP, c.NEED_NOT_PAY])),
                                           Attendee.promo_code_group_name == None,  # noqa: E711
                                           Attendee.badge_cost > 0]
        ind_subquery_base = session.query(Attendee.id).filter(*individual_filter).outerjoin(
                item_subquery, Attendee.id == item_subquery.c.owner_id
                ).outerjoin(txn_subquery, Attendee.id == txn_subquery.c.owner_id).group_by(Attendee.id).group_by(
                    item_subquery.c.item_total).group_by(txn_subquery.c.payment_total).group_by(
                        txn_subquery.c.refund_total)
        
        paid_ind_subquery = ind_subquery_base.having(
            (txn_subquery.c.payment_total - txn_subquery.c.refund_total) >= item_subquery.c.item_total).subquery()
        unpaid_ind_subquery = ind_subquery_base.having(
            (txn_subquery.c.payment_total - txn_subquery.c.refund_total) < item_subquery.c.item_total).subquery()

        individual_badges = get_grouped_costs(session, joins=[(paid_ind_subquery, Attendee.id == paid_ind_subquery.c.id)])
        unpaid_badges = get_grouped_costs(session, filters=[Attendee.default_cost > 0],
                                          joins=[(unpaid_ind_subquery, Attendee.id == unpaid_ind_subquery.c.id)])
        no_receipt_badges = get_grouped_costs(session,
                                              filters=individual_filter + [Attendee.default_cost > 0,
                                                                           ~Attendee.active_receipt.has()])
        for key, val in no_receipt_badges.items():
            unpaid_badges[key] += val

        comped_badges = session.query(Attendee).filter(*base_filter,
                                                       Attendee.promo_code_group_name == None,  # noqa: E711
                                                       Attendee.paid == c.NEED_NOT_PAY).count()
        individual_total = session.query(Attendee).filter(*individual_filter).count() + comped_badges

        return {
            'total_badges': attendees.filter(*base_filter).count(),
            'group_total': group_total,
            'group_counts': group_counts,
            'group_badges': paid_group_badges,
            'group_badges_total': sum(paid_group_badges.values()),
            'group_badges_sum': get_dict_sum(paid_group_badges),
            'unpaid_group_badges': unpaid_group_badges,
            'unpaid_group_badges_total': sum(unpaid_group_badges.values()),
            'unpaid_group_sum': get_dict_sum(unpaid_group_badges),
            'pc_group_total': pc_group_total,
            'pc_group_leaders': pc_group_leaders,
            'pc_comped_badges': pc_comped_badges,
            'pc_claimed_badges': pc_group_badges,
            'pc_claimed_badges_total': sum(pc_group_badges.values()),
            'pc_claimed_badges_sum': get_dict_sum(pc_group_badges),
            'pc_unused_badges': pc_unused_badges,
            'pc_unused_badges_total': sum(pc_unused_badges.values()),
            'pc_unused_badges_sum': get_dict_sum(pc_unused_badges),
            'individual_total': individual_total,
            'comped_badges': comped_badges,
            'individual_badges': individual_badges,
            'individual_badges_total': sum(individual_badges.values()),
            'individual_badges_sum': get_dict_sum(individual_badges),
            'unpaid_badges': unpaid_badges,
            'unpaid_badges_total': sum(unpaid_badges.values()),
            'unpaid_badges_sum': get_dict_sum(unpaid_badges),
            'now': localized_now(),
        }

    def dealer_cost_summary(self, session):
        dealers = session.query(Group).filter(Group.is_dealer == True,  # noqa: E712
                                              Group.attendees_have_badges == True, Group.cost > 0)  # noqa: E712

        paid_total = 0
        paid_custom = defaultdict(int)
        paid_tables = defaultdict(int)
        paid_table_sums = defaultdict(int)
        paid_badges = defaultdict(int)

        unpaid_total = 0
        unpaid_custom = defaultdict(int)
        unpaid_tables = defaultdict(int)
        unpaid_table_sums = defaultdict(int)
        unpaid_badges = defaultdict(int)

        for group in dealers:
            if group.is_paid:
                paid_total += 1
                if not group.auto_recalc:
                    paid_custom['count'] += 1
                    paid_custom['sum'] += group.cost
                else:
                    paid_tables[group.tables] += 1
                    paid_badges[group.badges_purchased] += 1
            else:
                unpaid_total += 1
                if not group.auto_recalc:
                    unpaid_custom['count'] += 1
                    unpaid_custom['sum'] += group.cost
                else:
                    unpaid_tables[group.tables] += 1
                    unpaid_badges[group.badges_purchased] += 1

        for dict in [paid_tables, paid_badges, unpaid_tables, unpaid_badges]:
            dict.pop(0, None)

        for tables in paid_tables:
            paid_table_sums[tables] = c.get_table_price(tables) * paid_tables[tables]
        for tables in unpaid_tables:
            unpaid_table_sums[tables] = c.get_table_price(tables) * unpaid_tables[tables]

        return {
            'total_dealers': dealers.count(),
            'paid_total': paid_total,
            'paid_custom': paid_custom,
            'paid_tables': paid_tables,
            'paid_tables_total': get_dict_sum(paid_tables),
            'paid_table_sums': paid_table_sums,
            'all_paid_tables_sum': sum(paid_table_sums.values()),
            'paid_badges': paid_badges,
            'paid_badges_total': get_dict_sum(paid_badges),
            'unpaid_total': unpaid_total,
            'unpaid_custom': unpaid_custom,
            'unpaid_tables': unpaid_tables,
            'unpaid_tables_total': get_dict_sum(unpaid_tables),
            'unpaid_table_sums': unpaid_table_sums,
            'all_unpaid_tables_sum': sum(unpaid_table_sums.values()),
            'unpaid_badges': unpaid_badges,
            'unpaid_badges_total': get_dict_sum(unpaid_badges),
            'now': localized_now(),
        }

    def attendee_addon_summary(self, session):
        base_filter = [Attendee.has_or_will_have_badge]
        preordered_merch_filter = base_filter + [Attendee.amount_extra > 0]
        extra_donation_filter = base_filter + [Attendee.extra_donation > 0]
        badge_upgrade_filter = base_filter + [Attendee.badge_type.in_(c.BADGE_TYPE_PRICES)]

        item_subquery = _build_item_subquery(session)
        txn_subquery = _build_txn_subquery(session)

        addons_subquery_base = session.query(Attendee.id).outerjoin(
                item_subquery, Attendee.id == item_subquery.c.owner_id
                ).outerjoin(txn_subquery, Attendee.id == txn_subquery.c.owner_id).group_by(Attendee.id).group_by(
                    item_subquery.c.item_total).group_by(txn_subquery.c.payment_total).group_by(
                        txn_subquery.c.refund_total)
        
        paid_addons_subquery = addons_subquery_base.having(
            (txn_subquery.c.payment_total - txn_subquery.c.refund_total) >= item_subquery.c.item_total).subquery()
        unpaid_addons_subquery = addons_subquery_base.having(
            (txn_subquery.c.payment_total - txn_subquery.c.refund_total) < item_subquery.c.item_total).subquery()

        paid_preordered_merch = get_grouped_costs(session,
                                                  filters=preordered_merch_filter,
                                                  joins=[(paid_addons_subquery, Attendee.id == paid_addons_subquery.c.id)],
                                                  selector=Attendee.amount_extra)
        unpaid_preordered_merch = get_grouped_costs(session,
                                                    filters=preordered_merch_filter + [Attendee.default_cost > 0],
                                                    joins=[(unpaid_addons_subquery, Attendee.id == unpaid_addons_subquery.c.id)],
                                                    selector=Attendee.amount_extra)
        no_receipt_preordered_merch = get_grouped_costs(session,
                                                       filters=preordered_merch_filter + [Attendee.default_cost > 0,
                                                                                          ~Attendee.active_receipt.has()],
                                                       selector=Attendee.amount_extra)
        for key, val in no_receipt_preordered_merch.items():
            unpaid_preordered_merch[key] += val

        paid_extra_donations = get_grouped_costs(session,
                                                 filters=extra_donation_filter,
                                                 joins=[(paid_addons_subquery, Attendee.id == paid_addons_subquery.c.id)],
                                                 selector=Attendee.extra_donation)
        no_receipt_extra_donations = get_grouped_costs(session,
                                                       filters=extra_donation_filter + [Attendee.default_cost > 0,
                                                                                        ~Attendee.active_receipt.has()],
                                                       selector=Attendee.extra_donation)
        unpaid_extra_donations = get_grouped_costs(session,
                                                   filters=extra_donation_filter + [Attendee.default_cost > 0],
                                                   joins=[(unpaid_addons_subquery, Attendee.id == unpaid_addons_subquery.c.id)],
                                                   selector=Attendee.extra_donation)
        for key, val in no_receipt_extra_donations.items():
            unpaid_extra_donations[key] += val

        paid_badge_upgrades = get_grouped_costs(session,
                                                filters=badge_upgrade_filter,
                                                joins=[(paid_addons_subquery, Attendee.id == paid_addons_subquery.c.id)],
                                                selector=Attendee.badge_type)
        unpaid_badge_upgrades = get_grouped_costs(session,
                                                  filters=badge_upgrade_filter + [Attendee.default_cost > 0],
                                                  joins=[(unpaid_addons_subquery, Attendee.id == unpaid_addons_subquery.c.id)],
                                                  selector=Attendee.badge_type)
        no_receipt_badge_upgrades = get_grouped_costs(session,
                                                      filters=badge_upgrade_filter + [Attendee.default_cost > 0,
                                                                                      ~Attendee.active_receipt.has()],
                                                      selector=Attendee.badge_type)
        for key, val in no_receipt_badge_upgrades.items():
            unpaid_badge_upgrades[key] += val
        
        paid_upgrades_by_cost = defaultdict(int)
        unpaid_upgrades_by_cost = defaultdict(int)
        for key, val in paid_badge_upgrades.items():
            paid_upgrades_by_cost[c.BADGE_TYPE_PRICES[key]] = val

        for key, val in unpaid_badge_upgrades.items():
            unpaid_upgrades_by_cost[c.BADGE_TYPE_PRICES[key]] = val

        return {
            'total_addons': session.query(Attendee).filter(*base_filter).filter(
                or_(Attendee.amount_extra > 0,
                    Attendee.extra_donation > 0,
                    Attendee.badge_type.in_(c.BADGE_TYPE_PRICES))).count(),
            'total_merch': session.query(Attendee).filter(*preordered_merch_filter).count(),
            'paid_preordered_merch_total': sum(paid_preordered_merch.values()),
            'paid_preordered_merch_sum': get_dict_sum(paid_preordered_merch),
            'paid_preordered_merch': paid_preordered_merch,
            'unpaid_preordered_merch_total': sum(unpaid_preordered_merch.values()),
            'unpaid_preordered_merch_sum': get_dict_sum(unpaid_preordered_merch),
            'unpaid_preordered_merch': unpaid_preordered_merch,
            'total_donations': session.query(Attendee).filter(*extra_donation_filter).count(),
            'paid_extra_donations_total': sum(paid_extra_donations.values()),
            'paid_extra_donations_sum': get_dict_sum(paid_extra_donations),
            'paid_extra_donations': paid_extra_donations,
            'unpaid_extra_donations_total': sum(unpaid_extra_donations.values()),
            'unpaid_extra_donations_sum': get_dict_sum(unpaid_extra_donations),
            'unpaid_extra_donations': unpaid_extra_donations,
            'total_upgrades': session.query(Attendee).filter(*badge_upgrade_filter).count(),
            'paid_upgrades_total': sum(paid_upgrades_by_cost.values()),
            'paid_upgrades_sum': get_dict_sum(paid_upgrades_by_cost),
            'paid_upgrades': paid_badge_upgrades,
            'unpaid_upgrades_total': sum(unpaid_upgrades_by_cost.values()),
            'unpaid_upgrades_sum': get_dict_sum(unpaid_upgrades_by_cost),
            'unpaid_upgrades': unpaid_badge_upgrades,
            'now': localized_now(),
        }

    @log_pageview
    def mpoints(self, session):
        groups = defaultdict(list)
        for mpu in session.query(MPointsForCash).options(
                joinedload(MPointsForCash.attendee).subqueryload(Attendee.group)):
            groups[mpu.attendee and mpu.attendee.group].append(mpu)

        all = [(sum(mpu.amount for mpu in mpus), group, mpus)
               for group, mpus in groups.items()]
        return {'all': sorted(all, reverse=True)}

    def view_promo_codes(self, session, message='', **params):
        redirect_site_section('budget', 'promo_codes', 'index')

    def generate_promo_codes(self, session, message='', **params):
        redirect_site_section('budget', 'promo_codes')
