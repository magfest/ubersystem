import math
import re
import logging

from collections import defaultdict
from sqlalchemy.orm import joinedload, lazyload
from sqlalchemy import or_, func, not_, and_
from typing import Iterable

from uber.config import c
from uber.decorators import all_renderable, log_pageview, csv_file
from uber.errors import HTTPRedirect
from uber.models import (ArbitraryCharge, Attendee, AttendeeAccount, Group, ModelReceipt, MPointsForCash, Sale, PromoCodeGroup,
                         ReceiptTransaction, ReceiptItem)
from uber.server import redirect_site_section
from uber.utils import localized_now, Order

from uber.models import ReceiptTransaction, ReceiptItem, AttendeeAccount

log = logging.getLogger(__name__)


def _build_item_subquery(session):
    return session.query(ModelReceipt.owner_id, ModelReceipt.item_total_sql.label('item_total')
                         ).join(ModelReceipt.receipt_items).group_by(ModelReceipt.owner_id).subquery()

def _build_txn_subquery(session):
    return session.query(ModelReceipt.owner_id, ModelReceipt.payment_total_sql.label('payment_total'),
                         ModelReceipt.refund_total_sql.label('refund_total')
                         ).join(ModelReceipt.receipt_txns).group_by(ModelReceipt.owner_id).subquery()

def _build_discount_subquery(session):
    return session.query(ModelReceipt.owner_id, ModelReceipt.discount_total_sql.label('discount_total')
                         ).join(ModelReceipt.receipt_discounts).group_by(ModelReceipt.owner_id).subquery()

