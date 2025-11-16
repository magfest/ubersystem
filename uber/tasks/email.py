from collections.abc import Mapping
from datetime import timedelta, datetime
import pytz
from time import sleep, time
import traceback

from celery.schedules import crontab
from pockets import groupify, listify
from pockets.autolog import log
from sqlalchemy.orm import joinedload, raiseload, sessionmaker
from sqlalchemy.orm.exc import NoResultFound

from uber import utils
from uber.amazon_ses import email_sender
from uber.automated_emails import AutomatedEmailFixture
from uber.config import c
from uber.decorators import render
from uber.models import AutomatedEmail, Email, MagModel, Session
from uber.tasks import celery


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

    to, cc, bcc, replyto = map(lambda x: listify(x if x else []), [to, cc, bcc, replyto])
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
    if not c.ENABLE_PENDING_EMAILS_REPORT or not c.PRE_CON or not (c.DEV_BOX or c.SEND_EMAILS):
        return None

    with Session() as session:
        pending_emails = session.query(AutomatedEmail).filter(*AutomatedEmail.filters_for_pending).all()
        pending_emails_by_sender = groupify(pending_emails, ['sender', 'ident'])

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

            subject = '{} Pending Emails Report for {}'.format(c.EVENT_NAME, utils.localized_now().strftime('%Y-%m-%d'))
            body = render('emails/daily_checks/pending_emails.html', {
                'pending_emails_by_sender': emails_by_sender,
                'primary_sender': sender,
            }, encoding=None)
            send_email(c.REPORTS_EMAIL, sender, subject, body, format='html', model='n/a', session=session)

        return groupify(pending_emails, 'sender', 'ident')


@celery.schedule(timedelta(minutes=5 if c.DEV_BOX else 15))
def send_automated_emails():
    """
    Send any automated emails that are currently active, and have been approved
    or do not need approval. For each unapproved email that needs approval from
    an admin, the unapproved_count will be updated to indicate the number of
    recepients that _would have_ received the email if it had been approved.
    """
    if not (c.DEV_BOX or c.SEND_EMAILS):
        return None

    try:
        quantity_sent = 0
        start_time = time()
        Session.session_factory = sessionmaker(bind=Session.engine, expire_on_commit=False, autoflush=False, autocommit=False,
                                           query_cls=Session.QuerySubclass)
        with Session() as session:
            active_automated_emails = session.query(AutomatedEmail) \
                .filter(*AutomatedEmail.filters_for_active).all()

            automated_emails_by_model = groupify(active_automated_emails, 'model')

            for model, query_func in AutomatedEmailFixture.queries.items():
                log.debug("Sending automated emails for " + model.__name__)
                automated_emails = automated_emails_by_model.get(model.__name__, [])
                log.debug("  Found " + str(len(automated_emails)) + " emails for " + model.__name__)
                load_start = time()
                model_instances = query_func(session).all()
                log.debug(f"Loaded {len(model_instances)} {model.__name__} instances in {time() - load_start} seconds")
                for automated_email in automated_emails:
                    # Lock the current automated email
                    try:
                        locked_automated_email = session.query(AutomatedEmail).filter(AutomatedEmail.id == automated_email.id).with_for_update(skip_locked=True).one()
                    except NoResultFound:
                        log.debug(automated_email.ident + " is currently locked, skipping.")
                        continue
                    unapproved_count = 0
                    timing = {
                        "iteration": 0,
                        "fk_id_retrieve": 0,
                        "fk_id_list": 0,
                        "would_send": 0,
                        "approved": 0,
                        "refresh": 0,
                        "send": 0,
                    }
                    begin = time()
                    if getattr(automated_email, 'shared_ident', None):
                        matching_email_ids = session.query(Email.fk_id).filter(Email.ident.startswith(automated_email.shared_ident))
                        fk_id_list = {id for id, in matching_email_ids}
                    else:
                        fk_id_list = {email.fk_id for email in automated_email.emails}
                    end = time()
                    timing['fk_id_retrieve'] += end - begin
                    begin = end
                    log.debug("  Loading instances for " + automated_email.ident)
                    for model_instance in model_instances:
                        end = time()
                        timing['iteration'] += end - begin
                        begin = end
                        if model_instance.id not in fk_id_list:
                            end = time()
                            timing['fk_id_list'] += end - begin
                            begin = end
                            if automated_email.would_send_if_approved(model_instance):
                                end = time()
                                timing['would_send'] += end - begin
                                begin = end
                                if automated_email.approved or not automated_email.needs_approval:
                                    end = time()
                                    timing['approved'] += end - begin
                                    begin = end
                                    if getattr(model_instance, 'active_receipt', None):
                                        session.refresh_receipt_and_model(model_instance)
                                    end = time()
                                    timing['refresh'] += end - begin
                                    begin = end
                                    automated_email.send_to(model_instance, delay=False)
                                    quantity_sent += 1
                                    end = time()
                                    timing['send'] += end - begin
                                    begin = end
                                else:
                                    unapproved_count += 1
                                    end = time()
                                    timing['approved'] += end - begin
                                    begin = end
                            else:
                                end = time()
                                timing['would_send'] += end - begin
                                begin = end
                        else:
                            end = time()
                            timing['fk_id_list'] += end - begin
                            begin = end

                    automated_email.unapproved_count = unapproved_count
                    session.add(automated_email)
                    
                    for key, duration in timing.items():
                        log.debug(f"    {key} took {duration} seconds")
                session.commit()
            log.info("Sent " + str(quantity_sent) + " emails in " + str(time() - start_time) + " seconds")
            return {e.ident: e.unapproved_count for e in active_automated_emails if e.unapproved_count > 0}
    except Exception:
        traceback.print_exc()

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
