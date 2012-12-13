from common import *

class Reminder:
    instances = []
    
    def __init__(self, model, subject, template, filter, sender=REGDESK_EMAIL):
        self.model, self.subject, self.template, self.filter, self.sender = model, subject, template, filter, sender
        self.instances.append(self)
    
    def __str__(self):
        return "<Email: subject={!r}>".format(self.subject)
    
    def prev(self, x, all_sent = None):
        if all_sent:
            return all_sent.get((x.__class__.__name__, x.id, self.subject))
        else:
            try:
                return Email.objects.get(fk_tab=x.__class__.__name__, fk_id=x.id, subject=self.subject)
            except:
                return None
    
    def should_send(self, x, all_sent = None):
        return not self.prev(x, all_sent) and self.filter(x)
    
    def send(self, x, raise_errors = True):
        try:
            body = render("emails/" + self.template, {x.__class__.__name__.lower(): x})
            format = "text" if self.template.endswith(".txt") else "html"
            send_email(self.sender, x.email, self.subject, body, format)
            Email.objects.create(fk_tab=x.__class__.__name__, fk_id=x.id, subject=self.subject, dest=x.email, body=body)
        except:
            log.error("error sending {0!r} email to {1}", self.subject, x.email, exc_info=True)
            if raise_errors:
                raise
    
    @staticmethod
    def send_all(raise_errors = False):
        attendees, groups = Group.everyone()
        models = {Attendee: attendees, Group: groups}
        all_sent = {(e.fk_tab, e.fk_id, e.subject): e for e in Email.objects.all()}
        if state.AUTO_EMAILS:
            for rem in Reminder.instances:
                for x in models[rem.model]:
                    if x.email and rem.should_send(x, all_sent):
                        rem.send(x, raise_errors = raise_errors)


### WARNING - changing the email subject line for a reminder causes ALL of those reminders to be re-sent

Reminder(Attendee, "Reminder to pay for MAGFest", "attendee_payment_reminder.txt",
         lambda a: a.paid == NOT_PAID and a.registered < datetime.now() - timedelta(days = 7))

Reminder(Attendee, "Last chance to pay for your MAGFest badge", "attendee_payment_reminder.txt",
         lambda a: a.paid == NOT_PAID and a.registered < datetime.now() - timedelta(days = 12))

Reminder(Group, "Reminder to pay for your MAGFest group", "group_payment_reminder.txt",
         lambda g: g.tables == 0 and g.amount_owed > 0 and g.amount_paid == 0
                                 and g.registered < datetime.now() - timedelta(days = 7))

Reminder(Group, "Last chance to pay for your MAGFest group", "group_payment_reminder.txt",
         lambda g: g.tables == 0 and g.amount_owed > 0 and g.amount_paid == 0
                                 and g.registered < datetime.now() - timedelta(days = 12))

Reminder(Group, "Reminder to pay for your MAGFest Dealer registration", "dealer_payment_reminder.txt",
         lambda g: g.is_dealer and g.status == APPROVED and g.amount_owed > 0 and g.amount_paid == 0
                               and g.approved < datetime.now() - timedelta(days = 30),
         sender = MARKETPLACE_EMAIL)

Reminder(Group, "Your MAGFest Dealer registration is due in one week", "dealer_payment_reminder.txt",
         lambda g: g.is_dealer and g.status == APPROVED and g.amount_owed > 0 and g.amount_paid == 0
                               and state.DEALER_PAYMENT_DUE < datetime.now() + timedelta(days = 7),
         sender = MARKETPLACE_EMAIL)

Reminder(Group, "Last chance to pay for your MAGFest Dealer registration", "dealer_payment_reminder.txt",
         lambda g: g.is_dealer and g.status == APPROVED and g.amount_owed > 0 and g.amount_paid == 0
                               and state.DEALER_PAYMENT_DUE < datetime.now() + timedelta(days = 2),
         sender = MARKETPLACE_EMAIL)

Reminder(Group, "MAGFest Dealer waitlist has been exhausted", "dealer_waitlist_closing.txt",
         lambda g: state.DEALER_WAITLIST_CLOSED and g.is_dealer and g.status == WAITLISTED,
         sender = MARKETPLACE_EMAIL)



Reminder(Group, "Your MAGFest Dealer registration has been approved", "dealer_approved.html",
         lambda g: g.is_dealer and g.status == APPROVED,
         sender = MARKETPLACE_EMAIL)

Reminder(Attendee, "MAGFest payment received", "attendee_confirmation.html",
         lambda a: a.paid == HAS_PAID and a.amount_paid == a.total_cost)

Reminder(Group, "MAGFest group payment received", "group_confirmation.html",
         lambda g: g.amount_paid == g.total_cost)



Reminder(Attendee, "MAGFest Badge Confirmation", "badge_confirmation.txt",
         lambda a: a.placeholder and a.first_name and a.last_name and a.email
                                 and a.badge_type not in [GUEST_BADGE, STAFF_BADGE]
                                 and a.ribbon not in [PANELIST_RIBBON, VOLUNTEER_RIBBON])

Reminder(Attendee, "MAGFest Panelist Badge Confirmation", "panelist_confirmation.txt",
         lambda a: a.placeholder and a.first_name and a.last_name and a.email
                                 and (a.badge_type == GUEST_BADGE or a.ribbon == PANELIST_RIBBON),
         sender = "panels@magfest.org")

