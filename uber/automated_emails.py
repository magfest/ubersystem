import os
import jinja2
import logging
from datetime import datetime, timedelta
import pathlib

from pytz import UTC
from sqlalchemy.orm import joinedload, subqueryload

from uber.config import c
from uber import decorators
from uber.jinja import JinjaEnv
from uber.models import (AdminAccount, Attendee, AttendeeAccount, ArtShowApplication, ArtShowBidder, AutomatedEmail, AttractionSignup, Department,
                         Email, Group, GuestGroup, IndieGame, IndieJudge, IndieStudio, ArtistMarketplaceApplication, MITSTeam,
                         MITSApplicant, ReceiptInfo, PanelApplication, PanelApplicant, PromoCode, PromoCodeGroup, Room, RoomAssignment, LotteryApplication, Shift)
from uber.utils import after, before, days_after, days_before, days_between, localized_now, DeptChecklistConf

log = logging.getLogger(__name__)


class AutomatedEmailFixture:
    """
    Represents one category of emails that we send out.
    An example of an email category would be "Your registration has been confirmed".
    """

    # A list of options to use when querying models for an email
    queries = {
        Attendee: [
            subqueryload(Attendee.admin_account),
            subqueryload(Attendee.group).subqueryload(Group.guest),
            subqueryload(Attendee.shifts).subqueryload(Shift.job),
            subqueryload(Attendee.assigned_depts),
            subqueryload(Attendee.dept_membership_requests),
            subqueryload(Attendee.checklist_admin_depts).subqueryload(Department.dept_checklist_items),
            subqueryload(Attendee.dept_memberships),
            subqueryload(Attendee.dept_memberships_with_role),
            subqueryload(Attendee.depts_where_working),
            subqueryload(Attendee.hotel_requests),
            subqueryload(Attendee.promo_code_groups),
            subqueryload(Attendee.promo_code),
            subqueryload(Attendee.assigned_panelists)],
        AttendeeAccount: [subqueryload(AttendeeAccount.attendees)],
        ArtShowApplication: [subqueryload(ArtShowApplication.attendee)],
        ArtShowBidder: [subqueryload(ArtShowBidder.attendee), subqueryload(ArtShowBidder.art_show_pieces)],
        ArtistMarketplaceApplication: [subqueryload(ArtistMarketplaceApplication.attendee)],
        Group: [subqueryload(Group.attendees)],
        LotteryApplication: [subqueryload(LotteryApplication.attendee)],
        PromoCodeGroup: [subqueryload(PromoCodeGroup.buyer)],
        Room: [subqueryload(Room.assignments).subqueryload(RoomAssignment.attendee)],
        IndieStudio: [subqueryload(IndieStudio.developers), subqueryload(IndieStudio.games)],
        IndieGame: [joinedload(IndieGame.studio).subqueryload(IndieStudio.developers)],
        IndieJudge: [joinedload(IndieJudge.admin_account).joinedload(AdminAccount.attendee)],
        MITSTeam: [joinedload(MITSTeam.applicants).subqueryload(MITSApplicant.attendee),
                   joinedload(MITSTeam.games), joinedload(MITSTeam.schedule)],
        MITSApplicant: [subqueryload(MITSApplicant.attendee), subqueryload(MITSApplicant.team)],
        PanelApplication: [subqueryload(PanelApplication.applicants).subqueryload(PanelApplicant.attendee)],
        GuestGroup: [joinedload(GuestGroup.group)]
    }

    def __init__(
            self,
            model,
            subject,
            template,
            filter,
            ident,
            *,
            shared_ident='',
            send_filter=None,
            when: list = [],
            sender=None,
            cc: list[str] = [],
            bcc: list[str] = [],
            replyto: list[str] = [],
            allow_at_the_con=False,
            allow_post_con=False,
            extra_data=None):

        assert ident, 'AutomatedEmail ident may not be empty.'

        AutomatedEmail._fixtures[ident] = self

        self.model = model
        self.subject = subject
        self.template = template
        self.format = 'text' if template.endswith('.txt') else 'html'
        self.filter = (lambda x: (x.gets_emails and filter(x))) if filter else None
        self.send_filter = (lambda x: (x.gets_emails and send_filter(x))) if send_filter else self.filter
        self.ident = ident
        self.shared_ident = shared_ident
        self.sender = sender or c.CONTACT_EMAIL
        self.cc = cc
        self.bcc = bcc
        self.replyto = replyto
        self.allow_at_the_con = allow_at_the_con
        self.allow_post_con = allow_post_con
        self.extra_data = extra_data or {}

        when = when

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
            path_offset = 0
            if template_path.parts[2] == 'plugins':
                path_offset = 2
            self.template_plugin_name = template_path.parts[2 + path_offset]
            self.template_url = (f"https://github.com/magfest/{self.template_plugin_name}/tree/main/"
                                 f"{self.template_plugin_name}/{pathlib.Path(*template_path.parts[(3 + path_offset):]).as_posix()}")
        except jinja2.exceptions.TemplateNotFound:
            self.template_plugin_name = "ERROR: TEMPLATE NOT FOUND"
            self.template_url = ""
        return self.template_plugin_name, self.template_url

    @property
    def body(self):
        return decorators.render_empty(os.path.join('emails', self.template))


class AdminReportEmailFixture(AutomatedEmailFixture):
    def __init__(self, subject, template, ident, **kwargs):
        AutomatedEmailFixture.__init__(self, None, subject,
                                       template,
                                       None,
                                       ident,
                                       sender=kwargs.pop('sender', c.ADMIN_EMAIL), **kwargs)


AutomatedEmailFixture(
    AttractionSignup,
    'Signed up from waitlist',
    'panels/attractions_waitlist.html', None,
    'signup_from_waitlist',
    sender=c.ATTRACTIONS_EMAIL)


AutomatedEmailFixture(
    AttractionSignup,
    f'Welcome to {c.EVENT_NAME} Attractions',
    'panels/attractions_welcome.html', None,
    'first_attractions_signup',
    sender=c.ATTRACTIONS_EMAIL,
)


AutomatedEmailFixture(
    AttractionSignup,
    'Checkin for {event.name} is at {event.checkin_start_time_label}',
    'panels/attractions_notification.html', None,
    'signup_checkin_notice',
    sender=c.ATTRACTIONS_EMAIL,
)


AutomatedEmailFixture(
    AdminAccount,
    f'New {c.EVENT_NAME} Admin Account',
    'accounts/new_account.txt', None,
    'new_admin_account',
    sender=c.ADMIN_EMAIL,
    send_filter=lambda a: a.admin_account,
)


AutomatedEmailFixture(
    AdminAccount,
    f'{c.EVENT_NAME} Admin Password Reset',
    'accounts/password_reset.txt', None,
    'admin_password_reset',
    sender=c.ADMIN_EMAIL,
    send_filter=lambda a: a.admin_account,
)


AutomatedEmailFixture(
    AttendeeAccount,
    f'{c.EVENT_NAME} Password Reset',
    'accounts/password_reset.html', None,
    'attendee_password_reset',
    sender=c.ADMIN_EMAIL,
    send_filter=lambda a: a.admin_account,
)


AdminReportEmailFixture(
    f'{c.EVENT_NAME} Panel Accepted With Accessibility Request(s)',
    'panels/accessibility_requested.txt',
    'panel_accepted_accessibility_admin',
)


AutomatedEmailFixture(
    AttendeeAccount,
    f'New Badge Added to Your {c.EVENT_NAME} Account',
    'accounts/attendee_added.html', None,
    'attendee_account_attendee_added',
    sender=c.ADMIN_EMAIL,
)


AutomatedEmailFixture(
    AttendeeAccount,
    f'{c.EVENT_NAME_AND_YEAR} Account Setup',
    'accounts/new_sso_account.html', None,
    'sso_account_setup',
    sender=c.ADMIN_EMAIL,
)


AutomatedEmailFixture(
    AttendeeAccount,
    f'{c.EVENT_NAME_AND_YEAR} Account Setup',
    'accounts/new_account.html', None,
    'local_account_setup',
    sender=c.ADMIN_EMAIL
)


AutomatedEmailFixture(
    None, f'Your {c.EVENT_NAME_AND_YEAR} receipt ' + '[#{receiptinfo.reference_id}]',
    'reg_workflow/receipt.html', None,
    'receipt_info',
    sender=c.ADMIN_EMAIL,
)


AutomatedEmailFixture(
    Attendee,
    f'{c.EVENT_NAME_AND_YEAR} Registration Confirmation',
    'reg_workflow/prereg_check.txt', None,
    'prereg_check',
    sender=c.REGDESK_EMAIL
)


AutomatedEmailFixture(
    None, f'Claim a {c.EVENT_NAME} badge in ' + '"{code.group.name}"',
    'reg_workflow/promo_code_invite.txt', None,
    'promo_code_group_invite',
    sender=c.REGDESK_EMAIL
)


AutomatedEmailFixture(
    Attendee,
    f'{c.EVENT_NAME} Pending Badge Code',
    'reg_workflow/pending_code.txt', None,
    'badge_transfer_code',
    sender=c.REGDESK_EMAIL,
    send_filter=lambda a: a.badge_status == c.PENDING_STATUS and a.paid == c.PENDING
)


AutomatedEmailFixture(
    None, f'{c.EVENT_NAME} Registration Transferred',
    'reg_workflow/badge_transferee.txt', None,
    'code_badge_transfer_new_badge',
    sender=c.REGDESK_EMAIL
)


AutomatedEmailFixture(
    None, f'{c.EVENT_NAME} Registration Transferred',
    'reg_workflow/badge_transferer.txt', None,
    'code_badge_transfer_old_badge',
    sender=c.REGDESK_EMAIL
)


AutomatedEmailFixture(
    None, f'{c.EVENT_NAME} Registration Transferred',
    'reg_workflow/badge_transfer.txt', None,
    'link_badge_transfer',
    sender=c.REGDESK_EMAIL
)


