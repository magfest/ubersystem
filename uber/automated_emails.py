from uber.common import *


class AutomatedEmail:
    """
    Represents one category of emails that we send out.
    An example of an email category would be "Your registration has been confirmed".
    """

    # global: all instances of every registered email category in the system
    instances = OrderedDict()

    # a list of queries to run during each automated email sending run to
    # return particular model instances of a given type.
    queries = {
        Attendee: lambda session: session.all_attendees(),
        Group: lambda session: session.query(Group).options(subqueryload(Group.attendees))
    }

    def __init__(self, model, subject, template, filter, ident, *, when=(),
                 sender=None, extra_data=None, cc=None, bcc=None,
                 post_con=False, needs_approval=True, allow_during_con=False):

        self.subject = subject.format(EVENT_NAME=c.EVENT_NAME, EVENT_DATE=c.EPOCH.strftime("(%b %Y)"))
        self.ident = ident

        assert self.ident, 'error: automated email ident may not be empty.'
        assert self.ident not in self.instances, 'error: automated email ident "{}" is registered twice.'.format(self.ident)

        self.instances[self.ident] = self

        self.model, self.template, self.needs_approval, self.allow_during_con = model, template, needs_approval, allow_during_con
        self.cc = cc or []
        self.bcc = bcc or []
        self.extra_data = extra_data or {}
        self.sender = sender or c.REGDESK_EMAIL
        self.when = listify(when)

        assert filter is not None

        if post_con:
            self.filter = lambda model_inst: c.POST_CON and filter(model_inst)
        else:
            self.filter = lambda model_inst: not c.POST_CON and filter(model_inst)

    def filters_run(self, model_inst):
        return all([self.filter(model_inst), self._run_date_filters()])

    def _run_date_filters(self):
        return all([date_filter() for date_filter in self.when])

    def __repr__(self):
        return '<{}: {!r}>'.format(self.__class__.__name__, self.subject)

    def computed_subject(self, x):
        """
        Given a model instance, return an email subject email for that instance.
        By default this just returns the default subject unmodified; this method
        exists only to be overriden in subclasses.  For example, we might want
        our panel email subjects to contain the name of the panel.
        """
        return self.subject

    def _already_sent(self, model_inst):
        """
        Returns true if we have a record of previously sending this email to this model

        NOTE: c.PREVIOUSLY_SENT_EMAILS is a cached property and will only update at the start of each daemon run.
        """
        return (model_inst.__class__.__name__, model_inst.id, self.ident) in c.PREVIOUSLY_SENT_EMAILS

    def send_if_should(self, model_inst, raise_errors=False):
        """
        If it's OK to send an email of our category to this model instance (i.e. a particular Attendee) then send it.
        """
        try:
            if self._should_send(model_inst):
                self.really_send(model_inst)
        except:
            log.error('error sending {!r} email to {}', self.subject, model_inst.email, exc_info=True)
            if raise_errors:
                raise

    def _should_send(self, model_inst):
        """
        If True, we should generate an actual email created from our email category
        and send it to a particular model instance.

        This is determined based on a few things like:
        1) whether we have sent this exact email out yet or not
        2) whether the email category has been approved
        3) whether the model instance passed in is the same type as what we want to process
        4) do any date-based filters exist on this email category? (i.e. send 7 days before magfest)
        5) do any other filters exist on this email category? (i.e. only if attendee.staffing == true)

        Example #1 of a model instance to check:
          self.ident: "You {attendee.name} have registered for our event!"
          model_inst:  class Attendee: id #4532, name: "John smith"

        Example #2 of a model instance to check:
          self.ident: "Your group {group.name} owes money"
          model_inst:  class Group: id #1251, name: "The Fighting Mongooses"

        :param model_inst: The model we've been requested to use (i.e. Attendee, Group, etc)

        :return: True if we should send this email to this model instance, False if not.
        """

        return all(condition() for condition in [
            lambda: not c.AT_THE_CON or self.allow_during_con,
            lambda: isinstance(model_inst, self.model),
            lambda: getattr(model_inst, 'email', None),
            lambda: not self._already_sent(model_inst),
            lambda: self.filters_run(model_inst),
            lambda: self.approved,
        ])

    @property
    def approved(self):
        """
        Check if this email category has been approved by the admins to send automated emails.

        :return: True if we are approved to send this email, or don't need approval. False otherwise

        Side effect: If running as part of the automated email daemon code, and we aren't approved, log the count of
        emails that would have been sent so we can report it via the UI later.
        """

        approved_to_send = not self.needs_approval or self.ident in c.EMAIL_APPROVED_IDENTS

        if not approved_to_send:
            # log statistics about how many emails would have been sent if we had approval.
            # if running as part of a daemon, this will record the data.
            SendAllAutomatedEmailsJob.log_unsent_because_unapproved(self)

        return approved_to_send

    def render(self, model_instance):
        model = getattr(model_instance, 'email_model_name', model_instance.__class__.__name__.lower())
        return render('emails/' + self.template, dict({model: model_instance}, **self.extra_data))

    def really_send(self, model_instance):
        """
        Actually send an email to a particular model instance (i.e. a particular attendee).

        Doesn't perform any kind of checks at all if we should be sending this, just immediately sends the email
        no matter what.

        NOTE: use send_if_should() instead of calling this method unless you 100% know what you're doing.
        NOTE: send_email() fails if c.SEND_EMAILS is False
        """
        try:
            subject = self.computed_subject(model_instance)
            format = 'text' if self.template.endswith('.txt') else 'html'
            send_email(self.sender, model_instance.email, subject,
                       self.render(model_instance), format,
                       model=model_instance, cc=self.cc, ident=self.ident)
        except:
            log.error('error sending {!r} email to {}', self.subject, model_instance.email, exc_info=True)
            raise

    @property
    def when_txt(self):
        """
        Return a textual description of when the date filters are active for this email category.
        """

        return '\n'.join([filter.active_when for filter in self.when])


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
                self._send_any_emails_for(model_instance)

    def _send_any_emails_for(self, model_instance):
        """
        Go through every email category in the system and ask it if it wants to send any email on behalf of this
        particular model instance.

        An example of a model + category combo to check:
          email_category: "You {attendee.name} have registered for our event!"
          model_instance:  Attendee #42
        """
        for email_category in AutomatedEmail.instances.values():
            email_category.send_if_should(model_instance, self.raise_errors)

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


