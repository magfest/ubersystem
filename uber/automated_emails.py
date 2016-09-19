# WARNING - changing the email subject line for an email WITHOUT 'ident' set causes ALL of those emails to be re-sent!
# Note that since c.EVENT_NAME is used in most of these emails, changing the event name mid-year
# could cause literally thousands of emails to be re-sent!

from uber.common import *


class AutomatedEmail:
    # all instances of every registered email category in the system
    instances = OrderedDict()

    # a list of queries to run during each automated email sending run to
    # return particular model instances of a given type.
    queries = {
        Attendee: lambda session: session.all_attendees(),
        Group: lambda session: session.query(Group).options(subqueryload(Group.attendees))
    }

    def __init__(self, model, subject, template, filter, *, when=(), sender=None, extra_data=None, cc=None, bcc=None, post_con=False, needs_approval=True, ident=None):
        self.model, self.template, self.needs_approval = model, template, needs_approval
        self.subject = subject.format(EVENT_NAME=c.EVENT_NAME)
        self.cc = cc or []
        self.bcc = bcc or []
        self.extra_data = extra_data or {}
        self.sender = sender or c.REGDESK_EMAIL
        self.instances[self.subject] = self
        self.ident = (ident or self.subject).format(EVENT_NAME=c.EVENT_NAME)
        self.when = when

        # after each daemon run, this will be set to the number of emails that would have been sent out but weren't
        # because they were not marked as approved.  Useful as a metric of how many emails need human intervention in
        # order to be approved for sending.
        #
        # A value of -1 means we haven't run yet, or email sending is disabled. Always check for > -1.
        self.unapproved_emails_not_sent = -1

        if post_con:
            self.filter = lambda x: c.POST_CON and filter(x)
        else:
            self.filter = lambda x: not c.POST_CON and filter(x)

    def filters_run(self, model_inst):
        if self.filter and not self.filter(model_inst):
            return False

        for date_filter in listify(self.when):
            if not date_filter():
                return False

        return True

    def __repr__(self):
        return '<{}: {!r}>'.format(self.__class__.__name__, self.subject)

    def _already_sent(self, model_inst, previously_sent_emails=None):
        """
        Returns true if we have a record of previously sending this email

        CPU Optimization: when using this function as part of batch processing, you can pass in a list of all
        previously sent emails, previously_sent_emails, in order to avoid having to query the DB for this specific email
        """
        if previously_sent_emails:
            # optimized version: use the cached previously_sent_emails so we don't have to query the DB
            return (model_inst.__class__.__name__, model_inst.id, self.ident) in previously_sent_emails
        else:
            # non-optimized version: query the DB to find any emails that were previously sent from this email category
            with Session() as session:
                return session.query(Email).filter_by(
                    model=model_inst.__class__.__name__, fk_id=model_inst.id, ident=self.ident).first()

    def attempt_to_send(self, session, model_inst,
                        approved_subjects=None, previously_sent_emails=None, raise_errors=False):
        """
        If it's OK to send an email of our category to this model instance (i.e. a particular Attendee) then send it.
        """
        if self.should_send(session, model_inst, approved_subjects, previously_sent_emails):
            self.send(model_inst, raise_errors=raise_errors)

    def should_send(self, session, model_inst, approved_subjects=None, previously_sent_emails=None):
        """
        If True, we should send out a particular email to a particular attendee.
        This is determined based on a few things like:
        1) whether we have sent this exact email out yet or not (previously_sent_emails)
        2) whether the email category has been approved (approved_subjects)
        3) whether the model instance passed in is the same type as what we want to process

        PERFORMANCE OPTIMIZATION: This function is called a LOT in a tight loop thousands of times per daemon run.
        To save CPU time, pass in a cached version of approved_subjects and previously_sent_emails so we don't have to
        compute them every single time.

        :param session: database session to use
        :param model_inst: The model we've been requested to use (i.e. Attendee, Group, etc)
        :param approved_subjects: optional: cached list of approved subject lines
        :param previously_sent_emails: optional: cached list of emails that were previously sent out
        :return: True if we should send this email to this model instance, False if not.
        """
        try:
            if not isinstance(model_inst, self.model) or not model_inst.email:
                return False

            if self._already_sent(model_inst, previously_sent_emails):
                return False

            if not self.filters_run(model_inst):
                return False

            approved_subjects = approved_subjects or AutomatedEmail.get_approved_subjects(session)
            if self.needs_approval and self.subject not in approved_subjects:
                self.unapproved_emails_not_sent += 1
                return False

            return True
        except:
            log.error('AutomatedEmail.should_send(): unexpected error', exc_info=True)

    def render(self, model_instance):
        model = getattr(model_instance, 'email_model_name', model_instance.__class__.__name__.lower())
        return render('emails/' + self.template, dict({model: model_instance}, **self.extra_data))

    def send(self, model_instance, raise_errors=True):
        """
        Actually send an email to a particular model instance (i.e. a particular attendee).

        Doesn't perform any kind of checks at all if we should be sending this, just immediately sends the email
        no matter what.

        NOTE: use attempt_to_send() instead of calling this directly if you don't 100% know what you're doing.
        """
        try:
            format = 'text' if self.template.endswith('.txt') else 'html'
            send_email(self.sender, model_instance.email, self.subject,
                       self.render(model_instance), format,
                       model=model_instance, cc=self.cc, ident=self.ident)
        except:
            log.error('error sending {!r} email to {}', self.subject, x.email, exc_info=True)
            if raise_errors:
                raise

    @property
    def when_txt(self):
        """
        Return a textual description of when the date filters are active for this email category.
        """

        return '\n'.join([filter.active_when for filter in listify(self.when)])

    @classmethod
    def get_approved_subjects(cls, session):
        return {ae.subject for ae in session.query(ApprovedEmail)}

    @classmethod
    def get_previously_sent_emails(cls, session):
        return set(session.query(Email.model, Email.fk_id, Email.ident))

    @classmethod
    def send_all(cls, raise_errors=False):
        """
        Do a run of our automated email service.  This function is called once every couple of minutes.
        """
        SendAllAutomatedEmailsJob().run(raise_errors)