AdminReportEmailFixture(
    f'{c.EVENT_NAME} WatchList Notification',
    'reg_workflow/attendee_watchlist.txt',
    'watchlist_match_admin',
    sender=c.SECURITY_EMAIL
)


AdminReportEmailFixture(
    f'{c.EVENT_NAME} Pending Emails Report',
    'daily_checks/pending_emails.html',
    'pending_emails_admin',
)


AdminReportEmailFixture(
    'Deleted Guidebook Items',
    'guidebook_deletes.txt',
    'guidebook_deletes',
    sender=c.REPORTS_EMAIL
)


AdminReportEmailFixture(
    'Guidebook Updates',
    'guidebook_updates.txt',
    'guidebook_updates',
    sender=c.REPORTS_EMAIL
)


AdminReportEmailFixture(
    f'{c.EVENT_NAME} Duplicates Report',
    'daily_checks/duplicates.html',
    'daily_duplicates_report',
    sender=c.REPORTS_EMAIL
)


AdminReportEmailFixture(
    f'{c.EVENT_NAME} Placeholder Badge Report',
    'daily_checks/placeholders.html',
    'daily_placeholder_report',
    sender=c.REPORTS_EMAIL
)


AdminReportEmailFixture(
    f'{c.EVENT_NAME} Pending Badges Report',
    'daily_checks/pending.html',
    'daily_pending_report',
    sender=c.REPORTS_EMAIL
)


AdminReportEmailFixture(
    f'{c.EVENT_NAME} Unassigned Volunteer Report',
    'daily_checks/unassigned.html',
    'daily_unassigned_report',
    sender=c.REPORTS_EMAIL
)


AdminReportEmailFixture(
    f'{c.EVENT_NAME} BADGES SOLD ALERT',
    'badges_sold_alert.txt',
    'badges_sold_alert',
    sender=c.REPORTS_EMAIL
)


AdminReportEmailFixture(
    f'AuthNet Held Transaction Declined',
    'held_txn_declined.html',
    'authnet_held_txn_admin',
    sender=c.REPORTS_EMAIL
)


# Payment reminder emails, including ones for groups, which are always safe to be here, since they just
# won't get sent if group registration is turned off.

AutomatedEmailFixture(
    Attendee,
    f'{c.EVENT_NAME} registration confirmed',
    'reg_workflow/attendee_confirmation.html',
    lambda a: ((a.paid == c.HAS_PAID and not a.promo_code_groups) or
              (a.paid == c.NEED_NOT_PAY and (a.confirmed or a.promo_code_id or a.age_discount))),
    'attendee_badge_confirmed',
    allow_at_the_con=True)

if c.ATTENDEE_ACCOUNTS_ENABLED:
    AutomatedEmailFixture(
        AttendeeAccount,
        f'{c.EVENT_NAME} account creation confirmed',
        'reg_workflow/account_confirmation.html',
        lambda a: not a.imported and a.hashed and not a.password_reset and not a.is_sso_account,
        'attendee_account_confirmed',
        allow_at_the_con=True)

AutomatedEmailFixture(
    PromoCodeGroup,
    f'{c.EVENT_NAME} group registration successful',
    'reg_workflow/promo_code_group_confirmation.html',
    lambda g: g.buyer and g.buyer.amount_paid > 0,
    'pc_group_payment_received',
    allow_at_the_con=True)

AutomatedEmailFixture(
    Group,
    f'{c.EVENT_NAME} group payment received',
    'reg_workflow/group_confirmation.html',
    lambda g: g.amount_paid == g.cost * 100 and g.cost != 0 and g.leader_id,
    'group_payment_received')

AutomatedEmailFixture(
    Group,
    f'{c.EVENT_NAME} group registration successful',
    'reg_workflow/group_confirmation.html',
    lambda g: g.cost == 0 and g.leader_id and not g.leader.placeholder,
    'group_registration_confirmation')

AutomatedEmailFixture(
    Attendee,
    f'{c.EVENT_NAME} group registration confirmed',
    'reg_workflow/attendee_confirmation.html',
    lambda a: a.group and (a.id != a.group.leader_id or a.group.cost == 0) and not a.placeholder \
              and a.paid == c.PAID_BY_GROUP,
    'attendee_group_reg_confirmation',
    allow_at_the_con=True)

AutomatedEmailFixture(
    None, f'{c.EVENT_NAME} group registration dropped',
    'reg_workflow/group_member_dropped.txt', None,
    'attendee_removed_from_group'
)

AutomatedEmailFixture(
    Attendee,
    f'{c.EVENT_NAME} merch pre-order received',
    'reg_workflow/group_donation.txt',
    lambda a: a.paid == c.PAID_BY_GROUP and a.amount_extra and a.amount_paid >= (a.amount_extra * 100),
    'group_extra_payment_received',
    sender=c.MERCH_EMAIL)


# Reminder emails for groups to allocated their unassigned badges.  These emails are safe to be turned on for
# all events, because they will only be sent for groups with unregistered badges, so if group preregistration
# has been turned off, they'll just never be sent.

AutomatedEmailFixture(
    Group,
    f'Reminder to pre-assign {c.EVENT_NAME} group badges',
    'reg_workflow/group_preassign_reminder.txt',
    lambda g: (
        c.BEFORE_GROUP_PREREG_TAKEDOWN
        and days_after(30, g.registered)()
        and g.unregistered_badges
        and not g.is_dealer),
    'group_preassign_badges_reminder',
    when=[before(c.GROUP_PREREG_TAKEDOWN)],
    sender=c.REGDESK_EMAIL)

AutomatedEmailFixture(
    Group,
    f'Last chance to pre-assign {c.EVENT_NAME} group badges',
    'reg_workflow/group_preassign_reminder.txt',
    lambda g: (
      c.AFTER_GROUP_PREREG_TAKEDOWN
      and g.unregistered_badges
      and (not g.is_dealer or g.status in c.DEALER_ACCEPTED_STATUSES)),
    'group_preassign_badges_reminder_last_chance',
    when=[after(c.GROUP_PREREG_TAKEDOWN)],
    allow_at_the_con=True,
    sender=c.REGDESK_EMAIL)


# =============================
# art show
# =============================

class ArtShowAppEmailFixture(AutomatedEmailFixture):
    def __init__(self, subject, template, filter, ident, **kwargs):
        AutomatedEmailFixture.__init__(self, ArtShowApplication, subject,
                                       template,
                                       filter,
                                       ident,
                                       sender=c.ART_SHOW_EMAIL,
                                       bcc=c.ART_SHOW_BCC_EMAIL, **kwargs)


if c.ART_SHOW_ENABLED:
    AdminReportEmailFixture(
        'Art Show Application Received',
        'art_show/reg_notification.txt',
        'new_art_show_app_admin',
        sender=c.ART_SHOW_EMAIL,
    )

    AdminReportEmailFixture(
        'Art Show Payment Received',
        'art_show/payment_notification.txt',
        'art_show_payment_admin',
        sender=c.ART_SHOW_EMAIL,
    )

    ArtShowAppEmailFixture(
        'Art Show Application Updated',
        'art_show/appchange_notification.html', None,
        'art_show_app_updated',
    )

    ArtShowAppEmailFixture(
        '[{app.artist_codes}] ' + f'{c.EVENT_NAME} Art Show: Pieces Updated',
        'art_show/pieces_confirmation.html', None,
        'art_show_piece_updated',
    )

    AutomatedEmailFixture(
        None, f'{c.EVENT_NAME} Art Show Agent Removed',
        'art_show/agent_removed.html', None,
        'art_show_agent_removed',
        bcc=c.ART_SHOW_BCC_EMAIL,
    )

    ArtShowAppEmailFixture(
        f'New Agent Code for the {c.EVENT_NAME} Art Show',
        'art_show/agent_code.html', None,
        'new_art_agent_code',
    )

    AutomatedEmailFixture(
        ArtShowBidder,
        f'Bidding Winner Notification for the {c.EVENT_NAME} Art Show',
        'art_show/pieces_won.html',
        lambda a: a.email_won_bids and len(
            [piece for piece in a.art_show_pieces if piece.winning_bid and piece.status == c.SOLD]) > 0,
        'art_show_pieces_won',
        allow_at_the_con=True,
        sender=c.ART_SHOW_EMAIL)

    ArtShowAppEmailFixture(
        f'{c.EVENT_NAME} Art Show Application Confirmation',
        'art_show/application.html',
        lambda a: a.status == c.UNAPPROVED,
        'art_show_confirm')

    ArtShowAppEmailFixture(
        f'Your {c.EVENT_NAME} Art Show application has been approved',
        'art_show/approved.html',
        lambda a: a.status == c.APPROVED,
        'art_show_approved')

    ArtShowAppEmailFixture(
        f'Your {c.EVENT_NAME} Art Show application has been waitlisted',
        'art_show/waitlisted.txt',
        lambda a: a.status == c.WAITLISTED,
        'art_show_waitlisted')

    ArtShowAppEmailFixture(
        f'Your {c.EVENT_NAME} Art Show application has been declined',
        'art_show/declined.txt',
        lambda a: a.status == c.DECLINED,
        'art_show_declined')

    ArtShowAppEmailFixture(
        f'Your {c.EVENT_NAME} Art Show payment has been received',
        'art_show/payment_confirmation.txt',
        lambda a: a.status == c.APPROVED and a.amount_paid,
        'art_show_payment_received'
    )

    if c.ART_SHOW_HAS_FEES:
        ArtShowAppEmailFixture(
            f'Reminder to pay for your {c.EVENT_NAME} Art Show application',
            'art_show/payment_reminder.txt',
            lambda a: a.status == c.APPROVED and a.amount_unpaid,
            'art_show_payment_reminder',
            when=[days_between((14, c.ART_SHOW_PAYMENT_DUE), (1, c.EPOCH))])

    ArtShowAppEmailFixture(
        f'{c.EVENT_NAME} Art Show piece entry needed',
        'art_show/pieces_reminder.txt',
        lambda a: a.status == c.APPROVED and not a.amount_unpaid and not a.art_show_pieces,
        'art_show_pieces_reminder',
        when=[days_before(15, c.EPOCH)])

    ArtShowAppEmailFixture(
        f'Reminder to assign an agent for your {c.EVENT_NAME} Art Show application',
        'art_show/agent_reminder.html',
        lambda a: a.status == c.APPROVED and not a.amount_unpaid and a.delivery_method == c.AGENT and not a.current_agents,
        'art_show_agent_reminder',
        when=[after(c.EVENT_TIMEZONE.localize(datetime(int(c.EVENT_YEAR), 11, 1)))])

    if c.ART_SHOW_REG_START < (c.EPOCH - timedelta(days=7)):
        ArtShowAppEmailFixture(
            f'{c.EVENT_NAME} Art Show MAIL IN Instructions',
            'art_show/mailing_in.html',
            lambda a: a.status == c.APPROVED and not a.amount_unpaid and a.delivery_method == c.BY_MAIL,
            'art_show_mail_in',
            when=[days_before(7, c.ART_SHOW_WAITLIST if c.ART_SHOW_WAITLIST else c.ART_SHOW_DEADLINE)])


