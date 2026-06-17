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


__all__ = ['notify_admins_of_pending_emails', 'send_automated_emails', 'send_email', 'check_emails_for_fixture']

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
        pending_emails = session.query(Email.automated_email_id, func.count(Email.id)).filter(Email.status == c.UNAPPROVED
                                                                                              ).group_by(Email.automated_email_id)
        pending_count_by_id = {id: count for id, count in pending_emails}
        pending_automated_emails = session.query(AutomatedEmail).filter(AutomatedEmail.id.in_(pending_count_by_id.keys()))
        pending_emails_by_sender = defaultdict(list)
        depts_by_sender = EmailService.emails_from_depts(session)

        for email in pending_automated_emails:
            pending_emails_by_sender[email.sender].append({email: pending_count_by_id[email.id]})

        for sender, automated_emails in pending_emails_by_sender.items():
            if sender == c.STAFF_EMAIL:
                # STOPS receives a report on ALL the pending emails.
                emails_by_sender = pending_emails_by_sender
            elif sender not in depts_by_sender:
                continue
            else:
                emails_by_sender = {sender: automated_emails}

            EmailService.queue_email(session, 'pending_emails_admin', to=sender, sender=c.REPORTS_EMAIL,
                                     subject=f'{c.EVENT_NAME} Pending Emails Report for {utils.localized_now().strftime('%Y-%m-%d')}',
                                     data={'pending_emails_by_sender': emails_by_sender, 'primary_sender': sender,
                                           'depts_by_sender': depts_by_sender},
                                     replace_unsent=True)

        return utils.groupify(pending_emails, 'sender', 'ident')
    

@celery.task
def check_emails_for_fixture(id):
    email_check_status = c.REDIS_STORE.hgetall(c.REDIS_PREFIX + 'email_generation:' + id)
    if email_check_status:
        request_timestamp = c.REDIS_STORE.hget(c.REDIS_PREFIX + 'email_generation:' + id, 'request_timestamp')
        request_time = datetime.fromtimestamp(float(request_timestamp))
        if request_time + timedelta(hours=2) < datetime.now():
            log.error(f"The check_emails_for_fixture task for {id} took more than 2 hours. There may be an issue with email generation.")
            c.REDIS_STORE.delete(c.REDIS_PREFIX + 'email_generation:' + id)
        else:
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
        if email_count or email_count == 0:
            c.REDIS_STORE.hset(c.REDIS_PREFIX + 'email_generation:' + id, 'emails_generated', email_count)


@celery.schedule(timedelta(minutes=5))
def send_automated_emails():
    """
    Send any queued emails while using DB locks to ensure the same email doesn't get processed twice.
    Emails are processed per model.
    """
    if not (c.DEV_BOX or c.SEND_EMAILS):
        return None

    quantity_sent = 0
    start_time = time()

    try:
        Session.session_factory = sessionmaker(bind=Session.engine, expire_on_commit=False, autoflush=False, autocommit=False,
                                               query_cls=UberSession.QuerySubclass)
        with Session() as session:
            for model_class in set([fixture.model for fixture in AutomatedEmail._fixtures.values()]):
                with Session.engine.connect() as guard_conn:
                    model_name = model_class.__name__ if model_class else 'Classless'
                    lock_key = model_name.lower() + '_email_queue'
                    lock_key = int.from_bytes(lock_key.encode())  & ((1<<63)-1)
                    log.debug(f"Attempting to lock {model_name} email queue for processing.")

                    with guard_conn.begin():
                        if guard_conn.execute(select(func.pg_try_advisory_lock(lock_key))).scalar():
                            log.debug(f"Sending queued emails for {model_name}.")
                            quantity_sent += EmailService.process_emails_by_class(session, model_class)
                            session.commit()
                            if guard_conn.execute(select(func.pg_advisory_unlock(lock_key))).scalar():
                                log.debug(f"{model_name} email queue sent and unlocked.")
                        else:
                            log.debug(f"Skipping {model_name} as it is being worked by another thread.")
            log.info(f"Sent {quantity_sent} emails in {time() - start_time} seconds.")
    except Exception:
        traceback.print_exc()
