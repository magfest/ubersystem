from collections import defaultdict
from sqlalchemy import or_, and_
from sqlalchemy.sql import func

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
    def attendee_receipt_discrepancies(self, session, include_pending=False, page=1):
        '''
        select model_receipt.owner_id
        from model_receipt
        join receipt_item on receipt_item.receipt_id = model_receipt.id
        join attendee on attendee.id = model_receipt.owner_id
        where
            model_receipt.closed is null
            and model_receipt.owner_model = 'Attendee'
        group by attendee.id, attendee.default_cost, attendee.badge_status
        having
            attendee.default_cost * 100 != sum(receipt_item.amount * receipt_item.count)
            and (attendee.badge_status NOT IN (175104371, 192297957, 229301191, 169050145, 91398854, 177900276));
        '''

        page = int(page)
        if page <= 0:
            offset = 0
        else:
            offset = (page - 1) * 50

        if include_pending:
            filter = or_(Attendee.badge_status.in_([c.PENDING_STATUS, c.AT_DOOR_PENDING_STATUS]),
                               Attendee.is_valid == True)  # noqa: E712
        else:
            filter = Attendee.is_valid == True  # noqa: E712
                
        receipt_query = (
            session.query(
                ModelReceipt.owner_id
            )
            .join(ReceiptItem, ReceiptItem.receipt_id == ModelReceipt.id)
            .join(Attendee, Attendee.id == ModelReceipt.owner_id)
            .filter(
                ModelReceipt.closed.is_(None),
                ModelReceipt.owner_model == 'Attendee'
            )
            .group_by(Attendee.id, Attendee.default_cost, Attendee.badge_status, ModelReceipt.id)
            .having(
                and_(
                    Attendee.default_cost_cents != func.sum(ReceiptItem.amount * ReceiptItem.count),
                    filter
                )
            )
        )
        
        count = receipt_query.count()
        
        receipt_owners = [x[0] for x in receipt_query.limit(50).offset(offset)]

        receipt_query = session.query(Attendee).join(Attendee.active_receipt).filter(Attendee.id.in_(receipt_owners))

        return {
            'current_page': page,
            'pages': (count // 50) + 1,
            'attendees': receipt_query,
            'include_pending': include_pending,
        }

    @log_pageview
    def attendees_nonzero_balance(self, session, include_no_receipts=False):
        attendees = session.query(Attendee,
                                  ModelReceipt).join(Attendee.active_receipt
                                                     ).filter(Attendee.default_cost_cents == ModelReceipt.item_total,
                                                              ModelReceipt.current_receipt_amount != 0)

        return {
            'attendees': attendees.filter(Attendee.is_valid == True)  # noqa: E712
        }

    @log_pageview
    def self_service_refunds(self, session):
        refunds = session.query(ReceiptTransaction).filter(ReceiptTransaction.amount < 0,
                                                           ReceiptTransaction.who == 'non-admin').all()

        refund_models = defaultdict(dict)
        for refund in refunds:
            model = session.get_model_by_receipt(refund.receipt)
            model_name = ''.join(' ' + char if char.isupper() else
                                 char.strip() for char in model.__class__.__name__).strip()
            refund_models[model_name][refund] = model

        return {
            'refund_models': refund_models,
        }
