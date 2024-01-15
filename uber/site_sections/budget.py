from collections import defaultdict

from sqlalchemy.orm import joinedload, aliased
from sqlalchemy import and_, or_, func, not_

from uber.config import c
from uber.decorators import all_renderable, log_pageview
from uber.models import ArbitraryCharge, Attendee, Group, MPointsForCash, ReceiptItem, Sale, PromoCode, PromoCodeGroup
from uber.server import redirect_site_section
from uber.utils import localized_now


def get_grouped_costs(session, filters, joins=[], selector=Attendee.badge_cost):
    # Returns a defaultdict with the {int(cost): count} of badges
    query = session.query(selector, func.count(selector))
    for join in joins:
        query.outerjoin(join)
    return defaultdict(int, query.filter(*filters).group_by(selector).order_by(selector).all())


def get_dict_sum(dict_to_sum):
    return sum([dict_to_sum[cost] * cost for cost in dict_to_sum])


@all_renderable()
class Root:
    @log_pageview
    def index(self, session):
        receipt_items = session.query(ReceiptItem)
        receipt_total = sum([item.amount for item in receipt_items.filter_by(txn_type=c.PAYMENT).all()]) \
                        - sum([item.amount for item in receipt_items.filter_by(txn_type=c.REFUND).all()])
        sales_total = sum([sale.cash * 100 for sale in session.query(Sale).all()])
        arbitrary_charge_total = sum([charge.amount * 100 for charge in session.query(ArbitraryCharge).all()])
        return {
            'receipt_items': receipt_items.filter_by(txn_type=c.REFUND),
            'arbitrary_charges': session.query(ArbitraryCharge),
            'sales': session.query(Sale),
            'total': receipt_total + sales_total + arbitrary_charge_total,
        }

    def badge_cost_summary(self, session):
        base_filter = [Attendee.has_or_will_have_badge]

        group_filter = base_filter + [Attendee.group_id != None, Attendee.paid == c.PAID_BY_GROUP]
        badge_cost_matters_filter = group_filter + [Group.cost > 0, Group.auto_recalc == True]

        group_counts = {}
        
        group_counts['free_groups'] = session.query(Attendee).outerjoin(Attendee.group, aliased=True).filter(
            *group_filter).filter(Group.cost <= 0).count()
        group_counts['custom_price'] = session.query(Attendee).outerjoin(Attendee.group, aliased=True).filter(
            *group_filter).filter(Group.cost > 0, Group.auto_recalc == False).count()
        
        paid_group_badges = get_grouped_costs(session, badge_cost_matters_filter + [Group.is_paid == True], [Attendee.group])
        unpaid_group_badges = get_grouped_costs(session, 
                                                badge_cost_matters_filter + [Group.cost > 0, Group.is_paid == False], 
                                                [Attendee.group])

        group_total = session.query(Attendee).filter(*group_filter).count()

        yield {
            'stream_content': True,
            'total_badges': session.query(Attendee).filter_by(has_or_will_have_badge=True).count(),
            'now': localized_now(),
            'group_total': group_total,
            'group_counts': group_counts,
            'group_badges': paid_group_badges,
            'group_badges_total': sum(paid_group_badges.values()),
            'group_badges_sum': get_dict_sum(paid_group_badges),
            'unpaid_group_badges': unpaid_group_badges,
            'unpaid_group_badges_total': sum(unpaid_group_badges.values()),
            'unpaid_group_sum': get_dict_sum(unpaid_group_badges)
        }

        pc_group_filter = base_filter + [Attendee.promo_code_group_name != None]
        paid_pc_group_filter = pc_group_filter + [PromoCodeGroup.total_cost > 0]

        pc_comped_badges = 0
        pc_unused_badges = defaultdict(int)
        pc_group_total = session.query(Attendee).filter(*pc_group_filter).count()

        pc_group_leaders = session.query(Attendee).filter(Attendee.promo_code_groups != None).count()
        pc_group_badges = get_grouped_costs(session, paid_pc_group_filter, [Attendee.promo_code, PromoCode.group])

        for group in session.query(PromoCodeGroup).filter(PromoCodeGroup.total_cost <= 0):
            pc_comped_badges += len(group.used_promo_codes)

        for group in session.query(PromoCodeGroup).filter(PromoCodeGroup.total_cost > 0):
            for code in group.unused_codes:
                pc_unused_badges[code.cost] += 1
                pc_group_total += 1

        yield {
            'pc_group_total': pc_group_total,
            'pc_group_leaders': pc_group_leaders,
            'pc_comped_badges': pc_comped_badges,
            'pc_claimed_badges': pc_group_badges,
            'pc_claimed_badges_total': sum(pc_group_badges.values()),
            'pc_claimed_badges_sum': get_dict_sum(pc_group_badges),
            'pc_unused_badges': pc_unused_badges,
            'pc_unused_badges_total': sum(pc_unused_badges.values()),
            'pc_unused_badges_sum': get_dict_sum(pc_unused_badges),
        }

        individual_filter = base_filter + [not_(Attendee.paid.in_([c.PAID_BY_GROUP, c.NEED_NOT_PAY])),
                                           Attendee.promo_code_group_name == None,
                                           Attendee.badge_cost > 0]
        paid_ind_filter = individual_filter + [Attendee.is_paid == True]
        unpaid_ind_filter = individual_filter + [Attendee.default_cost > 0, Attendee.is_paid == False]

        individual_badges = get_grouped_costs(session, paid_ind_filter)
        unpaid_badges = get_grouped_costs(session, unpaid_ind_filter)

        comped_badges = session.query(Attendee).filter(*base_filter).filter(Attendee.promo_code_group_name == None) \
            .filter_by(paid=c.NEED_NOT_PAY).count()
        individual_total = session.query(Attendee).filter(*individual_filter).count() + comped_badges
        
        yield {
            'individual_total': individual_total,
            'comped_badges': comped_badges,
            'individual_badges': individual_badges,
            'individual_badges_total': sum(individual_badges.values()),
            'individual_badges_sum': get_dict_sum(individual_badges),
            'unpaid_badges': unpaid_badges,
            'unpaid_badges_total': sum(unpaid_badges.values()),
            'unpaid_badges_sum': get_dict_sum(unpaid_badges),
        }
    badge_cost_summary._cp_config = {'response.stream': True}

    def dealer_cost_summary(self, session):
        dealers = session.query(Group).filter(Group.is_dealer==True, Group.attendees_have_badges==True, Group.cost > 0)

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

        paid_preordered_merch = get_grouped_costs(session,
                                                  preordered_merch_filter + [Attendee.is_paid == True],
                                                  selector=Attendee.amount_extra)
        unpaid_preordered_merch = get_grouped_costs(session,
                                                  preordered_merch_filter + [Attendee.default_cost > 0,
                                                                             Attendee.is_paid == False],
                                                  selector=Attendee.amount_extra)
        
        paid_extra_donations = get_grouped_costs(session,
                                                  extra_donation_filter + [Attendee.is_paid == True],
                                                  selector=Attendee.extra_donation)
        unpaid_extra_donations = get_grouped_costs(session,
                                                  extra_donation_filter + [Attendee.default_cost > 0,
                                                                             Attendee.is_paid == False],
                                                  selector=Attendee.extra_donation)

        return {
            'total_addons': session.query(Attendee).filter(*base_filter).filter(or_(Attendee.amount_extra > 0,
                                                                                Attendee.extra_donation > 0)).count(),
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
