from uber.common import *

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

AutomatedEmail(Attendee, '{EVENT_NAME} registration confirmed', 'reg_workflow/attendee_confirmation.html',
                lambda a: a.paid == c.NEED_NOT_PAY and (a.confirmed or a.promo_code_id),
                needs_approval=False, allow_during_con=True,
                ident='attendee_badge_confirmed')

AutomatedEmail(Group, '{EVENT_NAME} group payment received', 'reg_workflow/group_confirmation.html',
         lambda g: g.amount_paid == g.cost and g.cost != 0 and g.leader_id,
         needs_approval=False,
         ident='group_payment_received')

AutomatedEmail(Attendee, '{EVENT_NAME} group registration confirmed', 'reg_workflow/attendee_confirmation.html',
         lambda a: a.group and (a.id != a.group.leader_id or a.group.cost == 0) and not a.placeholder,
         needs_approval=False, allow_during_con=True,
         ident='attendee_group_reg_confirmation')

AutomatedEmail(Attendee, '{EVENT_NAME} extra payment received', 'reg_workflow/group_donation.txt',
         lambda a: a.paid == c.PAID_BY_GROUP and a.amount_extra and a.amount_paid == a.amount_extra,
         needs_approval=False,
         ident='group_extra_payment_received')

if c.PREREG_REQUEST_HOTEL_INFO_ENABLED:
    AutomatedEmail(Attendee, '{EVENT_NAME} hotel booking info', 'reg_workflow/hotel_booking_info.html',
        lambda a: a.requested_hotel_info,
        when=days_after(0, c.PREREG_HOTEL_INFO_EMAIL_DATE),
        needs_approval=True,
        sender=c.PREREG_HOTEL_INFO_EMAIL_SENDER,
        ident='hotel_booking_info')


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
               lambda a: a.placeholder and a.first_name and a.last_name and c.PANELIST_RIBBON in a.ribbon_ints,
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
                                       and not set([c.DEALER_RIBBON, c.PANELIST_RIBBON, c.VOLUNTEER_RIBBON]).intersection(a.ribbon_ints)),
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
           lambda a: c.SHIFTS_CREATED and c.VOLUNTEER_RIBBON in a.ribbon_ints and a.takes_shifts and a.weighted_hours == 0,
           when=days_before(28, c.FINAL_EMAIL_DEADLINE),
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
