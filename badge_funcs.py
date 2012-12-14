from common import *

def next_badge_num(badge_type):
    sametype = Attendee.objects.filter(badge_type = badge_type).exclude(badge_num = 0)
    if sametype.count():
        return sametype.order_by("-badge_num")[0].badge_num + 1
    else:
        return BADGE_RANGES[badge_type][0]

def change_badge(attendee):
    with BADGE_LOCK:
        new = attendee.badge_num
        old = Attendee.objects.get(id = attendee.id)
        out_of_range = check_range(attendee.badge_num, attendee.badge_type)
        if out_of_range:
            return out_of_range
        elif state.CUSTOM_BADGES_ORDERED:
            if attendee.badge_type in PREASSIGNED_BADGE_TYPES and old.badge_type not in PREASSIGNED_BADGE_TYPES:
                return "Custom badges have already been ordered; you can add new staffers by giving them an Attendee badge with a Volunteer Ribbon"
            elif attendee.badge_type not in PREASSIGNED_BADGE_TYPES and old.badge_type in PREASSIGNED_BADGE_TYPES:
                attendee.badge_num = 0
                attendee.save()
                return "Badge updated"
            elif attendee.badge_type in PREASSIGNED_BADGE_TYPES and attendee.badge_num != old.badge_num:
                return "Custom badges have already been ordered, so you cannot shift badge numbers"
        
        if state.AT_THE_CON:
            if not attendee.badge_num and attendee.badge_type in PREASSIGNED_BADGE_TYPES:
                return "You must assign a badge number for pre-assigned badge types"
            
            existing = Attendee.objects.filter(badge_type = attendee.badge_type, badge_num = attendee.badge_num)
            if existing and attendee.badge_num:
                return "That badge number already belongs to {!r}".format(existing[0].full_name)
        elif old.badge_num and old.badge_type == attendee.badge_type:
            next = next_badge_num(attendee.badge_type) - 1
            attendee.badge_num = min(attendee.badge_num or maxint, next)
            if old.badge_num < attendee.badge_num:
                shift_badges(old, down = True, until = attendee.badge_num)
            else:
                shift_badges(attendee, down = False, until = old.badge_num)
        else:
            if old.badge_num:
                shift_badges(old, down = True)
            
            next = next_badge_num(attendee.badge_type)
            if 0 < attendee.badge_num <= next:
                shift_badges(attendee, down = False)
            else:
                attendee.badge_num = next
        
        attendee.save()
        if state.AT_THE_CON or new <= next:
            return "Badge updated"
        else:
            return "That badge number was too high, so the next available badge was assigned instead"


def shift_badges(attendee, down, until = maxint):
    if state.AT_THE_CON:
        return
    
    with BADGE_LOCK:
        shift = -1 if down else 1
        for a in Attendee.objects.filter(badge_type = attendee.badge_type, badge_num__gte = attendee.badge_num) \
                                 .exclude(badge_num = 0).exclude(id = attendee.id).exclude(badge_num__gt = until):
            a.badge_num += shift
            a.save()


def get_new_badge_type(group):
    if GUEST_BADGE in group.attendee_set.values_list("badge_type", flat=True):
        return GUEST_BADGE
    else:
        return ATTENDEE_BADGE

def get_new_ribbon(group):
    ribbons = set(group.attendee_set.values_list("ribbon", flat=True))
    for ribbon in [DEALER_RIBBON, BAND_RIBBON, NO_RIBBON]:
        if ribbon in ribbons:
            return ribbon
    else:
        if group.tables and (group.amount_paid or group.amount_owed):
            return DEALER_RIBBON
        else:
            return NO_RIBBON

