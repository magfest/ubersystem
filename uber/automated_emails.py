### WARNING - changing the email subject line for an email causes ALL of those emails to be re-sent!
#   Note that since the EVENT_NAME is used in most of these emails, changing the event name mid-year
#   could cause literally thousands of emails to be re-sent!

from uber.common import *

class AutomatedEmail:
    instances = OrderedDict()

    def __init__(self, model, subject, template, filter, *, sender=REGDESK_EMAIL, extra_data=None, cc=None, bcc=None, post_con=False, needs_approval=False):
        self.model, self.template, self.sender, self.needs_approval = model, template, sender, needs_approval
        self.subject = subject.format(EVENT_NAME=EVENT_NAME)
        self.cc = cc or []
        self.bcc = bcc or []
        self.extra_data = extra_data or {}
        self.instances[self.subject] = self
        if post_con:
            self.filter = lambda x: POST_CON and filter(x)
        else:
            self.filter = lambda x: not POST_CON and filter(x)

    def __repr__(self):
        return '<{}: {!r}>'.format(self.__class__.__name__, self.subject)

    def prev(self, x, all_sent = None):
        if all_sent:
            return all_sent.get((x.__class__.__name__, x.id, self.subject))
        else:
            with Session() as session:
                return session.query(Email).filter_by(model=x.__class__.__name__, fk_id=x.id, subject=self.subject).all()

    def should_send(self, x, all_sent=None):
        try:
            return x.email and not self.prev(x, all_sent) and self.filter(x)
        except:
            log.error('unexpected error', exc_info=True)

    def render(self, x):
        model = 'attendee' if isinstance(x, PrevSeasonSupporter) else x.__class__.__name__.lower()
        return render('emails/' + self.template, dict({model: x}, **self.extra_data))

    def send(self, x, raise_errors=True):
        try:
            format = 'text' if self.template.endswith('.txt') else 'html'
            send_email(self.sender, x.email, self.subject, self.render(x), format, model=x, cc=self.cc)
        except:
            log.error('error sending {!r} email to {}', self.subject, x.email, exc_info=True)
            if raise_errors:
                raise

    # TODO: joinedload on other tables such as shifts as well, for performance (this is WAY slower than it could be)
    @classmethod
    def send_all(cls, raise_errors=False):
        with Session() as session:
            attendees, groups = session.everyone()
            approved = {ae.subject for ae in session.query(ApprovedEmail).all()}
            models = {Attendee: attendees, Group: groups, 'SeasonPass': session.season_passes()}
            all_sent = {(e.model, e.fk_id, e.subject): e for e in session.query(Email).all()}
            for rem in cls.instances.values():
                if not rem.needs_approval or rem.subject in approved:
                    for x in models[rem.model]:
                        if rem.should_send(x, all_sent):
                            rem.send(x, raise_errors=raise_errors)

class StopsEmail(AutomatedEmail):
    def __init__(self, subject, template, filter, **kwargs):
        AutomatedEmail.__init__(self, Attendee, subject, template, lambda a: a.staffing and filter(a), sender=STAFF_EMAIL, **kwargs)

class GuestEmail(AutomatedEmail):
    def __init__(self, subject, template, filter=lambda a: True, needs_approval=True, **kwargs):
        AutomatedEmail.__init__(self, Attendee, subject, template, lambda a: a.badge_type == GUEST_BADGE and filter(a), needs_approval=needs_approval, sender=PANELS_EMAIL, **kwargs)

class GroupEmail(AutomatedEmail):
    def __init__(self, subject, template, filter, **kwargs):
        AutomatedEmail.__init__(self, Group, subject, template, lambda g: not g.is_dealer and filter(g), sender=REGDESK_EMAIL, **kwargs)

class MarketplaceEmail(AutomatedEmail):
    def __init__(self, subject, template, filter, **kwargs):
        AutomatedEmail.__init__(self, Group, subject, template, lambda g: g.is_dealer and filter(g), sender=MARKETPLACE_EMAIL, **kwargs)

