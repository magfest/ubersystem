"""
IMPORTANT NOTES FOR CHANGING/ADDING EMAIL CATEGORIES:

'ident' is a unique ID for that email category that must not change after
emails in that category have started to send.

*****************************************************************************
IF YOU CHANGE THE IDENT FOR A CATEGORY, IT WILL CAUSE ANY EMAILS THAT HAVE
ALREADY SENT FOR THAT CATEGORY TO RE-SEND.
*****************************************************************************

"""

import os
import jinja2
from datetime import datetime, timedelta
import pathlib

from pockets import listify
from pytz import UTC
from sqlalchemy.orm import joinedload, subqueryload

from uber.config import c
from uber import decorators
from uber.jinja import JinjaEnv
from uber.models import (AdminAccount, Attendee, AttendeeAccount, ArtShowApplication, AutomatedEmail, Department,
                         Group, GuestGroup, IndieGame, IndieJudge, IndieStudio, MarketplaceApplication, MITSTeam,
                         MITSApplicant, PanelApplication, PanelApplicant, PromoCodeGroup, Room, RoomAssignment, Shift)
from uber.utils import after, before, days_after, days_before, days_between, localized_now, DeptChecklistConf


class AutomatedEmailFixture:
    """
    Represents one category of emails that we send out.
    An example of an email category would be "Your registration has been confirmed".
    """

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
        AttendeeAccount: lambda session: session.query(AttendeeAccount).options(
            subqueryload(AttendeeAccount.attendees)),
        Group: lambda session: session.query(Group).options(
            subqueryload(Group.attendees)).order_by(Group.id),
        PromoCodeGroup: lambda session: session.query(PromoCodeGroup).options(
            subqueryload(PromoCodeGroup.buyer)).order_by(PromoCodeGroup.id),
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
        MITSApplicant: lambda session: session.query(MITSApplicant).options(
            subqueryload(MITSApplicant.attendee),
            subqueryload(MITSApplicant.team)),
        PanelApplication: lambda session: session.query(PanelApplication).options(
            subqueryload(PanelApplication.applicants).subqueryload(PanelApplicant.attendee)
            ).order_by(PanelApplication.id),
        GuestGroup: lambda session: session.query(GuestGroup).options(joinedload(GuestGroup.group))
    }

    def __init__(
            self,
            model,
            subject,
            template,
            filter,
            ident,
            *,
            query=(),
            query_options=(),
            when=(),
            sender=None,
            cc=(),
            bcc=(),
            needs_approval=True,
            allow_at_the_con=False,
            allow_post_con=False,
            extra_data=None):

        assert ident, 'AutomatedEmail ident may not be empty.'
        assert ident not in AutomatedEmail._fixtures, 'AutomatedEmail ident "{}" already registered.'.format(ident)

        AutomatedEmail._fixtures[ident] = self

        self.model = model
        self.subject = subject \
            .replace('{EVENT_NAME}', c.EVENT_NAME) \
            .replace('{EVENT_YEAR}', c.EVENT_YEAR) \
            .replace('{EVENT_DATE}', c.EPOCH.strftime('%b %Y'))
        self.template = template
        self.format = 'text' if template.endswith('.txt') else 'html'
        self.filter = lambda x: (x.gets_emails and filter(x))
        self.ident = ident
        self.query = listify(query)
        self.query_options = listify(query_options)
        self.sender = sender or c.REGDESK_EMAIL
        self.cc = listify(cc)
        self.bcc = listify(bcc)
        self.needs_approval = needs_approval
        self.allow_at_the_con = allow_at_the_con
        self.allow_post_con = allow_post_con
        self.extra_data = extra_data or {}

        when = listify(when)

        after = [d.active_after for d in when if d.active_after]
        self.active_after = min(after) if after else None

        before = [d.active_before for d in when if d.active_before]
        self.active_before = max(before) if before else None

        self.template_plugin_name = ""
        self.template_url = ""

    def update_template_plugin_info(self):
        env = JinjaEnv.env()
        try:
            template_path = pathlib.Path(env.get_or_select_template(os.path.join('emails', self.template)).filename)
            self.template_plugin_name = template_path.parts[3]
            self.template_url = (f"https://github.com/magfest/{self.template_plugin_name}/tree/main/"
                                 f"{self.template_plugin_name}/{pathlib.Path(*template_path.parts[5:]).as_posix()}")
        except jinja2.exceptions.TemplateNotFound:
            self.template_plugin_name = "ERROR: TEMPLATE NOT FOUND"
            self.template_url = ""
        return self.template_plugin_name, self.template_url

    def update_subject_line(self, subject):
        self.subject = subject \
            .replace('{EVENT_NAME}', c.EVENT_NAME) \
            .replace('{EVENT_YEAR}', c.EVENT_YEAR) \
            .replace('{EVENT_DATE}', c.EPOCH.strftime('%b %Y'))

        AutomatedEmail._fixtures[self.ident] = self

    @property
    def body(self):
        return decorators.render_empty(os.path.join('emails', self.template))


# Payment reminder emails, including ones for groups, which are always safe to be here, since they just
# won't get sent if group registration is turned off.

AutomatedEmailFixture(
    Attendee,
    '{EVENT_NAME} registration confirmed',
    'reg_workflow/attendee_confirmation.html',
    lambda a: (a.paid == c.HAS_PAID and not a.promo_code_groups) or
              (a.paid == c.NEED_NOT_PAY and (a.confirmed or a.promo_code_id)),
    # query=Attendee.paid == c.HAS_PAID,
    needs_approval=False,
    allow_at_the_con=True,
    ident='attendee_badge_confirmed')

if c.ATTENDEE_ACCOUNTS_ENABLED:
    AutomatedEmailFixture(
        AttendeeAccount,
        '{EVENT_NAME} account creation confirmed',
        'reg_workflow/account_confirmation.html',
        lambda a: not a.imported and a.hashed and not a.password_reset and not a.is_sso_account,
        needs_approval=False,
        allow_at_the_con=True,
        ident='attendee_account_confirmed')

AutomatedEmailFixture(
    PromoCodeGroup,
    '{EVENT_NAME} group registration successful',
    'reg_workflow/promo_code_group_confirmation.html',
    lambda g: g.buyer and g.buyer.amount_paid > 0,
    needs_approval=False,
    allow_at_the_con=True,
    ident='pc_group_payment_received')

AutomatedEmailFixture(
    Group,
    '{EVENT_NAME} group payment received',
    'reg_workflow/group_confirmation.html',
    lambda g: g.amount_paid == g.cost * 100 and g.cost != 0 and g.leader_id,
    # query=and_(Group.amount_paid >= Group.cost, Group.cost > 0, Group.leader_id != None),
    needs_approval=False,
    ident='group_payment_received')