def assign_group_badges(group, new_badge_count):
    group.save()
    ribbon = get_new_ribbon(group)
    badge_type = get_new_badge_type(group)
    new_badge_count = int(new_badge_count)
    diff = new_badge_count - group.attendee_set.filter(paid = PAID_BY_GROUP).count()
    if diff > 0:
        for i in range(diff):
            Attendee.objects.create(group=group, badge_type=badge_type, ribbon=ribbon, paid=PAID_BY_GROUP)
    elif diff < 0:
        floating = list( group.attendee_set.filter(paid=PAID_BY_GROUP, first_name="", last_name="") )
        if len(floating) < abs(diff):
            return "You can't reduce the number of badges for a group to below the number of assigned badges"
        else:
            for i in range(abs(diff)):
                floating[i].delete()
    group.save()


def get_badge_type(badge_num):
    try:
        for (badge_type, (lowest, highest)) in BADGE_RANGES.items():
            if int(badge_num) in range(lowest, highest + 1):
                return badge_type, ""
        return None, "{0!r} isn't a valid badge number; it's not in the range of any badge type".format(badge_num)
    except:
        return None, "{0!r} is not a valid integer".format(badge_num)


def send_delete_email(model):
    if isinstance(model, Attendee):
        subject = "Your MAGFest preregistration has been deleted"
        body = render("emails/attendee_deleted.txt", {"attendee": model})
    else:
        subject = "Your MAGFest group preregistration has been deleted"
        body = render("emails/group_deleted.txt", {"group": model})
    
    try:
        send_email(REGDESK_EMAIL, model.email, subject, body)
        Email.objects.create(fk_tab = model.__class__.__name__, fk_id = model.id,
                             subject = subject, dest = model.email, body = body)
    except:
        log.error("unable to send unpaid deletion notification to {}", model.email, exc_info = True)


def delete_unpaid():
    for attendee in Attendee.objects.filter(paid = NOT_PAID):
        if datetime.now() > attendee.payment_deadline:
            send_delete_email(attendee)
            attendee.delete()
    
    for group in Group.objects.filter(tables = 0, amount_paid = 0, amount_owed__gt = 0):
        if datetime.now() > group.payment_deadline:
            send_delete_email(group)
            group.attendee_set.all().delete()
            group.delete()


def detect_duplicates():
    subject = "Duplicates Report for " + datetime.now().strftime("%Y-%m-%d")
    if not Email.objects.filter(subject = subject):
        grouped = defaultdict(list)
        for a in Attendee.objects.exclude(first_name = "").order_by("registered").select_related("group"):
            if not a.group or a.group.status != WAITLISTED:
                grouped[a.full_name, a.email].append(a)
        
        dupes = {k:v for k,v in grouped.items() if len(v) > 1}
        if dupes:
            body = render("emails/duplicates.html", {"dupes": sorted(dupes.items())})
            send_email(ADMIN_EMAIL, REGDESK_EMAIL, subject, body, format = "html")
            Email.objects.create(fk_tab = "n/a", fk_id = 0, subject = subject, body = body, dest = REGDESK_EMAIL)


def check_placeholders():
    emails = {
        STAFF_EMAIL: Q(staffing = True),
        PANELS_EMAIL: Q(badge_type = GUEST_BADGE) | Q(ribbon = PANELIST_RIBBON),
        REGDESK_EMAIL: ~(Q(staffing = True) | Q(badge_type = GUEST_BADGE) | Q(ribbon = PANELIST_RIBBON))
    }
    for dest,query in emails.items():
        email = [s for s in dest.split() if "@" in s][0].strip("<>").split("@")[0].title()
        subject = email + " Placeholder Badge Report for " + datetime.now().strftime("%Y-%m-%d")
        if not Email.objects.filter(subject = subject):
            placeholders = list(Attendee.objects.filter(query, placeholder = True,
                                                        registered__lt = datetime.now() - timedelta(days = 3))
                                        .order_by("registered","first_name","last_name")
                                        .select_related("group"))
            if placeholders:
                body = render("emails/placeholders.html", {"placeholders": placeholders})
                send_email(ADMIN_EMAIL, dest, subject, body, format = "html")
                Email.objects.create(fk_tab = "n/a", fk_id = 0, subject = subject, body = body, dest = dest)
