from authorizenet import apicontractsv1, apicontrollers
from collections import defaultdict
from datetime import datetime, timedelta
from pockets import groupify

import stripe
import time
import pytz
from celery.schedules import crontab
from pockets.autolog import log
from sqlalchemy import not_, or_, insert
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import NoResultFound

from uber.config import c
from uber.custom_tags import readable_join
from uber.decorators import render
from uber.models import (ApiJob, Attendee, AttendeeAccount, BadgeInfo, BadgePickupGroup, Email, Group, ModelReceipt,
                         ReceiptInfo, ReceiptItem, ReceiptTransaction, Session, TerminalSettlement)
from uber.tasks.email import send_email
from uber.tasks import celery
from uber.utils import localized_now, TaskUtils
from uber.payments import ReceiptManager, TransactionRequest


__all__ = ['check_duplicate_registrations', 'check_placeholder_registrations', 'check_pending_badges',
           'check_unassigned_volunteers', 'check_near_cap', 'check_missed_stripe_payments', 'process_api_queue',
           'process_terminal_sale', 'send_receipt_email', 'create_badge_nums', 'create_badge_pickup_groups', 'update_receipt']


@celery.schedule(timedelta(days=1))
def create_badge_nums():
    """
    Takes the configuration for badge ranges and creates BadgeInfo objects
    that can be assigned to attendees as needed. This allows us to rely on
    database-level locking to prevent badge number collisions.

    We take only the smallest and largest number from all badge ranges, ignoring
    any potential gaps -- this allows us to much more easily handle potential config
    changes by checking the min and max badge numbers that already exist.
    """

    if not c.NUMBERED_BADGES:
        return
    
    starts_ends = list(zip(*c.BADGE_RANGES.values()))
    first_badge_num = min(starts_ends[0])
    last_badge_num = max(starts_ends[1])

    with Session() as session:
        any_badge = session.query(BadgeInfo).first()
        if not any_badge:
            new_badge_list = [{"ident": x} for x in range(first_badge_num, last_badge_num + 1)]
        else:
            new_badge_list = []
            first_badge = session.query(BadgeInfo).filter(BadgeInfo.ident == first_badge_num).first()
            last_badge = session.query(BadgeInfo).filter(BadgeInfo.ident == last_badge_num).first()
            if not first_badge:
                min_badge_num = session.query(BadgeInfo.ident).order_by(BadgeInfo.ident).limit(1).first()
                new_badge_list.extend([{"ident": x} for x in range(first_badge_num, min_badge_num[0])])
            if not last_badge:
                max_badge_num = session.query(BadgeInfo.ident).order_by(BadgeInfo.ident.desc()).limit(1).first()
                new_badge_list.extend([{"ident": x} for x in range(max_badge_num[0] + 1, last_badge_num + 1)])
        session.execute(insert(BadgeInfo), new_badge_list)
        session.commit()


