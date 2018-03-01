"""
IMPORTANT NOTES FOR CHANGING/ADDING EMAIL CATEGORIES:

'ident' is a unique ID for that email category that must not change after
emails in that category have started to send.

*****************************************************************************
IF YOU CHANGE THE IDENT FOR A CATEGORY, IT WILL CAUSE ANY EMAILS THAT HAVE
ALREADY SENT FOR THAT CATEGORY TO RE-SEND.
*****************************************************************************

"""

from collections import defaultdict, OrderedDict
from datetime import datetime, timedelta

from pockets import listify
from pockets.autolog import log
from pytz import UTC
from sqlalchemy.orm import joinedload, subqueryload

from uber.config import c
from uber.decorators import render
from uber.models import AdminAccount, Attendee, Department, Group, GuestGroup, IndieGame, IndieJudge, IndieStudio, \
     MITSTeam, PanelApplication, PanelApplicant, Room, RoomAssignment, Shift
from uber.notifications import send_email
from uber.utils import before, days_after, days_before, localized_now, DeptChecklistConf


class AutomatedEmail:
    """
    Represents one category of emails that we send out.
    An example of an email category would be "Your registration has been confirmed".
    """

    # global: all instances of every registered email category, mapped by ident
    instances = OrderedDict()

    # global: all instances of every registered email category, mapped by model class
    instances_by_model = defaultdict(list)

    # a list of queries to run during each automated email sending run to
    # return particular model instances of a given type.
    queries = {
        Attendee: lambda session: session.all_attendees().options(
            subqueryload(Attendee.admin_account),
            subqueryload(Attendee.group),
            subqueryload(Attendee.shifts).subqueryload(Shift.job),
            subqueryload(Attendee.assigned_depts),
            subqueryload(Attendee.dept_membership_requests),
            subqueryload(Attendee.checklist_admin_depts).subqueryload(Department.dept_checklist_items),
            subqueryload(Attendee.dept_memberships),
            subqueryload(Attendee.dept_memberships_with_role),
            subqueryload(Attendee.depts_where_working),
            subqueryload(Attendee.hotel_requests),
            subqueryload(Attendee.assigned_panelists)),
        Group: lambda session: session.query(Group).options(
            subqueryload(Group.attendees)).order_by(Group.id),
        Room: lambda session: session.query(Room).options(
            subqueryload(Room.assignments).subqueryload(RoomAssignment.attendee)),
        IndieStudio: lambda session: session.query(IndieStudio).options(
            subqueryload(IndieStudio.developers),
            subqueryload(IndieStudio.games)),
        IndieGame: lambda session: session.query(IndieGame).options(
            joinedload(IndieGame.studio).subqueryload(IndieStudio.developers)),
        IndieJudge: lambda session: session.query(IndieJudge).options(
            joinedload(IndieJudge.admin_account).joinedload(AdminAccount.attendee)),
        MITSTeam: lambda session: session.mits_teams(),
        PanelApplication: lambda session: session.query(PanelApplication).options(
            subqueryload(PanelApplication.applicants).subqueryload(PanelApplicant.attendee)
            ).order_by(PanelApplication.id),
        GuestGroup: lambda session: session.query(GuestGroup).options(joinedload(GuestGroup.group))
    }

    def __init__(self, model, subject, template, filter, ident, *, when=(),
                 sender=None, extra_data=None, cc=None, bcc=None,
                 post_con=False, needs_approval=True, allow_during_con=False):

        self.subject = subject.format(EVENT_NAME=c.EVENT_NAME, EVENT_DATE=c.EPOCH.strftime("(%b %Y)"))
        self.ident = ident
        self.model = model

        assert self.ident, 'error: automated email ident may not be empty.'
        assert self.ident not in self.instances, \
            'error: automated email ident "{}" is registered twice.'.format(self.ident)

        self.instances[self.ident] = self
        self.instances_by_model[self.model].append(self)

        self.template = template
        self.needs_approval = needs_approval
        self.allow_during_con = allow_during_con
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
        exists only to be overridden in subclasses.  For example, we might want
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

        Do any error handling in the client functions we call

        :return: True if the email was actually sent, False otherwise.
        """
        if self._should_send(model_inst, raise_errors=raise_errors):
            return self.really_send(model_inst, raise_errors=raise_errors)
        return False

    def _should_send(self, model_inst, raise_errors=False):
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

        try:
            return self.would_send_if_approved(model_inst) and self.approved
        except Exception:
            log.error('error determining whether to send {!r} email to {}',
                      self.subject, model_inst.email, exc_info=True)
            if raise_errors:
                raise
            return False

    def would_send_if_approved(self, model_inst):
        """
        Check if this email category would be sent if this email category was approved.

        :return: True if this email would be sent without considering it's approved status. False otherwise
        """
        return all(condition() for condition in [
            lambda: not c.AT_THE_CON or self.allow_during_con,
            lambda: isinstance(model_inst, self.model),
            lambda: getattr(model_inst, 'email', None),
            lambda: not self._already_sent(model_inst),
            lambda: self.filters_run(model_inst),
        ])

    @property
    def approved(self):
        """
        Check if this email category has been approved by the admins to send automated emails.

        :return: True if we are approved to send this email, or don't need approval. False otherwise
        """

        return not self.needs_approval or self.ident in c.EMAIL_APPROVED_IDENTS

    def render(self, model_instance):
        model = getattr(model_instance, 'email_model_name', model_instance.__class__.__name__.lower())
        return render('emails/' + self.template, dict({model: model_instance}, **self.extra_data))

    def really_send(self, model_instance, raise_errors=False):
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
            return True
        except Exception:
            log.error('error sending {!r} email to {}', self.subject, model_instance.email, exc_info=True)
            if raise_errors:
                raise
        return False

    @property
    def when_txt(self):
        """
        Return a textual description of when the date filters are active for this email category.
        """

        return '\n'.join([filter.active_when for filter in self.when])


# Payment reminder emails, including ones for groups, which are always safe to be here, since they just
# won't get sent if group registration is turned off.

AutomatedEmail(Attendee, '{EVENT_NAME} payment received',
               'reg_workflow/attendee_confirmation.html',
               lambda a: a.paid == c.HAS_PAID,
               needs_approval=False,
               allow_during_con=True,
               ident='attendee_payment_received')

AutomatedEmail(Attendee, '{EVENT_NAME} registration confirmed',
               'reg_workflow/attendee_confirmation.html',
               lambda a: a.paid == c.NEED_NOT_PAY and (a.confirmed or a.promo_code_id),
               needs_approval=False,
               allow_during_con=True,
               ident='attendee_badge_confirmed')

AutomatedEmail(Group, '{EVENT_NAME} group payment received',
               'reg_workflow/group_confirmation.html',
               lambda g: g.amount_paid == g.cost and g.cost != 0 and g.leader_id,
               needs_approval=False,
               ident='group_payment_received')

AutomatedEmail(Attendee, '{EVENT_NAME} group registration confirmed',
               'reg_workflow/attendee_confirmation.html',
               lambda a: a.group and (a.id != a.group.leader_id or a.group.cost == 0) and not a.placeholder,
               needs_approval=False,
               allow_during_con=True,
               ident='attendee_group_reg_confirmation')

AutomatedEmail(Attendee, '{EVENT_NAME} extra payment received',
               'reg_workflow/group_donation.txt',
               lambda a: a.paid == c.PAID_BY_GROUP and a.amount_extra and a.amount_paid == a.amount_extra,
               needs_approval=False,
               ident='group_extra_payment_received')

# Reminder emails for groups to allocated their unassigned badges.  These emails are safe to be turned on for
# all events, because they will only be sent for groups with unregistered badges, so if group preregistration
# has been turned off, they'll just never be sent.


class GroupEmail(AutomatedEmail):
    def __init__(self, subject, template, filter, ident, **kwargs):
        AutomatedEmail.__init__(self, Group, subject,
                                template,
                                lambda g: not g.is_dealer and filter(g),
                                ident,
                                sender=c.REGDESK_EMAIL,
                                **kwargs)


GroupEmail('Reminder to pre-assign {EVENT_NAME} group badges',
           'reg_workflow/group_preassign_reminder.txt',
           lambda g: days_after(30, g.registered)() and c.BEFORE_GROUP_PREREG_TAKEDOWN and g.unregistered_badges,
           needs_approval=False,
           ident='group_preassign_badges_reminder')

AutomatedEmail(Group, 'Last chance to pre-assign {EVENT_NAME} group badges',
               'reg_workflow/group_preassign_reminder.txt',
               lambda g: (
                   c.AFTER_GROUP_PREREG_TAKEDOWN
                   and g.unregistered_badges
                   and (not g.is_dealer or g.status == c.APPROVED)),
               needs_approval=False,
               ident='group_preassign_badges_reminder_last_chance')


# Dealer emails; these are safe to be turned on for all events because even if the event doesn't have dealers,
# none of these emails will be sent unless someone has applied to be a dealer, which they cannot do until
# dealer registration has been turned on.

class MarketplaceEmail(AutomatedEmail):
    def __init__(self, subject, template, filter, ident, **kwargs):
        AutomatedEmail.__init__(self, Group, subject,
                                template,
                                lambda g: g.is_dealer and filter(g),
                                ident,
                                sender=c.MARKETPLACE_EMAIL,
                                **kwargs)


MarketplaceEmail('Your {EVENT_NAME} Dealer registration has been approved',
                 'dealers/approved.html',
                 lambda g: g.status == c.APPROVED,
                 needs_approval=False,
                 ident='dealer_reg_approved')

MarketplaceEmail('Reminder to pay for your {EVENT_NAME} Dealer registration',
                 'dealers/payment_reminder.txt',
                 lambda g: g.status == c.APPROVED and days_after(30, g.approved)() and g.is_unpaid,
                 needs_approval=False,
                 ident='dealer_reg_payment_reminder')

MarketplaceEmail('Your {EVENT_NAME} {EVENT_DATE} Dealer registration is due in one week',
                 'dealers/payment_reminder.txt',
                 lambda g: g.status == c.APPROVED and g.is_unpaid,
                 when=days_before(7, c.DEALER_PAYMENT_DUE, 2),
                 needs_approval=False,
                 ident='dealer_reg_payment_reminder_due_soon')

MarketplaceEmail('Last chance to pay for your {EVENT_NAME} {EVENT_DATE} Dealer registration',
                 'dealers/payment_reminder.txt',
                 lambda g: g.status == c.APPROVED and g.is_unpaid,
                 when=days_before(2, c.DEALER_PAYMENT_DUE),
                 needs_approval=False,
                 ident='dealer_reg_payment_reminder_last_chance')

MarketplaceEmail('{EVENT_NAME} Dealer waitlist has been exhausted',
                 'dealers/waitlist_closing.txt',
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


class StopsEmail(AutomatedEmail):
    def __init__(self, subject, template, filter, ident, **kwargs):
        AutomatedEmail.__init__(self, Attendee, subject,
                                template,
                                lambda a: a.staffing and filter(a),
                                ident,
                                sender=c.STAFF_EMAIL,
                                **kwargs)


AutomatedEmail(Attendee, '{EVENT_NAME} Panelist Badge Confirmation',
               'placeholders/panelist.txt',
               lambda a: a.placeholder and c.PANELIST_RIBBON in a.ribbon_ints,
               sender=c.PANELS_EMAIL,
               ident='panelist_badge_confirmation')

AutomatedEmail(Attendee, '{EVENT_NAME} Guest Badge Confirmation',
               'placeholders/guest.txt',
               lambda a: a.placeholder and a.badge_type == c.GUEST_BADGE,
               sender=c.GUEST_EMAIL,
               ident='guest_badge_confirmation')

AutomatedEmail(Attendee, '{EVENT_NAME} Dealer Information Required',
               'placeholders/dealer.txt',
               lambda a: a.placeholder and a.is_dealer and a.group.status == c.APPROVED,
               sender=c.MARKETPLACE_EMAIL,
               ident='dealer_info_required')

StopsEmail('Want to staff {EVENT_NAME} again?',
           'placeholders/imported_volunteer.txt',
           lambda a: a.placeholder and a.registered_local <= c.PREREG_OPEN,
           ident='volunteer_again_inquiry')

StopsEmail('{EVENT_NAME} Volunteer Badge Confirmation',
           'placeholders/volunteer.txt',
           lambda a: a.placeholder and a.registered_local > c.PREREG_OPEN,
           ident='volunteer_badge_confirmation')

AutomatedEmail(Attendee, '{EVENT_NAME} Badge Confirmation',
               'placeholders/regular.txt',
               lambda a: a.placeholder and (
                   c.AT_THE_CON
                   or a.badge_type not in [c.GUEST_BADGE, c.STAFF_BADGE]
                   and not set([c.DEALER_RIBBON, c.PANELIST_RIBBON, c.VOLUNTEER_RIBBON]).intersection(a.ribbon_ints)),
               allow_during_con=True,
               ident='regular_badge_confirmation')

AutomatedEmail(Attendee, '{EVENT_NAME} Badge Confirmation Reminder',
               'placeholders/reminder.txt',
               lambda a: days_after(7, a.registered)() and a.placeholder and not a.is_dealer,
               ident='badge_confirmation_reminder')

AutomatedEmail(Attendee, 'Last Chance to Accept Your {EVENT_NAME} {EVENT_DATE} Badge',
               'placeholders/reminder.txt',
               lambda a: a.placeholder and not a.is_dealer,
               when=days_before(7, c.PLACEHOLDER_DEADLINE),
               ident='badge_confirmation_reminder_last_chance')


# Volunteer emails; none of these will be sent unless SHIFTS_CREATED is set.

StopsEmail('Please complete your {EVENT_NAME} Staff/Volunteer Checklist',
           'shifts/created.txt',
           lambda a: a.takes_shifts,
           when=days_after(0, c.SHIFTS_CREATED),
           ident='volunteer_checklist_completion_request')

StopsEmail('Reminder to sign up for {EVENT_NAME} {EVENT_DATE} shifts',
           'shifts/reminder.txt',
           lambda a: (
               c.AFTER_SHIFTS_CREATED
               and days_after(30, max(a.registered_local, c.SHIFTS_CREATED))()
               and a.takes_shifts
               and not a.hours),
           when=before(c.PREREG_TAKEDOWN),
           ident='volunteer_shift_signup_reminder')

StopsEmail('Last chance to sign up for {EVENT_NAME} {EVENT_DATE} shifts',
           'shifts/reminder.txt',
           lambda a: c.AFTER_SHIFTS_CREATED and c.BEFORE_PREREG_TAKEDOWN and a.takes_shifts and not a.hours,
           when=days_before(10, c.EPOCH),
           ident='volunteer_shift_signup_reminder_last_chance')

StopsEmail('Still want to volunteer at {EVENT_NAME} {EVENT_DATE}?',
           'shifts/volunteer_check.txt',
           lambda a: (
               c.SHIFTS_CREATED
               and c.VOLUNTEER_RIBBON in a.ribbon_ints
               and a.takes_shifts
               and a.weighted_hours == 0),
           when=days_before(28, c.FINAL_EMAIL_DEADLINE),
           ident='volunteer_still_interested_inquiry')

StopsEmail('Your {EVENT_NAME} {EVENT_DATE} shift schedule',
           'shifts/schedule.html',
           lambda a: c.SHIFTS_CREATED and a.weighted_hours,
           when=days_before(1, c.FINAL_EMAIL_DEADLINE),
           ident='volunteer_shift_schedule')


# For events with customized badges, these emails remind people to let us know what we want on their badges.  We have
# one email for our volunteers who haven't bothered to confirm they're coming yet (bleh) and one for everyone else.

StopsEmail('Last chance to personalize your {EVENT_NAME} {EVENT_DATE} badge',
           'personalized_badges/volunteers.txt',
           lambda a: a.staffing and a.badge_type in c.PREASSIGNED_BADGE_TYPES and a.placeholder,
           when=days_before(7, c.PRINTED_BADGE_DEADLINE),
           ident='volunteer_personalized_badge_reminder')

AutomatedEmail(Attendee, 'Personalized {EVENT_NAME} {EVENT_DATE} badges will be ordered next week',
               'personalized_badges/reminder.txt',
               lambda a: a.badge_type in c.PREASSIGNED_BADGE_TYPES and not a.placeholder,
               when=days_before(7, c.PRINTED_BADGE_DEADLINE),
               ident='personalized_badge_reminder')


# MAGFest requires signed and notarized parental consent forms for anyone under 18.  This automated email reminder to
# bring the consent form only happens if this feature is turned on by setting the CONSENT_FORM_URL config option.
AutomatedEmail(Attendee, '{EVENT_NAME} {EVENT_DATE} parental consent form reminder',
               'reg_workflow/under_18_reminder.txt',
               lambda a: c.CONSENT_FORM_URL and a.age_group_conf['consent_form'],
               when=days_before(14, c.EPOCH),
               ident='under_18_parental_consent_reminder')


# Emails sent out to all attendees who can check in. These emails contain useful information about the event and are
# sent close to the event start date.
AutomatedEmail(Attendee, 'Check in faster at {EVENT_NAME}',
               'reg_workflow/attendee_qrcode.html',
               lambda a: not a.is_not_ready_to_checkin and c.USE_CHECKIN_BARCODE,
               when=days_before(14, c.EPOCH),
               ident='qrcode_for_checkin')


class DeptChecklistEmail(AutomatedEmail):
    def __init__(self, conf):
        AutomatedEmail.__init__(self, Attendee, '{EVENT_NAME} Department Checklist: ' + conf.name,
                                'shifts/dept_checklist.txt',
                                filter=lambda a: a.admin_account and any(
                                    not d.checklist_item_for_slug(conf.slug)
                                    for d in a.checklist_admin_depts),
                                ident='department_checklist_{}'.format(conf.name),
                                when=days_before(10, conf.deadline),
                                sender=c.STAFF_EMAIL,
                                extra_data={'conf': conf},
                                post_con=conf.email_post_con or False)


for _conf in DeptChecklistConf.instances.values():
    DeptChecklistEmail(_conf)


# =============================
# hotel
# =============================

AutomatedEmail(Attendee, 'Want volunteer hotel room space at {EVENT_NAME}?',
               'hotel/hotel_rooms.txt',
               lambda a: c.AFTER_SHIFTS_CREATED and a.hotel_eligible and a.takes_shifts, sender=c.ROOM_EMAIL_SENDER,
               when=days_before(45, c.ROOM_DEADLINE, 14),
               ident='volunteer_hotel_room_inquiry')

AutomatedEmail(Attendee, 'Reminder to sign up for {EVENT_NAME} hotel room space',
               'hotel/hotel_reminder.txt',
               lambda a: a.hotel_eligible and not a.hotel_requests and a.takes_shifts, sender=c.ROOM_EMAIL_SENDER,
               when=days_before(14, c.ROOM_DEADLINE, 2),
               ident='hotel_sign_up_reminder')

AutomatedEmail(Attendee, 'Last chance to sign up for {EVENT_NAME} hotel room space',
               'hotel/hotel_reminder.txt',
               lambda a: a.hotel_eligible and not a.hotel_requests and a.takes_shifts, sender=c.ROOM_EMAIL_SENDER,
               when=days_before(2, c.ROOM_DEADLINE),
               ident='hotel_sign_up_reminder_last_chance')

AutomatedEmail(Attendee, 'Reminder to meet your {EVENT_NAME} hotel room requirements',
               'hotel/hotel_hours.txt',
               lambda a: a.hotel_shifts_required and a.weighted_hours < c.HOTEL_REQ_HOURS, sender=c.ROOM_EMAIL_SENDER,
               when=days_before(14, c.FINAL_EMAIL_DEADLINE, 7),
               ident='hotel_requirements_reminder')

AutomatedEmail(Attendee, 'Final reminder to meet your {EVENT_NAME} hotel room requirements',
               'hotel/hotel_hours.txt',
               lambda a: a.hotel_shifts_required and a.weighted_hours < c.HOTEL_REQ_HOURS, sender=c.ROOM_EMAIL_SENDER,
               when=days_before(7, c.FINAL_EMAIL_DEADLINE),
               ident='hotel_requirements_reminder_last_chance')

AutomatedEmail(Room, '{EVENT_NAME} Hotel Room Assignment',
               'hotel/room_assignment.txt',
               lambda r: r.locked_in,
               sender=c.ROOM_EMAIL_SENDER,
               ident='hotel_room_assignment')


# =============================
# mivs
# =============================

class MIVSEmail(AutomatedEmail):
    def __init__(self, *args, **kwargs):
        if len(args) < 4 and 'filter' not in kwargs:
            kwargs['filter'] = lambda x: True
        AutomatedEmail.__init__(self, *args, sender=c.MIVS_EMAIL, **kwargs)


MIVSEmail(IndieStudio, 'Your MIVS Studio Has Been Registered',
          'mivs/studio_registered.txt',
          ident='mivs_studio_registered')

MIVSEmail(IndieGame, 'Your MIVS Game Video Has Been Submitted',
          'mivs/game_video_submitted.txt',
          lambda game: game.video_submitted,
          ident='mivs_video_submitted')

MIVSEmail(IndieGame, 'Your MIVS Game Has Been Submitted',
          'mivs/game_submitted.txt',
          lambda game: game.submitted,
          ident='mivs_game_submitted')

MIVSEmail(IndieStudio, 'MIVS - Wat no video?',
          'mivs/videoless_studio.txt',
          lambda studio: days_after(2, studio.registered)() and not any(game.video_submitted for game in studio.games),
          ident='mivs_missing_video_inquiry',
          when=days_before(7, c.MIVS_ROUND_ONE_DEADLINE))

MIVSEmail(IndieGame, 'MIVS: Your Submitted Video Is Broken',
          'mivs/video_broken.txt',
          lambda game: game.video_broken,
          ident='mivs_video_broken')

MIVSEmail(IndieGame, 'Last chance to submit your game to MIVS',
          'mivs/round_two_reminder.txt',
          lambda game: game.status == c.JUDGING and not game.submitted,
          ident='mivs_game_submission_reminder',
          when=days_before(7, c.MIVS_ROUND_TWO_DEADLINE))

MIVSEmail(IndieGame, 'Your game has made it into MIVS Round Two',
          'mivs/video_accepted.txt',
          lambda game: game.status == c.JUDGING,
          ident='mivs_game_made_it_to_round_two')

MIVSEmail(IndieGame, 'Your game has been declined from MIVS',
          'mivs/video_declined.txt',
          lambda game: game.status == c.VIDEO_DECLINED,
          ident='mivs_video_declined')

MIVSEmail(IndieGame, 'Your game has been accepted into MIVS',
          'mivs/game_accepted.txt',
          lambda game: game.status == c.ACCEPTED and not game.waitlisted,
          ident='mivs_game_accepted')

MIVSEmail(IndieGame, 'Your game has been accepted into MIVS from our waitlist',
          'mivs/game_accepted_from_waitlist.txt',
          lambda game: game.status == c.ACCEPTED and game.waitlisted,
          ident='mivs_game_accepted_from_waitlist')

MIVSEmail(IndieGame, 'Your game application has been declined from MIVS',
          'mivs/game_declined.txt',
          lambda game: game.status == c.GAME_DECLINED,
          ident='mivs_game_declined')

MIVSEmail(IndieGame, 'Your MIVS application has been waitlisted',
          'mivs/game_waitlisted.txt',
          lambda game: game.status == c.WAITLISTED,
          ident='mivs_game_waitlisted')

MIVSEmail(IndieGame, 'Last chance to accept your MIVS booth',
          'mivs/game_accept_reminder.txt',
          lambda game: (
              game.status == c.ACCEPTED
              and not game.confirmed
              and (localized_now() - timedelta(days=2)) > game.studio.confirm_deadline),
          ident='mivs_accept_booth_reminder')

MIVSEmail(IndieGame, 'MIVS December Updates: Hotels and Magfest Versus!',
          'mivs/december_updates.txt',
          lambda game: game.confirmed,
          ident='mivs_december_updates')

MIVSEmail(IndieGame, 'REQUIRED: Pre-flight for MIVS due by midnight, January 2nd',
          'mivs/game_preflight.txt',
          lambda game: game.confirmed,
          ident='mivs_game_preflight_reminder')

MIVSEmail(IndieGame, 'MIVS 2018: Hotel and selling signups',
          'mivs/2018_hotel_info.txt',
          lambda game: game.confirmed,
          ident='2018_hotel_info')

MIVSEmail(IndieGame, 'MIVS 2018: November Updates & info',
          'mivs/2018_email_blast.txt',
          lambda game: game.confirmed,
          ident='2018_email_blast')

MIVSEmail(IndieGame, 'Summary of judging feedback for your game',
          'mivs/reviews_summary.html',
          lambda game: game.status in c.FINAL_MIVS_GAME_STATUSES and game.reviews_to_email,
          ident='mivs_reviews_summary',
          post_con=True)

MIVSEmail(IndieGame, 'MIVS judging is wrapping up',
          'mivs/round_two_closing.txt',
          lambda game: game.submitted, when=days_before(14, c.MIVS_JUDGING_DEADLINE),
          ident='mivs_round_two_closing')

MIVSEmail(IndieJudge, 'MIVS Judging is about to begin!',
          'mivs/judge_intro.txt',
          ident='mivs_judge_intro')

MIVSEmail(IndieJudge, 'MIVS Judging has begun!',
          'mivs/judging_begun.txt',
          ident='mivs_judging_has_begun')

MIVSEmail(IndieJudge, 'MIVS Judging is almost over!',
          'mivs/judging_reminder.txt',
          when=days_before(7, c.SOFT_MIVS_JUDGING_DEADLINE),
          ident='mivs_judging_due_reminder')

MIVSEmail(IndieJudge, 'Reminder: MIVS Judging due by {}'.format(c.MIVS_JUDGING_DEADLINE.strftime('%B %-d')),
          'mivs/final_judging_reminder.txt',
          lambda judge: not judge.judging_complete,
          when=days_before(5, c.MIVS_JUDGING_DEADLINE),
          ident='mivs_judging_due_reminder_last_chance')

MIVSEmail(IndieJudge, 'MIVS Judging and {EVENT_NAME} Staffing',
          'mivs/judge_staffers.txt',
          ident='mivs_judge_staffers')

MIVSEmail(IndieJudge, 'MIVS Judge badge information',
          'mivs/judge_badge_info.txt',
          ident='mivs_judge_badge_info')

MIVSEmail(IndieJudge, 'MIVS Judging about to begin',
          'mivs/judge_2016.txt',
          ident='mivs_selected_to_judge')

MIVSEmail(IndieJudge, 'MIVS Judges: A Request for our MIVSY awards',
          'mivs/2018_mivsy_request.txt',
          ident='2018_mivsy_request')

MIVSEmail(IndieGame, 'MIVS: 2018 MIVSY Awards happening on January 6th, 7pm ',
          'mivs/2018_indie_mivsy_explination.txt',
          lambda game: game.confirmed,
          ident='2018_indie_mivsy_explination')

MIVSEmail(IndieGame, 'MIVS: December updates ',
          'mivs/2018_december_updates.txt',
          lambda game: game.confirmed,
          ident='2018_december_updates')

MIVSEmail(IndieGame, 'Thanks for Being part of MIVS 2018 - A Request for Feedback',
          'mivs/2018_feedback.txt',
          lambda game: game.confirmed,
          ident='2018_mivs_post_event_feedback',
          post_con=True)


# =============================
# mits
# =============================

class MITSEmail(AutomatedEmail):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('sender', c.MITS_EMAIL)
        AutomatedEmail.__init__(self, MITSTeam, *args, **kwargs)


# We wait an hour before sending out this email because the most common case
# of someone registering their team is that they'll immediately fill out the
# entire application, so there's no reason to send them an email showing their
# currently completion percentage when that info will probably be out of date
# by the time they read it.  By waiting an hour, we ensure this doesn't happen.
MITSEmail('Thanks for showing an interest in MITS!',
          'mits/mits_registered.txt',
          lambda team: not team.submitted and team.applied < datetime.now(UTC) - timedelta(hours=1),
          ident='mits_application_created')

# For similar reasons to the above, we wait at least 6 hours before sending this
# email because it would seem silly to immediately send someone a "last chance"
# email the minute they registered their team.  By waiting 6 hours, we wait
# until they've had a chance to complete the application and even receive the
# initial reminder email above before being pestered with this warning.
MITSEmail('Last chance to complete your MITS application!',
          'mits/mits_reminder.txt',
          lambda team: not team.submitted and team.applied < datetime.now(UTC) - timedelta(hours=6),
          when=days_before(3, c.MITS_SUBMISSION_DEADLINE),
          ident='mits_reminder')

MITSEmail('Thanks for submitting your MITS application!',
          'mits/mits_submitted.txt',
          lambda team: team.submitted,
          ident='mits_application_submitted')

MITSEmail('Please fill out the remainder of your MITS application',
          'mits/mits_preaccepted.txt',
          lambda team: team.accepted and team.completion_percentage < 100,
          ident='mits_preaccepted_incomplete')

MITSEmail('MITS initial panel information',
          'mits/mits_initial_panel_info.txt',
          lambda team: team.accepted and team.panel_interest,
          ident='mits_initial_panel_info')

# TODO: emails we still need to configure include but are not limited to:
# -> when teams have been accepted
# -> when teams have been declined
# -> when accepted teams have added people who have not given their hotel info
# -> final pre-event informational email


# =============================
# panels
# =============================

class PanelAppEmail(AutomatedEmail):
    def __init__(self, subject, template, filter, ident, **kwargs):
        AutomatedEmail.__init__(self, PanelApplication, subject,
                                template,
                                lambda app: filter(app) and (
                                    not app.submitter or
                                    not app.submitter.attendee_id or
                                    app.submitter.attendee.badge_type != c.GUEST_BADGE),
                                ident,
                                sender=c.PANELS_EMAIL,
                                **kwargs)

    def computed_subject(self, x):
        return self.subject.replace('<PANEL_NAME>', x.name)


PanelAppEmail('Your {EVENT_NAME} Panel Application Has Been Received: <PANEL_NAME>',
              'panels/panel_app_confirmation.txt',
              lambda a: True,
              needs_approval=False,
              ident='panel_received')

PanelAppEmail('Your {EVENT_NAME} Panel Application Has Been Accepted: <PANEL_NAME>',
              'panels/panel_app_accepted.txt',
              lambda app: app.status == c.ACCEPTED,
              ident='panel_accepted')

PanelAppEmail('Your {EVENT_NAME} Panel Application Has Been Declined: <PANEL_NAME>',
              'panels/panel_app_declined.txt',
              lambda app: app.status == c.DECLINED,
              ident='panel_declined')

PanelAppEmail('Your {EVENT_NAME} Panel Application Has Been Waitlisted: <PANEL_NAME>',
              'panels/panel_app_waitlisted.txt',
              lambda app: app.status == c.WAITLISTED,
              ident='panel_waitlisted')

PanelAppEmail('Your {EVENT_NAME} Panel Has Been Scheduled: <PANEL_NAME>',
              'panels/panel_app_scheduled.txt',
              lambda app: app.event_id,
              ident='panel_scheduled')

AutomatedEmail(Attendee, 'Your {EVENT_NAME} Event Schedule',
               'panels/panelist_schedule.txt',
               lambda a: a.badge_type != c.GUEST_BADGE and a.assigned_panelists,
               ident='event_schedule',
               sender=c.PANELS_EMAIL)


# =============================
# guests
# =============================

class BandEmail(AutomatedEmail):
    def __init__(self, subject, template, filter, ident, **kwargs):
        AutomatedEmail.__init__(self, GuestGroup, subject,
                                template,
                                lambda b: b.group_type == c.BAND and filter(b),
                                ident,
                                sender=c.BAND_EMAIL,
                                **kwargs)


class GuestEmail(AutomatedEmail):
    def __init__(self, subject, template, filter, ident, **kwargs):
        AutomatedEmail.__init__(self, GuestGroup, subject,
                                template,
                                lambda b: b.group_type == c.GUEST and filter(b),
                                ident,
                                sender=c.GUEST_EMAIL,
                                **kwargs)


AutomatedEmail(GuestGroup, '{EVENT_NAME} Performer Checklist',
               'guests/band_notification.txt',
               lambda b: b.group_type == c.BAND, sender=c.BAND_EMAIL,
               ident='band_checklist_inquiry')

BandEmail('Last chance to apply for a {EVENT_NAME} Panel',
          'guests/band_panel_reminder.txt',
          lambda b: not b.panel_status,
          when=days_before(3, c.BAND_PANEL_DEADLINE),
          ident='band_panel_reminder')

BandEmail('Last Chance to accept your offer to perform at {EVENT_NAME}',
          'guests/band_agreement_reminder.txt',
          lambda b: not b.info_status,
          when=days_before(3, c.BAND_INFO_DEADLINE),
          ident='band_agreement_reminder')

BandEmail('Last chance to include your bio info on the {EVENT_NAME} website',
          'guests/band_bio_reminder.txt',
          lambda b: not b.bio_status,
          when=days_before(3, c.BAND_BIO_DEADLINE),
          ident='band_bio_reminder')

BandEmail('{EVENT_NAME} W9 reminder',
          'guests/band_w9_reminder.txt',
          lambda b: b.payment and not b.taxes_status,
          when=days_before(3, c.BAND_TAXES_DEADLINE),
          ident='band_w9_reminder')

BandEmail('Last chance to sign up for selling merchandise at {EVENT_NAME}',
          'guests/band_merch_reminder.txt',
          lambda b: not b.merch_status,
          when=days_before(3, c.BAND_MERCH_DEADLINE),
          ident='band_merch_reminder')

BandEmail('{EVENT_NAME} charity auction reminder',
          'guests/band_charity_reminder.txt',
          lambda b: not b.charity_status,
          when=days_before(3, c.BAND_CHARITY_DEADLINE),
          ident='band_charity_reminder')

BandEmail('{EVENT_NAME} stage plot reminder',
          'guests/band_stage_plot_reminder.txt',
          lambda b: not b.stage_plot_status,
          when=days_before(3, c.BAND_STAGE_PLOT_DEADLINE),
          ident='band_stage_plot_reminder')

AutomatedEmail(GuestGroup, 'It\'s time to send us your info for {EVENT_NAME}!',
               'guests/guest_checklist_announce.html',
               lambda g: g.group_type == c.GUEST,
               ident='guest_checklist_inquiry',
               sender=c.GUEST_EMAIL)

GuestEmail('Reminder: Please complete your Guest Checklist for {EVENT_NAME}!',
           'guests/guest_checklist_reminder.html',
           lambda g: not g.checklist_completed,
           when=days_before(7, c.GUEST_BIO_DEADLINE - timedelta(days=7)),
           ident='guest_reminder_1')

GuestEmail('Have you forgotten anything? Your {EVENT_NAME} Guest Checklist needs you!',
           'guests/guest_checklist_reminder.html',
           lambda g: not g.checklist_completed,
           when=days_before(7, c.GUEST_BIO_DEADLINE),
           ident='guest_reminder_2')