def get_grouped_costs(session, filters=[], joins=[], selector=Attendee.badge_cost):
    # Returns a defaultdict with the {int(cost): count} of badges
    query = session.query(selector, func.count(selector))
    for join in joins:
        if isinstance(join, Iterable):
            query = query.join(*join)
        else:
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
        discount_subquery = _build_discount_subquery(session)  # TODO: Make this work

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

    @csv_file
    def purchaser_donation_report(self, out, session):
        out.writerow(['Purchaser ID', 'First Name', 'Last Name', 'Legal Name', 'Email',
                      'Country', 'Region', 'City', 'ZipCode', 'Address 1', 'Address 2',
                      'Purchaser Badge Type', 'Purchaser Badge #', 'Total Purchases', 'Total Credit',
                      '# Day Badges', '# Group Badges', '# Attendee Badges',
                      '# Sponsor Upgrades', '# Shiny Upgrades', '# Day-to-Attendee Upgrades'])

        badge_txn_purchasers = session.query(
            ModelReceipt.owner_id, ModelReceipt.owner_model, ReceiptTransaction,
            func.json_agg(func.json_build_object('id', ReceiptItem.id, 'amount', ReceiptItem.amount, 'count', ReceiptItem.count, 'category', ReceiptItem.category, 'desc', ReceiptItem.desc)),
            func.array_agg(ReceiptItem.purchaser_id)).filter(
                ReceiptTransaction.cancelled == None, ReceiptTransaction.on_hold == False, ReceiptTransaction.amount > 0, ReceiptTransaction.charge_id != '').join(ReceiptTransaction.receipt_items).filter(
                    ReceiptItem.reverted == False, ReceiptItem.comped == False, ReceiptItem.amount != 0,
                    ReceiptItem.category.in_([c.BADGE, c.GROUP_BADGE, c.BADGE_DISCOUNT, c.BADGE_UPGRADE])).join(
                        ReceiptTransaction.receipt).filter(ModelReceipt.closed == None).group_by(
                            ReceiptTransaction.id).group_by(ModelReceipt.owner_id).group_by(ModelReceipt.owner_model).options(lazyload("*"))
        
        transactions_by_purchaser = defaultdict(list)
        weird_transactions_by_purchaser = defaultdict(list)
        transactions_by_attendee = defaultdict(list)
        even_weirder_purchaser_ids = []
        for owner_id, owner_model, txn, items, purchasers in badge_txn_purchasers:
            purchasers_set = set(purchasers)
            purchasers_set.discard(None)
            purchasers_list = list(purchasers_set)
            if len(purchasers_list) == 1 and txn.amount_left:
                value = sum([item['amount'] * item['count'] for item in items if item['amount'] > 0])
                credit = sum([item['amount'] * item['count'] * -1 for item in items if item['amount'] < 0])
                if (value + credit) != txn.amount_left and any(item.category in [c.ITEM_COMP, c.CANCEL_ITEM, c.OTHER] for item in txn.receipt_items):
                    weird_transactions_by_purchaser[purchasers_list[0]].append((owner_id, owner_model, items))
                else:
                    transactions_by_purchaser[purchasers_list[0]].append((owner_id, owner_model, items))
            elif len(purchasers_list) != 1:
                log.error(f"Found multiple purchasers for one transaction while generating donation report. {purchasers}: {owner_id}, {owner_model}, {items}")
        
        purchaser_ids = set(transactions_by_purchaser.keys()) | set(weird_transactions_by_purchaser.keys())
        purchasers = session.query(AttendeeAccount).filter(AttendeeAccount.id.in_(purchaser_ids))
        attendee_purchasers = session.query(Attendee).filter(Attendee.id.in_(purchaser_ids))

        purchasers_by_id = {a.id: a for a in purchasers.all()}
        for attendee in attendee_purchasers:
            if attendee.managers:
                purchasers_by_id[attendee.id] = attendee.managers[0]
            else:
                purchasers_by_id[attendee.id] = attendee
        weird_purchaser_ids = list(weird_transactions_by_purchaser.keys())

        for purchaser_id, txns in transactions_by_purchaser.items():
            if purchaser_id in weird_purchaser_ids or purchaser_id not in purchasers_by_id:
                log.error(f"Could not generate donation report for {purchaser_id}. Transactions: {txns}")
            elif purchaser_id not in even_weirder_purchaser_ids:
                purchaser = purchasers_by_id[purchaser_id]
                if isinstance(purchaser, AttendeeAccount):
                    if purchaser.owner and purchaser.owner.is_valid:
                        p_attendee = purchaser.owner
                    else:
                        p_attendee = purchaser.backup_owner
                else:
                    p_attendee = purchaser if purchaser.is_valid else None
                
                if p_attendee:
                    transactions_by_attendee[p_attendee].extend(txns)
                else:
                    log.error(f"Purchaser donation report issue: {p_attendee} has valid payments but no valid badges.")
        
        for attendee, txns in transactions_by_attendee.items():
            total_pos, total_neg = 0, 0
            day_badges, group_badges, attendee_badges, sponsor_upgrades, shiny_upgrades, attendee_upgrades = 0, 0, 0, 0, 0, 0
            for owner_id, owner_model, items in txns:
                purchases = []
                refunds = []
                for item in items:
                    if item['amount'] > 0:
                        total_pos += (item['amount'] * item['count'])
                        if item['category'] != c.BADGE_DISCOUNT:
                            purchases.append(item)
                    else:
                        total_neg += (item['amount'] * item['count'])
                        if item['category'] != c.BADGE_DISCOUNT:
                            # Most of these are already filtered out, but e.g. groups can have their # of badges reduced
                            refunds.append(item)
                if owner_model == 'Group':
                    group_badges = sum([p['count'] for p in purchases]) - sum([r['count'] for r in refunds])
                else:
                    pc_group_badges = [p for p in purchases if p['category'] == c.GROUP_BADGE]
                    if pc_group_badges:
                        group_badges = sum([b['count'] for b in pc_group_badges]) - sum([r['count'] for r in refunds if r['category'] == c.GROUP_BADGE])
                    # day badge, attendee badge, sponsor upgrade, shiny upgrade
                    for purchase in purchases:
                        if purchase['category'] == c.BADGE:
                            if 'Friday' in purchase['desc'] or 'Saturday' in purchase['desc'] or 'Sunday' in purchase['desc'] or 'One Day' in purchase['desc']:
                                day_badges += 1
                            else:
                                attendee_badges += 1
                        elif purchase['category'] == c.BADGE_UPGRADE:
                            if 'Shiny' in purchase['desc']:
                                shiny_upgrades += 1
                            elif 'Sponsor' in purchase['desc']:
                                sponsor_upgrades += 1
                            elif 'Attendee' in purchase['desc']:
                                attendee_upgrades += 1
                            else:
                                purchase['desc']
                        else:
                            c.REG_RECEIPT_ITEMS[purchase['category']]

            out.writerow([attendee.id, attendee.first_name, attendee.last_name, attendee.legal_name, attendee.email,
                          attendee.country, attendee.region, attendee.city, attendee.zip_code, attendee.address1,
                          attendee.address2, attendee.badge_type_label, attendee.badge_num, total_pos, total_neg,
                          day_badges, group_badges, attendee_badges, sponsor_upgrades, shiny_upgrades, attendee_upgrades])

    def view_promo_codes(self, session, message='', **params):
        redirect_site_section('budget', 'promo_codes', 'index')

    def generate_promo_codes(self, session, message='', **params):
        redirect_site_section('budget', 'promo_codes')