class StopsEmail(AutomatedEmail):
    def __init__(self, subject, template, filter, ident, **kwargs):
        AutomatedEmail.__init__(self, Attendee, subject, template, lambda a: a.staffing and filter(a), ident, sender=c.STAFF_EMAIL, **kwargs)


class GuestEmail(AutomatedEmail):
    def __init__(self, subject, template, ident, filter=lambda a: True, **kwargs):
        AutomatedEmail.__init__(self, Attendee, subject, template, lambda a: a.badge_type == c.GUEST_BADGE and filter(a), ident=ident, sender=c.GUEST_EMAIL, **kwargs)


class GroupEmail(AutomatedEmail):
    def __init__(self, subject, template, filter, ident, **kwargs):
        AutomatedEmail.__init__(self, Group, subject, template, lambda g: not g.is_dealer and filter(g), ident, sender=c.REGDESK_EMAIL, **kwargs)


class MarketplaceEmail(AutomatedEmail):
    def __init__(self, subject, template, filter, ident, **kwargs):
        AutomatedEmail.__init__(self, Group, subject, template, lambda g: g.is_dealer and filter(g), ident, sender=c.MARKETPLACE_EMAIL, **kwargs)


class DeptChecklistEmail(AutomatedEmail):
    def __init__(self, conf):
        AutomatedEmail.__init__(self, Attendee,
                                subject='{EVENT_NAME} Department Checklist: ' + conf.name,
                                template='shifts/dept_checklist.txt',
                                filter=lambda a: a.is_single_dept_head and a.admin_account and not conf.completed(a),
                                ident='department_checklist_{}'.format(conf.name),
                                when=days_before(7, conf.deadline),
                                sender=c.STAFF_EMAIL,
                                extra_data={'conf': conf})


