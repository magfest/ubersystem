from collections import defaultdict

from sqlalchemy.orm import joinedload
from sqlalchemy import and_, or_

from uber.config import c
from uber.decorators import all_renderable, log_pageview
from uber.models import ArbitraryCharge, Attendee, Group, MPointsForCash, ReceiptItem, Sale, StripeTransaction
from uber.server import redirect_site_section


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
        
    @log_pageview
    def attendee_cost_breakdown(self, session):
        paid_attendees = session.query(Attendee.is_unassigned, 
                                       Attendee.purchased_items, 
                                       Attendee.first_name,
                                       Attendee.last_name,
                                       Group.name.label('group_name')).outerjoin(Attendee.group)\
                    .filter(Attendee.badge_status.in_([c.NEW_STATUS, c.COMPLETED_STATUS]),
                                                        or_(Attendee.amount_paid > 0, 
                                                            and_(Attendee.group_id == Group.id, 
                                                                 Group.amount_paid > 0, 
                                                                 Group.auto_recalc == True)))
        
        return {
            'paid_attendees': paid_attendees,
        }
        
    @log_pageview
    def group_cost_breakdown(self, session):
        return {
            'paid_groups': session.query(Group.auto_recalc, Group.name, Group.tables, Group.cost).filter(Group.amount_paid > 0),
            'table_cost_matrix': [
                (c.TABLE_PRICES[1], "First Table"),
                (sum(c.TABLE_PRICES[i] for i in range(1, 3)), "Second Table"),
                (sum(c.TABLE_PRICES[i] for i in range(1, 4)), "Third Table"),
                (sum(c.TABLE_PRICES[i] for i in range(1, 5)), "Fourth Table"),
            ]
        }
        
    @log_pageview
    def attendee_donation_breakdown(self, session):
        return {
            'donated_attendees': session.query(Attendee).filter(or_(Attendee.amount_extra > 0, Attendee.extra_donation > 0)),
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
            refund_attendees[refund.id] = refund.attendees[0].attendee if refund.attendees else None

        return {
            'refunds': refunds,
            'refund_attendees': refund_attendees,
        }

    def view_promo_codes(self, session, message='', **params):
        redirect_site_section('budget', 'promo_codes', 'index')

    def generate_promo_codes(self, session, message='', **params):
        redirect_site_section('budget', 'promo_codes')
