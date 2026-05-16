from collections.abc import Mapping
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
from uber.decorators import render
from uber.email import EmailService
from uber.models import AutomatedEmail, Email, MagModel, UberSession, Session
from uber.tasks import celery

log = logging.getLogger(__name__)


__all__ = ['notify_admins_of_pending_emails', 'send_automated_emails', 'send_email']

def _is_dev_email(email):
    """
    Returns True if `email` is a development email address.

    Development email addresses either end in "mailinator.com" or exist
    in the `c.DEVELOPER_EMAIL` list.
    """
    return email.endswith('mailinator.com') or email in c.DEVELOPER_EMAIL


@celery.task
def send_email(
        sender,
        to,
        subject,
        body,
        format='text',
        cc=(),
        bcc=(),
        replyto=(),
        model=None,
        ident=None,
        automated_email=None,
        session=None):
    return

    to, cc, bcc, replyto = map(lambda x: utils.listify(x if x else []), [to, cc, bcc, replyto])
    original_to, original_cc, original_bcc, original_replyto = to, cc, bcc, replyto
    ident = ident or subject
    if c.DEV_BOX:
        to, cc, bcc, replyto = map(lambda xs: list(filter(_is_dev_email, xs)), [to, cc, bcc, replyto])

    record_email = False

    if c.SEND_EMAILS and to:
        message = {
            'bodyText' if format == 'text' else 'bodyHtml': body,
            'subject': subject,
            'charset': 'UTF-8',
            }
        log.info('Attempting to send email {}', locals())

        try:
            error_msg = email_sender.sendEmail(
                            source=sender,
                            toAddresses=to,
                            replyToAddresses=replyto,
                            ccAddresses=cc,
                            bccAddresses=bcc,
                            message=message)
            if error_msg:
                log.error('Error while sending email: ' + str(error_msg))
            else:
                record_email = True
        except Exception as error:
            log.error('Error while sending email: {}'.format(str(error)))
        sleep(0.1)  # Avoid hitting rate limit
    else:
        log.error(f'Email sending turned off, so unable to send {locals()}')
        record_email = True if c.DEV_BOX else False

    if original_to:
        body = body.decode('utf-8') if isinstance(body, bytes) else body
        if isinstance(model, MagModel):
            fk_kwargs = {'fk_id': model.id, 'model': model.__class__.__name__}
        elif isinstance(model, Mapping):
            fk_kwargs = {'fk_id': model.get('id', None), 'model': model.get('_model', model.get('__type__', 'n/a'))}
        else:
            fk_kwargs = {'model': 'n/a'}

        if automated_email:
            if isinstance(automated_email, MagModel):
                fk_kwargs['automated_email_id'] = automated_email.id
            elif isinstance(model, Mapping):
                fk_kwargs['automated_email_id'] = automated_email.get('id', None)

        if record_email:
            email = Email(
                subject=subject,
                body=body,
                sender=sender,
                to=','.join(original_to),
                cc=','.join(original_cc),
                bcc=','.join(original_bcc),
                replyto=','.join(original_replyto),
                ident=ident,
                **fk_kwargs)

            session = session or getattr(model, 'session', getattr(automated_email, 'session', None))
            if session:
                session.add(email)
                session.commit()
            else:
                with Session() as session:
                    session.add(email)
                    session.commit()


@celery.schedule(crontab(hour=6, minute=0, day_of_week=1))
def notify_admins_of_pending_emails():
    """
    Generate and email a report which alerts admins that there are automated
    emails which are ready to send, but can't be sent until they are approved
    by an admin.

    This is important so we don't forget to let certain automated emails send.
    """
    return

    if not c.PRE_CON or not (c.DEV_BOX or c.SEND_EMAILS):
        return

    with Session() as session:
        pending_emails = session.query(AutomatedEmail).filter(*AutomatedEmail.filters_for_pending).all()
        pending_emails_by_sender = utils.groupify(pending_emails, ['sender', 'ident'])

        for sender, emails_by_ident in pending_emails_by_sender.items():
            if sender == c.STAFF_EMAIL:
                # STOPS receives a report on ALL the pending emails.
                emails_by_sender = pending_emails_by_sender
            elif sender == c.CONTACT_EMAIL:
                continue
            else:
                emails_by_sender = {sender: emails_by_ident}

            for email in emails_by_ident.values():
                if isinstance(email[0], AutomatedEmail):
                    email[0].reconcile(AutomatedEmail._fixtures[email[0].ident])

            EmailService.queue_email(session, 'pending_emails_admin', to=c.REPORTS_EMAIL, sender=sender,
                                     subject=f'{c.EVENT_NAME} Pending Emails Report for {utils.localized_now().strftime('%Y-%m-%d')}',
                                     data={'pending_emails_by_sender': emails_by_sender, 'primary_sender': sender},
                                     replace_unsent=True)

        return utils.groupify(pending_emails, 'sender', 'ident')


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
                    lock_key = model_class.__name__.lower() + '_email_queue'
                    lock_key = int.from_bytes(lock_key.encode())  & ((1<<63)-1)
                    log.debug(f"Attempting to lock {model_class.__name__} email queue for processing.")

                    with guard_conn.begin():
                        if guard_conn.execute(select(func.pg_try_advisory_lock(lock_key))).scalar():
                            log.debug(f"Sending queued emails for {model_class.__name__}.")
                            quantity_sent += EmailService.process_emails_by_class(session, model_class)
                        else:
                            log.debug(f"Skipping {model_class.__name__} as it is being worked by another thread.")
            log.info(f"Sent {quantity_sent} emails in {time() - start_time} seconds.")
    except Exception:
        traceback.print_exc()