class SendAllAutomatedEmailsJob:
    @timed
    def run(self, raise_errors=False):
        """
        Do a run of our automated email service.  Call this periodically to send any emails that should go out
        automatically.

        This will NOT run if we're on-site, or not configured to send emails.

        :param raise_errors: If True, exceptions are squashed during email sending and we'll try the next email.
        """
        allowed_to_run = not c.AT_THE_CON and (c.DEV_BOX or c.SEND_EMAILS)
        if not allowed_to_run:
            return

        with Session() as session:
            self._init(session, raise_errors)
            self._send_all_emails()

    def _init(self, session, raise_errors):
        self.session = session
        self.raise_errors = raise_errors

        # cache these so we don't have to compute them thousands of times per run
        self.approved_subjects = AutomatedEmail.get_approved_subjects(session)
        self.previously_sent_emails = AutomatedEmail.get_previously_sent_emails(session)

        # go through each email category and reset the count of
        # emails that would have been sent but they weren't approved
        for email_category in AutomatedEmail.instances.values():
            email_category.unapproved_emails_not_sent = 0

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
            email_category.attempt_to_send(self.session, model_instance,
                                           self.approved_subjects, self.previously_sent_emails,
                                           self.raise_errors)


class StopsEmail(AutomatedEmail):
    def __init__(self, subject, template, filter, **kwargs):
        AutomatedEmail.__init__(self, Attendee, subject, template, lambda a: a.staffing and filter(a), sender=c.STAFF_EMAIL, **kwargs)


class GuestEmail(AutomatedEmail):
    def __init__(self, subject, template, filter=lambda a: True, **kwargs):
        AutomatedEmail.__init__(self, Attendee, subject, template, lambda a: a.badge_type == c.GUEST_BADGE and filter(a), sender=c.PANELS_EMAIL, **kwargs)


class GroupEmail(AutomatedEmail):
    def __init__(self, subject, template, filter, **kwargs):
        AutomatedEmail.__init__(self, Group, subject, template, lambda g: not g.is_dealer and filter(g), sender=c.REGDESK_EMAIL, **kwargs)


class MarketplaceEmail(AutomatedEmail):
    def __init__(self, subject, template, filter, **kwargs):
        AutomatedEmail.__init__(self, Group, subject, template, lambda g: g.is_dealer and filter(g), sender=c.MARKETPLACE_EMAIL, **kwargs)


class DeptChecklistEmail(AutomatedEmail):
    def __init__(self, conf):
        AutomatedEmail.__init__(self, Attendee,
                                subject='{EVENT_NAME} Department Checklist: ' + conf.name,
                                template='shifts/dept_checklist.txt',
                                filter=lambda a: a.is_single_dept_head and a.admin_account and not conf.completed(a),
                                when=days_before(7, conf.deadline),
                                sender=c.STAFF_EMAIL,
                                extra_data={'conf': conf})


