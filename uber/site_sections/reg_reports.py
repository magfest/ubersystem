from sqlalchemy import or_

from uber.config import c
from uber.decorators import all_renderable, log_pageview
from uber.models import Attendee, Group, PromoCode, ReceiptTransaction


@all_renderable()
class Root:
    def comped_badges(self, session, message='', show='all'):
        regular_comped = session.attendees_with_badges().filter(Attendee.paid == c.NEED_NOT_PAY, 
                                                                Attendee.promo_code == None)
        promo_comped = session.query(Attendee).join(PromoCode).filter(Attendee.has_badge == True,
                                                                      Attendee.paid == c.NEED_NOT_PAY,
                                                                      or_(PromoCode.cost == None, 
                                                                          PromoCode.cost == 0))
        group_comped = session.query(Attendee).join(Group, Attendee.group_id == Group.id)\
                .filter(Attendee.has_badge == True, Attendee.paid == c.PAID_BY_GROUP, Group.cost == 0)
        all_comped = regular_comped.union(promo_comped, group_comped)
        claimed_comped = all_comped.filter(Attendee.placeholder == False)
        unclaimed_comped = all_comped.filter(Attendee.placeholder == True)
            
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
    def self_service_refunds(self, session):
        refunds = session.query(ReceiptTransaction).filter_by(type=c.REFUND)

        refund_attendees = {}
        for refund in refunds:
            refund_attendees[refund.id] = refund.attendees[0].attendee if refund.attendees else None

        return {
            'refunds': refunds,
            'refund_attendees': refund_attendees,
        }
