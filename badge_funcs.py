from common import *

def next_badge_num(badge_type):
    sametype = Attendee.objects.filter(badge_type = badge_type).exclude(badge_num = 0)
    if sametype.count():
        return sametype.order_by("-badge_num")[0].badge_num + 1
    else:
        return BADGE_RANGES[badge_type][0]

def change_badge(attendee, new_num):
    with BADGE_LOCK:
        old_num = int(attendee.badge_num)
        old_type = Attendee.objects.get(id = attendee.id).badge_type
        new_num = int(new_num) if str(new_num).isdigit() else maxint
        out_of_range = check_range(new_num, attendee.badge_type)
        if new_num != maxint and out_of_range:
            return out_of_range
        
        if state.AT_THE_CON:
            if attendee.badge_type in PREASSIGNED_BADGE_TYPES and new_num == 0:
                return "You must assign a badge number for pre-assigned badge types"
            
            existing = Attendee.objects.filter(badge_type=attendee.badge_type, badge_num=new_num)
            if existing and new_num:
                return "That badge number already belongs to {!r}".format(existing[0].full_name)
            
            attendee.badge_num = new_num
            attendee.save()
        else:
            if old_num != 0:
                shift_badges(old_type, old_num, down = True, exclude = attendee.id)
            
            next = next_badge_num(attendee.badge_type)
            if new_num <= next:
                attendee.badge_num = new_num
                shift_badges(attendee.badge_type, new_num, down = False, exclude = attendee.id)
            else:
                attendee.badge_num = next
            
            attendee.save()
        
        if state.AT_THE_CON or new_num <= next or new_num == maxint:
            return "Badge updated"
        else:
            return "That badge number was too high, so the next available badge was assigned instead"


def shift_badges(badge_type, badge_num, down, exclude):
    if state.AT_THE_CON:
        return
    
    with BADGE_LOCK:
        shift = -1 if down else 1
        order = "badge_num" if down else "-badge_num"
        for attendee in Attendee.objects.filter(badge_type = badge_type, badge_num__gte = badge_num) \
                                        .exclude(badge_num = 0).exclude(id = exclude).order_by(order):
            attendee.badge_num += shift
            attendee.save()


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