"""
IMPORTANT NOTES FOR CHANGING/ADDING EMAIL CATEGORIES:

'ident' is a unique ID for that email category that must not change after
emails in that category have started to send.

*****************************************************************************
IF YOU CHANGE THE IDENT FOR A CATEGORY, IT WILL CAUSE ANY EMAILS THAT HAVE
ALREADY SENT FOR THAT CATEGORY TO RE-SEND.
*****************************************************************************

"""


# Payment reminder emails, including ones for groups, which are always safe to be here, since they just
# won't get sent if group registration is turned off.

AutomatedEmail(Attendee, '{EVENT_NAME} payment received', 'reg_workflow/attendee_confirmation.html',
         lambda a: a.paid == c.HAS_PAID,
         needs_approval=False, allow_during_con=True,
         ident='attendee_payment_received')

AutomatedEmail(Group, '{EVENT_NAME} group payment received', 'reg_workflow/group_confirmation.html',
         lambda g: g.amount_paid == g.cost and g.cost != 0,
         needs_approval=False,
         ident='group_payment_received')

AutomatedEmail(Attendee, '{EVENT_NAME} group registration confirmed', 'reg_workflow/attendee_confirmation.html',
         lambda a: a.group and a != a.group.leader and not a.placeholder,
         needs_approval=False, allow_during_con=True,
         ident='attendee_group_reg_confirmation')

AutomatedEmail(Attendee, '{EVENT_NAME} extra payment received', 'reg_workflow/group_donation.txt',
         lambda a: a.paid == c.PAID_BY_GROUP and a.amount_extra and a.amount_paid == a.amount_extra,
         needs_approval=False,
         ident='group_extra_payment_received')


# Reminder emails for groups to allocated their unassigned badges.  These emails are safe to be turned on for
# all events, because they will only be sent for groups with unregistered badges, so if group preregistration
# has been turned off, they'll just never be sent.

GroupEmail('Reminder to pre-assign {EVENT_NAME} group badges', 'reg_workflow/group_preassign_reminder.txt',
           lambda g: days_after(30, g.registered)() and c.BEFORE_GROUP_PREREG_TAKEDOWN and g.unregistered_badges,
           needs_approval=False,
           ident='group_preassign_badges_reminder')

AutomatedEmail(Group, 'Last chance to pre-assign {EVENT_NAME} group badges', 'reg_workflow/group_preassign_reminder.txt',
         lambda g: c.AFTER_GROUP_PREREG_TAKEDOWN and g.unregistered_badges and (not g.is_dealer or g.status == c.APPROVED),
         needs_approval=False,
         ident='group_preassign_badges_reminder_last_chance')


# Dealer emails; these are safe to be turned on for all events because even if the event doesn't have dealers,
# none of these emails will be sent unless someone has applied to be a dealer, which they cannot do until
# dealer registration has been turned on.

MarketplaceEmail('Your {EVENT_NAME} Dealer registration has been approved', 'dealers/approved.html',
                 lambda g: g.status == c.APPROVED,
                 needs_approval=False,
                 ident='dealer_reg_approved')

MarketplaceEmail('Reminder to pay for your {EVENT_NAME} Dealer registration', 'dealers/payment_reminder.txt',
                 lambda g: g.status == c.APPROVED and days_after(30, g.approved)() and g.is_unpaid,
                 needs_approval=False,
                 ident='dealer_reg_payment_reminder')

MarketplaceEmail('Your {EVENT_NAME} {EVENT_DATE} Dealer registration is due in one week', 'dealers/payment_reminder.txt',
                 lambda g: g.status == c.APPROVED and g.is_unpaid,
                 when=days_before(7, c.DEALER_PAYMENT_DUE, 2),
                 needs_approval=False,
                 ident='dealer_reg_payment_reminder_due_soon')