# Payment reminder emails, including ones for groups, which are always safe to be here, since they just
# won't get sent if group registration is turned off.

AutomatedEmail(Attendee, '{EVENT_NAME} payment received', 'reg_workflow/attendee_confirmation.html',
         lambda a: a.paid == c.HAS_PAID,
         needs_approval=False)

AutomatedEmail(Group, '{EVENT_NAME} group payment received', 'reg_workflow/group_confirmation.html',
         lambda g: g.amount_paid == g.cost and g.cost != 0,
         needs_approval=False)

AutomatedEmail(Attendee, '{EVENT_NAME} group registration confirmed', 'reg_workflow/attendee_confirmation.html',
         lambda a: a.group and a != a.group.leader and not a.placeholder,
         needs_approval=False)

AutomatedEmail(Attendee, '{EVENT_NAME} extra payment received', 'reg_workflow/group_donation.txt',
         lambda a: a.paid == c.PAID_BY_GROUP and a.amount_extra and a.amount_paid == a.amount_extra,
         needs_approval=False)

AutomatedEmail(Attendee, '{EVENT_NAME} payment refunded', 'reg_workflow/payment_refunded.txt',
         lambda a: a.amount_refunded)

# Reminder emails for groups to allocated their unassigned badges.  These emails are safe to be turned on for
# all events, because they will only be sent for groups with unregistered badges, so if group preregistration
# has been turned off, they'll just never be sent.

GroupEmail('Reminder to pre-assign {EVENT_NAME} group badges', 'reg_workflow/group_preassign_reminder.txt',
           lambda g: days_after(30, g.registered) and c.BEFORE_GROUP_PREREG_TAKEDOWN and g.unregistered_badges,
           needs_approval=False)

AutomatedEmail(Group, 'Last chance to pre-assign {EVENT_NAME} group badges', 'reg_workflow/group_preassign_reminder.txt',
         lambda g: c.AFTER_GROUP_PREREG_TAKEDOWN and g.unregistered_badges and (not g.is_dealer or g.status == APPROVED),
         needs_approval=False)


# Dealer emails; these are safe to be turned on for all events because even if the event doesn't have dealers,
# none of these emails will be sent unless someone has applied to be a dealer, which they cannot do until
# dealer registration has been turned on.

MarketplaceEmail('Your {EVENT_NAME} Dealer registration has been approved', 'dealers/approved.html',
                 lambda g: g.status == c.APPROVED,
                 needs_approval=False)

MarketplaceEmail('Reminder to pay for your {EVENT_NAME} Dealer registration', 'dealers/payment_reminder.txt',
                 lambda g: g.status == c.APPROVED and days_after(30, g.approved) and g.is_unpaid,
                 needs_approval=False)

MarketplaceEmail('Your {EVENT_NAME} Dealer registration is due in one week', 'dealers/payment_reminder.txt',
                 lambda g: g.status == c.APPROVED and g.is_unpaid,
                 when=days_before(7, c.DEALER_PAYMENT_DUE, 2),
                 needs_approval=False)

MarketplaceEmail('Last chance to pay for your {EVENT_NAME} Dealer registration', 'dealers/payment_reminder.txt',
                 lambda g: g.status == c.APPROVED and g.is_unpaid,
                 when=days_before(2, c.DEALER_PAYMENT_DUE),
                 needs_approval=False)

MarketplaceEmail('{EVENT_NAME} Dealer waitlist has been exhausted', 'dealers/waitlist_closing.txt',
                 lambda g: g.status == c.WAITLISTED,
                 when=after(c.DEALER_WAITLIST_CLOSED))


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
               sender=c.PANELS_EMAIL)

AutomatedEmail(Attendee, '{EVENT_NAME} Guest Badge Confirmation', 'placeholders/guest.txt',
               lambda a: a.placeholder and a.first_name and a.last_name and a.badge_type == c.GUEST_BADGE,
               sender=c.PANELS_EMAIL)

AutomatedEmail(Attendee, '{EVENT_NAME} Dealer Information Required', 'placeholders/dealer.txt',
               lambda a: a.placeholder and a.is_dealer and a.group.status == c.APPROVED,
               sender=c.MARKETPLACE_EMAIL)

