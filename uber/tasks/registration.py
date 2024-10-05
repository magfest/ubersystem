from collections import defaultdict
from datetime import datetime, timedelta

import stripe
import time
import pytz
from celery.schedules import crontab
from pockets.autolog import log
from sqlalchemy import not_, or_
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import NoResultFound

from uber.config import c
from uber.custom_tags import readable_join
from uber.decorators import render
from uber.models import ApiJob, Attendee, TerminalSettlement, Email, Session, ReceiptInfo, ReceiptTransaction
from uber.tasks.email import send_email
from uber.tasks import celery
from uber.utils import localized_now, TaskUtils
from uber.payments import ReceiptManager


__all__ = ['check_duplicate_registrations', 'check_placeholder_registrations', 'check_pending_badges',
           'check_unassigned_volunteers', 'check_near_cap', 'check_missed_stripe_payments', 'process_api_queue',
           'process_terminal_sale', 'send_receipt_email']


@celery.schedule(crontab(minute=0, hour='*/6'))
def check_duplicate_registrations():
    """
    This function looks through registered attendees for attendees with the
    same names and email addresses. It first deletes any unpaid duplicates,
    then sets paid duplicates from "Completed" to "New" and sends an email to
    the registration email address. This allows us to see new duplicate
    attendees without repetitive emails.
    """
    if c.PRE_CON and (c.DEV_BOX or c.SEND_EMAILS) and c.REPORTS_EMAIL:
        subject = c.EVENT_NAME + ' Duplicates Report for ' + localized_now().strftime('%Y-%m-%d')
        with Session() as session:
            if session.no_email(subject):
                grouped = defaultdict(list)
                for a in session.query(Attendee).filter(Attendee.first_name != '') \
                        .filter(Attendee.badge_status == c.COMPLETED_STATUS).options(joinedload(Attendee.group)) \
                        .order_by(Attendee.registered):
                    if not a.group or (not a.group.is_dealer or a.group.status not in [c.WAITLISTED, c.UNAPPROVED]):
                        grouped[a.full_name, a.email.lower()].append(a)

                dupes = {k: v for k, v in grouped.items() if len(v) > 1}

                for who, attendees in dupes.items():
                    paid = [a for a in attendees if a.paid == c.HAS_PAID]
                    unpaid = [a for a in attendees if a.paid == c.NOT_PAID]
                    if len(paid) == 1 and len(attendees) == 1 + len(unpaid):
                        for a in unpaid:
                            session.delete(a)
                        del dupes[who]
                    for a in paid:
                        a.badge_status = c.NEW_STATUS

                if dupes and session.no_email(subject):
                    body = render('emails/daily_checks/duplicates.html',
                                  {'dupes': sorted(dupes.items())}, encoding=None)
                    send_email.delay(c.REPORTS_EMAIL, c.REGDESK_EMAIL, subject, body, format='html', model='n/a')