MarketplaceEmail('Last chance to pay for your {EVENT_NAME} {EVENT_DATE} Dealer registration', 'dealers/payment_reminder.txt',
                 lambda g: g.status == c.APPROVED and g.is_unpaid,
                 when=days_before(2, c.DEALER_PAYMENT_DUE),
                 needs_approval=False,
                 ident='dealer_reg_payment_reminder_last_chance')

MarketplaceEmail('{EVENT_NAME} Dealer waitlist has been exhausted', 'dealers/waitlist_closing.txt',
                 lambda g: g.status == c.WAITLISTED,
                 when=days_after(0, c.DEALER_WAITLIST_CLOSED),
                 ident='uber_marketplace_waitlist_exhausted')


# Placeholder badge emails; when an admin creates a "placeholder" badge, we send one of three different emails depending
# on whether the placeholder is a regular attendee, a guest/panelist, or a volunteer/staffer.  We also send a final
# reminder email before the placeholder deadline explaining that the badge must be explicitly accepted or we'll assume
# the person isn't coming.
#
# We usually import a bunch of last year's staffers before preregistration goes live with placeholder badges, so there's
# a special email for those people, which is basically the same as the normal email except it includes a special thanks
# message.  We identify those people by checking for volunteer placeholders which were created before prereg opens.
#
# These emails are safe to be turned on for all events because none of them are sent unless an administrator explicitly
# creates a "placeholder" registration.

AutomatedEmail(Attendee, '{EVENT_NAME} Panelist Badge Confirmation', 'placeholders/panelist.txt',
               lambda a: a.placeholder and a.first_name and a.last_name and a.ribbon == c.PANELIST_RIBBON,
               sender=c.PANELS_EMAIL,
               ident='panelist_badge_confirmation')

AutomatedEmail(Attendee, '{EVENT_NAME} Guest Badge Confirmation', 'placeholders/guest.txt',
               lambda a: a.placeholder and a.first_name and a.last_name and a.badge_type == c.GUEST_BADGE,
               sender=c.GUEST_EMAIL,
               ident='guest_badge_confirmation')

AutomatedEmail(Attendee, '{EVENT_NAME} Dealer Information Required', 'placeholders/dealer.txt',
               lambda a: a.placeholder and a.is_dealer and a.group.status == c.APPROVED,
               sender=c.MARKETPLACE_EMAIL,
               ident='dealer_info_required')

StopsEmail('Want to staff {EVENT_NAME} again?', 'placeholders/imported_volunteer.txt',
           lambda a: a.placeholder and a.staffing and a.registered_local <= c.PREREG_OPEN,
           ident='volunteer_again_inquiry')

StopsEmail('{EVENT_NAME} Volunteer Badge Confirmation', 'placeholders/volunteer.txt',
           lambda a: a.placeholder and a.first_name and a.last_name
                                      and a.registered_local > c.PREREG_OPEN,
           ident='volunteer_badge_confirmation')

AutomatedEmail(Attendee, '{EVENT_NAME} Badge Confirmation', 'placeholders/regular.txt',
               lambda a: a.placeholder and a.first_name and a.last_name
                                       and (c.AT_THE_CON or a.badge_type not in [c.GUEST_BADGE, c.STAFF_BADGE]
                                       and a.ribbon not in [c.DEALER_RIBBON, c.PANELIST_RIBBON, c.VOLUNTEER_RIBBON]),
               allow_during_con=True,
               ident='regular_badge_confirmation')

AutomatedEmail(Attendee, '{EVENT_NAME} Badge Confirmation Reminder', 'placeholders/reminder.txt',
               lambda a: days_after(7, a.registered)() and a.placeholder and a.first_name and a.last_name and not a.is_dealer,
               ident='badge_confirmation_reminder')

AutomatedEmail(Attendee, 'Last Chance to Accept Your {EVENT_NAME} {EVENT_DATE} Badge', 'placeholders/reminder.txt',
               lambda a: a.placeholder and a.first_name and a.last_name and not a.is_dealer,
               when=days_before(7, c.PLACEHOLDER_DEADLINE),
               ident='badge_confirmation_reminder_last_chance')