Reminder(Attendee, "MAGFest Volunteer Badge Confirmation", "volunteer_confirmation.txt",
         lambda a: a.placeholder and a.first_name and a.last_name and a.email and a.staffing
                                 and a.registered.date() > state.STAFFERS_IMPORTED.date(),
         sender = STAFF_EMAIL)



Reminder(Attendee, "Want to staff MAGFest again?", "imported_staffer.txt",
         lambda a: a.placeholder and a.first_name and a.last_name and a.email and a.staffing
                                 and a.registered.date() <= state.STAFFERS_IMPORTED.date(),
         sender = STAFF_EMAIL)

Reminder(Attendee, "MAGFest shifts available", "shifts_available.txt",
         lambda a: state.SHIFTS_AVAILABLE and a.takes_shifts,
         sender = STAFF_EMAIL)

Reminder(Attendee, "Reminder to sign up for MAGFest shifts", "shift_reminder.txt",
         lambda a: state.SHIFTS_AVAILABLE and not state.PREREG_CLOSED and a.takes_shifts and not a.hours
                                          and max(a.registered, state.SHIFTS_CREATED) < datetime.now() - timedelta(days = 30),
         sender = STAFF_EMAIL)

Reminder(Attendee, "Last chance to sign up for MAGFest shifts", "shift_reminder.txt",
         lambda a: state.SHIFTS_AVAILABLE and not state.PREREG_CLOSED and a.takes_shifts and not a.hours
                                          and datetime.now() > state.EPOCH - timedelta(days = 10),
         sender = STAFF_EMAIL)

Reminder(Attendee, "Want volunteer hotel room space at MAGFest?", "hotel_rooms.txt",
         lambda a: state.SHIFTS_AVAILABLE and a.hotel_eligible and datetime.now() < state.ROOM_DEADLINE,
         sender = STAFF_EMAIL)

Reminder(Attendee, "Reminder to sign up for MAGFest hotel room space", "hotel_reminder.txt",
         lambda a: state.SHIFTS_AVAILABLE and a.hotel_eligible and not a.hotel_requests
                                          and a.registered < state.ROOM_DEADLINE - timedelta(days = 14) < datetime.now() < state.ROOM_DEADLINE,
         sender = STAFF_EMAIL)

Reminder(Attendee, "Last chance to sign up for MAGFest hotel room space", "hotel_reminder.txt",
         lambda a: state.SHIFTS_AVAILABLE and a.hotel_eligible and not a.hotel_requests
                                          and a.registered < state.ROOM_DEADLINE - timedelta(days = 2) < datetime.now() < state.ROOM_DEADLINE,
         sender = STAFF_EMAIL)

Reminder(Attendee, "Last chance to personalize your MAGFest badge", "personalized_badge_reminder.txt",
         lambda a: a.badge_type == STAFF_BADGE and a.placeholder and state.STAFF_BADGE_DEADLINE - timedelta(days = 7) < datetime.now() < state.STAFF_BADGE_DEADLINE,
         sender = STAFF_EMAIL)

Reminder(Attendee, "Personalized MAGFest badges will be ordered next week", "personalized_badge_deadline.txt",
         lambda a: a.badge_type in [STAFF_BADGE, SUPPORTER_BADGE] and not a.placeholder and state.STAFF_BADGE_DEADLINE - timedelta(days = 7) < datetime.now() < state.STAFF_BADGE_DEADLINE)



Reminder(Attendee, "Details on Saturday MAGFest Staff Meeting", "staff_meeting.txt",
         lambda a: a.staffing and datetime(2012, 11, 11) < datetime.now() < datetime(2012, 11, 17, 18),
         sender = STAFF_EMAIL)

Reminder(Attendee, "Hotel reminder for MAGFest department heads", "dept_head_rooms.txt",
         lambda a: a.ribbon == DEPT_HEAD_RIBBON and state.ROOM_DEADLINE - timedelta(days = 9) < datetime.now() < state.ROOM_DEADLINE,
         sender = STAFF_EMAIL)

Reminder(Attendee, "Last chance for Department Heads to get Staff badges for your people", "dept_head_badges.txt",
         lambda a: a.ribbon == DEPT_HEAD_RIBBON and state.STAFF_BADGE_DEADLINE - timedelta(days = 7) < datetime.now() < state.STAFF_BADGE_DEADLINE,
         sender = STAFF_EMAIL)



Reminder(Group, "Reminder to pre-assign MAGFest group badges", "group_preassign_reminder.txt",
         lambda g: state.GROUP_REG_OPEN and not g.is_dealer and g.unregistered_badges
                                        and g.registered < datetime.now() - timedelta(days = 30))

Reminder(Group, "Last chance to pre-assign MAGFest group badges", "group_preassign_reminder.txt",
         lambda g: not state.GROUP_REG_OPEN and g.unregistered_badges and (not g.is_dealer or g.status == APPROVED))



Reminder(Attendee, "MAGFest parental consent form reminder", "under_18_reminder.txt",
         lambda a: a.age_group == UNDER_18 and datetime.now() > state.EPOCH - timedelta(days = 7))


@all_renderable(PEOPLE)
class Root:
    def index(self):
        raise HTTPRedirect("by_sent")
    
    def by_sent(self, page = "1"):
        emails = Email.objects.order_by("-when")
        return {
            "page": page,
            "emails": get_page(page, emails),
            "count": emails.count()
        }
    
    def sent(self, **params):
        return {"emails": Email.objects.filter(**params).order_by("when")}