class SeasonSupporterEmail(AutomatedEmail):
    def __init__(self, event):
        AutomatedEmail.__init__(self, 'SeasonPass',
                                subject = 'Claim your {} tickets with your {} Season Pass'.format(event.name, EVENT_NAME),
                                template = 'reg_workflow/season_supporter_event_invite.txt',
                                filter = lambda a: before(event.deadline),
                                needs_approval = True,
                                extra_data = {'event': event})

class DeptChecklistEmail(AutomatedEmail):
    def __init__(self, conf):
        AutomatedEmail.__init__(self, Attendee,
                                subject = '{EVENT_NAME} Department Checklist: ' + conf.name,
                                template = 'shifts/dept_checklist.txt',
                                filter = lambda a: a.is_single_dept_head and a.admin_account and days_before(7, conf.deadline) and not conf.completed(a),
                                sender = STAFF_EMAIL,
                                extra_data = {'conf': conf})

before = lambda dt: bool(dt) and localized_now() < dt
days_after = lambda days, dt: bool(dt) and (localized_now() > dt + timedelta(days=days))
def days_before(days, dt, until=None):
    if dt:
        until = (dt - timedelta(days=until)) if until else dt
        return dt - timedelta(days=days) < localized_now() < until


# Payment reminder emails, including ones for groups, which are always safe to be here, since they just
# won't get sent if group registration is turned off.

AutomatedEmail(Attendee, '{EVENT_NAME} payment received', 'reg_workflow/attendee_confirmation.html',
         lambda a: a.paid == HAS_PAID)

AutomatedEmail(Group, '{EVENT_NAME} group payment received', 'reg_workflow/group_confirmation.html',
         lambda g: g.amount_paid == g.cost)

AutomatedEmail(Attendee, '{EVENT_NAME} group registration confirmed', 'reg_workflow/attendee_confirmation.html',
         lambda a: a.group and a != a.group.leader)

AutomatedEmail(Attendee, '{EVENT_NAME} extra payment received', 'reg_workflow/group_donation.txt',
         lambda a: a.paid == PAID_BY_GROUP and a.amount_extra and a.amount_paid == a.amount_extra)


# Reminder emails for groups to allocated their unassigned badges.  These emails are safe to be turned on for
# all events, because they will only be sent for groups with unregistered badges, so if group preregistration
# has been turned off, they'll just never be sent.

GroupEmail('Reminder to pre-assign {EVENT_NAME} group badges', 'reg_workflow/group_preassign_reminder.txt',
           lambda g: days_after(30, g.registered) and state.BEFORE_GROUP_PREREG_TAKEDOWN and g.unregistered_badges)

AutomatedEmail(Group, 'Last chance to pre-assign {EVENT_NAME} group badges', 'reg_workflow/group_preassign_reminder.txt',
         lambda g: state.AFTER_GROUP_PREREG_TAKEDOWN and g.unregistered_badges and (not g.is_dealer or g.status == APPROVED))

# Reminder emails for groups with a remaining balance to pay. These are sometimes necessary for when groups
# add badges after registering.

AutomatedEmail(Group, 'Reminder to pay for your {EVENT_NAME} group badges', 'reg_workflow/group_payment_reminder.txt',
           lambda g: days_before(30, EPOCH) and g.amount_unpaid and (not g.is_dealer or g.status == APPROVED))

AutomatedEmail(Group, 'Last chance to pay for your {EVENT_NAME} group badges', 'reg_workflow/group_payment_reminder.txt',
           lambda g: days_before(7, EPOCH) and g.amount_unpaid and (not g.is_dealer or g.status == APPROVED))

# Dealer emails; these are safe to be turned on for all events because even if the event doesn't have dealers,
# none of these emails will be sent unless someone has applied to be a dealer, which they cannot do until
# dealer registration has been turned on.