@celery.schedule(crontab(minute=0, hour='*/6'))
def check_placeholder_registrations():
    if c.PRE_CON and c.CHECK_PLACEHOLDERS and (c.DEV_BOX or c.SEND_EMAILS) and c.REPORTS_EMAIL:
        emails = [[
            'Staff',
            c.STAFF_EMAIL,
            Attendee.staffing == True,  # noqa: E712
            Attendee.is_valid == True  # noqa: E712
        ], [
            'Panelist',
            c.PANELS_EMAIL,
            or_(Attendee.badge_type == c.GUEST_BADGE, Attendee.ribbon.contains(c.PANELIST_RIBBON)),
            Attendee.is_valid == True  # noqa: E712
        ], [
            'Attendee',
            c.REGDESK_EMAIL,
            not_(or_(
                Attendee.staffing == True,  # noqa: E712
                Attendee.badge_type == c.GUEST_BADGE,
                Attendee.ribbon.contains(c.PANELIST_RIBBON))),
            Attendee.is_valid == True  # noqa: E712
        ]]

        with Session() as session:
            for badge_type, to, per_email_filter in emails:
                weeks_until = (c.EPOCH - localized_now()).days // 7
                subject = '{} {} Placeholder Badge Report ({} weeks to go)'.format(
                    c.EVENT_NAME, badge_type, weeks_until)

                if session.no_email(subject):
                    placeholders = (session.query(Attendee)
                                           .filter(Attendee.placeholder == True,  # noqa: E712
                                                   Attendee.registered < localized_now() - timedelta(days=3),
                                                   Attendee.badge_status.in_([c.NEW_STATUS, c.COMPLETED_STATUS]),
                                                   per_email_filter)
                                           .options(joinedload(Attendee.group))
                                           .order_by(Attendee.registered, Attendee.full_name).all())
                    if placeholders:
                        body = render('emails/daily_checks/placeholders.html',
                                      {'placeholders': placeholders}, encoding=None)
                        send_email.delay(c.REPORTS_EMAIL, to, subject, body, format='html', model='n/a')


@celery.schedule(crontab(minute=0, hour='*/6'))
def check_pending_badges():
    if c.PRE_CON and (c.DEV_BOX or c.SEND_EMAILS) and c.REPORTS_EMAIL:
        emails = [[
            'Staff',
            c.STAFF_EMAIL,
            Attendee.badge_type == c.STAFF_BADGE,
            'staffing_admin'
        ], [
            'Attendee',
            c.REGDESK_EMAIL,
            Attendee.badge_type != c.STAFF_BADGE,
            'registration'
        ]]
        subject = c.EVENT_NAME + ' Pending {} Badge Report for ' + localized_now().strftime('%Y-%m-%d')
        with Session() as session:
            for badge_type, to, per_email_filter, site_section in emails:
                pending = session.query(Attendee).filter(Attendee.badge_status == c.PENDING_STATUS,
                                                         Attendee.paid != c.PENDING,
                                                         per_email_filter).all()
                if pending and session.no_email(subject.format(badge_type)):
                    body = render('emails/daily_checks/pending.html',
                                  {'pending': pending, 'site_section': site_section}, encoding=None)
                    send_email.delay(c.REPORTS_EMAIL, to, subject.format(badge_type), body,
                                     format='html', model='n/a')


@celery.schedule(crontab(minute=0, hour='*/6'))
def check_unassigned_volunteers():
    if c.PRE_CON and (c.DEV_BOX or c.SEND_EMAILS) and c.REPORTS_EMAIL:
        with Session() as session:
            unassigned = session.query(Attendee).filter(
                Attendee.is_valid == True,  # noqa: E712
                Attendee.staffing == True,  # noqa: E712
                Attendee.badge_status != c.REFUNDED_STATUS,
                Attendee.is_unassigned == False,  # noqa: E712
                not_(Attendee.dept_memberships.any())).order_by(Attendee.full_name).all()  # noqa: E712
            subject = c.EVENT_NAME + ' Unassigned Volunteer Report for ' + localized_now().strftime('%Y-%m-%d')
            if unassigned and session.no_email(subject):
                body = render('emails/daily_checks/unassigned.html', {'unassigned': unassigned}, encoding=None)
                send_email.delay(c.REPORTS_EMAIL, c.STAFF_EMAIL, subject, body, format='html', model='n/a')


@celery.schedule(timedelta(minutes=5))
def check_near_cap():
    if c.REPORTS_EMAIL:
        actual_badges_left = c.ATTENDEE_BADGE_STOCK - c.ATTENDEE_BADGE_COUNT
        for badges_left in [int(num) for num in c.BADGES_LEFT_ALERTS]:
            subject = "BADGES SOLD ALERT: {} BADGES LEFT!".format(badges_left)
            with Session() as session:
                if not session.query(Email).filter_by(subject=subject).first() and actual_badges_left <= badges_left:
                    body = render('emails/badges_sold_alert.txt', {'badges_left': actual_badges_left}, encoding=None)
                    send_email.delay(c.REPORTS_EMAIL, [c.REGDESK_EMAIL, c.ADMIN_EMAIL], subject, body, model='n/a')