# =============================
# marketplace
# =============================

class ArtistMarketplaceEmailFixture(AutomatedEmailFixture):
    def __init__(self, subject, template, filter, ident, **kwargs):
        AutomatedEmailFixture.__init__(self, ArtistMarketplaceApplication, subject,
                                       template,
                                       lambda app: True and filter(app),
                                       ident,
                                       sender=c.ARTIST_MARKETPLACE_EMAIL, **kwargs)


if c.MARKETPLACE_REG_START:
    AdminReportEmailFixture(
        'Marketplace Application Updated',
        'marketplace/appchange_notification.html',
        'marketplace_app_updated_admin',
        sender=c.ARTIST_MARKETPLACE_EMAIL,
    )

    AdminReportEmailFixture(
        'Marketplace Application Cancelled',
        'marketplace/cancelled.txt',
        'marketplace_app_cancelled_admin',
        sender=c.ARTIST_MARKETPLACE_EMAIL,
    )

    ArtistMarketplaceEmailFixture(
        f'{c.EVENT_NAME} Artist Marketplace Application Confirmation',
        'marketplace/application.html',
        lambda a: a.status == c.PENDING,
        'marketplace_confirm')

    ArtistMarketplaceEmailFixture(
        f'Your {c.EVENT_NAME} Artist Marketplace application has been accepted',
        'marketplace/approved.html',
        lambda a: a.status == c.ACCEPTED,
        'marketplace_approved')

    ArtistMarketplaceEmailFixture(
        f'Your {c.EVENT_NAME} Artist Marketplace application has been waitlisted',
        'marketplace/waitlisted.txt',
        lambda a: a.status == c.WAITLISTED,
        'marketplace_waitlisted')

    ArtistMarketplaceEmailFixture(
        f'Your {c.EVENT_NAME} Artist Marketplace application has been declined',
        'marketplace/declined.txt',
        lambda a: a.status == c.DECLINED,
        'marketplace_declined')

    ArtistMarketplaceEmailFixture(
        f'Reminder to pay for your {c.EVENT_NAME} Artist Marketplace application',
        'marketplace/payment_reminder.txt',
        lambda a: a.status == c.ACCEPTED and a.amount_unpaid,
        'marketplace_payment_reminder',
        when=[days_before(14, c.MARKETPLACE_PAYMENT_DUE)])

    ArtistMarketplaceEmailFixture(
        f'Your {c.EVENT_NAME} Artist Marketplace payment has been received',
        'marketplace/payment_confirmation.txt',
        lambda a: a.status == c.ACCEPTED and a.amount_paid,
        'marketplace_payment_received'
    )


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
            sender=c.MARKETPLACE_EMAIL,
            **kwargs)


if c.DEALER_REG_START:
    AdminReportEmailFixture(
        f'{c.DEALER_APP_TERM.title()} Received',
        'dealers/reg_notification.txt',
        'dealer_applied_admin',
        sender=c.MARKETPLACE_EMAIL
    )

    AdminReportEmailFixture(
        f'{c.DEALER_APP_TERM.title()} Changed',
        'dealers/appchange_notification.html',
        'dealer_app_updated_admin',
        sender=c.MARKETPLACE_EMAIL,
    )

    AdminReportEmailFixture(
        f'{c.DEALER_TERM.title()} Payment Completed',
        'dealers/payment_notification.txt',
        'dealer_payment_admin',
        sender=c.MARKETPLACE_EMAIL,
    )

    AutomatedEmailFixture(
        Attendee,
        f'Update About Your {c.EVENT_NAME} Registration',
        'dealers/badge_converted.html', None,
        'dealer_decline_convert',
        sender=c.MARKETPLACE_EMAIL,
    )

    MarketplaceEmailFixture(
        f'{c.DEALER_APP_TERM.title()} Received',
        'dealers/application.html', None,
        'dealer_reg_received'
    )

    MarketplaceEmailFixture(
        f'Your {c.EVENT_NAME} {c.DEALER_APP_TERM.capitalize()} has been waitlisted',
        'dealers/waitlisted.txt',
        lambda g: g.status == c.WAITLISTED,
        'dealer_reg_waitlisted')

    MarketplaceEmailFixture(
        f'Your {c.EVENT_NAME} {c.DEALER_APP_TERM.capitalize()} has been declined',
        'dealers/declined.txt',
        lambda g: g.status == c.DECLINED,
        'dealer_reg_declined')

    MarketplaceEmailFixture(
        f'Your {c.EVENT_NAME} {c.DEALER_APP_TERM.capitalize()} has been approved',
        'dealers/approved.html',
        lambda g: g.status == c.APPROVED,
        'dealer_reg_approved')
    
    if c.ALLOW_SHARED_TABLES:
        MarketplaceEmailFixture(
            f'Your {c.DEALER_APP_TERM} is now shared',
            'dealers/table_shared.html',
            lambda g: g.status == c.SHARED,
            'dealer_reg_shared')

    if c.SIGNNOW_DEALER_TEMPLATE_ID:
        MarketplaceEmailFixture(
            f'Please complete your {c.EVENT_NAME} {c.DEALER_APP_TERM.capitalize()}!',
            'dealers/signnow_request.html',
            lambda g: g.status in [c.APPROVED,
                                   c.SHARED] and c.SIGNNOW_DEALER_TEMPLATE_ID and not g.signnow_document_signed,
            'dealer_signnow_email')

    MarketplaceEmailFixture(
        f'Reminder to pay for your {c.EVENT_NAME} {c.DEALER_REG_TERM.capitalize()}',
        'dealers/payment_reminder.txt',
        lambda g: g.status in c.DEALER_ACCEPTED_STATUSES and days_after(30, g.approved)() and g.is_unpaid,
        'dealer_reg_payment_reminder',
        when=[days_before(60, c.DEALER_PAYMENT_DUE, 7)])

    MarketplaceEmailFixture(
        f'Your {c.EVENT_NAME} ({c.EVENT_DATE}) {c.DEALER_REG_TERM.capitalize()} is due in one week',
        'dealers/payment_reminder.txt',
        lambda g: g.status in c.DEALER_ACCEPTED_STATUSES and g.is_unpaid,
        'dealer_reg_payment_reminder_due_soon',
        when=[days_before(7, c.DEALER_PAYMENT_DUE, 2)])

    MarketplaceEmailFixture(
        f'Last chance to pay for your {c.EVENT_NAME} ({c.EVENT_DATE}) {c.DEALER_REG_TERM.capitalize()}',
        'dealers/payment_reminder.txt',
        lambda g: g.status in c.DEALER_ACCEPTED_STATUSES and g.is_unpaid,
        'dealer_reg_payment_reminder_last_chance',
        when=[days_before(2, c.DEALER_PAYMENT_DUE)])


class StopsEmailFixture(AutomatedEmailFixture):
    def __init__(self, subject, template, filter, ident, **kwargs):
        AutomatedEmailFixture.__init__(
            self,
            Attendee,
            subject,
            template,
            lambda a: a.staffing and filter(a),
            ident,
            sender=c.STAFF_EMAIL,
            **kwargs)


earliest_opening_date = min(c.PREREG_OPEN, c.DEALER_REG_START) if c.DEALER_REG_START else c.PREREG_OPEN

def staff_import_placeholder(a): return a.placeholder and (a.registered_local <= c.PREREG_OPEN
                                                           and (a.admin_account or
                                                                "staff import" in a.admin_notes.lower()))

AutomatedEmailFixture(
    Attendee,
    f'Claim your badge for {c.EVENT_NAME_AND_YEAR}!',
    'placeholders/regular.txt',
    lambda a: a.placeholder and a.registered_local > earliest_opening_date and a.paid == c.NEED_NOT_PAY,
    'generic_badge_confirmation_comped',
    sender=c.CONTACT_EMAIL,
    allow_at_the_con=True)

AutomatedEmailFixture(
    Attendee,
    f'Please complete your {c.EVENT_NAME_AND_YEAR} registration',
    'placeholders/regular.txt',
    lambda a: (a.placeholder and a.registered_local > earliest_opening_date and
               a.paid != c.NEED_NOT_PAY and "converted badge" not in a.admin_notes.lower()),
    'generic_badge_confirmation',
    sender=c.CONTACT_EMAIL,
    allow_at_the_con=True)

AutomatedEmailFixture(
    Attendee,
    f'Last chance to claim your badge for {c.EVENT_NAME}',
    'dealers/claim_badge.html',
    lambda a: a.placeholder and 'converted badge' in a.admin_notes.lower(),
    'converted_dealer_last_chance',
    sender=c.MARKETPLACE_EMAIL,
    when=[days_before(7, c.PREREG_HOTEL_ELIGIBILITY_CUTOFF)]
)

