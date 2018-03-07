from pockets import groupify
from sqlalchemy.orm import joinedload

from uber.automated_emails import AutomatedEmailFixture
from uber.config import c
from uber.decorators import render
from uber.models import AutomatedEmail, Session
from uber.notifications import send_email
from uber.tasks import schedule
from uber.utils import localized_now


__all__ = ['notify_admins_of_pending_emails', 'send_automated_emails']


def notify_admins_of_pending_emails():
    """
    Generate an email a report which alerts admins that there are emails which
    are ready to send, but won't because they need approval from an admin.

    This is useful so we don't forget to let certain categories of emails send.
    """
    if not c.ENABLE_PENDING_EMAILS_REPORT or not c.PRE_CON or not (c.DEV_BOX or c.SEND_EMAILS):
        return

    with Session() as session:
        pending_emails = session.query(AutomatedEmail).filter(*AutomatedEmail.filters_for_pending).all()
        pending_email_categories = groupify(pending_emails, ['sender', 'ident'], lambda e: {
            'unapproved_count': e.unapproved_count,
            'subject': e.subject,
            'sender': e.sender,
        })

    if not pending_email_categories:
        return

    for sender, email_categories in pending_email_categories.items():
        if sender == c.STAFF_EMAIL:
            email_categories = pending_email_categories

        subject = '{EVENT_NAME} Pending Emails Report for ' + localized_now().strftime('%Y-%m-%d')
        body = render('emails/daily_checks/pending_emails.html', {
            'pending_email_categories': email_categories,
            'primary_sender': sender,
        })
        send_email(c.STAFF_EMAIL, sender, subject, body, format='html', model='n/a')


def send_automated_emails():
    if not (c.DEV_BOX or c.SEND_EMAILS):
        return

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
                                automated_email.send_to(model_instance)
                            else:
                                automated_email.unapproved_count += 1

        return {e.ident: e.unapproved_count for e in active_automated_emails if e.unapproved_count > 0}

        # TODO: Once we finish converting each AutomatedEmailFixture.filter
        #       into an AutomatedEmailFixture.query, we'll be able to get rid
        #       of AutomatedEmailFixture.queries entirely, and send our
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
        #                 automated_email.send_to(model_instance)
        #             else:
        #                 automated_email.unapproved_count += 1
        #
        # return {e.ident: e.unapproved_count for e in active_automated_emails if e.unapproved_count > 0}


schedule.on_startup(AutomatedEmail.reconcile_fixtures)
schedule.every().day.at('06:00').do(notify_admins_of_pending_emails)
schedule.every(5).minutes.do(send_automated_emails)