@celery.task
def update_receipt(attendee_id, params):
    with Session() as session:
        attendee = session.attendee(attendee_id)
        receipt = session.get_receipt_by_model(attendee)
        if receipt:
            receipt_items = ReceiptManager.auto_update_receipt(attendee, receipt, params)
            session.add_all(receipt_items)
            session.commit()


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
        subject = c.EVENT_NAME + ' Pending Badges Report for ' + localized_now().strftime('%Y-%m-%d')
        with Session() as session:
            pending = session.query(Attendee).filter(Attendee.badge_status == c.PENDING_STATUS,
                                                        Attendee.paid != c.PENDING).all()
            if pending and session.no_email(subject):
                body = render('emails/daily_checks/pending.html',
                                {'pending': pending}, encoding=None)
                send_email.delay(c.REPORTS_EMAIL, c.STAFF_EMAIL, subject, body,
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
def invalidate_at_door_badges():
    if not c.POST_CON:
        return

    with Session() as session:
        pending_badges = session.query(Attendee).filter(Attendee.paid == c.PENDING,
                                                        Attendee.badge_status == c.NEW_STATUS)
        for badge in pending_badges:
            badge.badge_status = c.INVALID_STATUS
            session.add(badge)

        session.commit()


@celery.schedule(timedelta(days=1))
def invalidate_dealer_badges():
    if not c.DEALER_BADGE_DEADLINE or not c.AFTER_DEALER_BADGE_DEADLINE:
        return

    with Session() as session:
        pending_badges = session.query(Attendee).filter(Attendee.admin_notes.contains('Converted badge'),
                                                        Attendee.placeholder,
                                                        Attendee.paid == c.NOT_PAID,
                                                        Attendee.badge_status != c.INVALID_STATUS)
        for badge in pending_badges:
            badge.badge_status = c.INVALID_STATUS
            session.add(badge)

        session.commit()


@celery.schedule(timedelta(days=1))
def email_pending_attendees():
    if c.REMAINING_BADGES < int(c.BADGES_LEFT_ALERTS[0]) or not c.PRE_CON:
        return

    already_emailed_accounts = []

    with Session() as session:
        four_days_old = datetime.now(pytz.UTC) - timedelta(hours=96)
        pending_badges = session.query(Attendee).filter(
            Attendee.paid == c.PENDING,
            Attendee.badge_status == c.PENDING_STATUS,
            Attendee.transfer_code == '',
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
def process_terminal_sale(workstation_num, terminal_id, model_id=None, pickup_group_id=None, **kwargs):
    from uber.payments import SpinTerminalRequest
    from uber.models import TxnRequestTracking, AdminAccount

    message = ''
    c.REDIS_STORE.hset(c.REDIS_PREFIX + 'spin_terminal_txns:' + terminal_id, 'last_request_timestamp',
                       datetime.now().timestamp())

    with Session() as session:
        txn_tracker = TxnRequestTracking(workstation_num=workstation_num, terminal_id=terminal_id,
                                         fk_id=pickup_group_id or model_id,
                                         who=AdminAccount.admin_name())
        session.add(txn_tracker)
        session.commit()

        c.REDIS_STORE.hset(c.REDIS_PREFIX + 'spin_terminal_txns:' + terminal_id, 'tracking_id', txn_tracker.id)
        intent_id = SpinTerminalRequest.intent_id_from_txn_tracker(txn_tracker)

        if pickup_group_id:
            try:
                pickup_group = session.badge_pickup_group(pickup_group_id)
            except NoResultFound:
                txn_tracker.internal_error = f"Badge pickup group {pickup_group_id} not found!"
                session.commit()
                return

            txn_total = 0
            attendee_names_list = []
            receipts = []
            account_email = ''
            try:
                for attendee in pickup_group.pending_paid_attendees:
                    if attendee.managers and not account_email:
                        account_email = attendee.primary_account_email
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

            # Pickup groups get a custom payment description defined here, so get rid of whatever was passed in
            kwargs.pop("description", None)

            payment_request = SpinTerminalRequest(terminal_id=terminal_id,
                                                  receipt_email=account_email,
                                                  description="At-door registration for "
                                                  f"{readable_join(attendee_names_list)}",
                                                  amount=txn_total,
                                                  tracker=txn_tracker,
                                                  **kwargs)
            message = payment_request.create_payment_intent(intent_id)
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
            error = payment_request.error_message or 'Terminal request timed out or was interrupted'
            c.REDIS_STORE.hset(c.REDIS_PREFIX + 'spin_terminal_txns:' + terminal_id,
                               'last_error', error)
            txn_tracker.internal_error = error


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


@celery.schedule(timedelta(hours=3))
def check_authnet_held_txns():
    if not c.AUTHORIZENET_LOGIN_ID:
        return

    held_ids = []
    
    merchantAuth = apicontractsv1.merchantAuthenticationType(
        name=c.AUTHORIZENET_LOGIN_ID,
        transactionKey=c.AUTHORIZENET_LOGIN_KEY
        )
    
    heldTransactionListRequest = apicontractsv1.getUnsettledTransactionListRequest()
    heldTransactionListRequest.merchantAuthentication = merchantAuth
    heldTransactionListRequest.status = 'pendingApproval'
    heldTransactionListController = apicontrollers.getUnsettledTransactionListController(heldTransactionListRequest)
    heldTransactionListController.execute()
    heldTransactionListResponse = heldTransactionListController.getresponse()

    if heldTransactionListResponse is not None:
        if heldTransactionListResponse.messages.resultCode == apicontractsv1.messageTypeEnum.Ok:
            if heldTransactionListResponse.totalNumInResultSet > 0:
                for transaction in heldTransactionListResponse.transactions.transaction:
                    held_ids.append(str(transaction.transId))
        else:
            if heldTransactionListResponse.messages:
                log.debug('Failed to get unsettled transaction list.\nCode:%s \nText:%s' % (heldTransactionListResponse.messages.message[0]['code'].text,
                                                                                            heldTransactionListResponse.messages.message[0]['text'].text))

    with Session() as session:
        hold_txns = session.query(ReceiptTransaction).filter(ReceiptTransaction.charge_id.in_(held_ids),
                                                             ReceiptTransaction.on_hold == False)
        release_txns = session.query(ReceiptTransaction).filter(~ReceiptTransaction.charge_id.in_(held_ids),
                                                                ReceiptTransaction.on_hold == True)

        for txn in hold_txns:
            txn.on_hold = True
            session.add(txn)

        release_txns_by_charge_id = groupify(release_txns, 'charge_id')

        for charge_id, txns in release_txns_by_charge_id.items():
            txn_status = TransactionRequest()
            error = txn_status.get_authorizenet_txn(charge_id)

            if error:
                log.error(f"Tried to check status of transaction {charge_id} but got the error: {error}")
            else:
                if txn_status.response.transactionStatus != "settledSuccessfully":
                    body = render('emails/held_txn_declined.html',
                                  {'txns': txns, 'status': str(txn_status.response.transactionStatus)},
                                  encoding=None)
                    subject = f"AuthNet Held Transaction Declined: {charge_id}"
                    send_email.delay(c.REPORTS_EMAIL, c.REGDESK_EMAIL, subject, body,
                                     format='html', model='n/a')

                for txn in txns:
                    if txn_status.response.transactionStatus != "settledSuccessfully":
                        txn.cancelled = datetime.now()
                    else:
                        txn.on_hold = False
                    session.add(txn)


@celery.schedule(timedelta(days=1))
def create_badge_pickup_groups():
    if c.ATTENDEE_ACCOUNTS_ENABLED and c.BADGE_PICKUP_GROUPS_ENABLED and (c.AFTER_PREREG_TAKEDOWN or c.DEV_BOX):
        with Session() as session:
            skip_account_ids = set(s for (s,) in session.query(BadgePickupGroup.account_id).all())
            for account in session.query(AttendeeAccount).filter(~AttendeeAccount.id.in_(skip_account_ids)):
                pickup_group = BadgePickupGroup(account_id=account.id)
                pickup_group.build_from_account(account)
                session.add(pickup_group)
            session.commit()


@celery.schedule(timedelta(days=14))
def reassign_purchaser_ids():
    with Session() as session:
        purchaser_ids = session.query(
            ReceiptItem.purchaser_id).filter(ReceiptItem.purchaser_id != None).join(
                ModelReceipt).join(Attendee, ModelReceipt.owner_id == Attendee.id
                                   ).filter(Attendee.is_valid == True).group_by(ReceiptItem.purchaser_id).all()
        group_purchaser_ids = session.query(
            ReceiptItem.purchaser_id).filter(ReceiptItem.purchaser_id != None).join(
                ModelReceipt).join(Group, ModelReceipt.owner_id == Group.id
                                   ).filter(Group.is_valid == True).group_by(ReceiptItem.purchaser_id).all()
        purchaser_id_list = [r for r, in purchaser_ids] + [r for r, in group_purchaser_ids]
        invalid_attendees = session.query(Attendee).filter(Attendee.is_valid == False, Attendee.id.in_(purchaser_id_list))

        for attendee in invalid_attendees:
            alt_id = None
            valid_dupe = session.query(Attendee).filter(Attendee.is_valid == True,
                                                        Attendee.first_name == attendee.first_name,
                                                        Attendee.last_name == Attendee.last_name,
                                                        Attendee.email == attendee.email).first()
            if valid_dupe:
                alt_id = valid_dupe.id
            elif not c.ATTENDEE_ACCOUNTS_ENABLED and attendee.badge_pickup_group:
                alt_id = attendee.badge_pickup_group.fallback_purchaser_id

            if alt_id:
                receipt_items = session.query(ReceiptItem).filter(ReceiptItem.purchaser_id == attendee.id).join(
                    ModelReceipt).join(Attendee, ModelReceipt.owner_id == Attendee.id).filter(Attendee.is_valid == True)
                for item in receipt_items:
                    item.purchaser_id = alt_id
                    session.add(item)


@celery.schedule(timedelta(days=60))
def sunset_empty_accounts():
    with Session() as session:
        empty_accounts = session.query(AttendeeAccount).filter(AttendeeAccount.unused_years > 2)
        for account in empty_accounts:
            session.delete(account)
        session.commit()


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