@celery.schedule(timedelta(days=1))
def email_pending_attendees():
    if c.REMAINING_BADGES < int(c.BADGES_LEFT_ALERTS[0]) or c.AT_THE_CON:
        return

    already_emailed_accounts = []

    with Session() as session:
        four_days_old = datetime.now(pytz.UTC) - timedelta(hours=96)
        pending_badges = session.query(Attendee).filter(
            Attendee.badge_status == c.PENDING_STATUS,
            Attendee.registered < datetime.now(pytz.UTC) - timedelta(hours=24)).order_by(Attendee.registered)
        for badge in pending_badges:
            # Update `compare_date` to prevent early deletion of badges registered before a certain date
            # Implemented for MFF 2023 but let's be honest, we'll probably need it again
            compare_date = max(badge.registered, datetime(2023, 9, 25, tzinfo=pytz.UTC))
            if compare_date < four_days_old:
                badge.badge_status = c.INVALID_STATUS
                session.commit()
            else:
                if c.ATTENDEE_ACCOUNTS_ENABLED:
                    email_to = badge.managers[0].email
                    if email_to in already_emailed_accounts:
                        continue
                else:
                    email_to = badge.email

                email_ident = 'pending_badge_' + badge.id
                already_emailed = session.query(Email.ident).filter(Email.ident == email_ident).first()

                if already_emailed:
                    if c.ATTENDEE_ACCOUNTS_ENABLED:
                        already_emailed_accounts.append(email_to)
                    continue

                body = render('emails/reg_workflow/pending_badges.html',
                              {'account': badge.managers[0] if badge.managers else None,
                               'attendee': badge, 'compare_date': compare_date}, encoding=None)
                send_email.delay(
                    c.REGDESK_EMAIL,
                    email_to,
                    f"You have an incomplete {c.EVENT_NAME} registration!",
                    body,
                    format='html',
                    model=badge.managers[0].to_dict() if c.ATTENDEE_ACCOUNTS_ENABLED else badge.to_dict(),
                    ident=email_ident
                )

                if c.ATTENDEE_ACCOUNTS_ENABLED:
                    already_emailed_accounts.append(email_to)


@celery.task
def send_receipt_email(receipt_id):
    with Session() as session:
        receipt = session.query(ReceiptInfo).filter_by(id=receipt_id).first()
        if not receipt:
            log.error(f"Could not send receipt {receipt_id} to model {receipt.fk_email_model} {receipt.fk_email_id}: "
                      "receipt info not found!")
            return

        if not receipt.receipt_txns:
            log.error(f"Could not send receipt {receipt_id} to model {receipt.fk_email_model} {receipt.fk_email_id}: "
                      "receipt transactions not found!")
            return

        model = Session.resolve_model(receipt.fk_email_model)
        email_to = session.query(model).filter_by(id=receipt.fk_email_id).first()
        if not email_to:
            log.error(f"Could not send receipt {receipt_id} to model {receipt.fk_email_model} "
                      f"{receipt.fk_email_id}: model not found!")
            return

        to = getattr(email_to, 'email', getattr(email_to, 'email_address', ''))
        subject = f"Your {c.EVENT_NAME_AND_YEAR} receipt [#{receipt.reference_id}]"

        body = render('emails/reg_workflow/receipt.html', {'receipt': receipt}, encoding=None)
        send_email.delay(c.ADMIN_EMAIL, to, subject, body, format='html', model='n/a')