AutomatedEmailFixture(
    Attendee,
    '{EVENT_NAME} group registration confirmed',
    'reg_workflow/attendee_confirmation.html',
    lambda a: a.group and (a.id != a.group.leader_id or a.group.cost == 0) and not a.placeholder,
    # query=and_(
    #     Attendee.placeholder == False,
    #     Attendee.group_id != None,
    #     or_(Attendee.id != Group.leader_id, Group.cost == 0)),
    needs_approval=False,
    allow_at_the_con=True,
    ident='attendee_group_reg_confirmation')

AutomatedEmailFixture(
    Attendee,
    '{EVENT_NAME} merch pre-order received',
    'reg_workflow/group_donation.txt',
    lambda a: a.paid == c.PAID_BY_GROUP and a.amount_extra and a.amount_paid >= (a.amount_extra * 100),
    # query=and_(
    #     Attendee.paid == c.PAID_BY_GROUP,
    #     Attendee.amount_extra != 0,
    #     Attendee.amount_paid >= Attendee.amount_extra),
    needs_approval=False,
    sender=c.MERCH_EMAIL,
    ident='group_extra_payment_received')


# Reminder emails for groups to allocated their unassigned badges.  These emails are safe to be turned on for
# all events, because they will only be sent for groups with unregistered badges, so if group preregistration
# has been turned off, they'll just never be sent.

AutomatedEmailFixture(
    Group,
    'Reminder to pre-assign {EVENT_NAME} group badges',
    'reg_workflow/group_preassign_reminder.txt',
    lambda g: (
        c.BEFORE_GROUP_PREREG_TAKEDOWN
        and days_after(30, g.registered)()
        and g.unregistered_badges
        and not g.is_dealer),
    # query=and_(
    #     Group.unregistered_badges == True,
    #     Group.is_dealer == False,
    #     Group.registered < (func.now() - timedelta(days=30))),
    when=before(c.GROUP_PREREG_TAKEDOWN),
    needs_approval=False,
    ident='group_preassign_badges_reminder',
    sender=c.REGDESK_EMAIL)

AutomatedEmailFixture(
    Group,
    'Last chance to pre-assign {EVENT_NAME} group badges',
    'reg_workflow/group_preassign_reminder.txt',
    lambda g: (
      c.AFTER_GROUP_PREREG_TAKEDOWN
      and g.unregistered_badges
      and (not g.is_dealer or g.status == c.APPROVED)),
    # query=and_(
    #     Group.unregistered_badges == True,
    #     or_(Group.is_dealer == False, Group.status == c.APPROVED)),
    when=after(c.GROUP_PREREG_TAKEDOWN),
    needs_approval=False,
    allow_at_the_con=True,
    ident='group_preassign_badges_reminder_last_chance',
    sender=c.REGDESK_EMAIL)


# =============================
# art show
# =============================
AutomatedEmailFixture.queries.update({
    ArtShowApplication:
        lambda session: session.query(ArtShowApplication).options(subqueryload(ArtShowApplication.attendee))
})


class ArtShowAppEmailFixture(AutomatedEmailFixture):
    def __init__(self, subject, template, filter, ident, **kwargs):
        AutomatedEmailFixture.__init__(self, ArtShowApplication, subject,
                                       template,
                                       lambda app: True and filter(app),
                                       ident,
                                       sender=c.ART_SHOW_EMAIL, **kwargs)


if c.ART_SHOW_ENABLED:
    ArtShowAppEmailFixture(
        '{EVENT_NAME} Art Show Application Confirmation',
        'art_show/application.html',
        lambda a: a.status == c.UNAPPROVED,
        ident='art_show_confirm')

    ArtShowAppEmailFixture(
        'Your {EVENT_NAME} Art Show application has been approved',
        'art_show/approved.html',
        lambda a: a.status == c.APPROVED,
        ident='art_show_approved')

    ArtShowAppEmailFixture(
        'Your {EVENT_NAME} Art Show application has been waitlisted',
        'art_show/waitlisted.txt',
        lambda a: a.status == c.WAITLISTED,
        ident='art_show_waitlisted')

    ArtShowAppEmailFixture(
        'Your {EVENT_NAME} Art Show application has been declined',
        'art_show/declined.txt',
        lambda a: a.status == c.DECLINED,
        ident='art_show_declined')

    ArtShowAppEmailFixture(
        'Your {EVENT_NAME} Art Show payment has been received',
        'art_show/payment_confirmation.txt',
        lambda a: a.status == c.APPROVED and a.amount_paid,
        ident='art_show_payment_received'
    )

    ArtShowAppEmailFixture(
        'Reminder to pay for your {EVENT_NAME} Art Show application',
        'art_show/payment_reminder.txt',
        lambda a: a.status == c.APPROVED and a.is_unpaid,
        when=days_between((14, c.ART_SHOW_PAYMENT_DUE), (1, c.EPOCH)),
        ident='art_show_payment_reminder')

    ArtShowAppEmailFixture(
        '{EVENT_NAME} Art Show piece entry needed',
        'art_show/pieces_reminder.txt',
        lambda a: a.status == c.APPROVED and not a.is_unpaid and not a.art_show_pieces,
        when=days_before(15, c.EPOCH),
        ident='art_show_pieces_reminder')

    ArtShowAppEmailFixture(
        'Reminder to assign an agent for your {EVENT_NAME} Art Show application',
        'art_show/agent_reminder.html',
        lambda a: a.status == c.APPROVED and not a.is_unpaid and a.delivery_method == c.AGENT and not a.agent,
        when=after(c.EVENT_TIMEZONE.localize(datetime(int(c.EVENT_YEAR), 11, 1))),
        ident='art_show_agent_reminder')

    ArtShowAppEmailFixture(
        '{EVENT_NAME} Art Show MAIL IN Instructions',
        'art_show/mailing_in.html',
        lambda a: a.status == c.APPROVED and not a.is_unpaid and a.delivery_method == c.BY_MAIL,
        when=days_between((c.ART_SHOW_REG_START, 13), (16, c.ART_SHOW_WAITLIST)),
        ident='art_show_mail_in')


# =============================
# marketplace
# =============================
AutomatedEmailFixture.queries.update({
    MarketplaceApplication:
        lambda session: session.query(MarketplaceApplication).options(subqueryload(MarketplaceApplication.attendee))
})


class MarketplaceAppEmailFixture(AutomatedEmailFixture):
    def __init__(self, subject, template, filter, ident, **kwargs):
        AutomatedEmailFixture.__init__(self, MarketplaceApplication, subject,
                                       template,
                                       lambda app: True and filter(app),
                                       ident,
                                       sender=c.MARKETPLACE_APP_EMAIL, **kwargs)


