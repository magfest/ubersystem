import six
import calendar
from collections import defaultdict
from sqlalchemy import or_, and_
from sqlalchemy.sql import func
from sqlalchemy.sql.expression import literal

from uber.config import c
from uber.decorators import all_renderable, log_pageview, csv_file
from uber.models import Attendee, Group, PromoCode, ReceiptTransaction, ModelReceipt, ReceiptItem, Tracking
from uber.utils import localize_datetime


def date_trunc_hour(*args, **kwargs):
    # sqlite doesn't support date_trunc
    if c.SQLALCHEMY_URL.startswith('sqlite'):
        return func.strftime(literal('%Y-%m-%d %H:00'), *args, **kwargs)
    else:
        return func.date_trunc(literal('hour'), *args, **kwargs)


def checkins_by_hour_query(session):
    return session.query(date_trunc_hour(Attendee.checked_in),
                         func.count(date_trunc_hour(Attendee.checked_in))) \
            .filter(Attendee.checked_in.isnot(None)) \
            .group_by(date_trunc_hour(Attendee.checked_in)) \
            .order_by(date_trunc_hour(Attendee.checked_in))


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
            filter = or_(Attendee.badge_status == c.PENDING_STATUS, Attendee.is_valid == True)  # noqa: E712
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
    
    def checkins_by_hour(self, session):
        query_result = checkins_by_hour_query(session).all()

        hourly_checkins = dict()
        daily_checkins = defaultdict(int)
        outside_event_checkins = []
        for result in query_result:
            localized_hour = localize_datetime(result[0])
            hourly_checkins[localized_hour] = result[1]
            if localized_hour > c.EPOCH and localized_hour < c.ESCHATON:
                daily_checkins[calendar.day_name[localized_hour.weekday()]] += result[1]
            else:
                outside_event_checkins.append(localized_hour)

        return {
            'checkins': hourly_checkins,
            'daily_checkins': daily_checkins,
            'outside_event_checkins': outside_event_checkins,
        }

    @csv_file
    def checkins_by_hour_csv(self, out, session):
        out.writerow(["Time", "# Checked In"])
        query_result = checkins_by_hour_query(session).all()

        for result in query_result:
            hour = localize_datetime(result[0])
            count = result[1]
            out.writerow([hour, count])

    @csv_file
    def checkins_by_admin_by_hour(self, out, session):
        header = ["Time", "Total Checked In"]
        admins = session.query(Tracking.who).filter(Tracking.action == c.UPDATED,
                                                    Tracking.model == "Attendee",
                                                    Tracking.data.contains("checked_in='None -> datetime")
                                                    ).group_by(Tracking.who).order_by(Tracking.who).distinct().all()
        for admin in admins:
            if not isinstance(admin, six.string_types):
                admin = admin[0]  # SQLAlchemy quirk

            header.append(f"{admin} # Checked In")

        out.writerow(header)

        query_result = checkins_by_hour_query(session).all()

        for result in query_result:
            hour = localize_datetime(result[0])
            count = result[1]
            row = [hour, count]

            hour_admins = session.query(
                Tracking.who,
                func.count(Tracking.who)).filter(
                    date_trunc_hour(Tracking.when) == result[0],
                    Tracking.action == c.UPDATED,
                    Tracking.model == "Attendee",
                    Tracking.data.contains("checked_in='None -> datetime")
                    ).group_by(Tracking.who).order_by(Tracking.who)
            for admin, admin_count in hour_admins:
                row.append(admin_count)
            out.writerow(row)
