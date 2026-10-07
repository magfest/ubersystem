from collections import defaultdict
from datetime import timedelta, datetime
import pytz
import uuid
from time import sleep, time
import traceback
import logging

from celery.schedules import crontab
from sqlalchemy import select, func
from sqlalchemy.orm import joinedload, raiseload, sessionmaker
from sqlalchemy.orm.exc import NoResultFound

from uber import utils
from uber.amazon_ses import email_sender
from uber.automated_emails import AutomatedEmailFixture
from uber.config import c
from uber.email import EmailService
from uber.models import AutomatedEmail, Email, MagModel, UberSession, Session
from uber.tasks import celery

log = logging.getLogger(__name__)


__all__ = ['notify_admins_of_pending_emails', 'send_automated_emails', 'send_email',
           'check_emails_for_fixture', 'generate_missing_emails']

def _is_dev_email(email):
    """
    Returns True if `email` is a development email address.

    Development email addresses either end in "mailinator.com" or exist
    in the `c.DEVELOPER_EMAIL` list.
    """
    return email.endswith('mailinator.com') or email in c.DEVELOPER_EMAIL


@celery.schedule(crontab(hour=6, minute=0, day_of_week=1))
def notify_admins_of_pending_emails():
    """
    Generate and email a report which alerts admins that there are automated
    emails which are ready to send, but can't be sent until they are approved
    by an admin.

    Also notifies them if there's any emails with no policy.
    """

    if not c.PRE_CON or not (c.DEV_BOX or c.SEND_EMAILS):
        return

    with Session() as session:
        pending_emails = session.query(Email.automated_email_id, func.count(Email.id)).filter(
            Email.status == c.UNAPPROVED).group_by(Email.automated_email_id)
        pending_count_by_id = {id: count for id, count in pending_emails}
        pending_automated_emails = session.query(AutomatedEmail).filter(AutomatedEmail.id.in_(pending_count_by_id.keys()))
        pending_emails_by_sender = defaultdict(list)
        depts_by_sender = EmailService.emails_from_depts(session)
        subjects_by_id = {}

        for email in pending_automated_emails:
            pending_emails_by_sender[email.sender].append((email.id, pending_count_by_id[email.id]))
            subjects_by_id[email.id] = email.subject

        for sender, automated_emails in pending_emails_by_sender.items():
            if sender == c.REPORTS_CC_EMAIL:
                emails_by_sender = pending_emails_by_sender
            elif sender not in depts_by_sender:
                continue
            else:
                emails_by_sender = {sender: automated_emails}

            EmailService.queue_email(session, 'pending_emails_admin', to=sender, sender=c.REPORTS_EMAIL,
                                     subject=f'{c.EVENT_NAME} Pending Emails Report for {utils.localized_now().strftime('%Y-%m-%d')}',
                                     data={'pending_emails_by_sender': emails_by_sender, 'primary_sender': sender,
                                           'subjects_by_id': subjects_by_id})
        
        session.commit()
        return pending_emails_by_sender
    

@celery.task
def check_emails_for_fixture(id):
    from uber.tasks import redis

    task_in_progress = redis.check_task_progress('email_generation:' + id, 'check_emails_for_fixture')
    if task_in_progress:
        return

    c.REDIS_STORE.hset(c.REDIS_PREFIX + 'email_generation:' + id, 'request_timestamp',
                       datetime.now().timestamp())
    with Session() as session:
        fixture_obj = session.get(AutomatedEmail, id)
        if not fixture_obj.fixture:
            c.REDIS_STORE.hset(c.REDIS_PREFIX + 'email_generation:' + id, 'error',
                               "This email has no configuration. If this issue persists, contact your developer.")
        if not fixture_obj.can_generate:
            c.REDIS_STORE.hset(c.REDIS_PREFIX + 'email_generation:' + id, 'error',
                               "This email is not eligible for generation. Please check the send policy and date restrictions.")
        email_count = EmailService.check_emails_for_fixture(session, fixture_obj)
        session.commit()
        if email_count or email_count == 0:
            c.REDIS_STORE.hset(c.REDIS_PREFIX + 'email_generation:' + id, 'emails_generated', email_count)


@celery.schedule(timedelta(minutes=60))
def generate_missing_emails():
    with Session() as session:
        fixture_objs = session.query(AutomatedEmail).filter(*AutomatedEmail.filters_for_allowed)
        for fixture_obj in fixture_objs:
            id = fixture_obj.id
            email_check_status = c.REDIS_STORE.hgetall(c.REDIS_PREFIX + 'email_generation:' + id)
            if not email_check_status and fixture_obj.fixture:
                c.REDIS_STORE.hset(c.REDIS_PREFIX + 'email_generation:' + id, 'request_timestamp',
                                   datetime.now().timestamp())
                email_count = EmailService.check_emails_for_fixture(session, fixture_obj)
                session.commit()
                if email_count or email_count == 0:
                    # Give admins a chance to see a result if they try to poll email gen while this function is running
                    c.REDIS_STORE.hset(c.REDIS_PREFIX + 'email_generation:' + id, 'emails_generated', email_count)
                    sleep(300)
                    c.REDIS_STORE.delete(c.REDIS_PREFIX + 'email_generation:' + id)


@celery.schedule(timedelta(minutes=5))
def send_automated_emails():
    from uber.tasks import panels, redis

    if not (c.DEV_BOX or c.SEND_EMAILS):
        return

    task_in_progress = redis.check_task_progress('email_processing', 'send_automated_emails')
    if task_in_progress:
        log.debug("Skipping email processing as it's being worked on by another thread.")
        return

    quantity_sent = 0
    panels.setup_panel_emails(reconcile_fixtures=False)
    started = datetime.now()
    c.REDIS_STORE.hset(c.REDIS_PREFIX + 'email_processing', 'started_timestamp', started.timestamp())

    try:
        with Session() as session:
            for model_class in set([fixture.model for fixture in AutomatedEmail._fixtures.values()]):
                model_name = model_class.__name__ if model_class else 'Classless'
                log.debug(f"Sending queued emails for {model_name}.")
                quantity_sent += EmailService.process_emails_by_class(session, model_class)
            log.info(f"Sent {quantity_sent} emails in {(datetime.now() - started).seconds} seconds.")
    except Exception:
        traceback.print_exc()

    c.REDIS_STORE.delete(c.REDIS_PREFIX + 'email_processing')