if c.MARKETPLACE_REG_START:
    MarketplaceAppEmailFixture(
        '{EVENT_NAME} Marketplace Application Confirmation',
        'marketplace/application.html',
        lambda a: a.status == c.UNAPPROVED,
        ident='marketplace_confirm')

    MarketplaceAppEmailFixture(
        'Your {EVENT_NAME} Marketplace application has been approved',
        'marketplace/approved.html',
        lambda a: a.status == c.APPROVED,
        ident='marketplace_approved')

    MarketplaceAppEmailFixture(
        'Your {EVENT_NAME} Marketplace application has been waitlisted',
        'marketplace/waitlisted.txt',
        lambda a: a.status == c.WAITLISTED,
        ident='marketplace_waitlisted')

    MarketplaceAppEmailFixture(
        'Your {EVENT_NAME} Marketplace application has been declined',
        'marketplace/declined.txt',
        lambda a: a.status == c.DECLINED,
        ident='marketplace_declined')

    MarketplaceAppEmailFixture(
        'Reminder to pay for your {EVENT_NAME} Marketplace application',
        'marketplace/payment_reminder.txt',
        lambda a: a.status == c.APPROVED and a.amount_unpaid,
        when=days_before(14, c.MARKETPLACE_PAYMENT_DUE),
        ident='marketplace_payment_reminder')


# Dealer emails; these are safe to be turned on for all events because even if the event doesn't have dealers,
# none of these emails will be sent unless someone has applied to be a dealer, which they cannot do until
# dealer registration has been turned on.

class MarketplaceEmailFixture(AutomatedEmailFixture):
    def __init__(self, subject, template, filter, ident, **kwargs):
        AutomatedEmailFixture.__init__(
            self,
            Group,
            subject,
            template,
            lambda g: g.is_dealer and filter(g),
            ident,
            # query=[Group.is_dealer == False] + listify(query),
            sender=c.MARKETPLACE_EMAIL,
            **kwargs)


if c.DEALER_REG_START:

    MarketplaceEmailFixture(
        'Your {} {} has been approved'.format(c.EVENT_NAME, c.DEALER_APP_TERM.capitalize()),
        'dealers/approved.html',
        lambda g: g.status == c.APPROVED,
        # query=Group.status == c.APPROVED,
        needs_approval=True,
        ident='dealer_reg_approved')

    if c.SIGNNOW_DEALER_TEMPLATE_ID:
        MarketplaceEmailFixture(
            'Please complete your {} {}!'.format(c.EVENT_NAME, c.DEALER_APP_TERM.capitalize()),
            'dealers/signnow_request.html',
            lambda g: g.status == c.APPROVED and c.SIGNNOW_DEALER_TEMPLATE_ID and not g.signnow_document_signed,
            needs_approval=True,
            ident='dealer_signnow_email')

    MarketplaceEmailFixture(
        'Reminder to pay for your {} {}'.format(c.EVENT_NAME, c.DEALER_REG_TERM.capitalize()),
        'dealers/payment_reminder.txt',
        lambda g: g.status == c.APPROVED and days_after(30, g.approved)() and g.is_unpaid,
        # query=and_(
        #     Group.status == c.APPROVED,
        #     Group.approved < (func.now() - timedelta(days=30)),
        #     Group.is_unpaid == True),
        when=days_before(60, c.DEALER_PAYMENT_DUE, 7),
        needs_approval=True,
        ident='dealer_reg_payment_reminder')

    MarketplaceEmailFixture(
        'Your {} ({}) {} is due in one week'.format(c.EVENT_NAME,
                                                    c.EPOCH.strftime('%b %Y'),
                                                    c.DEALER_REG_TERM.capitalize()),
        'dealers/payment_reminder.txt',
        lambda g: g.status == c.APPROVED and g.is_unpaid,
        # query=and_(Group.status == c.APPROVED, Group.is_unpaid == True),
        when=days_before(7, c.DEALER_PAYMENT_DUE, 2),
        needs_approval=True,
        ident='dealer_reg_payment_reminder_due_soon')

    MarketplaceEmailFixture(
        'Last chance to pay for your {} ({}) {}'.format(c.EVENT_NAME,
                                                        c.EPOCH.strftime('%b %Y'),
                                                        c.DEALER_REG_TERM.capitalize()),
        'dealers/payment_reminder.txt',
        lambda g: g.status == c.APPROVED and g.is_unpaid,
        # query=and_(Group.status == c.APPROVED, Group.is_unpaid == True),
        when=days_before(2, c.DEALER_PAYMENT_DUE),
        needs_approval=True,
        ident='dealer_reg_payment_reminder_last_chance')


# Placeholder badge emails; when an admin creates a "placeholder" badge, we send an email asking them to fill in the
# rest of their information. We also send two reminder emails before the placeholder deadline explaining that the
# badge must be explicitly accepted or we'll assume the person isn't coming.
#
# We usually import a bunch of last year's staffers before preregistration goes live with placeholder badges, so there's
# a special email for those people, which is basically the same as the normal email except it includes a special thanks
# message. We identify those people by checking for volunteer placeholders which were created before prereg opens.
#
# These emails are safe to be turned on for all events because none of them are sent unless an administrator explicitly
# creates a "placeholder" registration.

class StopsEmailFixture(AutomatedEmailFixture):
    def __init__(self, subject, template, filter, ident, **kwargs):
        AutomatedEmailFixture.__init__(
            self,
            Attendee,
            subject,
            template,
            lambda a: a.staffing and filter(a),
            ident,
            # query=[Attendee.staffing == True] + listify(query),
            sender=c.STAFF_EMAIL,
            **kwargs)


# TODO: Refactor all this into something less lazy
def deferred_attendee_placeholder(a): return a.placeholder and (a.registered_local <= min(c.PREREG_OPEN,
                                                                                          c.DEALER_REG_START)
                                                                and a.badge_type == c.ATTENDEE_BADGE
                                                                and a.paid == c.NEED_NOT_PAY
                                                                and "staff import".lower() not in a.admin_notes.lower()
                                                                and not a.admin_account)


def panelist_placeholder(a): return a.placeholder and c.PANELIST_RIBBON in a.ribbon_ints


def guest_placeholder(a): return a.placeholder and a.badge_type == c.GUEST_BADGE and (
            not a.group
            or a.group.guest
            and a.group.guest.group_type == c.GUEST)


def band_placeholder(a): return a.placeholder and a.badge_type == c.GUEST_BADGE and (
            not a.group
            or a.group.guest
            and a.group.guest.group_type == c.BAND)


def dealer_placeholder(a): return a.placeholder and a.is_dealer and a.group.status == c.APPROVED


def staff_import_placeholder(a): return a.placeholder and (a.registered_local <= c.PREREG_OPEN
                                                           and (a.admin_account or
                                                                "staff import".lower() in a.admin_notes.lower()))


