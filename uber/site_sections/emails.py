from uber.common import *

class Reminder:
    instances = OrderedDict()
    
    def __init__(self, model, subject, template, filter, sender=REGDESK_EMAIL, extra_data=None, cc=None, post_con=False, category=None):
        self.model, self.subject, self.template, self.sender = model, subject, template, sender
        self.cc = cc or []
        self.extra_data = extra_data or {}
        self.instances[subject] = self
        self.category = category or 'uncategorized'

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
            try:
                return Email.objects.get(model=x.__class__.__name__, fk_id=x.id, subject=self.subject)
            except:
                return None
    
    def should_send(self, x, all_sent = None):
        try:
            email_category_allowed = 'all' in EMAIL_CATEGORIES_ALLOWED_TO_SEND or self.category in EMAIL_CATEGORIES_ALLOWED_TO_SEND
            return not self.prev(x, all_sent) and email_category_allowed and self.filter(x)
        except:
            log.error('unexpected error', exc_info=True)

    def send_email(self, source, dest, subject, body, format = 'text', cc = [], bcc = [], model = None, render_only=False):
        if render_only:
            return {'source': source,'dest': listify(dest),'subject': subject,'body': body,'format': format,'cc': listify(cc),'bcc': listify(bcc)}
        else:
            # really send an email
            send_email(source, dest, subject, body, format, cc, bcc, model)

    def send(self, x, raise_errors = True, render_only = False):
        try:
            body = render('emails/' + self.template, dict({x.__class__.__name__.lower(): x}, **self.extra_data))
            format = 'text' if self.template.endswith('.txt') else 'html'
            return self.send_email(self.sender, x.email, self.subject, body, format, model = x, cc=self.cc, render_only=render_only)
        except:
            log.error('error sending {!r} email to {}', self.subject, x.email, exc_info=True)
            if raise_errors:
                raise

    # if render_only is True, this will return all rendered emails as a list, instead of sending them
    @staticmethod
    def send_all(raise_errors = False, render_only = False):
        dont_send_emails = not SEND_EMAILS or AT_THE_CON
        if dont_send_emails and not render_only:
            return

        results = []
        attendees, groups = Group.everyone()
        models = {Attendee: attendees, Group: groups}
        all_sent = {(e.model, e.fk_id, e.subject): e for e in Email.objects.all()}

        for rem in Reminder.instances.values():
            for x in models[rem.model]:
                if x.email and rem.should_send(x, all_sent):
                    result = rem.send(x, raise_errors = raise_errors, render_only = render_only)
                    results.append(result)

        return results

class StopsReminder(Reminder):
    def __init__(self, subject, template, filter, **kwargs):
        Reminder.__init__(self, Attendee, subject, template, lambda a: a.staffing and filter(a), STAFF_EMAIL, **kwargs)

class GuestReminder(Reminder):
    def __init__(self, subject, template, filter=lambda a: True, **kwargs):
        Reminder.__init__(self, Attendee, subject, template, lambda a: a.badge_type == GUEST_BADGE and filter(a), PANELS_EMAIL, **kwargs)

class DeptHeadReminder(Reminder):
    def __init__(self, subject, template, filter=lambda a: True, sender=STAFF_EMAIL, **kwargs):
        Reminder.__init__(self, Attendee, subject, template, lambda a: a.ribbon == DEPT_HEAD_RIBBON and len(a.assigned) == 1 and filter(a), sender, **kwargs)

class GroupReminder(Reminder):
    def __init__(self, subject, template, filter, **kwargs):
        Reminder.__init__(self, Group, subject, template, lambda g: not g.is_dealer and filter(g), REGDESK_EMAIL, **kwargs)

class MarketplaceReminder(Reminder):
    def __init__(self, subject, template, filter, **kwargs):
        Reminder.__init__(self, Group, subject, template, lambda g: g.is_dealer and filter(g), MARKETPLACE_EMAIL, **kwargs)

# see issue #173 about rewriting this
class SeasonSupporterReminder(Reminder):
    def __init__(self, event):
        Reminder.__init__(self, Attendee,
                                subject = 'Claim your {} tickets with your '+ EVENT_NAME +' Season Pass'.format(event['name']),
                                template = 'season_supporter_event_invite.txt',
                                filter = lambda a: a.amount_extra >= SEASON_LEVEL and before(event['deadline']),
                                extra_data = {'event': event})

before = lambda dt: bool(dt) and datetime.now() < dt
days_after = lambda days, dt: bool(dt) and (datetime.now() > dt + timedelta(days=days))
def days_before(days, dt, until=None):
    if dt:
        until = (dt - timedelta(days=until)) if until else dt
        return dt - timedelta(days=days) < datetime.now() < until




