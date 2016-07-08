# WARNING - changing the email subject line for an email causes ALL of those emails to be re-sent!
# Note that since c.EVENT_NAME is used in most of these emails, changing the event name mid-year
# could cause literally thousands of emails to be re-sent!

from uber.common import *


class AutomatedEmail:
    instances = OrderedDict()

    queries = {
        Attendee: lambda session: session.staffers(only_staffing=False),
        Group: lambda session: session.query(Group).options(subqueryload(Group.attendees))
    }

    def __init__(self, model, subject, template, filter, *, date_filters=[], sender=None, extra_data=None, cc=None, bcc=None, post_con=False, needs_approval=True):
        self.model, self.template, self.needs_approval = model, template, needs_approval
        self.subject = subject.format(EVENT_NAME=c.EVENT_NAME)
        self.cc = cc or []
        self.bcc = bcc or []
        self.extra_data = extra_data or {}
        self.sender = sender or c.REGDESK_EMAIL
        self.instances[self.subject] = self
        self.date_filters = date_filters

        # after each daemon run, this is set to the number of emails that would have been sent out but weren't because
        # they were not marked as approved.
        self.count_emails_not_sent_need_approval = 0

        # old filter
        if post_con:
            self.filter = lambda x: c.POST_CON and filter(x)
        else:
            self.filter = lambda x: not c.POST_CON and filter(x)

    def filters_run(self, x):
        if self.filter and not self.filter(x):
            return False

        for date_filter in listify(self.date_filters):
            if not date_filter():
                return False

        return True

    def __repr__(self):
        return '<{}: {!r}>'.format(self.__class__.__name__, self.subject)

    def already_sent(self, x, previously_sent_emails=None):
        """
        Returns true if we have a record of previously sending this email

        Speed Optimization: when using this function as part of batch processing, you can pass in a list of all
        previously sent emails, previously_sent_emails, in order to avoid having to query the DB for this specific email
        """
        if previously_sent_emails:
            return (x.__class__.__name__, x.id, self.subject) in previously_sent_emails
        else:
            with Session() as session:
                return session.query(Email).filter_by(model=x.__class__.__name__, fk_id=x.id, subject=self.subject).first()

    def should_send(self, model_inst, approved_subjects, previously_sent_emails=None):
        try:
            if not isinstance(model_inst, self.model) or not model_inst.email:
                return False

            if self.already_sent(model_inst, previously_sent_emails):
                return False

            if not self.filters_run(model_inst):
                return False

            if self.needs_approval and self.subject not in approved_subjects:
                self.count_emails_not_sent_need_approval += 1
                return False

            return True
        except:
            log.error('unexpected error', exc_info=True)

    def render(self, x):
        model = getattr(x, 'email_model_name', x.__class__.__name__.lower())
        return render('emails/' + self.template, dict({model: x}, **self.extra_data))

    def send(self, x, raise_errors=True):
        try:
            format = 'text' if self.template.endswith('.txt') else 'html'
            send_email(self.sender, x.email, self.subject, self.render(x), format, model=x, cc=self.cc)
        except:
            log.error('error sending {!r} email to {}', self.subject, x.email, exc_info=True)
            if raise_errors:
                raise

    @property
    def date_filters_txt(self):
        """
        Return a textual description of when the date filters are active for this email category
        """

        return '\n'.join([filter.active_when for filter in listify(self.date_filters)])

    @classmethod
    def send_all(cls, raise_errors=False):
        if not c.AT_THE_CON and (c.DEV_BOX or c.SEND_EMAILS):
            with Session() as session:
                # CPU+speed optimization: cache these values for later use
                approved_subjects = {ae.subject for ae in session.query(ApprovedEmail)}
                previously_sent_emails = set(session.query(Email.model, Email.fk_id, Email.subject))

                for model, query in cls.queries.items():
                    for model_inst in query(session):
                        sleep(0.01)  # throttle CPU usage
                        for automated_email in cls.instances.values():
                            automated_email.count_emails_not_sent_need_approval = 0  # reset
                            if automated_email.should_send(model_inst, approved_subjects, previously_sent_emails):
                                automated_email.send(model_inst, raise_errors=raise_errors)



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
                                date_filters=days_before(7, conf.deadline),
                                sender=c.STAFF_EMAIL,
                                extra_data={'conf': conf})


print_dateformat = "%m/%d"


class days_before:
    def __init__(self, days, dt, until=None):
        self.dt = dt
        self.days = days
        self.until = until

        if dt:
            self.starting_date = self.dt - timedelta(days=self.days)
            self.ending_date = (dt - timedelta(days=until)) if until else dt

    def __call__(self):
        return self.starting_date < localized_now() < self.ending_date if self.dt else False

    @property
    def active_when(self):
        return 'between {} and {}'.format(self.starting_date.strftime(print_dateformat),
                                          self.ending_date.strftime(print_dateformat)) \
            if self.dt else ''