def volunteer_placeholder(a): return a.placeholder and a.registered_local > c.PREREG_OPEN
# a.staffing provided by StopsEmailFixture


# TODO: Add an email for MIVS judges, an email for non-Guest or Band guest group badges,
# and an email for group-leader-created badges
def generic_placeholder(a): return a.placeholder and (c.AT_THE_CON or not panelist_placeholder(a)
                                                      and not band_placeholder(a)
                                                      and not guest_placeholder(a)
                                                      and not dealer_placeholder(a)
                                                      and a.registered_local > min(c.PREREG_OPEN,
                                                                                   c.DEALER_REG_START)
                                                      and not volunteer_placeholder(a))


AutomatedEmailFixture(
    Attendee,
    'Claim your badge for {EVENT_NAME} {EVENT_YEAR}!',
    'placeholders/regular.txt',
    lambda a: generic_placeholder(a) and a.paid == c.NEED_NOT_PAY,
    sender=c.CONTACT_EMAIL,
    needs_approval=False,
    allow_at_the_con=True,
    ident='generic_badge_confirmation_comped')

AutomatedEmailFixture(
    Attendee,
    'Please complete your {EVENT_NAME} {EVENT_YEAR} registration',
    'placeholders/regular.txt',
    lambda a: generic_placeholder(a) and a.paid != c.NEED_NOT_PAY,
    sender=c.CONTACT_EMAIL,
    needs_approval=False,
    allow_at_the_con=True,
    ident='generic_badge_confirmation')

AutomatedEmailFixture(
    Attendee,
    'Claim your deferred badge for {EVENT_NAME} {EVENT_YEAR}!',
    'placeholders/deferred.html',
    deferred_attendee_placeholder,
    when=after(c.PREREG_OPEN),
    ident='claim_deferred_badge')

AutomatedEmailFixture(
    Attendee,
    'Claim your Panelist badge for {EVENT_NAME} {EVENT_YEAR}',
    'placeholders/panelist.txt',
    panelist_placeholder,
    sender=c.PANELS_EMAIL,
    ident='panelist_badge_confirmation')

AutomatedEmailFixture(
    Attendee,
    'Claim your Guest badge for {EVENT_NAME} {EVENT_YEAR}',
    'placeholders/guest.txt',
    guest_placeholder,
    # query=and_(Attendee.placeholder == True, Attendee.badge_type == c.GUEST_BADGE),
    sender=c.GUEST_EMAIL,
    ident='guest_badge_confirmation')

AutomatedEmailFixture(
    Attendee,
    'Claim your performer badge for {EVENT_NAME} {EVENT_YEAR}',
    'placeholders/band.txt',
    band_placeholder,
    sender=c.BAND_EMAIL,
    ident='band_badge_confirmation')

AutomatedEmailFixture(
    Attendee,
    f'{c.EVENT_NAME} {c.DEALER_TERM.title()} information required',
    'placeholders/dealer.txt',
    dealer_placeholder,
    # query=and_(
    #     Attendee.placeholder == True,
    #     Attendee.paid == c.PAID_BY_GROUP,
    #     Group.id == Attendee.group_id,
    #     Group.is_dealer == True,
    #     Group.status == c.APPROVED))),
    sender=c.MARKETPLACE_EMAIL,
    ident='dealer_info_required')

StopsEmailFixture(
    'Claim your Staff badge for {EVENT_NAME} {EVENT_YEAR}!',
    'placeholders/imported_volunteer.txt',
    staff_import_placeholder,
    ident='volunteer_again_inquiry')

StopsEmailFixture(
    'Claim your Volunteer badge for {EVENT_NAME} {EVENT_YEAR}',
    'placeholders/volunteer.txt',
    lambda a: volunteer_placeholder(a),
    ident='volunteer_badge_confirmation')

AutomatedEmailFixture(
    Attendee,
    '{EVENT_NAME} Badge Confirmation Reminder',
    'placeholders/reminder.txt',
    lambda a: days_after(7, a.registered)() and a.placeholder and not a.is_dealer,
    ident='badge_confirmation_reminder')

AutomatedEmailFixture(
    Attendee,
    'Last Chance to Accept Your {EVENT_NAME} ({EVENT_DATE}) Badge',
    'placeholders/reminder.txt',
    lambda a: a.placeholder and not a.is_dealer,
    when=days_before(7, c.PLACEHOLDER_DEADLINE if c.PLACEHOLDER_DEADLINE else c.UBER_TAKEDOWN),
    ident='badge_confirmation_reminder_last_chance')


# Volunteer emails; none of these will be sent unless VOLUNTEER_CHECKLIST_OPEN is set.

StopsEmailFixture(
    'Please complete your {EVENT_NAME} Staff/Volunteer Checklist',
    'shifts/created.txt',
    lambda a: a.staffing,
    when=after(c.VOLUNTEER_CHECKLIST_OPEN),
    allow_at_the_con=True,
    ident='volunteer_checklist_completion_request')

StopsEmailFixture(
    '{EVENT_NAME} ({EVENT_DATE}) shifts are live!',
    'shifts/shifts_created.txt',
    lambda a: (
        c.AFTER_SHIFTS_CREATED
        and a.badge_type != c.CONTRACTOR_BADGE
        and a.takes_shifts
        and a.registered_local <= c.SHIFTS_CREATED),
    when=before(c.PREREG_TAKEDOWN),
    ident='volunteer_shift_signup_notification')

StopsEmailFixture(
    'Reminder to sign up for {EVENT_NAME} ({EVENT_DATE}) shifts',
    'shifts/reminder.txt',
    lambda a: (
        c.AFTER_SHIFTS_CREATED
        and a.badge_type != c.CONTRACTOR_BADGE
        and days_after(14, max(a.registered_local, c.SHIFTS_CREATED))()
        and a.takes_shifts
        and not a.shift_minutes),
    when=before(c.PREREG_TAKEDOWN),
    ident='volunteer_shift_signup_reminder')

StopsEmailFixture(
    'Last chance to sign up for {EVENT_NAME} ({EVENT_DATE}) shifts',
    'shifts/reminder.txt',
    lambda a: (c.AFTER_SHIFTS_CREATED and a.badge_type != c.CONTRACTOR_BADGE
               and (not c.PREREG_TAKEDOWN or c.BEFORE_PREREG_TAKEDOWN) and a.takes_shifts and not a.shift_minutes),
    when=days_before(10, c.EPOCH),
    ident='volunteer_shift_signup_reminder_last_chance')

