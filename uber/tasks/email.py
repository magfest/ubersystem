from collections import defaultdict
from time import sleep

from uber.automated_emails import AutomatedEmail
from uber.config import c
from uber.decorators import render
from uber.models import Session
from uber.notifications import send_email
from uber.tasks import schedule
from uber.utils import localized_now, request_cached_context


__all__ = ['notify_admins_of_pending_emails', 'SendAutomatedEmailsJob']


class SendAutomatedEmailsJob:
    completed = False
    running = False

    last_result = None
    running_result = None

    @classmethod
    def run(cls, raise_errors=False):
        """
        Do one run of our automated email service.

        Call this periodically to send any emails that should go out
        automatically. Returns immediately if we're not configured to send
        emails.

        Args:
            raise_errors (bool): If False, exceptions are squashed during email
                sending and we'll try the next email.
        """
        if not c.DEV_BOX or not c.SEND_EMAILS:
            return

        # We use request_cached_context() to force cache invalidation
        # of variables like c.EMAIL_APPROVED_IDENTS
        with request_cached_context(clear_cache_on_start=True):
            cls.running = True
            cls.completed = False
            cls.running_result = defaultdict(lambda: defaultdict(int))

            cls._send_all_emails(raise_errors)

            cls.running = False
            cls.completed = True
            cls.last_result = cls.running_result

    @classmethod
    def _send_all_emails(cls, raise_errors=False):
        """
        This function is the heart of the automated email daemon in ubersystem.

        To send automated emails, we look at AutomatedEmail.queries for a list
        of DB queries to run. The result of these queries are a list of model
        instances that we might want to send emails for.

        These model instances will be of type 'MagModel'. Examples: 'Attendee',
        'Group'. Each model instance is, for example, a particular group, or a
        particular attendee.

        Next, we'll go through *ALL* AutomatedEmail's that are registered in
        the system. (When you see AutomatedEmail think "email category"). On
        each of these we'll ask that email category if it wants to send any
        emails for this particular model (i.e. a specific attendee).

        If that automated email decides the time is right (i.e. it hasn't sent
        the email already, the attendee has a valid email address, email has
        been approved for sending, and a bunch of other stuff), then it will
        actually send an email for this model instance.
        """
        with Session() as session:
            for model, query_fn in AutomatedEmail.queries.items():
                model_instances = query_fn(session)
                for model_instance in model_instances:
                    sleep(0.01)  # Throttle CPU usage
                    for email_category in AutomatedEmail.instances_by_model.get(model, []):
                        if not email_category.send_if_should(model_instance, raise_errors):
                            if not email_category.approved and email_category.would_send_if_approved(model_instance):
                                cls.log_unsent_because_unapproved(email_category)

    @classmethod
    def log_unsent_because_unapproved(cls, automated_email):
        """
        Log information that a particular email wanted to send out an email,
        but could not because it didn't have approval.

        Args:
            automated_email (AutomatedEmail): The automated email category that
                would have sent, but needed approval.

        """
        cls.running_result[automated_email.ident]['unsent_because_unapproved'] += 1


def get_pending_email_data():
    """
    Generate a list of emails which are ready to send, but need approval.

    Returns:
        A dict of senders -> email idents -> pending counts for any email
        category with pending emails, or None if none are waiting to send or
        the email daemon service has not finished any runs yet.

    """
    if not SendAutomatedEmailsJob.completed:
        return None

    if not SendAutomatedEmailsJob.last_result:
        return None

    pending_emails_by_sender = defaultdict(dict)

    for automated_email in AutomatedEmail.instances.values():
        sender = automated_email.sender
        ident = automated_email.ident

        category_results = SendAutomatedEmailsJob.last_result.get(ident, None)
        if not category_results:
            continue

        unsent_because_unapproved_count = category_results.get('unsent_because_unapproved', 0)
        if unsent_because_unapproved_count <= 0:
            continue

        pending_emails_by_sender[sender][ident] = {
            'num_unsent': unsent_because_unapproved_count,
            'subject': automated_email.subject,
            'sender': automated_email.sender,
        }

    return pending_emails_by_sender


def send_pending_email_report(pending_email_categories, sender):
    rendering_data = {
        'pending_email_categories': pending_email_categories,
        'primary_sender': sender,
    }
    subject = c.EVENT_NAME + ' Pending Emails Report for ' + localized_now().strftime('%Y-%m-%d')
    body = render('emails/daily_checks/pending_emails.html', rendering_data)
    send_email(c.STAFF_EMAIL, sender, subject, body, format='html', model='n/a')


def notify_admins_of_pending_emails():
    """
    Generate an email a report which alerts admins that there are emails which
    are ready to send, but won't because they need approval from an admin.

    This is useful so we don't forget to let certain categories of emails send.
    """
    if not c.ENABLE_PENDING_EMAILS_REPORT or not c.PRE_CON or not (c.DEV_BOX or c.SEND_EMAILS):
        return

    pending_email_categories = get_pending_email_data()
    if not pending_email_categories:
        return

    for sender, email_categories in pending_email_categories.items():
        include_all_categories = sender == c.STAFF_EMAIL
        included_categories = pending_email_categories

        if not include_all_categories:
            included_categories = {
                c_sender: categories for c_sender, categories in pending_email_categories.items() if c_sender == sender
            }

        send_pending_email_report(included_categories, sender)


schedule.every().day.at('06:00').do(notify_admins_of_pending_emails)
schedule.every(5).minutes.do(SendAutomatedEmailsJob.run)