class days_after:
    def __init__(self, days, dt):
        self.dt = dt
        self.days = days

        self.starting_date = dt + timedelta(days=days) if dt else None

    def __call__(self):
        return bool(self.dt) and (localized_now() > self.starting_date)

    @property
    def active_when(self):
        return 'after {}'.format(self.starting_date.strftime(print_dateformat)) if self.starting_date else ''


class before:
    def __init__(self, dt):
        self.dt = dt

    def __call__(self):
        return bool(self.dt) and localized_now() < self.dt

    @property
    def active_when(self):
        return 'before {}'.format(self.dt.strftime(print_dateformat)) if self.dt else ''


class after:
    def __init__(self, dt):
        self.dt = dt

    def __call__(self):
        return bool(self.dt) and localized_now() > self.dt

    @property
    def active_when(self):
        return 'after {}'.format(self.dt.strftime(print_dateformat)) if self.dt else ''


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
                 date_filters=days_before(7, c.DEALER_PAYMENT_DUE, 2),
                 needs_approval=False)

MarketplaceEmail('Last chance to pay for your {EVENT_NAME} Dealer registration', 'dealers/payment_reminder.txt',
                 lambda g: g.status == c.APPROVED and g.is_unpaid,
                 date_filters=days_before(2, c.DEALER_PAYMENT_DUE),
                 needs_approval=False)

MarketplaceEmail('{EVENT_NAME} Dealer waitlist has been exhausted', 'dealers/waitlist_closing.txt',
                 lambda g: g.status == c.WAITLISTED,
                 date_filters=after(c.DEALER_WAITLIST_CLOSED))


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
               date_filters=days_before(7, c.PLACEHOLDER_DEADLINE))


# Volunteer emails; none of these will be sent unless SHIFTS_CREATED is set.

StopsEmail('{EVENT_NAME} shifts available', 'shifts/created.txt',
           lambda a: a.takes_shifts,
           date_filters=after(c.SHIFTS_CREATED))

StopsEmail('Reminder to sign up for {EVENT_NAME} shifts', 'shifts/reminder.txt',
           lambda a: c.AFTER_SHIFTS_CREATED and days_after(30, max(a.registered_local, c.SHIFTS_CREATED))
                 and a.takes_shifts and not a.hours,
           date_filters=before(c.PREREG_TAKEDOWN))

StopsEmail('Last chance to sign up for {EVENT_NAME} shifts', 'shifts/reminder.txt',
              lambda a: c.AFTER_SHIFTS_CREATED and c.BEFORE_PREREG_TAKEDOWN and a.takes_shifts and not a.hours,
              date_filters=days_before(10, c.EPOCH))

StopsEmail('Still want to volunteer at {EVENT_NAME}?', 'shifts/volunteer_check.txt',
            lambda a: c.SHIFTS_CREATED and a.ribbon == c.VOLUNTEER_RIBBON and a.takes_shifts and a.weighted_hours == 0,
            date_filters=days_before(5, c.FINAL_EMAIL_DEADLINE))

StopsEmail('Your {EVENT_NAME} shift schedule', 'shifts/schedule.html',
           lambda a: c.SHIFTS_CREATED and a.weighted_hours,
           date_filters=days_before(1, c.FINAL_EMAIL_DEADLINE))


# For events with customized badges, these emails remind people to let us know what we want on their badges.  We have
# one email for our volunteers who haven't bothered to confirm they're coming yet (bleh) and one for everyone else.

StopsEmail('Last chance to personalize your {EVENT_NAME} badge', 'personalized_badges/volunteers.txt',
           lambda a: a.staffing and a.badge_type in c.PREASSIGNED_BADGE_TYPES and a.placeholder,
           date_filters=days_before(7, c.PRINTED_BADGE_DEADLINE))

AutomatedEmail(Attendee, 'Personalized {EVENT_NAME} badges will be ordered next week', 'personalized_badges/reminder.txt',
               lambda a: a.badge_type in c.PREASSIGNED_BADGE_TYPES and not a.placeholder,
               date_filters=days_before(7, c.PRINTED_BADGE_DEADLINE))


# MAGFest requires signed and notarized parental consent forms for anyone under 18.  This automated email reminder to
# bring the consent form only happens if this feature is turned on by setting the CONSENT_FORM_URL config option.
AutomatedEmail(Attendee, '{EVENT_NAME} parental consent form reminder', 'reg_workflow/under_18_reminder.txt',
               lambda a: c.CONSENT_FORM_URL and a.age_group_conf['consent_form'],
               date_filters=days_before(14, c.EPOCH))


for _conf in DeptChecklistConf.instances.values():
    DeptChecklistEmail(_conf)