StopsEmailFixture(
    'Still want to volunteer at {EVENT_NAME} ({EVENT_DATE})?',
    'shifts/volunteer_check.txt',
    lambda a: (
        c.VOLUNTEER_CHECKLIST_OPEN
        and a.badge_type != c.CONTRACTOR_BADGE
        and c.VOLUNTEER_RIBBON in a.ribbon_ints
        and a.takes_shifts
        and a.weighted_hours == 0),
    when=days_before(28, c.FINAL_EMAIL_DEADLINE),
    ident='volunteer_still_interested_inquiry')

StopsEmailFixture(
    'Your {EVENT_NAME} ({EVENT_DATE}) shift schedule',
    'shifts/schedule.html',
    lambda a: c.SHIFTS_CREATED and a.weighted_hours and a.badge_type != c.CONTRACTOR_BADGE,
    allow_at_the_con=True,
    when=days_before(1, c.FINAL_EMAIL_DEADLINE),
    ident='volunteer_shift_schedule')

StopsEmailFixture(
    'Please review your worked shifts for {EVENT_NAME}!',
    'shifts/shifts_worked.html',
    lambda a: (a.weighted_hours or a.nonshift_minutes) and a.badge_type != c.CONTRACTOR_BADGE,
    when=days_after(1, c.ESCHATON),
    ident='volunteer_shifts_worked',
    allow_post_con=True)

if c.VOLUNTEER_AGREEMENT_ENABLED:
    StopsEmailFixture(
        'Reminder: Please agree to terms of {EVENT_NAME} ({EVENT_DATE}) volunteer agreement',
        'staffing/volunteer_agreement.txt',
        lambda a: c.VOLUNTEER_CHECKLIST_OPEN and c.VOLUNTEER_AGREEMENT_ENABLED and not a.agreed_to_volunteer_agreement,
        when=days_before(45, c.FINAL_EMAIL_DEADLINE),
        ident='volunteer_agreement')


# For events with customized badges, these emails remind people to let us know what we want on their badges.  We have
# one email for our volunteers who haven't bothered to confirm they're coming yet (bleh) and one for everyone else.

if c.PRINTED_BADGE_DEADLINE:
    StopsEmailFixture(
        'Last chance to personalize your {EVENT_NAME} ({EVENT_DATE}) badge',
        'personalized_badges/volunteers.txt',
        lambda a: (a.staffing and a.badge_type in c.PREASSIGNED_BADGE_TYPES and a.placeholder
                   and a.badge_type != c.CONTRACTOR_BADGE),
        when=days_before(7, c.PRINTED_BADGE_DEADLINE),
        ident='volunteer_personalized_badge_reminder')

    if [badge_type for badge_type in c.PREASSIGNED_BADGE_TYPES if badge_type not in [c.STAFF_BADGE,
                                                                                     c.CONTRACTOR_BADGE]]:
        AutomatedEmailFixture(
            Attendee,
            'Personalized {EVENT_NAME} ({EVENT_DATE}) badges will be ordered next week',
            'personalized_badges/reminder.txt',
            lambda a: a.badge_type in c.PREASSIGNED_BADGE_TYPES and not a.placeholder,
            when=days_before(7, c.PRINTED_BADGE_DEADLINE),
            ident='personalized_badge_reminder')


# MAGFest requires signed and notarized parental consent forms for anyone under 18.  This automated email reminder to
# bring the consent form only happens if this feature is turned on by setting the CONSENT_FORM_URL config option.
AutomatedEmailFixture(
    Attendee,
    '{EVENT_NAME} ({EVENT_DATE}) parental consent form reminder',
    'reg_workflow/under_18_reminder.txt',
    lambda a: c.CONSENT_FORM_URL and a.age_group_conf['consent_form'] and days_after(14, a.registered)(),
    when=days_before(60, c.EPOCH),
    allow_at_the_con=True,
    ident='under_18_parental_consent_reminder')


# Emails sent out to all attendees who can check in. These emails contain useful information about the event and are
# sent close to the event start date.
AutomatedEmailFixture(
    Attendee,
    'Check in faster at {EVENT_NAME}',
    'reg_workflow/attendee_qrcode.html',
    lambda a: not a.is_not_ready_to_checkin and c.USE_CHECKIN_BARCODE,
    when=days_before(7, c.EPOCH),
    allow_at_the_con=True,
    ident='qrcode_for_checkin')


class DeptChecklistEmailFixture(AutomatedEmailFixture):
    def __init__(self, conf):
        when = [days_before(10, conf.deadline)]
        if conf.email_post_con:
            when.append(after(c.EPOCH))

        AutomatedEmailFixture.__init__(
            self,
            Attendee,
            '{EVENT_NAME} Department Checklist: ' + conf.name,
            'shifts/dept_checklist.txt',
            filter=lambda a: a.admin_account and any(
                not d.checklist_item_for_slug(conf.slug)
                for d in a.checklist_admin_depts),
            ident='department_checklist_{}'.format(conf.name),
            when=when,
            sender=c.STAFF_EMAIL,
            extra_data={'conf': conf},
            allow_post_con=conf.email_post_con)


for _conf in DeptChecklistConf.instances.values():
    DeptChecklistEmailFixture(_conf)


# =============================
# hotel
# =============================

if c.HOTELS_ENABLED:

    AutomatedEmailFixture(
        Attendee,
        'Want volunteer hotel room space at {EVENT_NAME}?',
        'hotel/hotel_rooms.txt',
        lambda a: (a.badge_type != c.CONTRACTOR_BADGE and a.hotel_eligible
                   and not a.hotel_requests and a.takes_shifts),
        sender=c.ROOM_EMAIL_SENDER,
        when=days_before(45, c.ROOM_DEADLINE, 14),
        ident='volunteer_hotel_room_inquiry')

    AutomatedEmailFixture(
        Attendee,
        'Reminder to sign up for {EVENT_NAME} hotel room space',
        'hotel/hotel_reminder.txt',
        lambda a: (a.badge_type != c.CONTRACTOR_BADGE and a.hotel_eligible
                   and not a.hotel_requests and a.takes_shifts),
        sender=c.ROOM_EMAIL_SENDER,
        when=days_before(14, c.ROOM_DEADLINE, 2),
        ident='hotel_sign_up_reminder')

    AutomatedEmailFixture(
        Attendee,
        'Last chance to sign up for {EVENT_NAME} hotel room space',
        'hotel/hotel_reminder.txt',
        lambda a: (a.badge_type != c.CONTRACTOR_BADGE and a.hotel_eligible
                   and not a.hotel_requests and a.takes_shifts),
        sender=c.ROOM_EMAIL_SENDER,
        when=days_before(2, c.ROOM_DEADLINE),
        ident='hotel_sign_up_reminder_last_chance')

    AutomatedEmailFixture(
        Attendee,
        'Reminder to meet your {EVENT_NAME} hotel room requirements',
        'hotel/hotel_hours.txt',
        lambda a: (a.badge_type != c.CONTRACTOR_BADGE and a.hotel_shifts_required
                   and a.weighted_hours < c.HOURS_FOR_HOTEL_SPACE),
        sender=c.ROOM_EMAIL_SENDER,
        when=days_before(14, c.FINAL_EMAIL_DEADLINE, 7),
        ident='hotel_requirements_reminder')

    AutomatedEmailFixture(
        Attendee,
        'Final reminder to meet your {EVENT_NAME} hotel room requirements',
        'hotel/hotel_hours.txt',
        lambda a: (a.badge_type != c.CONTRACTOR_BADGE and a.hotel_shifts_required
                   and a.weighted_hours < c.HOURS_FOR_HOTEL_SPACE),
        sender=c.ROOM_EMAIL_SENDER,
        when=days_before(7, c.FINAL_EMAIL_DEADLINE),
        ident='hotel_requirements_reminder_last_chance')

    AutomatedEmailFixture(
        Room,
        '{EVENT_NAME} Hotel Room Assignment',
        'hotel/room_assignment.txt',
        lambda r: r.locked_in,
        sender=c.ROOM_EMAIL_SENDER,
        ident='hotel_room_assignment')