MarketplaceEmail('Your {EVENT_NAME} Dealer registration has been approved', 'dealers/approved.html',
                 lambda g: g.status == APPROVED)

MarketplaceEmail('Reminder to pay for your {EVENT_NAME} Dealer registration', 'dealers/payment_reminder.txt',
                 lambda g: g.status == APPROVED and days_after(30, g.approved) and g.is_unpaid)

MarketplaceEmail('Your {EVENT_NAME} Dealer registration is due in one week', 'dealers/payment_reminder.txt',
                 lambda g: g.status == APPROVED and days_before(7, DEALER_PAYMENT_DUE, 2) and g.is_unpaid)

MarketplaceEmail('Last chance to pay for your {EVENT_NAME} Dealer registration', 'dealers/payment_reminder.txt',
                 lambda g: g.status == APPROVED and days_before(2, DEALER_PAYMENT_DUE) and g.is_unpaid)

MarketplaceEmail('{EVENT_NAME} Dealer waitlist has been exhausted', 'dealers/waitlist_closing.txt',
                 lambda g: state.AFTER_DEALER_WAITLIST_CLOSED and g.status == WAITLISTED)


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
               lambda a: a.placeholder and a.first_name and a.last_name and a.ribbon == PANELIST_RIBBON,
               sender = PANELS_EMAIL)

AutomatedEmail(Attendee, '{EVENT_NAME} Guest Badge Confirmation', 'placeholders/guest.txt',
               lambda a: a.placeholder and a.first_name and a.last_name and a.badge_type == GUEST_BADGE,
               sender = PANELS_EMAIL)

AutomatedEmail(Attendee, '{EVENT_NAME} Dealer Information Required', 'placeholders/dealer.txt',
               lambda a: a.placeholder and a.is_dealer and a.group.status == APPROVED,
               sender=MARKETPLACE_EMAIL)

StopsEmail('Want to staff {EVENT_NAME} again?', 'placeholders/imported_volunteer.txt',
           lambda a: a.placeholder and a.staffing and a.registered_local <= PREREG_OPEN)

StopsEmail('{EVENT_NAME} Volunteer Badge Confirmation', 'placeholders/volunteer.txt',
           lambda a: a.placeholder and a.first_name and a.last_name
                                      and a.registered_local > PREREG_OPEN)

AutomatedEmail(Attendee, '{EVENT_NAME} Badge Confirmation', 'placeholders/regular.txt',
               lambda a: a.placeholder and a.first_name and a.last_name
                                       and a.badge_type not in [GUEST_BADGE, STAFF_BADGE]
                                       and a.ribbon not in [DEALER_RIBBON, PANELIST_RIBBON, VOLUNTEER_RIBBON])

AutomatedEmail(Attendee, '{EVENT_NAME} Badge Confirmation Reminder', 'placeholders/reminder.txt',
               lambda a: days_after(7, a.registered) and a.placeholder and a.first_name and a.last_name and not a.is_dealer)

AutomatedEmail(Attendee, 'Last Chance to Accept Your {EVENT_NAME} Badge', 'placeholders/reminder.txt',
               lambda a: days_before(7, PLACEHOLDER_DEADLINE) and a.placeholder and a.first_name and a.last_name
                                                              and not a.is_dealer)


# Volunteer emails; none of these will be sent unless SHIFTS_CREATED is set.

StopsEmail('{EVENT_NAME} shifts available', 'shifts/created.txt',
           lambda a: state.AFTER_SHIFTS_CREATED and a.takes_shifts)

StopsEmail('Reminder to sign up for {EVENT_NAME} shifts', 'shifts/reminder.txt',
           lambda a: state.AFTER_SHIFTS_CREATED and days_after(30, max(a.registered_local, SHIFTS_CREATED))
                 and state.BEFORE_PREREG_TAKEDOWN and a.takes_shifts and not a.hours)

