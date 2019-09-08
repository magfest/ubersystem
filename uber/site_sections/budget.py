from collections import defaultdict

from sqlalchemy.orm import joinedload

from uber.config import c
from uber.decorators import all_renderable, log_pageview
from uber.models import ArbitraryCharge, Attendee, Group, MPointsForCash, ReceiptItem, Sale, StripeTransaction
from uber.server import redirect_site_section


def prereg_money(session):
    preregs = defaultdict(int)
    for attendee in session.query(Attendee):
        preregs['Attendee'] += attendee.amount_paid - attendee.amount_extra
        preregs['extra'] += attendee.amount_extra

    preregs['group_badges'] = sum(
        g.badge_cost for g in session.query(Group).filter(
            Group.tables == 0, Group.amount_paid > 0).options(joinedload(Group.attendees)))

    dealers = session.query(Group).filter(
        Group.tables > 0, Group.amount_paid > 0).options(joinedload(Group.attendees)).all()
    preregs['dealer_tables'] = sum(d.table_cost for d in dealers)
    preregs['dealer_badges'] = sum(d.badge_cost for d in dealers)

    return preregs


def sale_money(session):
    sales = defaultdict(int)
    for sale in session.query(Sale).all():
        sales[sale.what] += sale.cash
    return dict(sales)  # converted to a dict so we can say sales.items in our template


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
            'receipt_items': session.query(ReceiptItem),
            'arbitrary_charges': session.query(ArbitraryCharge),
            'sales': session.query(Sale),
            'total': receipt_total + sales_total + arbitrary_charge_total,
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

    @log_pageview
    def refunds(self, session):
        refunds = session.query(StripeTransaction).filter_by(type=c.REFUND)

        refund_attendees = {}
        for refund in refunds:
            refund_attendees[refund.id] = session.query(Attendee)\
                .filter_by(id=refund.fk_id).first() if refund.fk_model == 'Attendee' else None

        return {
            'refunds': refunds,
            'refund_attendees': refund_attendees,
        }

    def view_promo_codes(self, session, message='', **params):
        redirect_site_section('budget', 'promo_codes', 'index')

    def generate_promo_codes(self, session, message='', **params):
        redirect_site_section('budget', 'promo_codes')