# =============================
# mivs
# =============================

class MIVSEmailFixture(AutomatedEmailFixture):
    def __init__(self, *args, **kwargs):
        if len(args) < 4 and 'filter' not in kwargs:
            kwargs['filter'] = lambda x: True
        AutomatedEmailFixture.__init__(self, *args, sender=c.MIVS_EMAIL, **kwargs)


class MIVSGuestEmailFixture(AutomatedEmailFixture):
    def __init__(self, subject, template, filter, ident, **kwargs):
        AutomatedEmailFixture.__init__(
            self,
            GuestGroup,
            subject,
            template,
            lambda mg: mg.group_type == c.MIVS and mg.group.studio and filter(mg),
            ident,
            sender=c.MIVS_EMAIL,
            **kwargs)


if c.MIVS_ENABLED:

    MIVSEmailFixture(
        IndieStudio,
        'Your MIVS Studio Has Been Registered',
        'mivs/studio_registered.txt',
        ident='mivs_studio_registered')

    MIVSEmailFixture(
        IndieGame,
        'Your MIVS Game Has Been Submitted',
        'mivs/game_submitted.txt',
        lambda game: game.submitted,
        ident='mivs_game_submitted')

    MIVSEmailFixture(
        IndieGame,
        'MIVS: Your Submitted Video Is Broken',
        'mivs/video_broken.txt',
        lambda game: game.video_broken,
        ident='mivs_video_broken')

    MIVSEmailFixture(
        IndieGame,
        'Reminder to submit your game to MIVS',
        'mivs/submission_reminder.txt',
        lambda game: not game.submitted,
        ident='mivs_game_submission_reminder',
        when=days_before(7, c.MIVS_DEADLINE))

    MIVSEmailFixture(
        IndieGame,
        'Final Reminder to submit your game to MIVS',
        'mivs/submission_reminder.txt',
        lambda game: not game.submitted,
        ident='mivs_game_submission_final_reminder',
        when=days_before(2, c.MIVS_DEADLINE))

    MIVSEmailFixture(
        IndieGame,
        'Your game has been accepted into MIVS',
        'mivs/game_accepted.txt',
        lambda game: game.status == c.ACCEPTED and not game.waitlisted,
        ident='mivs_game_accepted')

    MIVSEmailFixture(
        IndieGame,
        'Your game has been accepted into MIVS from our waitlist',
        'mivs/game_accepted_from_waitlist.txt',
        lambda game: game.status == c.ACCEPTED and game.waitlisted,
        ident='mivs_game_accepted_from_waitlist')

    MIVSEmailFixture(
        IndieGame,
        'Your game application has been declined from MIVS',
        'mivs/game_declined.txt',
        lambda game: game.status == c.DECLINED,
        ident='mivs_game_declined')

    MIVSEmailFixture(
        IndieGame,
        'Your MIVS application has been waitlisted',
        'mivs/game_waitlisted.txt',
        lambda game: game.status == c.WAITLISTED,
        ident='mivs_game_waitlisted')

    MIVSEmailFixture(
        IndieGame,
        'MIVS {EVENT_YEAR} Waitlist: Additional Information Required',
        'mivs/waitlist_info.txt',
        lambda game: game.status == c.WAITLISTED,
        ident='mivs_waitlist_info'
    )

    MIVSEmailFixture(
        IndieGame,
        'Last chance to accept your MIVS booth',
        'mivs/game_accept_reminder.txt',
        lambda game: (
            game.status == c.ACCEPTED
            and not game.confirmed
            and (localized_now() + timedelta(days=2)) > game.studio.confirm_deadline),
        ident='mivs_accept_booth_reminder')

    MIVSEmailFixture(
        IndieGame,
        'Summary of judging feedback for your game',
        'mivs/reviews_summary.html',
        lambda game: game.status in c.FINAL_MIVS_GAME_STATUSES and game.reviews_to_email,
        ident='mivs_reviews_summary',
        allow_post_con=True)

    MIVSEmailFixture(
        IndieGame,
        'MIVS judging is wrapping up',
        'mivs/results_almost_ready.txt',
        lambda game: game.submitted, when=days_before(14, c.MIVS_JUDGING_DEADLINE),
        ident='mivs_results_almost_ready')

    MIVSEmailFixture(
        IndieJudge,
        'Welcome as a MIVS Judge!',
        'mivs/judging/judge_welcome.txt',
        ident='mivs_judge_welcome')

    MIVSEmailFixture(
        IndieJudge,
        'Reminder to update your MIVS Judge status',
        'mivs/judging/judge_welcome_reminder.txt',
        lambda judge: judge.status == c.UNCONFIRMED,
        ident='mivs_judge_welcome_reminder')

    MIVSEmailFixture(
        IndieJudge,
        'MIVS Judging is about to begin!',
        'mivs/judge_intro.txt',
        lambda judge: judge.status == c.CONFIRMED,
        ident='mivs_judge_intro')

    MIVSEmailFixture(
        IndieJudge,
        'MIVS Judging has begun!',
        'mivs/judging_begun.txt',
        lambda judge: judge.status == c.CONFIRMED,
        ident='mivs_judging_has_begun')

    MIVSEmailFixture(
        IndieJudge,
        'MIVS Judging is almost over!',
        'mivs/judging_reminder.txt',
        lambda judge: judge.status == c.CONFIRMED,
        when=days_before(7, c.SOFT_MIVS_JUDGING_DEADLINE),
        ident='mivs_judging_due_reminder')

    MIVSEmailFixture(
        IndieJudge,
        'Reminder: MIVS Judging due by {}'.format(c.MIVS_JUDGING_DEADLINE.strftime('%B %-d')),
        'mivs/judging_reminder.txt',
        lambda judge: not judge.judging_complete and judge.status == c.CONFIRMED,
        when=days_before(5, c.MIVS_JUDGING_DEADLINE),
        ident='mivs_judging_due_reminder_last_chance')

    MIVSEmailFixture(
        IndieJudge,
        'MIVS Judging survey and {EVENT_NAME} badge information',
        'mivs/judge_badge_info.txt',
        lambda judge: judge.status == c.CONFIRMED,
        ident='mivs_judge_badge_info')

    MIVSEmailFixture(
        IndieGame,
        'MIVS: Tournaments and Leaderboard Challenges',
        'mivs/confirmed/tournaments.txt',
        lambda game: game.confirmed,
        ident='mivs_tournaments'
    )

    MIVSGuestEmailFixture(
        '{EVENT_NAME} MIVS Checklist',
        'mivs/checklist_open.txt',
        lambda mg: True,
        ident='mivs_checklist_open'
    )

    MIVSGuestEmailFixture(
        'New {EVENT_NAME} MIVS Checklist Item: Update Studio and Game Information',
        'mivs/checklist/new_update_studio_information.txt',
        lambda mg: True,
        ident='mivs_checklist_update_studio_information'
    )

    MIVSGuestEmailFixture(
        'New {EVENT_NAME} MIVS Checklist Item: MIVS Indie Handbook',
        'mivs/checklist/new_update_indiehandbook_information.txt',
        lambda mg: True,
        ident='mivs_checklist_update_indiehandbook_information'
    )

    MIVSGuestEmailFixture(
        'New {EVENT_NAME} MIVS Checklist Item: Selling Information',
        'mivs/checklist/new_update_selling_information.txt',
        lambda mg: True,
        ident='mivs_checklist_update_selling_information'
    )

    MIVSGuestEmailFixture(
        'New {EVENT_NAME} MIVS Checklist Item: Hotel Signups',
        'mivs/checklist/new_update_hotel_information.txt',
        lambda mg: True,
        ident='mivs_checklist_update_hotel_information'
    )

    MIVSGuestEmailFixture(
        'New {EVENT_NAME} MIVS Checklist Item: MIVS Training',
        'mivs/checklist/new_update_training_information.txt',
        lambda mg: True,
        ident='mivs_checklist_update_training_information'
    )

    # At-Con MIVS Emails
    MIVSEmailFixture(
        IndieGame,
        '{EVENT_NAME} MIVS {EVENT_YEAR}: Wednesday Setup',
        'mivs/At-Con/LoadIn.txt',
        lambda game: game.confirmed,
        ident='mivs_LoadIn.txt'
    )

    MIVSEmailFixture(
        IndieGame,
        '{EVENT_NAME} MIVS {EVENT_YEAR}: Thursday, Day 1',
        'mivs/At-Con/Day1.txt',
        lambda game: game.confirmed,
        ident='mivs_Day1.txt'
    )

    # start year specific MIVS Emails
    MIVSEmailFixture(
        IndieGame,
        'MIVS December Update',
        'mivs/2022/december_update.txt',
        lambda game: game.confirmed,
        ident='mivs_december_update.txt'
    )

    # post con emails
    MIVSEmailFixture(
        IndieGame,
        '{EVENT_NAME} MIVS {EVENT_YEAR}: Request for Feedback',
        'mivs/feedback/indie_survey.txt',
        lambda game: game.confirmed,
        ident='mivs_feedback_survey',
        allow_post_con=True,
    )