@celery.task
def close_out_terminals(workstation_and_terminal_ids, who):
    from uber.payments import SpinTerminalRequest

    request_timestamp = datetime.now().timestamp()

    with Session() as session:
        for workstation_num, terminal_id in workstation_and_terminal_ids:
            settlement = TerminalSettlement(
                batch_timestamp=request_timestamp,
                batch_who=who,
                workstation_num=workstation_num,
                terminal_id=terminal_id,
            )
            session.add(settlement)
            session.commit()

            settle_request = SpinTerminalRequest(terminal_id)
            settle_response = settle_request.close_out_terminal()
            if settle_response:
                settle_response_json = settle_response.json()
                settlement.response = settle_response_json
                if not settle_request.api_response_successful(settle_response_json):
                    settlement.error = settle_request.error_message_from_response(settle_response_json)
            else:
                settlement.error = "No response!"
            session.add(settlement)
            session.commit()


@celery.task
def process_terminal_sale(workstation_num, terminal_id, model_id=None, account_id=None, **kwargs):
    from uber.payments import SpinTerminalRequest
    from uber.models import TxnRequestTracking, AdminAccount

    message = ''
    c.REDIS_STORE.hset(c.REDIS_PREFIX + 'spin_terminal_txns:' + terminal_id, 'last_request_timestamp',
                       datetime.now().timestamp())

    with Session() as session:
        txn_tracker = TxnRequestTracking(workstation_num=workstation_num, terminal_id=terminal_id,
                                         who=AdminAccount.admin_name())
        session.add(txn_tracker)
        session.commit()

        c.REDIS_STORE.hset(c.REDIS_PREFIX + 'spin_terminal_txns:' + terminal_id, 'tracking_id', txn_tracker.id)
        intent_id = SpinTerminalRequest.intent_id_from_txn_tracker(txn_tracker)

        if account_id:
            try:
                account = session.attendee_account(account_id)
            except NoResultFound:
                txn_tracker.internal_error = f"Account {account_id} not found!"
                session.commit()
                return

            txn_total = 0
            attendee_names_list = []
            receipts = []
            try:
                for attendee in account.at_door_attendees:
                    receipt = session.get_receipt_by_model(attendee)
                    if receipt:
                        incomplete_txn = receipt.get_last_incomplete_txn()
                        if incomplete_txn:
                            incomplete_txn.cancelled = datetime.now()
                            session.add(incomplete_txn)
                    else:
                        receipt = session.get_receipt_by_model(attendee, create_if_none="DEFAULT")
                        session.add(receipt)

                    if receipt.current_amount_owed:
                        receipts.append(receipt)
                        txn_total += receipt.current_amount_owed
                        attendee_names_list.append(attendee.full_name +
                                                   (f" ({attendee.badge_printed_name})"
                                                    if attendee.badge_printed_name else ""))
            except Exception as e:
                txn_tracker.internal_error = f"Exception while building at-door group payment: {str(e)}"
                session.commit()
                return

            # Accounts get a custom payment description defined here, so get rid of whatever was passed in
            kwargs.pop("description", None)

            payment_request = SpinTerminalRequest(terminal_id=terminal_id,
                                                  receipt_email=account.email,
                                                  description="At-door registration for "
                                                  f"{readable_join(attendee_names_list)}",
                                                  amount=txn_total,
                                                  tracker=txn_tracker,
                                                  **kwargs)
            message = payment_request.create_stripe_intent(intent_id)
            if message:
                txn_tracker.internal_error = message
                session.commit()
                return
            for receipt in receipts:
                receipt_manager = ReceiptManager(receipt)
                error = receipt_manager.create_payment_transaction(payment_request.description,
                                                                   payment_request.intent,
                                                                   receipt.current_amount_owed,
                                                                   method=c.SQUARE)
                if error:
                    session.rollback()
                    txn_tracker.internal_error = error
                    session.commit()
                    return
                session.add_all(receipt_manager.items_to_add)
        elif model_id:
            try:
                model = session.attendee(model_id)
            except NoResultFound:
                try:
                    model = session.group(model_id)
                except NoResultFound:
                    try:
                        model = session.art_show_application(model_id)
                    except NoResultFound:
                        txn_tracker.internal_error = f"Could not find model {model_id}!"
                        session.commit()
                        return
            receipt = session.get_receipt_by_model(model, create_if_none="DEFAULT")
            payment_request = SpinTerminalRequest(terminal_id=terminal_id,
                                                  receipt=receipt,
                                                  tracker=txn_tracker,
                                                  **kwargs)
            message = payment_request.prepare_payment(intent_id=intent_id, payment_method=c.SQUARE)
            if message:
                txn_tracker.internal_error = message
                session.commit()
                return
        c.REDIS_STORE.hset(c.REDIS_PREFIX + 'spin_terminal_txns:' + terminal_id, 'intent_id', payment_request.intent.id)

        response = payment_request.send_sale_txn()

        if response:
            payment_request.process_sale_response(session, response)
        else:
            c.REDIS_STORE.hset(c.REDIS_PREFIX + 'spin_terminal_txns:' + terminal_id,
                               'last_error', payment_request.error_message)
            txn_tracker.internal_error = payment_request.error_message