AutomatedEmailFixture(
    Attendee,
    f'You have an incomplete {c.EVENT_NAME} registration!',
    'reg_workflow/pending_badges.html', None,
    'incomplete_reg_notification',
    send_filter=lambda a: a.badge_status == c.PENDING_STATUS and a.paid == c.PENDING,
    sender=c.REGDESK_EMAIL,
)

StopsEmailFixture(
    f'Claim your Staff badge for {c.EVENT_NAME} {c.EVENT_YEAR}!',
    'placeholders/imported_volunteer.txt',
    staff_import_placeholder,
    'volunteer_again_inquiry')

AutomatedEmailFixture(
    Attendee,
    f'{c.EVENT_NAME} Badge Confirmation Reminder',
    'placeholders/reminder.txt',
    lambda a: days_after(7, a.registered)() and a.placeholder and not a.is_dealer,
    'badge_confirmation_reminder')

AutomatedEmailFixture(
    Attendee,
    f'Last Chance to Accept Your {c.EVENT_NAME} ({c.EVENT_DATE}) Badge',
    'placeholders/reminder.txt',
    lambda a: a.placeholder and not a.is_dealer,
    'badge_confirmation_reminder_last_chance',
    when=[days_before(7, c.PLACEHOLDER_DEADLINE if c.PLACEHOLDER_DEADLINE else c.UBER_TAKEDOWN)])

if c.VOLUNTEER_CHECKLIST_OPEN:
    StopsEmailFixture(
        f'Please complete your {c.EVENT_NAME} Staff/Volunteer Checklist',
        'shifts/created.txt',
        lambda a: a.staffing,
        'volunteer_checklist_completion_request',
        when=[after(c.VOLUNTEER_CHECKLIST_OPEN)],
        allow_at_the_con=True)

    StopsEmailFixture(
        f'Still want to volunteer at {c.EVENT_NAME} ({c.EVENT_DATE})?',
        'shifts/volunteer_check.txt',
        lambda a: (
            c.VOLUNTEER_SIGNUPS_AVAILABLE
            and a.badge_type != c.CONTRACTOR_BADGE
            and c.VOLUNTEER_RIBBON in a.ribbon_ints
            and a.takes_shifts
            and a.weighted_hours == 0),
        'volunteer_still_interested_inquiry',
        when=[days_before(28, c.FINAL_EMAIL_DEADLINE)])

if c.VOLUNTEER_AGREEMENT_ENABLED:
    StopsEmailFixture(
        f'Reminder: Please agree to terms of {c.EVENT_NAME} ({c.EVENT_DATE}) volunteer agreement',
        'staffing/volunteer_agreement.txt',
        lambda a: c.VOLUNTEER_CHECKLIST_OPEN and c.VOLUNTEER_AGREEMENT_ENABLED and not a.agreed_to_volunteer_agreement,
        'volunteer_agreement',
        when=[days_before(45, c.FINAL_EMAIL_DEADLINE)])

if c.SHIFTS_CREATED:
    StopsEmailFixture(
        f'{c.EVENT_NAME} ({c.EVENT_DATE}) shifts are live!',
        'shifts/shifts_created.txt',
        lambda a: (
            c.AFTER_SHIFTS_CREATED
            and a.badge_type != c.CONTRACTOR_BADGE
            and a.takes_shifts
            and a.registered_local <= c.SHIFTS_CREATED),
        'volunteer_shift_signup_notification',
        when=[before(c.PREREG_TAKEDOWN)])

    StopsEmailFixture(
        f'Reminder to sign up for {c.EVENT_NAME} ({c.EVENT_DATE}) shifts',
        'shifts/reminder.txt',
        lambda a: (
            c.AFTER_SHIFTS_CREATED
            and a.badge_type != c.CONTRACTOR_BADGE
            and days_after(14, max(a.registered_local, c.SHIFTS_CREATED))()
            and a.takes_shifts
            and not a.shift_minutes),
        'volunteer_shift_signup_reminder',
        when=[before(c.PREREG_TAKEDOWN)])

    StopsEmailFixture(
        f'Last chance to sign up for {c.EVENT_NAME} ({c.EVENT_DATE}) shifts',
        'shifts/reminder.txt',
        lambda a: (c.AFTER_SHIFTS_CREATED and a.badge_type != c.CONTRACTOR_BADGE
                and (not c.PREREG_TAKEDOWN or c.BEFORE_PREREG_TAKEDOWN) and a.takes_shifts and not a.shift_minutes),
        'volunteer_shift_signup_reminder_last_chance',
        when=[days_before(10, c.EPOCH)])

    StopsEmailFixture(
        f'Your {c.EVENT_NAME} ({c.EVENT_DATE}) shift schedule',
        'shifts/schedule.html',
        lambda a: c.SHIFTS_CREATED and a.weighted_hours and a.badge_type != c.CONTRACTOR_BADGE,
        'volunteer_shift_schedule',
        when=[days_before(1, c.FINAL_EMAIL_DEADLINE)],
        allow_at_the_con=True)

    StopsEmailFixture(
        f'Please review your worked shifts for {c.EVENT_NAME}!',
        'shifts/shifts_worked.html',
        lambda a: (a.weighted_hours or a.nonshift_minutes) and a.badge_type != c.CONTRACTOR_BADGE,
        'volunteer_shifts_worked',
        when=[days_after(1, c.ESCHATON)],
        allow_post_con=True)


# For events with customized badges, these emails remind people to let us know what we want on their badges.  We have
# one email for our volunteers who haven't bothered to confirm they're coming yet (bleh) and one for everyone else.

if c.PRINTED_BADGE_DEADLINE:
    StopsEmailFixture(
        f'Last chance to personalize your {c.EVENT_NAME} ({c.EVENT_DATE}) badge',
        'personalized_badges/volunteers.txt',
        lambda a: (a.staffing and a.has_personalized_badge and a.placeholder
                   and a.badge_type != c.CONTRACTOR_BADGE),
        'volunteer_personalized_badge_reminder',
        when=[days_before(7, c.PRINTED_BADGE_DEADLINE)])

    if [badge_type for badge_type in c.PREASSIGNED_BADGE_TYPES if badge_type not in [c.STAFF_BADGE,
                                                                                     c.CONTRACTOR_BADGE]]:
        AutomatedEmailFixture(
            Attendee,
            f'Personalized {c.EVENT_NAME} ({c.EVENT_DATE}) badges will be ordered next week',
            'personalized_badges/reminder.txt',
            lambda a: a.has_personalized_badge and not a.placeholder,
            'personalized_badge_reminder',
            when=[days_before(7, c.PRINTED_BADGE_DEADLINE)])


# MAGFest requires signed and notarized parental consent forms for anyone under 18.  This automated email reminder to
# bring the consent form only happens if this feature is turned on by setting the CONSENT_FORM_URL config option.
AutomatedEmailFixture(
    Attendee,
    f'{c.EVENT_NAME} ({c.EVENT_DATE}) parental consent form reminder',
    'reg_workflow/under_18_reminder.txt',
    lambda a: c.CONSENT_FORM_URL and a.age_group_conf['consent_form'] and days_after(14, a.registered)(),
    'under_18_parental_consent_reminder',
    when=[days_before(60, c.EPOCH)],
    allow_at_the_con=True)


# Emails sent out to all attendees who can check in. These emails contain useful information about the event and are
# sent close to the event start date.
AutomatedEmailFixture(
    Attendee,
    f'Check in faster at {c.EVENT_NAME}',
    'reg_workflow/attendee_qrcode.html',
    lambda a: not a.cannot_check_in_reason and c.USE_CHECKIN_BARCODE,
    'qrcode_for_checkin',
    when=[days_before(7, c.EPOCH)],
    allow_at_the_con=True)


class DeptChecklistEmailFixture(AutomatedEmailFixture):
    def __init__(self, conf):
        when = [days_before(10, conf.deadline)]
        if conf.email_post_con:
            when.append(after(c.EPOCH))
        else:
            when.append(after(c.DEPT_CHECKLIST_START))

        AutomatedEmailFixture.__init__(
            self,
            Attendee,
            f'{c.EVENT_NAME} Department Checklist: ' + conf.name,
            'shifts/dept_checklist.txt',
            lambda a: a.admin_account and any(
                not d.checklist_item_for_slug(conf.slug)
                for d in a.checklist_admin_depts),
            'department_checklist_{}'.format(conf.name),
            when=when,
            sender=c.STAFF_EMAIL,
            extra_data={'conf': conf},
            allow_post_con=conf.email_post_con)

if c.DEPT_CHECKLIST_START:
    for _conf in DeptChecklistConf.instances.values():
        DeptChecklistEmailFixture(_conf)


# =============================
# hotel/hotel lottery
# =============================

class HotelLotteryEmailFixture(AutomatedEmailFixture):
    def __init__(self, subject, template, filter, ident, **kwargs):
        AutomatedEmailFixture.__init__(
            self,
            LotteryApplication,
            subject,
            template,
            lambda a: (a.attendee and filter(a)) if filter else None,
            ident,
            sender=c.HOTEL_LOTTERY_EMAIL,
            **kwargs)


if c.HOTEL_LOTTERY_STAFF_START:
    HotelLotteryEmailFixture(
        'Last chance to complete your staff hotel lottery entry',
        'hotel/lottery_reminder.html',
        lambda a: a.status == c.PARTIAL and a.qualifies_for_staff_lottery and days_after(1, a.entry_started)(),
        'staff_hotel_lottery_reminder',
        when=[days_before(3, c.HOTEL_LOTTERY_STAFF_DEADLINE)]
    )


