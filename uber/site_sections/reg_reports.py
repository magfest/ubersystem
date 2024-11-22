from collections import defaultdict
from sqlalchemy import or_, and_
from sqlalchemy.sql import func
from sqlalchemy.sql.functions import coalesce

from uber.config import c
from uber.decorators import all_renderable, log_pageview, streamable
from uber.models import Attendee, Group, PromoCode, ReceiptTransaction, ModelReceipt, ReceiptItem


@all_renderable()
class Root:
    def comped_badges(self, session, message='', show='all'):
        regular_comped = session.attendees_with_badges().filter(Attendee.paid == c.NEED_NOT_PAY,
                                                                Attendee.promo_code == None)  # noqa: E711
        promo_comped = session.query(Attendee).join(PromoCode).filter(Attendee.has_badge == True,  # noqa: E712
                                                                      Attendee.paid == c.NEED_NOT_PAY,
                                                                      or_(PromoCode.cost == None,  # noqa: E711
                                                                          PromoCode.cost == 0))
        group_comped = session.query(Attendee).join(Group, Attendee.group_id == Group.id)\
            .filter(Attendee.has_badge == True,  # noqa: E712
                    Attendee.paid == c.PAID_BY_GROUP, Group.cost == 0)
        all_comped = regular_comped.union(promo_comped, group_comped)
        claimed_comped = all_comped.filter(Attendee.placeholder == False)  # noqa: E712
        unclaimed_comped = all_comped.filter(Attendee.placeholder == True)  # noqa: E712

        return {
            'message': message,
            'comped_attendees': all_comped,
            'all_comped': all_comped.count(),
            'claimed_comped': claimed_comped.count(),
            'unclaimed_comped': unclaimed_comped.count(),
            'show': show,
        }

    def found_how(self, session):
        return {'all': sorted(
            [a.found_how for a in session.query(Attendee).filter(Attendee.found_how != '').all()],
            key=lambda s: s.lower())}

    @log_pageview
    def attendee_receipt_discrepancies(self, session, include_pending=False):
        if include_pending:
            filter = or_(Attendee.badge_status.in_([c.PENDING_STATUS, c.AT_DOOR_PENDING_STATUS]),
                               Attendee.is_valid == True)  # noqa: E712
        else:
            filter = Attendee.is_valid == True  # noqa: E712

        attendees = session.query(Attendee).filter(filter).join(  # noqa: E712
                Attendee.active_receipt).outerjoin(ModelReceipt.receipt_items).group_by(
                    ModelReceipt.id).group_by(Attendee.id).having(Attendee.default_cost_cents != ModelReceipt.item_total_sql)

        return {
            'attendees': attendees,
            'include_pending': include_pending,
        }

    @log_pageview
    def attendees_nonzero_balance(self, session, include_discrepancies=False):
        item_subquery = session.query(ModelReceipt.owner_id, ModelReceipt.item_total_sql.label('item_total')
                                      ).join(ModelReceipt.receipt_items).group_by(ModelReceipt.owner_id).subquery()

        if include_discrepancies:
            filter = True
        else:
            filter = Attendee.default_cost_cents != item_subquery.c.item_total

        attendees_and_totals = session.query(
            Attendee, ModelReceipt.payment_total_sql, ModelReceipt.refund_total_sql, item_subquery.c.item_total
            ).filter(Attendee.is_valid == True).join(Attendee.active_receipt).outerjoin(
                ModelReceipt.receipt_txns).join(item_subquery, Attendee.id == item_subquery.c.owner_id).group_by(
                    ModelReceipt.id).group_by(Attendee.id).group_by(item_subquery.c.item_total).having(
                        and_((ModelReceipt.payment_total_sql - ModelReceipt.refund_total_sql) != item_subquery.c.item_total,
                             filter))

        return {
            'attendees_and_totals': attendees_and_totals,
            'include_discrepancies': include_discrepancies,
        }

    @log_pageview
    def self_service_refunds(self, session):
        refunds = session.query(ReceiptTransaction).filter(ReceiptTransaction.amount < 0,
                                                           ReceiptTransaction.who == 'non-admin').all()
        
        counts = defaultdict(int)
        refund_models = defaultdict(dict)
        for refund in refunds:
            model = session.get_model_by_receipt(refund.receipt)
            model_name = ''.join(' ' + char if char.isupper() else
                                 char.strip() for char in model.__class__.__name__).strip()
            refund_models[model_name][refund] = model
            if c.BADGE_TYPE_PRICES and isinstance(model, Attendee):
                if model.badge_type in c.BADGE_TYPE_PRICES:
                    counts[model.badge_type] += 1
                else:
                    counts[c.ATTENDEE_BADGE] += 1

        return {
            'refund_models': refund_models,
            'counts': counts,
        }