# =============================
# mits
# =============================
class MITSEmailFixture(AutomatedEmailFixture):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('sender', c.MITS_EMAIL)
        AutomatedEmailFixture.__init__(self, MITSTeam, *args, **kwargs)


if c.MITS_ENABLED:

    # We wait an hour before sending out this email because the most common case
    # of someone registering their team is that they'll immediately fill out the
    # entire application, so there's no reason to send them an email showing their
    # currently completion percentage when that info will probably be out of date
    # by the time they read it.  By waiting an hour, we ensure this doesn't happen.
    MITSEmailFixture(
        'Thanks for showing an interest in MITS!',
        'mits/mits_registered.txt',
        lambda team: not team.submitted and team.applied < datetime.now(UTC) - timedelta(hours=1),
        ident='mits_application_created')

    # For similar reasons to the above, we wait at least 6 hours before sending this
    # email because it would seem silly to immediately send someone a "last chance"
    # email the minute they registered their team.  By waiting 6 hours, we wait
    # until they've had a chance to complete the application and even receive the
    # initial reminder email above before being pestered with this warning.
    MITSEmailFixture(
        'Last chance to complete your MITS application!',
        'mits/mits_reminder.txt',
        lambda team: not team.submitted and team.applied < datetime.now(UTC) - timedelta(hours=6),
        when=days_before(3, c.MITS_SUBMISSION_DEADLINE),
        ident='mits_reminder')

    MITSEmailFixture(
        'Thanks for submitting your MITS application!',
        'mits/mits_submitted.txt',
        lambda team: team.submitted,
        ident='mits_application_submitted')

    MITSEmailFixture(
        'Please fill out the remainder of your MITS application',
        'mits/mits_preaccepted.txt',
        lambda team: team.accepted and team.completion_percentage < 100,
        ident='mits_preaccepted_incomplete')

    MITSEmailFixture(
        'MITS initial panel information',
        'mits/mits_initial_panel_info.txt',
        lambda team: team.accepted and team.panel_interest,
        ident='mits_initial_panel_info')

    MITSEmailFixture(
        'Please sign the MITS waiver for {EVENT_NAME}',
        'mits/mits_waiver.txt',
        lambda team: team.accepted and not team.waiver_signed,
        ident='mits_waiver')

    MITSEmailFixture(
        'Reminder to sign the MITS waiver for {EVENT_NAME}',
        'mits/mits_waiver.txt',
        lambda team: team.accepted and not team.waiver_signed,
        when=days_before(10, c.EPOCH),
        ident='mits_waiver_reminder')

    MITSEmailFixture(
        'Tax Form for selling in MITS',
        'mits/mits_tax_form.txt',
        lambda team: team.accepted and team.want_to_sell,
        ident='mits_tax_form')

    MITSEmailFixture(
        'MITS 2024 Developer Perspective Feedback',
        'mits/mits_feedback.txt',
        lambda team: team.accepted,
        ident='mits_feedback',
        allow_post_con=True)

    AutomatedEmailFixture(
        MITSApplicant,
        '{EVENT_NAME} parking information',
        'mits/mits_parking.txt',
        lambda ma: ma.attendee and ma.team and ma.team.accepted,
        sender=c.MITS_EMAIL,
        ident='mits_parking')

    AutomatedEmailFixture(
        MITSApplicant,
        'Automated MITS FAQ Email',
        'mits/mits_faq.html',
        lambda ma: ma.attendee and ma.team and ma.team.accepted,
        sender=c.MITS_EMAIL,
        ident='mits_faq')

    # TODO: emails we still need to configure include but are not limited to:
    # -> when teams have been accepted
    # -> when teams have been declined
    # -> when accepted teams have added people who have not given their hotel info
    # -> final pre-event informational email