StopsEmail('Want to staff {EVENT_NAME} again?', 'placeholders/imported_volunteer.txt',
           lambda a: a.placeholder and a.staffing and a.registered_local <= c.PREREG_OPEN)

StopsEmail('{EVENT_NAME} Volunteer Badge Confirmation', 'placeholders/volunteer.txt',
           lambda a: a.placeholder and a.first_name and a.last_name
                                      and a.registered_local > c.PREREG_OPEN)

AutomatedEmail(Attendee, '{EVENT_NAME} Badge Confirmation', 'placeholders/regular.txt',
               lambda a: a.placeholder and a.first_name and a.last_name
                                       and a.badge_type not in [c.GUEST_BADGE, c.STAFF_BADGE]
                                       and a.ribbon not in [c.DEALER_RIBBON, c.PANELIST_RIBBON, c.VOLUNTEER_RIBBON])

AutomatedEmail(Attendee, '{EVENT_NAME} Badge Confirmation Reminder', 'placeholders/reminder.txt',
               lambda a: days_after(7, a.registered) and a.placeholder and a.first_name and a.last_name and not a.is_dealer)

AutomatedEmail(Attendee, 'Last Chance to Accept Your {EVENT_NAME} Badge', 'placeholders/reminder.txt',
               lambda a: a.placeholder and a.first_name and a.last_name and not a.is_dealer,
               when=days_before(7, c.PLACEHOLDER_DEADLINE))


# Volunteer emails; none of these will be sent unless SHIFTS_CREATED is set.

StopsEmail('Please complete your {EVENT_NAME} Staff/Volunteer Checklist', 'shifts/created.txt',
           lambda a: a.takes_shifts,
           when=after(c.SHIFTS_CREATED))

StopsEmail('Reminder to sign up for {EVENT_NAME} shifts', 'shifts/reminder.txt',
           lambda a: c.AFTER_SHIFTS_CREATED and days_after(30, max(a.registered_local, c.SHIFTS_CREATED))
                 and a.takes_shifts and not a.hours,
           when=before(c.PREREG_TAKEDOWN))

StopsEmail('Last chance to sign up for {EVENT_NAME} shifts', 'shifts/reminder.txt',
              lambda a: c.AFTER_SHIFTS_CREATED and c.BEFORE_PREREG_TAKEDOWN and a.takes_shifts and not a.hours,
              when=days_before(10, c.EPOCH))

StopsEmail('Still want to volunteer at {EVENT_NAME}?', 'shifts/volunteer_check.txt',
            lambda a: c.SHIFTS_CREATED and a.ribbon == c.VOLUNTEER_RIBBON and a.takes_shifts and a.weighted_hours == 0,
            when=days_before(5, c.FINAL_EMAIL_DEADLINE))

StopsEmail('Your {EVENT_NAME} shift schedule', 'shifts/schedule.html',
           lambda a: c.SHIFTS_CREATED and a.weighted_hours,
           when=days_before(1, c.FINAL_EMAIL_DEADLINE))


# For events with customized badges, these emails remind people to let us know what we want on their badges.  We have
# one email for our volunteers who haven't bothered to confirm they're coming yet (bleh) and one for everyone else.

StopsEmail('Last chance to personalize your {EVENT_NAME} badge', 'personalized_badges/volunteers.txt',
           lambda a: a.staffing and a.badge_type in c.PREASSIGNED_BADGE_TYPES and a.placeholder,
           when=days_before(7, c.PRINTED_BADGE_DEADLINE))

AutomatedEmail(Attendee, 'Personalized {EVENT_NAME} badges will be ordered next week', 'personalized_badges/reminder.txt',
               lambda a: a.badge_type in c.PREASSIGNED_BADGE_TYPES and not a.placeholder,
               when=days_before(7, c.PRINTED_BADGE_DEADLINE))


# MAGFest requires signed and notarized parental consent forms for anyone under 18.  This automated email reminder to
# bring the consent form only happens if this feature is turned on by setting the CONSENT_FORM_URL config option.
AutomatedEmail(Attendee, '{EVENT_NAME} parental consent form reminder', 'reg_workflow/under_18_reminder.txt',
               lambda a: c.CONSENT_FORM_URL and a.age_group_conf['consent_form'],
               when=days_before(14, c.EPOCH))


for _conf in DeptChecklistConf.instances.values():
    DeptChecklistEmail(_conf)
