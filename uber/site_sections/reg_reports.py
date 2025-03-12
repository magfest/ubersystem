import six
import calendar
from collections import defaultdict
from sqlalchemy import or_, and_
from sqlalchemy.sql import func
from sqlalchemy.sql.expression import literal

from uber.config import c
from uber.custom_tags import datetime_local_filter, format_currency
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
    
    @csv_file
    def comped_badges_csv(self, out, session):
        comped = session.query(Attendee).filter(
            Attendee.has_badge == True).outerjoin(PromoCode).outerjoin(Group, Attendee.group_id == Group.id).filter(
                or_(and_(Attendee.paid == c.NEED_NOT_PAY, Attendee.promo_code == None),
                    and_(Attendee.paid == c.NEED_NOT_PAY, Attendee.promo_code != None, 
                         or_(PromoCode.cost == None, PromoCode.cost == 0)),
                    and_(Attendee.group != None, Attendee.paid == c.PAID_BY_GROUP, Group.cost == 0))
            )
        
        out.writerow(['Claimed?', 'Group Name', 'Promo Code', 'ID', 'Name', 'Name on ID',
                      'Badge Type', 'Badge #', 'Created By', 'Admin Notes'])
        
        for attendee in comped:
            out.writerow(["Yes" if not attendee.placeholder else "No", attendee.group.name if attendee.group else 'N/A',
                          attendee.promo_code.code if attendee.promo_code else 'N/A', attendee.id, attendee.full_name,
                          attendee.legal_name, attendee.badge_type_label, attendee.badge_num,
                          attendee.creator.full_name if attendee.creator else 'N/A', attendee.admin_notes])

    def found_how(self, session):
        return {'all': sorted(
            [a.found_how for a in session.query(Attendee).filter(Attendee.found_how != '').all()],
            key=lambda s: s.lower())}

    @log_pageview
    def attendee_receipt_discrepancies(self, session, include_pending=False):
        if include_pending:
            filter = or_(Attendee.badge_status == c.PENDING_STATUS, Attendee.is_valid == True)  # noqa: E712
        else:
            filter = Attendee.is_valid == True  # noqa: E712

        attendees = session.query(Attendee).filter(
            filter).join(Attendee.active_receipt).outerjoin(ModelReceipt.receipt_items).group_by(
                ModelReceipt.id).group_by(Attendee.id).having(
                    Attendee.default_cost_cents != ModelReceipt.fkless_item_total_sql)

        return {
            'attendees': attendees,
            'include_pending': include_pending,
        }

    @log_pageview
    def attendees_nonzero_balance(self, session, include_no_receipts=False, include_discrepancies=False):
        item_subquery = session.query(ModelReceipt.owner_id, ModelReceipt.item_total_sql.label('item_total')
                                      ).join(ModelReceipt.receipt_items).group_by(ModelReceipt.owner_id).subquery()

        if include_discrepancies:
            filter = True
        else:
            filter = Attendee.default_cost_cents == item_subquery.c.item_total

        attendees_and_totals = session.query(
            Attendee, ModelReceipt.payment_total_sql, ModelReceipt.refund_total_sql, item_subquery.c.item_total
            ).filter(Attendee.is_valid == True).join(Attendee.active_receipt).outerjoin(
                ModelReceipt.receipt_txns).join(item_subquery, Attendee.id == item_subquery.c.owner_id).group_by(
                    ModelReceipt.id).group_by(Attendee.id).group_by(item_subquery.c.item_total).having(
                        and_((ModelReceipt.payment_total_sql - ModelReceipt.refund_total_sql) != item_subquery.c.item_total,
                             filter))
        
        if include_no_receipts:
            attendees_no_receipts = session.query(Attendee).outerjoin(
                ModelReceipt, Attendee.active_receipt).filter(Attendee.default_cost > 0, ModelReceipt.id == None)
        else:
            attendees_no_receipts = []

        return {
            'attendees_and_totals': attendees_and_totals,
            'include_discrepancies': include_discrepancies,
            'attendees_no_receipts': attendees_no_receipts,
        }

    @log_pageview
    def self_service_refunds(self, session):
        refunds = session.query(ReceiptTransaction).filter(ReceiptTransaction.amount < 0,
                                                           ReceiptTransaction.who == 'non-admin').all()
        
        counts = defaultdict(int)
        refund_models = defaultdict(dict)
        for refund in refunds:
            model = session.get_model_by_receipt(refund.receipt)
            model_name = refund.receipt.owner_model
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
    
    @csv_file
    def self_service_refunds_csv(self, out, session):
        refunds = session.query(ReceiptTransaction).filter(ReceiptTransaction.amount < 0,
                                                           ReceiptTransaction.who == 'non-admin').all()
        out.writerow(['Transaction ID', 'Model Type', 'Model ID', 'Model Name', 'Refunded Date', 'Amount', 'Desc'])
        for refund in refunds:
            model = session.get_model_by_receipt(refund.receipt)
            model_type = refund.receipt.owner_model
            if not model:
                continue

            if model_type == 'Attendee':
                model_name = model.full_name
            elif model_type == 'Group':
                model_name = model.name
            elif getattr(model, 'attendee', None) is not None:
                model_name = model.attendee.full_name
            else:
                model_name = getattr(model, 'name', '???')
            
            out.writerow([refund.refund_id, model_type, model.id, model_name, datetime_local_filter(refund.added),
                          format_currency(refund.amount * -1 / 100), refund.desc])
            
    
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
        admin_list = []
        admins = session.query(Tracking.who).filter(Tracking.action == c.UPDATED,
                                                    Tracking.model == "Attendee",
                                                    Tracking.data.contains("checked_in='None -> datetime")
                                                    ).group_by(Tracking.who).order_by(Tracking.who).distinct().all()
        for admin in admins:
            if not isinstance(admin, six.string_types):
                admin = admin[0]  # SQLAlchemy quirk

            admin_list.append(admin)

        out.writerow(header + list(map(lambda a: f"{a} # Checked In", admin_list)))

        checkin_totals = checkins_by_hour_query(session).all()
        hour_admin_checkins = session.query(
                date_trunc_hour(Tracking.when),
                Tracking.who,
                func.count(Tracking.who)).filter(
                    Tracking.action == c.UPDATED,
                    Tracking.model == "Attendee",
                    Tracking.data.contains("checked_in='None -> datetime")
                    ).group_by(date_trunc_hour(Tracking.when)).group_by(Tracking.who).order_by(
                        date_trunc_hour(Tracking.when))
        admin_checkins = {(result[0], result[1]): result[2] for result in hour_admin_checkins}

        for result in checkin_totals:
            row = [localize_datetime(result[0]), result[1]]

            for admin in admin_list:
                row.append(admin_checkins[result[0], admin] if (result[0], admin) in admin_checkins else '')
            out.writerow(row)