### WARNING - changing the email subject line for an email causes ALL of those emails to be re-sent!

Reminder(Attendee, EVENT_NAME +' schedule, maps, and other FAQs', 'precon_faqs.html',
         lambda a: days_before(7, EPOCH), category='precon_faq')


Reminder(Attendee, EVENT_NAME +' payment received', 'attendee_confirmation.html',
         lambda a: a.paid == HAS_PAID,
         category='attendee_registration_confirmation')

Reminder(Attendee, EVENT_NAME +' group registration confirmed', 'attendee_confirmation.html',
         lambda a: a.group and a != a.group.leader and a.registered > datetime(2013, 11, 11),
         category='attendee_registration_confirmation')

Reminder(Group, EVENT_NAME +' group payment received', 'group_confirmation.html',
         lambda g: g.amount_paid == g.total_cost,
         category='attendee_registration_confirmation')



Reminder(Attendee, EVENT_NAME +' extra payment received', 'group_donation.txt',
         lambda a: a.paid == PAID_BY_GROUP and a.amount_extra and a.amount_paid == a.amount_extra,
         category='attendee_registration_confirmation')


MarketplaceReminder('Reminder to pay for your '+ EVENT_NAME +' Dealer registration', 'dealer_payment_reminder.txt',
                    lambda g: g.status == APPROVED and days_after(30, g.approved) and g.is_unpaid,
                    category='marketplace_registration_confirmation')

MarketplaceReminder('Your '+ EVENT_NAME +' Dealer registration is due in one week', 'dealer_payment_reminder.txt',
                    lambda g: g.status == APPROVED and days_before(7, DEALER_PAYMENT_DUE, 2) and g.is_unpaid,
                    category='marketplace_registration_confirmation')

MarketplaceReminder('Last chance to pay for your '+ EVENT_NAME +' Dealer registration', 'dealer_payment_reminder.txt',
                    lambda g: g.status == APPROVED and days_before(2, DEALER_PAYMENT_DUE) and g.is_unpaid,
                    category='marketplace_registration_confirmation')

MarketplaceReminder(EVENT_NAME +' Dealer waitlist has been exhausted', 'dealer_waitlist_closing.txt',
                    lambda g: DEALER_WAITLIST_CLOSED and g.status == WAITLISTED,
                    category='marketplace_registration_confirmation')



MarketplaceReminder('Your '+ EVENT_NAME +' Dealer registration has been approved', 'dealer_approved.html',
                    lambda g: g.status == APPROVED,
                    category='marketplace_registration_confirmation')


Reminder(Attendee, EVENT_NAME +' Badge Confirmation', 'badge_confirmation.txt',
         lambda a: a.placeholder and a.first_name and a.last_name
                                 and a.badge_type not in [GUEST_BADGE, STAFF_BADGE]
                                 and a.ribbon not in [PANELIST_RIBBON, VOLUNTEER_RIBBON],
         category='placeholder_badge_confirmation')

Reminder(Attendee, EVENT_NAME +' Panelist Badge Confirmation', 'panelist_confirmation.txt',
         lambda a: a.placeholder and a.first_name and a.last_name
                                 and (a.badge_type == GUEST_BADGE or a.ribbon == PANELIST_RIBBON),
         sender = PANELS_EMAIL,
         category='placeholder_badge_confirmation')

StopsReminder(EVENT_NAME +' Volunteer Badge Confirmation', 'volunteer_confirmation.txt',
              lambda a: a.placeholder and a.first_name and a.last_name
                                      and a.registered > PREREG_OPENING,
              category='placeholder_badge_confirmation')

Reminder(Attendee, EVENT_NAME +' Badge Confirmation Reminder', 'confirmation_reminder.txt',
         lambda a: days_after(7, a.registered) and a.placeholder and a.first_name and a.last_name,
         category='placeholder_badge_confirmation')

Reminder(Attendee, 'Last Chance to Accept Your '+ EVENT_NAME +' Badge', 'confirmation_reminder.txt',
         lambda a: days_before(7, PLACEHOLDER_DEADLINE) and a.placeholder and a.first_name and a.last_name,
         category='placeholder_badge_confirmation')



StopsReminder('Want to staff '+ EVENT_NAME +' again?', 'imported_staffer.txt',
              lambda a: a.placeholder and a.badge_type == STAFF_BADGE and a.registered < PREREG_OPENING,
              category='staff_precon_reminder')