if c.HOTEL_LOTTERY_FORM_START:
    earliest_hotel_deadline = c.HOTEL_LOTTERY_FORM_WAITLIST if c.HOTEL_LOTTERY_FORM_WAITLIST else c.HOTEL_LOTTERY_FORM_DEADLINE

    AutomatedEmailFixture(
        Attendee,
        f'Did you want to enter the {c.EVENT_NAME} {c.EVENT_YEAR} hotel lottery?',
        'hotel/enter_lottery.html',
        lambda a: a.hotel_lottery_eligible and not a.lottery_application and days_after(1, a.registered)(),
        'enter_hotel_lottery',
        when=[days_before(7, earliest_hotel_deadline)],
        sender=c.HOTEL_LOTTERY_EMAIL,)

    HotelLotteryEmailFixture(
        'Last chance to complete your hotel lottery entry',
        'hotel/lottery_reminder.html',
        lambda a: a.status == c.PARTIAL and days_after(1, a.entry_started)(),
        'hotel_lottery_reminder',
        when=[days_before(3, earliest_hotel_deadline)],
    )


if c.HOTEL_LOTTERY_STAFF_START or c.HOTEL_LOTTERY_FORM_START:
    HotelLotteryEmailFixture(
        f'{c.EVENT_NAME_AND_YEAR} Hotel Lottery Notification',
        'hotel/award_notification.html',
        lambda a: a.status == c.AWARDED and not a.final_status_hidden and a.booking_url_ready,
        'hotel_lottery_awarded'
    )

    HotelLotteryEmailFixture(
        f'{c.EVENT_NAME_AND_YEAR} Hotel Lottery Notification',
        'hotel/reject_notification.html',
        lambda a: a.status == c.REJECTED and not a.final_status_hidden,
        'hotel_lottery_rejected'
    )

    if c.HOTEL_LOTTERY_FORM_WAITLIST:
        HotelLotteryEmailFixture(
            f'{c.EVENT_NAME_AND_YEAR} Hotel Lottery Notification',
            'hotel/reject_notification.html',
            lambda a: a.status == c.COMPLETE and a.qualifies_for_first_round,
            'hotel_lottery_first_round_rejected',
            when=[after(c.HOTEL_LOTTERY_FORM_WAITLIST)],
        )

    HotelLotteryEmailFixture(
        f'Reminder to confirm your {c.EVENT_NAME_AND_YEAR} hotel reservation',
        'hotel/guarantee_reminder.html',
        lambda a: a.status == c.AWARDED and a.booking_url_ready and \
            days_before(7, a.guarantee_deadline)() and not a.parent_application,
        'hotel_lottery_guarantee_reminder'
    )
    
    HotelLotteryEmailFixture(
        f'{c.EVENT_NAME_AND_YEAR} Hotel Lottery Award Cancelled',
        'hotel/cancel_notification.html',
        lambda a: a.status == c.CANCELLED,
        'hotel_lottery_award_cancelled'
    )

    HotelLotteryEmailFixture(
        f'{c.EVENT_NAME_AND_YEAR} Hotel Lottery Award Confirmed!',
        'hotel/secure_notification.html',
        lambda a: a.status == c.SECURED,
        'hotel_lottery_secured'
    )

    HotelLotteryEmailFixture(
        f'{c.EVENT_NAME} Lottery {c.HOTEL_LOTTERY_GROUP_TERM} Disbanded',
        'hotel/removed_from_group.html', None,
        'hotel_lottery_group_removed'
    )

    HotelLotteryEmailFixture(
        f'{c.EVENT_NAME_AND_YEAR} ' + '{app.entry_type_label} Lottery Confirmation',
        'hotel/hotel_lottery_entry.html', None,
        'hotel_lottery_confirmation'
    )

    HotelLotteryEmailFixture(
        f'{c.EVENT_NAME_AND_YEAR} Room Lottery Updated',
        'hotel/group_entry_updated.html', None,
        'group_lottery_updated'
    )

    HotelLotteryEmailFixture(
        '{app.attendee.first_name} ' + f'has left your {c.EVENT_NAME} Lottery {c.HOTEL_LOTTERY_GROUP_TERM}',
        'hotel/group_member_left.html', None,
        'hotel_lottery_group_member_left'
    )

    HotelLotteryEmailFixture(
        f'{c.EVENT_NAME_AND_YEAR} Lottery Entry Cancelled',
        'hotel/lottery_entry_cancelled.html', None,
        'hotel_lottery_cancelled'
    )

    HotelLotteryEmailFixture(
        f'{c.EVENT_NAME} Lottery {c.HOTEL_LOTTERY_GROUP_TERM} Leader Changed',
        'hotel/group_new_leader.html', None,
        'group_lottery_leader_changed'
    )

    HotelLotteryEmailFixture(
        f'Someone has joined your {c.EVENT_NAME} Lottery {c.HOTEL_LOTTERY_GROUP_TERM}',
        'hotel/group_member_joined.html', None,
        'group_lottery_member_joined'
    )


if c.HOTELS_ENABLED and c.HOURS_FOR_HOTEL_SPACE:
    AutomatedEmailFixture(
        Attendee,
        f'Want volunteer hotel room space at {c.EVENT_NAME}?',
        'hotel/hotel_rooms.txt',
        lambda a: (a.badge_type != c.CONTRACTOR_BADGE and a.hotel_eligible
                   and not a.hotel_requests and a.takes_shifts),
        'volunteer_hotel_room_inquiry',
        sender=c.ROOM_EMAIL_SENDER,
        when=[days_before(45, c.ROOM_DEADLINE, 14)])

    AutomatedEmailFixture(
        Attendee,
        f'Reminder to sign up for {c.EVENT_NAME} hotel room space',
        'hotel/hotel_reminder.txt',
        lambda a: (a.badge_type != c.CONTRACTOR_BADGE and a.hotel_eligible
                   and not a.hotel_requests and a.takes_shifts),
        'hotel_sign_up_reminder',
        sender=c.ROOM_EMAIL_SENDER,
        when=[days_before(14, c.ROOM_DEADLINE, 2)])

    AutomatedEmailFixture(
        Attendee,
        f'Last chance to sign up for {c.EVENT_NAME} hotel room space',
        'hotel/hotel_reminder.txt',
        lambda a: (a.badge_type != c.CONTRACTOR_BADGE and a.hotel_eligible
                   and not a.hotel_requests and a.takes_shifts),
        'hotel_sign_up_reminder_last_chance',
        sender=c.ROOM_EMAIL_SENDER,
        when=[days_before(2, c.ROOM_DEADLINE)])

    AutomatedEmailFixture(
        Attendee,
        f'Reminder to meet your {c.EVENT_NAME} hotel room requirements',
        'hotel/hotel_hours.txt',
        lambda a: (a.badge_type != c.CONTRACTOR_BADGE and a.hotel_shifts_required
                   and a.weighted_hours < c.HOURS_FOR_HOTEL_SPACE),
        'hotel_requirements_reminder',
        sender=c.ROOM_EMAIL_SENDER,
        when=[days_before(14, c.FINAL_EMAIL_DEADLINE, 7)])

    AutomatedEmailFixture(
        Attendee,
        f'Final reminder to meet your {c.EVENT_NAME} hotel room requirements',
        'hotel/hotel_hours.txt',
        lambda a: (a.badge_type != c.CONTRACTOR_BADGE and a.hotel_shifts_required
                   and a.weighted_hours < c.HOURS_FOR_HOTEL_SPACE),
        'hotel_requirements_reminder_last_chance',
        sender=c.ROOM_EMAIL_SENDER,
        when=[days_before(7, c.FINAL_EMAIL_DEADLINE)])

    if not c.HOTEL_REQUESTS_URL:
        AutomatedEmailFixture(
            Room,
            f'{c.EVENT_NAME} Hotel Room Assignment',
            'hotel/room_assignment.txt',
            lambda r: r.locked_in,
            'hotel_room_assignment',
            sender=c.ROOM_EMAIL_SENDER,)


# =============================
# showcase
# =============================