@celery.schedule(timedelta(minutes=30))
def check_missed_stripe_payments():
    if c.AUTHORIZENET_LOGIN_ID:
        return

    pending_ids = []
    paid_ids = []
    with Session() as session:
        pending_payments = session.query(ReceiptTransaction).filter(ReceiptTransaction.intent_id != '',
                                                                    ReceiptTransaction.charge_id == '')
        for payment in pending_payments:
            pending_ids.append(payment.intent_id)

    events = stripe.Event.list(type='payment_intent.succeeded', created={
        # Check for events created in the last hour.
        'gte': int(time.time() - 60 * 60),
    })

    for event in events.auto_paging_iter():
        payment_intent = event.data.object
        if payment_intent.id in pending_ids:
            paid_ids.append(payment_intent.id)
            ReceiptManager.mark_paid_from_stripe_intent(payment_intent)
    return paid_ids


@celery.task
def import_attendee_accounts(accounts, admin_id, admin_name, target_server, api_token):
    already_queued = 0
    with Session() as session:
        for account in accounts:
            id = account['id']
            existing_import = session.query(ApiJob).filter(ApiJob.job_name == "attendee_account_import",
                                                           ApiJob.query == id,
                                                           ApiJob.completed == None,  # noqa: E711
                                                           ApiJob.cancelled == None,  # noqa: E711
                                                           ApiJob.errors == '').count()
            if existing_import:
                already_queued += 1
            else:
                import_job = ApiJob(
                    admin_id=admin_id,
                    admin_name=admin_name,
                    job_name="attendee_account_import",
                    target_server=target_server,
                    api_token=api_token,
                    query=id,
                    json_data={'all': False}
            )
                if len(accounts) < 25:
                    TaskUtils.attendee_account_import(import_job)
                else:
                    session.add(import_job)
        session.commit()
    count = len(accounts) - already_queued
    return f"{count} account(s) queued for import. {already_queued} jobs were already in the queue."
    


@celery.schedule(timedelta(minutes=30))
def process_api_queue():
    known_job_names = ['attendee_account_import', 'attendee_import', 'group_import']
    completed_jobs = {}
    safety_limit = 500
    jobs_processed = 0

    with Session() as session:
        for job_name in known_job_names:
            jobs_to_run = session.query(ApiJob).filter(ApiJob.job_name == job_name,
                                                       ApiJob.queued == None).limit(safety_limit)  # noqa: E711
            completed_jobs[job_name] = 0

            for job in jobs_to_run:
                getattr(TaskUtils, job_name)(job)
                session.commit()
                completed_jobs[job_name] += 1
                jobs_processed += 1

            if jobs_processed >= safety_limit:
                return completed_jobs
    return completed_jobs