StopsReminder(EVENT_NAME +' shifts available', 'shifts_available.txt',
              lambda a: state.AFTER_SHIFTS_CREATED and a.takes_shifts,
              category='staff_precon_reminder')

StopsReminder('Reminder to sign up for '+ EVENT_NAME +' shifts', 'shift_reminder.txt',
              lambda a: days_after(30, max(a.registered, SHIFTS_CREATED))
                    and state.AFTER_SHIFTS_CREATED and not PREREG_CLOSED and a.takes_shifts and not a.hours,
              category='staff_precon_reminder')

StopsReminder('Last chance to sign up for '+ EVENT_NAME +' shifts', 'shift_reminder.txt',
              lambda a: days_before(10, EPOCH) and state.AFTER_SHIFTS_CREATED and not PREREG_CLOSED
                                               and a.takes_shifts and not a.hours,
              category='staff_precon_reminder')

StopsReminder('Still want to volunteer at '+ EVENT_NAME +'?', 'volunteer_check.txt',
              lambda a: days_before(5, UBER_TAKEDOWN) and a.ribbon == VOLUNTEER_RIBBON
                                                      and a.takes_shifts and a.weighted_hours == 0,
              category='staff_precon_reminder')

StopsReminder('MAGCon - the convention to plan '+ EVENT_NAME +'!', 'magcon.txt',
              lambda a: days_before(14, MAGCON),
              category='staff_precon_reminder')


StopsReminder('Want volunteer hotel room space at '+ EVENT_NAME +'?', 'hotel_rooms.txt',
              lambda a: days_before(45, ROOM_DEADLINE, 14) and state.AFTER_SHIFTS_CREATED and a.hotel_eligible,
              category='staff_hotel_reminder')

StopsReminder('Reminder to sign up for '+ EVENT_NAME +' hotel room space', 'hotel_reminder.txt',
              lambda a: days_before(14, ROOM_DEADLINE, 2) and a.hotel_eligible and not a.hotel_requests,
              category='staff_hotel_reminder')

StopsReminder('Last chance to sign up for '+ EVENT_NAME +' hotel room space', 'hotel_reminder.txt',
              lambda a: days_before(2, ROOM_DEADLINE) and a.hotel_eligible and not a.hotel_requests,
              category='staff_hotel_reminder')

StopsReminder('Reminder to meet your '+ EVENT_NAME +' hotel room requirements', 'hotel_hours.txt',
              lambda a: days_before(14, UBER_TAKEDOWN, 7) and a.hotel_shifts_required and a.weighted_hours < 30,
              category='staff_hotel_reminder')

StopsReminder('Final reminder to meet your '+ EVENT_NAME +' hotel room requirements', 'hotel_hours.txt',
              lambda a: days_before(7, UBER_TAKEDOWN) and a.hotel_shifts_required and a.weighted_hours < 30,
              category='staff_hotel_reminder')

StopsReminder('Last chance to personalize your '+ EVENT_NAME +' badge', 'personalized_badge_reminder.txt',
              lambda a: days_before(7, PRINTED_BADGE_DEADLINE) and a.badge_type == STAFF_BADGE and a.placeholder,
              category='attendee_registration_confirmation')

Reminder(Attendee, 'Personalized '+ EVENT_NAME +' badges will be ordered next week', 'personalized_badge_deadline.txt',
         lambda a: days_before(7, PRINTED_BADGE_DEADLINE) and a.badge_type in [STAFF_BADGE, SUPPORTER_BADGE] and not a.placeholder,
         category='attendee_registration_confirmation')

StopsReminder(EVENT_NAME +' Tech Ops volunteering', 'techops.txt',
              lambda a: TECH_OPS in a.requested_depts_ints and TECH_OPS not in a.assigned)

StopsReminder(EVENT_NAME +' Chipspace volunteering', 'chipspace.txt',
              lambda a: (JAMSPACE in a.requested_depts_ints or JAMSPACE in a.assigned) and CHIPSPACE not in a.assigned)

StopsReminder(EVENT_NAME +' Chipspace shifts', 'chipspace_trusted.txt',
              lambda a: CHIPSPACE in a.assigned and a.trusted)

StopsReminder(EVENT_NAME +' Chipspace', 'chipspace_untrusted.txt',
              lambda a: a.has_shifts_in(CHIPSPACE) and not a.trusted)

StopsReminder(EVENT_NAME +' food prep volunteering', 'food_interest.txt',
              lambda a: FOOD_PREP in a.requested_depts_ints and not a.assigned_depts,
              category='staff_precon_reminder')

StopsReminder(EVENT_NAME +' food prep rules', 'food_volunteers.txt',
              lambda a: a.has_shifts_in(FOOD_PREP) and not a.trusted,
              category='staff_precon_reminder')

