import threading
from collections import defaultdict
from time import sleep

from pockets.autolog import log
from sideboard.lib import threadlocal

from uber.automated_emails import AutomatedEmail
from uber.config import c
from uber.decorators import render, timed
from uber.models import Session
from uber.notifications import send_email
from uber.tasks import schedule
from uber.utils import localized_now, request_cached_context


__all__ = ['notify_admins_of_pending_emails', 'SendAllAutomatedEmailsJob']


class SendAllAutomatedEmailsJob:

    # save information about the last time the daemon ran so that we can display stats on things like
    # unapproved emails/etc
    last_result = dict()

    run_lock = threading.Lock()

    @classmethod
    def send_all_emails(cls, raise_errors=False):
        """ Helper method to start a run of our automated email processing """
        cls().run(raise_errors)

    @timed
    def run(self, raise_errors=False):
        """
        Do one run of our automated email service.  Call this periodically to send any emails that should go out
        automatically.

        This will NOT run if we're on-site, or not configured to send emails.

        :param raise_errors: If False, exceptions are squashed during email sending and we'll try the next email.
        """
        if not (c.DEV_BOX or c.SEND_EMAILS):
            return

        if not SendAllAutomatedEmailsJob.run_lock.acquire(blocking=False):
            log.warn("can't acquire lock for email daemon (already running?), skipping this run.")
            return

        try:
            self._run(raise_errors)
        finally:
            SendAllAutomatedEmailsJob.run_lock.release()

    def _run(self, raise_errors):
        with Session() as session:
            # performance: we use request_cached_context() to force cache invalidation
            # of variables like c.EMAIL_APPROVED_IDENTS
            with request_cached_context(clear_cache_on_start=True):
                self._init(session, raise_errors)
                self._send_all_emails()
                self._on_finished_run()

    def _init(self, session, raise_errors):
        self.session = session
        self.raise_errors = raise_errors
        self.results = {
            'running': True,
            'completed': False,
            'categories': defaultdict(lambda: defaultdict(int))
        }

        # note: this will get cleared after request_cached_context object is released.
        assert not threadlocal.get('currently_running_email_daemon')
        threadlocal.set('currently_running_email_daemon', self)

    def _on_finished_run(self):
        self.results['running'] = False
        self.results['completed'] = True

        SendAllAutomatedEmailsJob.last_result = self.results

    def _send_all_emails(self):
        """
        This function is the heart of the automated email daemon in ubersystem
        and is called once every couple of minutes.

        To send automated emails, we look at AutomatedEmail.queries for a list of DB queries to run.
        The result of these queries are a list of model instances that we might want to send emails for.

        These model instances will be of type 'MagModel'. Examples: 'Attendee', 'Group'.
        Each model instance is, for example, a particular group, or a particular attendee.

        Next, we'll go through *ALL* AutomatedEmail's that are registered in the system.
        (When you see AutomatedEmail think "email category").  On each of these we'll ask that
        email category if it wants to send any emails for this particular model (i.e. a specific attendee).

        If that automated email decides the time is right (i.e. it hasn't sent the email already, the attendee has a
        valid email address, email has been approved for sending, and a bunch of other stuff), then it will actually
        send an email for this model instance.
        """
        for model, query_fn in AutomatedEmail.queries.items():
            model_instances = query_fn(self.session)
            for model_instance in model_instances:
                sleep(0.01)  # throttle CPU usage
                self._send_any_emails_for(model_instance, model)

    def _send_any_emails_for(self, model_instance, model=None):
        """
        Go through every email category in the system and ask it if it wants to send any email on behalf of this
        particular model instance.

        An example of a model + category combo to check:
          email_category: "You {attendee.name} have registered for our event!"
          model_instance:  Attendee #42
        """
        if not model:
            model = model_instance.__class__
        for email_category in AutomatedEmail.instances_by_model.get(model, []):
            if not email_category.send_if_should(model_instance, self.raise_errors):
                if email_category.would_send_if_approved(model_instance) and not email_category.approved:
                    self.log_unsent_because_unapproved(email_category)

    @classmethod
    def _currently_running_daemon_on_this_thread(cls):
        return threadlocal.get('currently_running_email_daemon')

    @classmethod
    def log_unsent_because_unapproved(cls, automated_email_category):
        running_daemon = cls._currently_running_daemon_on_this_thread()
        if running_daemon:
            running_daemon._increment_unsent_because_unapproved_count(automated_email_category)

    def _increment_unsent_because_unapproved_count(self, automated_email_category):
        """
        Log information that a particular email wanted to send out an email, but could not because it didn't have
        approval.

        :param automated_email_category: The category that wanted to send but needed approval
        """

        self.results['categories'][automated_email_category.ident]['unsent_because_unapproved'] += 1


def get_pending_email_data():
    """
    Generate a list of emails which are ready to send, but need approval.

    Returns: A dict of senders -> email idents -> pending counts for any email category with pending emails,
    or None if none are waiting to send or the email daemon service has not finished any runs yet.
    """
    has_email_daemon_run_yet = SendAllAutomatedEmailsJob.last_result.get('completed', False)
    if not has_email_daemon_run_yet:
        return None

    categories_results = SendAllAutomatedEmailsJob.last_result.get('categories', None)
    if not categories_results:
        return None

    pending_emails_by_sender = defaultdict(dict)

    for automated_email in AutomatedEmail.instances.values():
        sender = automated_email.sender
        ident = automated_email.ident

        category_results = categories_results.get(ident, None)
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
    Generate an email a report which alerts admins that there are emails which are ready to send,
    but won't because they need approval from an admin.

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
schedule.every(5).minutes.do(SendAllAutomatedEmailsJob.send_all_emails)