if c.ENABLED_INDIES_STR:
    AutomatedEmailFixture(
        IndieStudio,
        'Your Studio Has Been Registered',
        'indie_studio_registered.txt',
        lambda x: True,
        'showcase_studio_registered',
        sender=c.INDIE_SHOWCASE_EMAIL,
    )

    AutomatedEmailFixture(
        IndieStudio,
        f'Reminder to submit your game to {c.EVENT_NAME}',
        'mivs/game_reminder.txt',
        lambda studio: not studio.games,
        'mivs_studio_submission_reminder',
        sender=c.INDIE_SHOWCASE_EMAIL,
        when=[days_before(7, c.MIVS_DEADLINE)]
    )

    AutomatedEmailFixture(
        IndieStudio,
        f'Final Reminder to submit your game to {c.EVENT_NAME}',
        'mivs/game_reminder.txt',
        lambda studio: not studio.games,
        'mivs_game_submission_final_reminder',
        sender=c.INDIE_SHOWCASE_EMAIL,
        when=[days_before(2, c.MIVS_DEADLINE)])

    AutomatedEmailFixture(
        IndieStudio,
        f'{c.EVENT_NAME} checklist items due',
        'mivs/checklist_reminder.txt', None,
        'mivs_checklist_reminder',
        sender=c.MIVS_EMAIL,
    )

    AutomatedEmailFixture(
        IndieStudio,
        f'{c.EVENT_NAME} checklist items due',
        'indie_arcade/checklist_reminder.txt', None,
        'indie_arcade_checklist_reminder',
        sender=c.INDIE_ARCADE_EMAIL
    )

    AutomatedEmailFixture(
        IndieStudio,
        f'{c.EVENT_NAME} checklist items due',
        'indie_retro/checklist_reminder.txt', None,
        'indie_retro_checklist_reminder',
        sender=c.INDIE_RETRO_EMAIL
    )

    AutomatedEmailFixture(
        AdminAccount,
        f'New {c.EVENT_NAME} Indies Judge Account',
        'accounts/new_account.txt', None,
        'new_judge_admin_account',
        sender=c.INDIE_SHOWCASE_EMAIL,
        send_filter=lambda a: a.admin_account,
    )

    AutomatedEmailFixture(
        IndieJudge,
        f'Welcome as a {c.EVENT_NAME} Indies Judge!',
        'judge_welcome.html',
        lambda judge: judge.showcases and len(judge.showcases_ints) > 1,
        'multi_judge_welcome',
        sender=c.INDIE_SHOWCASE_EMAIL,
    )

    AutomatedEmailFixture(
        IndieGame,
        f'{c.EVENT_NAME} Indies December Update',
        'mivs/2022/december_update.txt',
        lambda game: game.confirmed,
        'indies_december_update',
        sender=c.INDIE_SHOWCASE_EMAIL,
    )

    AutomatedEmailFixture(
        IndieJudge,
        f'Indies Judging Disqualification',
        'mivs/judge_disqualified.txt', None,
        'indies_judge_disqualified',
        sender=c.INDIE_SHOWCASE_EMAIL,
    )

    AutomatedEmailFixture(
        IndieJudge,
        'Video Problems Resolved',
        'mivs/video_fixed.txt', None,
        'indies_video_problems_fixed',
        sender=c.INDIE_SHOWCASE_EMAIL,
    )

    AutomatedEmailFixture(
        IndieJudge,
        'Game Problems Resolved',
        'mivs/game_fixed.txt', None,
        'indies_game_problems_fixed',
        sender=c.INDIE_SHOWCASE_EMAIL,
    )

    AdminReportEmailFixture(
        'Indies Video Submission Marked as Broken',
        'mivs/admin_video_broken.txt',
        'indies_video_problems_admin',
        sender=c.INDIE_SHOWCASE_EMAIL,
    )

    AdminReportEmailFixture(
        'Indies Game Submission Marked as Broken',
        'mivs/admin_game_broken.txt',
        'indies_game_problems_admin',
        sender=c.INDIE_SHOWCASE_EMAIL,
    )


class RetroEmailFixture(AutomatedEmailFixture):
    def __init__(self, *args, **kwargs):
        if len(args) < 4 and 'filter' not in kwargs:
            kwargs['filter'] = lambda x: True
        AutomatedEmailFixture.__init__(self, *args, sender=c.INDIE_RETRO_EMAIL, **kwargs)


class RetroGuestEmailFixture(AutomatedEmailFixture):
    def __init__(self, subject, template, filter, ident, **kwargs):
        AutomatedEmailFixture.__init__(
            self,
            GuestGroup,
            subject,
            template,
            lambda mg: mg.group_type == c.MIVS and mg.group.studio and mg.matches_showcases([c.INDIE_RETRO]) and filter(mg),
            ident,
            sender=c.INDIE_RETRO_EMAIL,
            **kwargs)


if c.INDIE_RETRO_START:
    RetroEmailFixture(
        IndieGame,
        'Your Indie Retro Game Has Been Submitted',
        'indie_retro/game_submitted.txt',
        lambda game: game.submitted and game.showcase_type == c.INDIE_RETRO,
        'retro_game_submitted')

    RetroEmailFixture(
        IndieJudge,
        'Welcome as an Indie Retro Judge!',
        'indie_retro/judge_welcome.html',
        lambda judge: judge.single_showcase == c.INDIE_RETRO,
        'retro_judge_welcome')
    
    RetroGuestEmailFixture(
        f'{c.EVENT_NAME} Indie Retro Checklist',
        'indie_arcade/checklist_open.txt',
        lambda mg: True,
        'ia_checklist_open'
    )


class IAEmailFixture(AutomatedEmailFixture):
    def __init__(self, *args, **kwargs):
        if len(args) < 4 and 'filter' not in kwargs:
            kwargs['filter'] = lambda x: True
        AutomatedEmailFixture.__init__(self, *args, sender=c.INDIE_ARCADE_EMAIL, **kwargs)


class IAGuestEmailFixture(AutomatedEmailFixture):
    def __init__(self, subject, template, filter, ident, **kwargs):
        AutomatedEmailFixture.__init__(
            self,
            GuestGroup,
            subject,
            template,
            lambda mg: mg.group_type == c.MIVS and mg.group.studio and mg.matches_showcases([c.INDIE_ARCADE]) and filter(mg),
            ident,
            sender=c.INDIE_ARCADE_EMAIL,
            **kwargs)


if c.INDIE_ARCADE_START:
    IAEmailFixture(
        IndieGame,
        'Your Indie Arcade Game Has Been Submitted',
        'indie_arcade/game_submitted.txt',
        lambda game: game.submitted and game.showcase_type == c.INDIE_ARCADE,
        'ia_game_submitted')
    
    IAEmailFixture(
        IndieJudge,
        'Welcome as an Indie Arcade Judge!',
        'indie_arcade/judge_welcome.html',
        lambda judge: judge.single_showcase == c.INDIE_ARCADE,
        'ia_judge_welcome')

    IAEmailFixture(
        IndieGame,
        f'Your game has been accepted into the {c.EVENT_NAME} Indie Arcade',
        'indie_arcade/game_accepted.txt',
        lambda game: game.status == c.ACCEPTED and not game.waitlisted and game.showcase_type == c.INDIE_ARCADE,
        'ia_game_accepted')

    IAEmailFixture(
        IndieGame,
        f'Your game has been accepted into the {c.EVENT_NAME} Indie Arcade from our waitlist',
        'indie_arcade/game_accepted_from_waitlist.txt',
        lambda game: game.status == c.ACCEPTED and game.waitlisted and game.showcase_type == c.INDIE_ARCADE,
        'ia_game_accepted_from_waitlist')

    IAEmailFixture(
        IndieGame,
        f'Your game application has been declined from the {c.EVENT_YEAR} Indie Arcade',
        'indie_arcade/game_declined.txt',
        lambda game: game.status == c.DECLINED and game.showcase_type == c.INDIE_ARCADE,
        'ia_game_declined')

    IAEmailFixture(
        IndieGame,
        'Your Indie Arcade application has been waitlisted',
        'indie_arcade/game_waitlisted.txt',
        lambda game: game.status == c.WAITLISTED and game.showcase_type == c.INDIE_ARCADE,
        'ia_game_waitlisted')
    
    IAGuestEmailFixture(
        f'{c.EVENT_NAME_AND_YEAR} Indie Arcade Checklist',
        'indie_arcade/checklist_open.txt',
        lambda mg: True,
        'ia_checklist_open'
    )

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
            lambda mg: mg.group_type == c.MIVS and mg.group.studio and mg.matches_showcases([c.MIVS]) and filter(mg),
            ident,
            sender=c.MIVS_EMAIL,
            **kwargs)


