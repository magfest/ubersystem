from uber.common import *

def next_badge_num(badge_type):
    sametype = Attendee.objects.filter(badge_type = badge_type).exclude(badge_num = 0)
    if sametype.count():
        return sametype.order_by('-badge_num')[0].badge_num + 1
    else:
        return BADGE_RANGES[badge_type][0]


def change_badge(attendee):
    with BADGE_LOCK:
        new = attendee.badge_num
        old = Attendee.objects.get(id = attendee.id)
        out_of_range = check_range(attendee.badge_num, attendee.badge_type)
        if out_of_range:
            return out_of_range
        elif CUSTOM_BADGES_REALLY_ORDERED:
            if attendee.badge_type in PREASSIGNED_BADGE_TYPES and old.badge_type not in PREASSIGNED_BADGE_TYPES:
                return 'Custom badges have already been ordered; you can add new staffers by giving them an Attendee badge with a Volunteer Ribbon'
            elif attendee.badge_type not in PREASSIGNED_BADGE_TYPES and old.badge_type in PREASSIGNED_BADGE_TYPES:
                attendee.badge_num = 0
                attendee.save()
                return 'Badge updated'
            elif attendee.badge_type in PREASSIGNED_BADGE_TYPES and attendee.badge_num != old.badge_num:
                return 'Custom badges have already been ordered, so you cannot shift badge numbers'
        
        if AT_THE_CON:
            if not attendee.badge_num and attendee.badge_type in PREASSIGNED_BADGE_TYPES:
                return 'You must assign a badge number for pre-assigned badge types'
            
            existing = Attendee.objects.filter(badge_type = attendee.badge_type, badge_num = attendee.badge_num)
            if existing and attendee.badge_num:
                return 'That badge number already belongs to {!r}'.format(existing[0].full_name)
        elif old.badge_num and old.badge_type == attendee.badge_type:
            next = next_badge_num(attendee.badge_type) - 1
            attendee.badge_num = min(attendee.badge_num or MAX_BADGE, next)
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
        if AT_THE_CON or new <= next:
            return 'Badge updated'
        else:
            return 'That badge number was too high, so the next available badge was assigned instead'


def shift_badges(attendee, down, until = MAX_BADGE):
    if AT_THE_CON:
        return
    
    with BADGE_LOCK:
        shift = -1 if down else 1
        for a in Attendee.objects.filter(badge_type = attendee.badge_type, badge_num__gte = attendee.badge_num) \
                                 .exclude(badge_num = 0).exclude(id = attendee.id).exclude(badge_num__gt = until):
            a.badge_num += shift
            a.save()


def get_badge_type(badge_num):
    try:
        for (badge_type, (lowest, highest)) in BADGE_RANGES.items():
            if int(badge_num) in range(lowest, highest + 1):
                return badge_type, ''
        return None, "{0!r} isn't a valid badge number; it's not in the range of any badge type".format(badge_num)
    except:
        return None, '{0!r} is not a valid integer'.format(badge_num)


def detect_duplicates():
    subject = 'Duplicates Report for ' + datetime.now().strftime('%Y-%m-%d')
    if not Email.objects.filter(subject = subject):
        grouped = defaultdict(list)
        for a in Attendee.objects.exclude(first_name = '').order_by('registered').select_related('group'):
            if not a.group or a.group.status != WAITLISTED:
                grouped[a.full_name, a.email.lower()].append(a)
        
        dupes = {k:v for k,v in grouped.items() if len(v) > 1}
        
        for who,attendees in dupes.items():
            paid = [a for a in attendees if a.paid == HAS_PAID]
            unpaid = [a for a in attendees if a.paid == NOT_PAID]
            if len(paid) == 1 and len(attendees) == 1 + len(unpaid):
                for a in unpaid:
                    a.delete()
                del dupes[who]
        
        if dupes:
            body = render('emails/duplicates.html', {'dupes': sorted(dupes.items())})
            send_email(ADMIN_EMAIL, REGDESK_EMAIL, subject, body, format = 'html', model = 'n/a')


def check_placeholders():
    emails = {
        STAFF_EMAIL: Q(staffing = True),
        PANELS_EMAIL: Q(badge_type = GUEST_BADGE) | Q(ribbon = PANELIST_RIBBON),
        REGDESK_EMAIL: ~(Q(staffing = True) | Q(badge_type = GUEST_BADGE) | Q(ribbon = PANELIST_RIBBON))
    }
    for dest,query in emails.items():
        email = [s for s in dest.split() if '@' in s][0].strip('<>').split('@')[0].title()
        subject = email + ' Placeholder Badge Report for ' + datetime.now().strftime('%Y-%m-%d')
        if not Email.objects.filter(subject = subject):
            placeholders = list(Attendee.objects.filter(query, placeholder = True,
                                                        registered__lt = datetime.now() - timedelta(days = 30))
                                        .order_by('registered','first_name','last_name')
                                        .select_related('group'))
            if placeholders:
                body = render('emails/placeholders.html', {'placeholders': placeholders})
                send_email(ADMIN_EMAIL, dest, subject, body, format = 'html', model = 'n/a')