# =============================
# panels
# =============================

class PanelAppEmailFixture(AutomatedEmailFixture):
    def __init__(self, subject, template, filter, ident, **kwargs):
        AutomatedEmailFixture.__init__(
            self,
            PanelApplication,
            subject,
            template,
            lambda app: filter(app) and (
                not app.submitter or
                not app.submitter.attendee_id or
                app.submitter.attendee.badge_type != c.GUEST_BADGE),
            ident,
            sender=c.PANELS_EMAIL,
            **kwargs)


if c.PANELS_ENABLED:

    PanelAppEmailFixture(
        'Your {EVENT_NAME} Panel Application Has Been Received: {{ app.name }}',
        'panels/application.html',
        lambda a: True,
        needs_approval=False,
        ident='panel_received')

    PanelAppEmailFixture(
        'Your {EVENT_NAME} Panel Application Has Been Accepted: {{ app.name }}',
        'panels/panel_app_accepted.txt',
        lambda app: app.status == c.ACCEPTED,
        ident='panel_accepted')

    PanelAppEmailFixture(
        'Your {EVENT_NAME} Panel Application Has Been Declined: {{ app.name }}',
        'panels/panel_app_declined.txt',
        lambda app: app.status == c.DECLINED,
        ident='panel_declined')

    PanelAppEmailFixture(
        'Your {EVENT_NAME} Panel Application Has Been Waitlisted: {{ app.name }}',
        'panels/panel_app_waitlisted.txt',
        lambda app: app.status == c.WAITLISTED,
        ident='panel_waitlisted')

    PanelAppEmailFixture(
        'Last chance to confirm your panel',
        'panels/panel_accept_reminder.txt',
        lambda app: (
            c.PANELS_CONFIRM_DEADLINE
            and app.confirm_deadline
            and (localized_now() + timedelta(days=2)) > app.confirm_deadline),
        ident='panel_accept_reminder')

    PanelAppEmailFixture(
        'Your {EVENT_NAME} Panel Has Been Scheduled: {{ app.name }}',
        'panels/panel_app_scheduled.txt',
        lambda app: app.event_id,
        ident='panel_scheduled')

    AutomatedEmailFixture(
        Attendee,
        'Your {EVENT_NAME} Event Schedule',
        'panels/panelist_schedule.txt',
        lambda a: a.badge_type != c.GUEST_BADGE and a.assigned_panelists,
        ident='event_schedule',
        sender=c.PANELS_EMAIL)


# =============================
# guests
# =============================

class BandEmailFixture(AutomatedEmailFixture):
    def __init__(self, subject, template, filter, ident, **kwargs):
        AutomatedEmailFixture.__init__(
            self,
            GuestGroup,
            subject,
            template,
            lambda b: b.group_type == c.BAND and filter(b),
            ident,
            sender=c.BAND_EMAIL,
            **kwargs)


class GuestEmailFixture(AutomatedEmailFixture):
    def __init__(self, subject, template, filter, ident, **kwargs):
        AutomatedEmailFixture.__init__(
            self,
            GuestGroup,
            subject,
            template,
            lambda b: b.group_type == c.GUEST and filter(b),
            ident,
            sender=c.GUEST_EMAIL,
            **kwargs)


AutomatedEmailFixture(
    GuestGroup,
    '{EVENT_NAME} Performer Checklist',
    'guests/band_notification.txt',
    lambda b: b.group_type == c.BAND, sender=c.BAND_EMAIL,
    ident='band_checklist_inquiry')

BandEmailFixture(
    'Last chance to apply for a {EVENT_NAME} Panel',
    'guests/band_panel_reminder.txt',
    lambda b: not b.panel_status,
    when=days_before(3, c.BAND_PANEL_DEADLINE),
    ident='band_panel_reminder')

BandEmailFixture(
    'Last Chance to accept your offer to perform at {EVENT_NAME}',
    'guests/band_agreement_reminder.txt',
    lambda b: not b.info_status,
    when=days_before(3, c.BAND_INFO_DEADLINE),
    ident='band_agreement_reminder')

BandEmailFixture(
    'Last chance to include your bio info on the {EVENT_NAME} website',
    'guests/band_bio_reminder.txt',
    lambda b: not b.bio_status,
    when=days_before(3, c.BAND_BIO_DEADLINE),
    ident='band_bio_reminder')

BandEmailFixture(
    '{EVENT_NAME} W9 reminder',
    'guests/band_w9_reminder.txt',
    lambda b: b.payment and not b.taxes_status,
    when=days_before(3, c.BAND_TAXES_DEADLINE),
    ident='band_w9_reminder')

BandEmailFixture(
    'Last chance to sign up for selling merchandise at {EVENT_NAME}',
    'guests/band_merch_reminder.txt',
    lambda b: not b.merch_status,
    when=days_before(3, c.BAND_MERCH_DEADLINE),
    ident='band_merch_reminder')

BandEmailFixture(
    '{EVENT_NAME} charity auction reminder',
    'guests/band_charity_reminder.txt',
    lambda b: not b.charity_status,
    when=days_before(3, c.BAND_CHARITY_DEADLINE),
    ident='band_charity_reminder')

BandEmailFixture(
    '{EVENT_NAME} stage plot reminder',
    'guests/band_stage_plot_reminder.txt',
    lambda b: not b.stage_plot_status,
    when=days_before(3, c.BAND_STAGE_PLOT_DEADLINE),
    ident='band_stage_plot_reminder')

GuestEmailFixture(
    'It\'s time to send us your info for {EVENT_NAME}!',
    'guests/guest_checklist_announce.html',
    lambda g: True,
    ident='guest_checklist_inquiry')

GuestEmailFixture(
    'Reminder: Please complete your Guest Checklist for {EVENT_NAME}!',
    'guests/guest_checklist_reminder.html',
    lambda g: not g.checklist_completed,
    when=days_before(7, c.GUEST_INFO_DEADLINE),
    ident='guest_reminder_1')

GuestEmailFixture(
    'Have you forgotten anything? Your {EVENT_NAME} Guest Checklist needs you!',
    'guests/guest_checklist_reminder.html',
    lambda g: not g.checklist_completed,
    when=days_after(7, c.GUEST_INFO_DEADLINE),
    ident='guest_reminder_2')