if c.MIVS_START:
    MIVSEmailFixture(
        IndieGame,
        'Your MIVS Game Has Been Submitted',
        'mivs/game_submitted.txt',
        lambda game: game.submitted and game.showcase_type == c.MIVS,
        'mivs_game_submitted')

    MIVSEmailFixture(
        IndieGame,
        'MIVS: Your Submitted Video Is Broken',
        'mivs/video_broken.txt',
        lambda game: game.video_broken and game.showcase_type == c.MIVS,
        'mivs_video_broken')

    MIVSEmailFixture(
        IndieGame,
        'Your game has been accepted into MIVS',
        'mivs/game_accepted.txt',
        lambda game: game.status == c.ACCEPTED and not game.waitlisted and game.showcase_type == c.MIVS,
        'mivs_game_accepted')

    MIVSEmailFixture(
        IndieGame,
        'Your game has been accepted into MIVS from our waitlist',
        'mivs/game_accepted_from_waitlist.txt',
        lambda game: game.status == c.ACCEPTED and game.waitlisted and game.showcase_type == c.MIVS,
        'mivs_game_accepted_from_waitlist')

    MIVSEmailFixture(
        IndieGame,
        'Your game application has been declined from MIVS',
        'mivs/game_declined.txt',
        lambda game: game.status == c.DECLINED and game.showcase_type == c.MIVS,
        'mivs_game_declined')

    MIVSEmailFixture(
        IndieGame,
        'Your MIVS application has been waitlisted',
        'mivs/game_waitlisted.txt',
        lambda game: game.status == c.WAITLISTED and game.showcase_type == c.MIVS,
        'mivs_game_waitlisted')

    MIVSEmailFixture(
        IndieGame,
        f'MIVS {c.EVENT_YEAR} Waitlist: Additional Information Required',
        'mivs/waitlist_info.txt',
        lambda game: game.status == c.WAITLISTED and game.showcase_type == c.MIVS,
        'mivs_waitlist_info'
    )

    MIVSEmailFixture(
        IndieGame,
        'Last chance to accept your MIVS booth',
        'mivs/game_accept_reminder.txt',
        lambda game: (
            game.status == c.ACCEPTED and game.showcase_type == c.MIVS
            and not game.confirmed
            and (localized_now() + timedelta(days=2)) > game.studio.confirm_deadline),
        'mivs_accept_booth_reminder')

    MIVSEmailFixture(
        IndieGame,
        'Summary of judging feedback for your game',
        'mivs/reviews_summary.html',
        lambda game: game.status in c.FINAL_MIVS_GAME_STATUSES and game.reviews_to_email and game.showcase_type == c.MIVS,
        'mivs_reviews_summary',
        allow_post_con=True)

    MIVSEmailFixture(
        IndieGame,
        'MIVS judging is wrapping up',
        'mivs/results_almost_ready.txt',
        lambda game: game.submitted and game.showcase_type == c.MIVS,
        'mivs_results_almost_ready',
        when=[days_before(14, c.MIVS_JUDGING_DEADLINE)],)

    MIVSEmailFixture(
        IndieJudge,
        'Welcome as a MIVS Judge!',
        'mivs/judging/judge_welcome.html',
        lambda judge: judge.single_showcase == c.MIVS,
        'mivs_judge_welcome')

    MIVSEmailFixture(
        IndieJudge,
        'Reminder to update your MIVS Judge status',
        'mivs/judging/judge_welcome_reminder.txt',
        lambda judge: judge.status == c.UNCONFIRMED and judge.single_showcase == c.MIVS,
        'mivs_judge_welcome_reminder')

    MIVSEmailFixture(
        IndieJudge,
        'MIVS Judging is about to begin!',
        'mivs/judge_intro.txt',
        lambda judge: judge.status == c.CONFIRMED and judge.single_showcase == c.MIVS,
        'mivs_judge_intro')

    MIVSEmailFixture(
        IndieJudge,
        'MIVS Judging has begun!',
        'mivs/judging_begun.txt',
        lambda judge: judge.status == c.CONFIRMED and judge.single_showcase == c.MIVS,
        'mivs_judging_has_begun')

    MIVSEmailFixture(
        IndieJudge,
        'MIVS Judging is almost over!',
        'mivs/judging_reminder.txt',
        lambda judge: judge.status == c.CONFIRMED and judge.single_showcase == c.MIVS,
        'mivs_judging_due_reminder',
        when=[days_before(7, c.SOFT_MIVS_JUDGING_DEADLINE)])

    MIVSEmailFixture(
        IndieJudge,
        f'Reminder: MIVS Judging due by {c.MIVS_JUDGING_DEADLINE.strftime('%B %-d')}',
        'mivs/judging_reminder.txt',
        lambda judge: not judge.judging_complete and judge.status == c.CONFIRMED and judge.single_showcase == c.MIVS,
        'mivs_judging_due_reminder_last_chance',
        when=[days_before(5, c.MIVS_JUDGING_DEADLINE)])

    MIVSEmailFixture(
        IndieJudge,
        f'MIVS Judging survey and {c.EVENT_NAME} badge information',
        'mivs/judge_badge_info.txt',
        lambda judge: judge.status == c.CONFIRMED and judge.single_showcase == c.MIVS,
        'mivs_judge_badge_info')

    MIVSEmailFixture(
        IndieGame,
        'MIVS: Tournaments and Leaderboard Challenges',
        'mivs/confirmed/tournaments.txt',
        lambda game: game.confirmed and game.showcase_type == c.MIVS,
        'mivs_tournaments'
    )

    MIVSGuestEmailFixture(
        f'{c.EVENT_NAME} MIVS Checklist',
        'mivs/checklist_open.txt',
        lambda mg: True,
        'mivs_checklist_open'
    )

    MIVSGuestEmailFixture(
        f'New {c.EVENT_NAME} MIVS Checklist Item: Update Studio and Game Information',
        'mivs/checklist/new_update_studio_information.txt',
        lambda mg: True,
        'mivs_checklist_update_studio_information'
    )

    MIVSGuestEmailFixture(
        f'New {c.EVENT_NAME} MIVS Checklist Item: MIVS Indie Handbook',
        'mivs/checklist/new_update_indiehandbook_information.txt',
        lambda mg: True,
        'mivs_checklist_update_indiehandbook_information'
    )

    MIVSGuestEmailFixture(
        f'New {c.EVENT_NAME} MIVS Checklist Item: Selling Information',
        'mivs/checklist/new_update_selling_information.txt',
        lambda mg: True,
        'mivs_checklist_update_selling_information'
    )

    MIVSGuestEmailFixture(
        f'New {c.EVENT_NAME} MIVS Checklist Item: Hotel Signups',
        'mivs/checklist/new_update_hotel_information.txt',
        lambda mg: True,
        'mivs_checklist_update_hotel_information'
    )

    MIVSGuestEmailFixture(
        f'New {c.EVENT_NAME} MIVS Checklist Item: MIVS Training',
        'mivs/checklist/new_update_training_information.txt',
        lambda mg: True,
        'mivs_checklist_update_training_information'
    )

    # At-Con MIVS Emails
    MIVSEmailFixture(
        IndieGame,
        f'{c.EVENT_NAME} MIVS {c.EVENT_YEAR}: Wednesday Setup',
        'mivs/At-Con/LoadIn.txt',
        lambda game: game.confirmed and game.showcase_type == c.MIVS,
        'mivs_LoadIn.txt'
    )

    MIVSEmailFixture(
        IndieGame,
        f'{c.EVENT_NAME} MIVS {c.EVENT_YEAR}: Thursday, Day 1',
        'mivs/At-Con/Day1.txt',
        lambda game: game.confirmed and game.showcase_type == c.MIVS,
        'mivs_Day1.txt'
    )

    # post con emails
    MIVSEmailFixture(
        IndieGame,
        f'{c.EVENT_NAME} MIVS {c.EVENT_YEAR}: Request for Feedback',
        'mivs/feedback/indie_survey.txt',
        lambda game: game.confirmed and game.showcase_type == c.MIVS,
        'mivs_feedback_survey',
        allow_post_con=True,
    )


# =============================
# mits
# =============================
class MITSEmailFixture(AutomatedEmailFixture):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('sender', c.MITS_EMAIL)
        AutomatedEmailFixture.__init__(self, MITSTeam, *args, **kwargs)


if c.MITS_START:
    AutomatedEmailFixture(
        None, f'{c.EVENT_NAME_AND_YEAR} MITS Team Confirmation',
        'mits/mits_check.txt', None,
        'mits_team_check', sender=c.MITS_EMAIL
    )

    # We wait an hour before sending out this email because the most common case
    # of someone registering their team is that they'll immediately fill out the
    # entire application, so there's no reason to send them an email showing their
    # currently completion percentage when that info will probably be out of date
    # by the time they read it. By waiting an hour, we ensure this doesn't happen.
    MITSEmailFixture(
        'Thanks for showing an interest in MITS!',
        'mits/mits_registered.txt',
        lambda team: not team.submitted and team.applied < datetime.now(UTC) - timedelta(hours=1),
        'mits_application_created')

    # For similar reasons to the above, we wait at least 6 hours before sending this
    # email because it would seem silly to immediately send someone a "last chance"
    # email the minute they registered their team. By waiting 6 hours, we wait
    # until they've had a chance to complete the application and even receive the
    # initial reminder email above before being pestered with this warning.
    MITSEmailFixture(
        'Last chance to complete your MITS application!',
        'mits/mits_reminder.txt',
        lambda team: not team.submitted and team.applied < datetime.now(UTC) - timedelta(hours=6),
        'mits_reminder',
        when=[days_before(3, c.MITS_SUBMISSION_DEADLINE)])

    MITSEmailFixture(
        'Thanks for submitting your MITS application!',
        'mits/mits_submitted.txt',
        lambda team: team.submitted,
        'mits_application_submitted')

    MITSEmailFixture(
        'Please fill out the remainder of your MITS application',
        'mits/mits_preaccepted.txt',
        lambda team: team.accepted and team.completion_percentage < 100,
        'mits_preaccepted_incomplete')

    MITSEmailFixture(
        'MITS initial panel information',
        'mits/mits_initial_panel_info.txt',
        lambda team: team.accepted and team.panel_interest,
        'mits_initial_panel_info')

    MITSEmailFixture(
        f'Please sign the MITS waiver for {c.EVENT_NAME}',
        'mits/mits_waiver.txt',
        lambda team: team.accepted and not team.waiver_signed,
        'mits_waiver')

    MITSEmailFixture(
        f'Reminder to sign the MITS waiver for {c.EVENT_NAME}',
        'mits/mits_waiver.txt',
        lambda team: team.accepted and not team.waiver_signed,
        'mits_waiver_reminder',
        when=[days_before(10, c.EPOCH)])

    MITSEmailFixture(
        'Tax Form for selling in MITS',
        'mits/mits_tax_form.txt',
        lambda team: team.accepted and team.want_to_sell,
        'mits_tax_form')

    MITSEmailFixture(
        'MITS 2024 Developer Perspective Feedback',
        'mits/mits_feedback.txt',
        lambda team: team.accepted,
        'mits_feedback',
        allow_post_con=True)

    AutomatedEmailFixture(
        MITSApplicant,
        f'{c.EVENT_NAME} parking information',
        'mits/mits_parking.txt',
        lambda ma: ma.attendee and ma.team and ma.team.accepted,
        'mits_parking',
        sender=c.MITS_EMAIL)

    AutomatedEmailFixture(
        MITSApplicant,
        'Automated MITS FAQ Email',
        'mits/mits_faq.html',
        lambda ma: ma.attendee and ma.team and ma.team.accepted,
        'mits_faq',
        sender=c.MITS_EMAIL)

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
                not app.submitter.attendee_id
                ),
            ident,
            sender=kwargs.pop('sender', c.PANELS_EMAIL),
            **kwargs)