StopsReminder(EVENT_NAME +' message from Chef', 'food_trusted_staffers.txt',
              lambda a: a.has_shifts_in(FOOD_PREP) and a.trusted,
              category='staff_precon_reminder')

StopsReminder(EVENT_NAME +' Volunteer Food', 'volunteer_food_info.txt',
              lambda a: days_before(7, UBER_TAKEDOWN),
              category='food_information_confirmation')

Reminder(Attendee, 'Want to help run '+ EVENT_NAME +' poker tournaments?', 'poker.txt',
         lambda a: a.has_shifts_in(TABLETOP), sender='tabletop@magfest.org',
         category='staff_precon_reminder')


DeptHeadReminder('Assign '+ EVENT_NAME +' hotel rooms for your department', 'room_assignments.txt',
                 lambda a: days_before(45, ROOM_DEADLINE),
                 category='staff_hotel_reminder')

DeptHeadReminder('Reminder for '+ EVENT_NAME +' department heads to double-check their staffers', 'dept_head_rooms.txt',
                 lambda a: days_before(45, ROOM_DEADLINE),
                 category='staff_precon_reminder')

DeptHeadReminder('Last reminder for '+ EVENT_NAME +' department heads to double-check their staffers', 'dept_head_rooms.txt',
                 lambda a: days_before(7, ROOM_DEADLINE),
                 category='staff_precon_reminder')

DeptHeadReminder('Last chance for Department Heads to get Staff badges for your people', 'dept_head_badges.txt',
                 lambda a: days_before(7, PRINTED_BADGE_DEADLINE),
                 category='staff_precon_reminder')

DeptHeadReminder('Need help with '+ EVENT_NAME +' setup/teardown?', 'dept_head_setup_teardown.txt',
                 lambda a: days_before(14, ROOM_DEADLINE),
                 category='staff_precon_reminder')

DeptHeadReminder('Department Ribbons', 'dept_head_ribbons.txt',
                 lambda a: days_before(1, ROOM_DEADLINE),
                 sender=REGDESK_EMAIL,
                 category='custom_ribbon_reminder')

DeptHeadReminder('Final list of '+ EVENT_NAME +' hotel allocations for your department', 'hotel_list.txt',
                 lambda a: days_before(1, ROOM_DEADLINE + timedelta(days=6)),
                 category='staff_hotel_reminder')

DeptHeadReminder('Unconfirmed '+ EVENT_NAME +' staffers in your department', 'dept_placeholders.txt',
                 lambda a: days_before(21, UBER_TAKEDOWN),
                 category='staff_precon_reminder')


GroupReminder('Reminder to pre-assign '+ EVENT_NAME +' group badges', 'group_preassign_reminder.txt',
              lambda g: days_after(30, g.registered) and state.BEFORE_GROUP_REG_TAKEDOWN and g.unregistered_badges,
              category='placeholder_badge_confirmation')

Reminder(Group, 'Last chance to pre-assign '+ EVENT_NAME +' group badges', 'group_preassign_reminder.txt',
         lambda g: state.AFTER_GROUP_REG_TAKEDOWN and g.unregistered_badges and (not g.is_dealer or g.status == APPROVED),
         category='placeholder_badge_confirmation')



Reminder(Attendee, EVENT_NAME +' parental consent form reminder', 'under_18_reminder.txt',
         lambda a: a.age_group == UNDER_18 and days_before(7, EPOCH),
         category='attendee_registration_confirmation')

GuestReminder(EVENT_NAME +' food for guests', 'guest_food.txt',
              category='food_information_confirmation')

GuestReminder(EVENT_NAME +' hospitality suite information', 'guest_food_info.txt',
              category='food_information_confirmation')


DeptHeadReminder(EVENT_NAME +' staffers need to be marked and rated', 'postcon_hours.txt', post_con=True,
                 category='staff_postcon_reminder')


# see issue #173 about rewriting this
#for _event in SEASON_EVENTS.values():
#    SeasonSupporterReminder(_event)


@all_renderable(PEOPLE)
class Root:
    def index(self):
        raise HTTPRedirect('by_sent')
    
    def by_sent(self, page='1'):
        emails = Email.objects.order_by('-when')
        return {
            'page': page,
            'emails': get_page(page, emails),
            'count': emails.count()
        }

    def preview_tosend(self):
        emails = Reminder.send_all(render_only = True)
        return {
            'emails': emails
        }
    
    def sent(self, **params):
        return {'emails': Email.objects.filter(**params).order_by('when')}
