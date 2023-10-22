from collections import defaultdict
from datetime import datetime, timedelta

import stripe
import time
import pytz
from celery.schedules import crontab
from pockets.autolog import log
from sqlalchemy import not_, or_
from sqlalchemy.orm import joinedload

from uber.config import c
from uber.decorators import render
from uber.models import ApiJob, Attendee, Email, Session, ReceiptTransaction
from uber.tasks.email import send_email
from uber.tasks import celery
from uber.utils import localized_now, TaskUtils
from uber.payments import ReceiptManager


__all__ = ['check_duplicate_registrations', 'check_placeholder_registrations', 'check_pending_badges',
           'check_unassigned_volunteers', 'check_near_cap', 'check_missed_stripe_payments', 'process_api_queue']


@celery.schedule(crontab(minute=0, hour='*/6'))
def check_duplicate_registrations():
    """
    This function looks through registered attendees for attendees with the
    same names and email addresses. It first deletes any unpaid duplicates,
    then sets paid duplicates from "Completed" to "New" and sends an email to
    the registration email address. This allows us to see new duplicate
    attendees without repetitive emails.
    """
    if c.PRE_CON and (c.DEV_BOX or c.SEND_EMAILS):
        subject = c.EVENT_NAME + ' Duplicates Report for ' + localized_now().strftime('%Y-%m-%d')
        with Session() as session:
            if session.no_email(subject):
                grouped = defaultdict(list)
                for a in session.query(Attendee).filter(Attendee.first_name != '') \
                        .filter(Attendee.badge_status == c.COMPLETED_STATUS).options(joinedload(Attendee.group)) \
                        .order_by(Attendee.registered):
                    if not a.group or a.group.status not in [c.WAITLISTED, c.UNAPPROVED]:
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

                if dupes:
                    body = render('emails/daily_checks/duplicates.html', {'dupes': sorted(dupes.items())}, encoding=None)
                    send_email.delay(c.ADMIN_EMAIL, c.REGDESK_EMAIL, subject, body, format='html', model='n/a')


@celery.schedule(crontab(minute=0, hour='*/6'))
def check_placeholder_registrations():
    if c.PRE_CON and c.CHECK_PLACEHOLDERS and (c.DEV_BOX or c.SEND_EMAILS):
        emails = [[
            'Staff',
            c.STAFF_EMAIL,
            Attendee.staffing == True
        ], [
            'Panelist',
            c.PANELS_EMAIL,
            or_(Attendee.badge_type == c.GUEST_BADGE, Attendee.ribbon.contains(c.PANELIST_RIBBON))
        ], [
            'Attendee',
            c.REGDESK_EMAIL,
            not_(or_(
                Attendee.staffing == True,
                Attendee.badge_type == c.GUEST_BADGE,
                Attendee.ribbon.contains(c.PANELIST_RIBBON)))
        ]]  # noqa: E712

        with Session() as session:
            for badge_type, to, per_email_filter in emails:
                weeks_until = (c.EPOCH - localized_now()).days // 7
                subject = '{} {} Placeholder Badge Report ({} weeks to go)'.format(
                    c.EVENT_NAME, badge_type, weeks_until)

                if session.no_email(subject):
                    placeholders = (session.query(Attendee)
                                           .filter(Attendee.placeholder == True,
                                                   Attendee.registered < localized_now() - timedelta(days=3),
                                                   Attendee.badge_status.in_([c.NEW_STATUS, c.COMPLETED_STATUS]),
                                                   per_email_filter)
                                           .options(joinedload(Attendee.group))
                                           .order_by(Attendee.registered, Attendee.full_name).all())  # noqa: E712
                    if placeholders:
                        body = render('emails/daily_checks/placeholders.html', {'placeholders': placeholders}, encoding=None)
                        send_email.delay(c.ADMIN_EMAIL, to, subject, body, format='html', model='n/a')


@celery.schedule(crontab(minute=0, hour='*/6'))
def check_pending_badges():
    if c.PRE_CON and (c.DEV_BOX or c.SEND_EMAILS):
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
                pending = session.query(Attendee).filter_by(badge_status=c.PENDING_STATUS).filter(per_email_filter).all()
                if pending and session.no_email(subject.format(badge_type)):
                    body = render('emails/daily_checks/pending.html', {'pending': pending, 'site_section': site_section}, encoding=None)
                    send_email.delay(c.ADMIN_EMAIL, to, subject.format(badge_type), body, format='html', model='n/a')


@celery.schedule(crontab(minute=0, hour='*/6'))
def check_unassigned_volunteers():
    if c.PRE_CON and (c.DEV_BOX or c.SEND_EMAILS):
        with Session() as session:
            unassigned = session.query(Attendee).filter(
                Attendee.staffing == True,
                not_(Attendee.dept_memberships.any())).order_by(Attendee.full_name).all()  # noqa: E712
            subject = c.EVENT_NAME + ' Unassigned Volunteer Report for ' + localized_now().strftime('%Y-%m-%d')
            if unassigned and session.no_email(subject):
                body = render('emails/daily_checks/unassigned.html', {'unassigned': unassigned}, encoding=None)
                send_email.delay(c.STAFF_EMAIL, c.STAFF_EMAIL, subject, body, format='html', model='n/a')


@celery.schedule(timedelta(minutes=5))
def check_near_cap():
    actual_badges_left = c.ATTENDEE_BADGE_STOCK - c.ATTENDEE_BADGE_COUNT
    for badges_left in [int(num) for num in c.BADGES_LEFT_ALERTS]:
        subject = "BADGES SOLD ALERT: {} BADGES LEFT!".format(badges_left)
        with Session() as session:
            if not session.query(Email).filter_by(subject=subject).first() and actual_badges_left <= badges_left:
                body = render('emails/badges_sold_alert.txt', {'badges_left': actual_badges_left}, encoding=None)
                send_email.delay(c.ADMIN_EMAIL, [c.REGDESK_EMAIL, c.ADMIN_EMAIL], subject, body, model='n/a')


@celery.schedule(timedelta(days=1))
def email_pending_attendees():
    already_emailed_accounts = []

    with Session() as session:
        four_days_old = datetime.now(pytz.UTC) - timedelta(hours=96)
        pending_badges = session.query(Attendee).filter(Attendee.badge_status == c.PENDING_STATUS,
                                                        Attendee.registered < datetime.now(pytz.UTC) - timedelta(hours=24)
                                                        ).order_by(Attendee.registered)
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


@celery.schedule(timedelta(minutes=30))
def process_api_queue():
    known_job_names = ['attendee_account_import', 'attendee_import', 'group_import']
    completed_jobs = {}
    safety_limit = 500
    jobs_processed = 0

    with Session() as session:
        for job_name in known_job_names:
            jobs_to_run = session.query(ApiJob).filter(ApiJob.job_name == job_name, ApiJob.queued == None).limit(safety_limit)
            completed_jobs[job_name] = 0

            for job in jobs_to_run:
                getattr(TaskUtils, job_name)(job)
                session.commit()
                completed_jobs[job_name] += 1
                jobs_processed += 1

            if jobs_processed >= safety_limit:
                return completed_jobs
    return completed_jobs