StopsEmail('Last chance to sign up for {EVENT_NAME} shifts', 'shifts/reminder.txt',
              lambda a: days_before(10, EPOCH) and state.AFTER_SHIFTS_CREATED and state.BEFORE_PREREG_TAKEDOWN
                                               and a.takes_shifts and not a.hours)

StopsEmail('Still want to volunteer at {EVENT_NAME}?', 'shifts/volunteer_check.txt',
              lambda a: SHIFTS_CREATED and days_before(5, UBER_TAKEDOWN)
                                       and a.ribbon == VOLUNTEER_RIBBON and a.takes_shifts and a.weighted_hours == 0)

StopsEmail('Please tell us your {EVENT_NAME} shirt size', 'shifts/shirt_reminder.txt',
           lambda a: SHIFTS_CREATED and a.shirt == NO_SHIRT and a.gets_shirt
                                    and days_before(30, UBER_TAKEDOWN) and days_after(1, a.registered),
           needs_approval=True)

StopsEmail('Review your {EVENT_NAME} shift schedule', 'shifts/schedule.html',
           lambda a: SHIFTS_CREATED and a.takes_shifts and a.hours and days_before(14, UBER_TAKEDOWN),
           needs_approval=True)

# MAGFest provides staff rooms for returning volunteers; leave ROOM_DEADLINE blank to keep these emails turned off.

StopsEmail('Want volunteer hotel room space at {EVENT_NAME}?', 'shifts/hotel_rooms.txt',
           lambda a: days_before(45, ROOM_DEADLINE, 14) and state.AFTER_SHIFTS_CREATED and a.hotel_eligible)

StopsEmail('Reminder to sign up for {EVENT_NAME} hotel room space', 'shifts/hotel_reminder.txt',
           lambda a: days_before(14, ROOM_DEADLINE, 2) and a.hotel_eligible and not a.hotel_requests)

StopsEmail('Last chance to sign up for {EVENT_NAME} hotel room space', 'shifts/hotel_reminder.txt',
           lambda a: days_before(2, ROOM_DEADLINE) and a.hotel_eligible and not a.hotel_requests)

StopsEmail('Reminder to meet your {EVENT_NAME} hotel room requirements', 'shifts/hotel_hours.txt',
           lambda a: days_after(14, ROOM_DEADLINE) and a.hotel_shifts_required and a.weighted_hours < 30)

StopsEmail('Final reminder to meet your {EVENT_NAME} hotel room requirements', 'shifts/hotel_hours.txt',
           lambda a: days_before(14, UBER_TAKEDOWN) and a.hotel_shifts_required and a.weighted_hours < 30)


# For events with customized badges, these emails remind people to let us know what we want on their badges.  We have
# one email for our volunteers who haven't bothered to confirm they're coming yet (bleh) and one for everyone else.

StopsEmail('Last chance to personalize your {EVENT_NAME} badge', 'personalized_badges/volunteers.txt',
           lambda a: days_before(7, PRINTED_BADGE_DEADLINE) and a.staffing and a.badge_type in PREASSIGNED_BADGE_TYPES and a.placeholder)

AutomatedEmail(Attendee, 'Personalized {EVENT_NAME} badges will be ordered next week', 'personalized_badges/reminder.txt',
               lambda a: days_before(7, PRINTED_BADGE_DEADLINE) and a.badge_type in PREASSIGNED_BADGE_TYPES and not a.placeholder)


# MAGFest requires signed and notarized parental consent forms for anyone under 18.  This automated email reminder to
# bring the consent form only happens if this feature is turned on by setting the CONSENT_FORM_URL config option.
AutomatedEmail(Attendee, '{EVENT_NAME} parental consent form reminder', 'reg_workflow/under_18_reminder.txt',
               lambda a: CONSENT_FORM_URL and a.age_group == UNDER_18 and days_before(7, EPOCH))


for _event in SeasonEvent.instances.values():
    SeasonSupporterEmail(_event)

for _conf in DeptChecklistConf.instances.values():
    DeptChecklistEmail(_conf)