# Volunteer emails; none of these will be sent unless SHIFTS_CREATED is set.

StopsEmail('Please complete your {EVENT_NAME} Staff/Volunteer Checklist', 'shifts/created.txt',
           lambda a: a.takes_shifts,
           when=days_after(0, c.SHIFTS_CREATED),
           ident='volunteer_checklist_completion_request')

StopsEmail('Reminder to sign up for {EVENT_NAME} {EVENT_DATE} shifts', 'shifts/reminder.txt',
           lambda a: c.AFTER_SHIFTS_CREATED and days_after(30, max(a.registered_local, c.SHIFTS_CREATED))()
                 and a.takes_shifts and not a.hours,
           when=before(c.PREREG_TAKEDOWN),
           ident='volunteer_shift_signup_reminder')

StopsEmail('Last chance to sign up for {EVENT_NAME} {EVENT_DATE} shifts', 'shifts/reminder.txt',
           lambda a: c.AFTER_SHIFTS_CREATED and c.BEFORE_PREREG_TAKEDOWN and a.takes_shifts and not a.hours,
           when=days_before(10, c.EPOCH),
           ident='volunteer_shift_signup_reminder_last_chance')

StopsEmail('Still want to volunteer at {EVENT_NAME} {EVENT_DATE}?', 'shifts/volunteer_check.txt',
           lambda a: c.SHIFTS_CREATED and a.ribbon == c.VOLUNTEER_RIBBON and a.takes_shifts and a.weighted_hours == 0,
           when=days_before(5, c.FINAL_EMAIL_DEADLINE),
           ident='volunteer_still_interested_inquiry')

StopsEmail('Your {EVENT_NAME} {EVENT_DATE} shift schedule', 'shifts/schedule.html',
           lambda a: c.SHIFTS_CREATED and a.weighted_hours,
           when=days_before(1, c.FINAL_EMAIL_DEADLINE),
           ident='volunteer_shift_schedule')


# For events with customized badges, these emails remind people to let us know what we want on their badges.  We have
# one email for our volunteers who haven't bothered to confirm they're coming yet (bleh) and one for everyone else.

StopsEmail('Last chance to personalize your {EVENT_NAME} {EVENT_DATE} badge', 'personalized_badges/volunteers.txt',
           lambda a: a.staffing and a.badge_type in c.PREASSIGNED_BADGE_TYPES and a.placeholder,
           when=days_before(7, c.PRINTED_BADGE_DEADLINE),
           ident='volunteer_personalized_badge_reminder')

AutomatedEmail(Attendee, 'Personalized {EVENT_NAME} {EVENT_DATE} badges will be ordered next week', 'personalized_badges/reminder.txt',
               lambda a: a.badge_type in c.PREASSIGNED_BADGE_TYPES and not a.placeholder,
               when=days_before(7, c.PRINTED_BADGE_DEADLINE),
               ident='personalized_badge_reminder')


# MAGFest requires signed and notarized parental consent forms for anyone under 18.  This automated email reminder to
# bring the consent form only happens if this feature is turned on by setting the CONSENT_FORM_URL config option.
AutomatedEmail(Attendee, '{EVENT_NAME} {EVENT_DATE} parental consent form reminder', 'reg_workflow/under_18_reminder.txt',
               lambda a: c.CONSENT_FORM_URL and a.age_group_conf['consent_form'],
               when=days_before(14, c.EPOCH),
               ident='under_18_parental_consent_reminder')


# Emails sent out to all attendees who can check in. These emails contain useful information about the event and are
# sent close to the event start date.
AutomatedEmail(Attendee, 'Check in faster at {EVENT_NAME}', 'reg_workflow/attendee_qrcode.html',
               lambda a: not a.is_not_ready_to_checkin and c.USE_CHECKIN_BARCODE,
               when=days_before(14, c.EPOCH), ident='qrcode_for_checkin')

for _conf in DeptChecklistConf.instances.values():
    DeptChecklistEmail(_conf)