if c.PANELS_START:
    PanelAppEmailFixture(
        f'Your {c.EVENT_NAME} Panel Application Has Been Received: ' + '{app.name}',
        'panels/application.html',
        lambda a: True,
        'panel_received')

    PanelAppEmailFixture(
        f'Your {c.EVENT_NAME} Panel Application Has Been Accepted: ' + '{app.name}',
        'panels/panel_app_accepted.txt',
        lambda app: app.status == c.ACCEPTED and app.department in c.EMAILLESS_PANEL_DEPTS,
        'panel_accepted')

    PanelAppEmailFixture(
        f'Your {c.EVENT_NAME} Panel Application Has Been Declined: ' + '{app.name}',
        'panels/panel_app_declined.txt',
        lambda app: app.status == c.DECLINED and app.department in c.EMAILLESS_PANEL_DEPTS,
        'panel_declined')

    PanelAppEmailFixture(
        f'Your {c.EVENT_NAME} Panel Application Has Been Waitlisted: ' + '{app.name}',
        'panels/panel_app_waitlisted.txt',
        lambda app: app.status == c.WAITLISTED and app.department in c.EMAILLESS_PANEL_DEPTS,
        'panel_waitlisted')

    PanelAppEmailFixture(
        'Last chance to confirm your panel',
        'panels/panel_accept_reminder.txt',
        lambda app: (
            c.PANELS_CONFIRM_DEADLINE
            and app.confirm_deadline
            and app.department in c.EMAILLESS_PANEL_DEPTS
            and (localized_now() + timedelta(days=2)) > app.confirm_deadline),
        'panel_accept_reminder')

    PanelAppEmailFixture(
        f'Your {c.EVENT_NAME} Panel Application Has Been Automatically Waitlisted: ' + '{app.name}',
        'panels/panel_app_waitlisted.txt', None,
        'panel_waitlisted',
        send_filter=lambda app: app.status == c.WAITLISTED,
        shared_ident='panelapps_waitlisted'
    )

    PanelAppEmailFixture(
        f'Your {c.EVENT_NAME} Panel Has Been Scheduled: ' + '{app.name}',
        'panels/panel_app_scheduled.txt',
        lambda app: app.event_id and app.department in c.EMAILLESS_PANEL_DEPTS,
        'panel_scheduled')

    AutomatedEmailFixture(
        Attendee,
        f'Your {c.EVENT_NAME} Event Schedule',
        'panels/panelist_schedule.txt',
        lambda a: a.badge_type != c.GUEST_BADGE and a.assigned_panelists,
        'event_schedule',
        sender=c.PANELS_EMAIL)


# =============================
# guests
# =============================

class ArenaEmailFixture(AutomatedEmailFixture):
    def __init__(self, subject, template, filter, ident, **kwargs):
        AutomatedEmailFixture.__init__(
            self,
            GuestGroup,
            subject,
            template,
            lambda b: b.group_type == c.ARENA and filter(b),
            ident,
            sender=c.ARENA_EMAIL,
            **kwargs)


class BandEmailFixture(AutomatedEmailFixture):
    def __init__(self, subject, template, filter, ident, **kwargs):
        AutomatedEmailFixture.__init__(
            self,
            GuestGroup,
            subject,
            template,
            lambda b: b.group_type in [c.BAND, c.SIDE_STAGE] and filter(b),
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


AdminReportEmailFixture(
    '{guest.group.name} Meet & Greet Notification',
    'guests/meetgreet_notification.txt',
    'guest_meet_greet_admin',
    sender=c.ROCK_ISLAND_EMAIL,
)


AdminReportEmailFixture(
    '{guest.group.name} Donation Notification',
    'guests/charity_notification.txt',
    'guest_charity_admin',
    sender=c.CHARITY_EMAIL,
)


AdminReportEmailFixture(
    f'{c.EVENT_NAME} Rock Island Inventory Updates',
    'daily_checks/ri_inventory_updates.html',
    'rock_island_updates_admin',
    sender=c.REPORTS_EMAIL
)


BandEmailFixture(
    f'{c.EVENT_NAME} Performer Checklist',
    'guests/band_notification.txt',
    lambda b: True,
    'band_checklist_inquiry')

BandEmailFixture(
    f'Reminder to apply for a {c.EVENT_NAME} Panel',
    'guests/band_panel_reminder.txt',
    lambda b: not b.panel_status,
    'band_panel_reminder',
    when=[days_before(14, c.BAND_PANEL_DEADLINE, 3)])

BandEmailFixture(
    f'Last chance to apply for a {c.EVENT_NAME} Panel',
    'guests/band_panel_reminder.txt',
    lambda b: not b.panel_status,
    'band_panel_reminder_last',
    when=[days_before(3, c.BAND_PANEL_DEADLINE)])

BandEmailFixture(
    f'Reminder to accept your offer to perform at {c.EVENT_NAME}',
    'guests/band_agreement_reminder.txt',
    lambda b: not b.info_status,
    'band_agreement_reminder',
    when=[days_before(14, c.BAND_INFO_DEADLINE, 3)])

BandEmailFixture(
    f'Last chance to accept your offer to perform at {c.EVENT_NAME}',
    'guests/band_agreement_reminder.txt',
    lambda b: not b.info_status,
    'band_agreement_reminder_last',
    when=[days_before(3, c.BAND_INFO_DEADLINE)])

BandEmailFixture(
    f'Reminder to include your bio info on the {c.EVENT_NAME} website',
    'guests/band_bio_reminder.txt',
    lambda b: not b.bio_status,
    'band_bio_reminder',
    when=[days_before(14, c.BAND_BIO_DEADLINE, 3)])

BandEmailFixture(
    f'Last chance to include your bio info on the {c.EVENT_NAME} website',
    'guests/band_bio_reminder.txt',
    lambda b: not b.bio_status,
    'band_bio_reminder_last',
    when=[days_before(3, c.BAND_BIO_DEADLINE)])

BandEmailFixture(
    f'Reminder to submit your W9 for {c.EVENT_NAME}',
    'guests/band_w9_reminder.txt',
    lambda b: b.payment and not b.taxes_status,
    'band_w9_reminder',
    when=[days_before(14, c.BAND_TAXES_DEADLINE, 3)])

BandEmailFixture(
    f'Last chance to submit your W9 for {c.EVENT_NAME}',
    'guests/band_w9_reminder.txt',
    lambda b: b.payment and not b.taxes_status,
    'band_w9_reminder_last',
    when=[days_before(3, c.BAND_TAXES_DEADLINE)])

BandEmailFixture(
    f'Reminder to sign up for selling merchandise at {c.EVENT_NAME}',
    'guests/band_merch_reminder.txt',
    lambda b: not b.merch_status,
    'band_merch_reminder',
    when=[days_before(14, c.BAND_MERCH_DEADLINE, 3)])

BandEmailFixture(
    f'Last chance to sign up for selling merchandise at {c.EVENT_NAME}',
    'guests/band_merch_reminder.txt',
    lambda b: not b.merch_status,
    'band_merch_reminder_last',
    when=[days_before(3, c.BAND_MERCH_DEADLINE)])

BandEmailFixture(
    f'Reminder to submit items for the {c.EVENT_NAME} charity auction',
    'guests/band_charity_reminder.txt',
    lambda b: not b.charity_status,
    'band_charity_reminder',
    when=[days_before(14, c.BAND_CHARITY_DEADLINE, 3)])

BandEmailFixture(
    f'Last chance to submit items for the {c.EVENT_NAME} charity auction',
    'guests/band_charity_reminder.txt',
    lambda b: not b.charity_status,
    'band_charity_reminder_last',
    when=[days_before(3, c.BAND_CHARITY_DEADLINE)])

BandEmailFixture(
    f'Reminder to submit a stage plot for {c.EVENT_NAME}',
    'guests/band_stage_plot_reminder.txt',
    lambda b: not b.stage_plot_status,
    'band_stage_plot_reminder',
    when=[days_before(14, c.BAND_STAGE_PLOT_DEADLINE, 3)])

BandEmailFixture(
    f'Last chance to submit a stage plot for {c.EVENT_NAME}',
    'guests/band_stage_plot_reminder.txt',
    lambda b: not b.stage_plot_status,
    'band_stage_plot_reminder_last',
    when=[days_before(3, c.BAND_STAGE_PLOT_DEADLINE)])

GuestEmailFixture(
    f'It\'s time to send us your info for {c.EVENT_NAME}!',
    'guests/guest_checklist_announce.html',
    lambda g: True,
    'guest_checklist_inquiry')

GuestEmailFixture(
    f'Reminder: Please complete your Guest Checklist for {c.EVENT_NAME}!',
    'guests/guest_checklist_reminder.html',
    lambda g: not g.checklist_completed,
    'guest_reminder_1',
    when=[days_before(7, c.GUEST_INFO_DEADLINE)])

GuestEmailFixture(
    f'Have you forgotten anything? Your {c.EVENT_NAME} Guest Checklist needs you!',
    'guests/guest_checklist_reminder.html',
    lambda g: not g.checklist_completed,
    'guest_reminder_2',
    when=[days_after(7, c.GUEST_INFO_DEADLINE)])

ArenaEmailFixture(
    f'It\'s time to send us your info for {c.EVENT_NAME}!',
    'guests/guest_checklist_announce.html',
    lambda g: True,
    'arena_checklist_inquiry')

ArenaEmailFixture(
    f'Reminder: Please complete your Arena Checklist for {c.EVENT_NAME}!',
    'guests/guest_checklist_reminder.html',
    lambda g: not g.checklist_completed,
    'arena_reminder_1',
    when=[days_before(7, c.ARENA_INFO_DEADLINE)])

ArenaEmailFixture(
    f'Have you forgotten anything? Your {c.EVENT_NAME} Arena Checklist needs you!',
    'guests/guest_checklist_reminder.html',
    lambda g: not g.checklist_completed,
    'arena_reminder_2',
    when=[days_after(7, c.ARENA_INFO_DEADLINE)])

AutomatedEmailFixture(
    GuestGroup,
    f'Sign up to sell merch at {c.EVENT_NAME} Rock Island',
    'guests/rock_island_intro.txt',
    lambda g: g.group_type in c.ROCK_ISLAND_GROUPS and g.deadline_from_model('merch') and not g.group_type == c.BAND,
    'rock_island_intro',
    sender=c.ROCK_ISLAND_EMAIL)

AutomatedEmailFixture(
    GuestGroup,
    f'Last chance to finalize your {c.EVENT_NAME} Rock Island Inventory',
    'guests/rock_island_inventory_reminder.txt',
    lambda g: g.group_type in c.ROCK_ISLAND_GROUPS and g.merch and g.merch.selling_merch == c.ROCK_ISLAND,
    'ri_inventory_reminder',
    when=[days_before(7, c.ROCK_ISLAND_DEADLINE)],
    sender=c.ROCK_ISLAND_EMAIL)