from collections import Mapping
from datetime import timedelta
from time import sleep

from celery.schedules import crontab
from pockets import groupify, listify
from pockets.autolog import log
from sqlalchemy.orm import joinedload

from uber import utils
from uber.amazon_ses import AmazonSES, EmailMessage  # TODO: replace this after boto adds Python 3 support
from uber.automated_emails import AutomatedEmailFixture
from uber.config import c
from uber.decorators import render
from uber.models import AutomatedEmail, Email, MagModel, Session
from uber.tasks import celery


__all__ = ['notify_admins_of_pending_emails', 'send_automated_emails', 'send_email']


celery.on_startup(AutomatedEmail.reconcile_fixtures)


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
        model=None,
        ident=None,
        automated_email=None,
        session=None):

    to, cc, bcc = map(lambda x: listify(x if x else []), [to, cc, bcc])
    original_to, original_cc, original_bcc = to, cc, bcc
    ident = ident or subject
    if c.DEV_BOX:
        to, cc, bcc = map(lambda xs: list(filter(_is_dev_email, xs)), [to, cc, bcc])

    if c.SEND_EMAILS and to:
        msg_kwargs = {'bodyText' if format == 'text' else 'bodyHtml': body}
        message = EmailMessage(subject=subject, **msg_kwargs)
        AmazonSES(c.AWS_ACCESS_KEY, c.AWS_SECRET_KEY).sendEmail(
            source=sender,
            toAddresses=to,
            ccAddresses=cc,
            bccAddresses=bcc,
            message=message)
        sleep(0.1)  # Avoid hitting rate limit
    else:
        log.error('Email sending turned off, so unable to send {}', locals())

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

        email = Email(
            subject=subject,
            body=body,
            sender=sender,
            to=','.join(original_to),
            cc=','.join(original_cc),
            bcc=','.join(original_bcc),
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
    if not c.ENABLE_PENDING_EMAILS_REPORT or not c.PRE_CON or not (c.DEV_BOX or c.SEND_EMAILS):
        return None

    with Session() as session:
        pending_emails = session.query(AutomatedEmail).filter(*AutomatedEmail.filters_for_pending).all()
        pending_emails_by_sender = groupify(pending_emails, ['sender', 'ident'])

        for sender, emails_by_ident in pending_emails_by_sender.items():
            if sender == c.STAFF_EMAIL:
                # STOPS receives a report on ALL the pending emails.
                emails_by_sender = pending_emails_by_sender
            else:
                emails_by_sender = {sender: emails_by_ident}

            subject = '{} Pending Emails Report for {}'.format(c.EVENT_NAME, utils.localized_now().strftime('%Y-%m-%d'))
            body = render('emails/daily_checks/pending_emails.html', {
                'pending_emails_by_sender': emails_by_sender,
                'primary_sender': sender,
            })
            send_email(c.STAFF_EMAIL, sender, subject, body, format='html', model='n/a', session=session)

        return groupify(pending_emails, 'sender', 'ident')


@celery.schedule(timedelta(minutes=5))
def send_automated_emails():
    """
    Send any automated emails that are currently active, and have been approved
    or do not need approval. For each unapproved email that needs approval from
    an admin, the unapproved_count will be updated to indicate the number of
    recepients that _would have_ received the email if it had been approved.
    """
    if not (c.DEV_BOX or c.SEND_EMAILS):
        return None

    with Session() as session:
        active_automated_emails = session.query(AutomatedEmail) \
            .filter(*AutomatedEmail.filters_for_active) \
            .options(joinedload(AutomatedEmail.emails)).all()

        for automated_email in active_automated_emails:
            automated_email.unapproved_count = 0
        automated_emails_by_model = groupify(active_automated_emails, 'model')

        for model, query_func in AutomatedEmailFixture.queries.items():
            model_instances = query_func(session)
            for model_instance in model_instances:
                automated_emails = automated_emails_by_model.get(model.__name__, [])
                for automated_email in automated_emails:
                    if model_instance.id not in automated_email.emails_by_fk_id:
                        if automated_email.would_send_if_approved(model_instance):
                            if automated_email.approved or not automated_email.needs_approval:
                                automated_email.send_to(model_instance, delay=False)
                            else:
                                automated_email.unapproved_count += 1

        return {e.ident: e.unapproved_count for e in active_automated_emails if e.unapproved_count > 0}

        # TODO: Once we finish converting each AutomatedEmailFixture.filter
        #       into an AutomatedEmailFixture.query, we'll be able to remove
        #       AutomatedEmailFixture.queries entirely and send our
        #       automated emails using the code below.
        #
        # for automated_email in active_automated_emails:
        #     model_class = automated_email.model_class or Attendee
        #     model_instances = session.query(model_class).filter(
        #         not_(exists().where(and_(
        #             Email.fk_id == model_class.id,
        #             Email.automated_email_id == automated_email.id))
        #         ),
        #         *automated_email.query
        #     ).options(*automated_email.query_options)
        #
        #     automated_email.unapproved_count = 0
        #     for model_instance in model_instances:
        #         if automated_email.would_send_if_approved(model_instance):
        #             if automated_email.approved or not automated_email.needs_approval:
        #                 automated_email.send_to(model_instance, delay=False)
        #             else:
        #                 automated_email.unapproved_count += 1
        #
        # return {e.ident: e.unapproved_count for e in active_automated_emails if e.unapproved_count > 0}
