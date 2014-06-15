from uber.common import *


def check_range(badge_num, badge_type):
    try:
        badge_num = int(badge_num)
    except:
        return '"{}" is not a valid badge number (should be an integer)'.format(badge_num)

    if badge_num:
        min_num, max_num = BADGE_RANGES[int(badge_type)]
        if not min_num <= badge_num <= max_num:
            return '{} badge numbers must fall within the range {} - {}'.format(dict(BADGE_OPTS)[badge_type], min_num, max_num)


# TODO: returning (result, error) is not a convention we're using anywhere else,
#       so maybe change this to be more idiomatic if convenient, but not a big deal
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
                send_email(ADMIN_EMAIL, dest, subject, body, format='html', model='n/a')


def check_unassigned():
    unassigned = list(Attendee.objects.filter(staffing=True, assigned_depts='').order_by('first_name', 'last_name'))
    subject = 'Unassigned Volunteer Report for ' + datetime.now().strftime('%Y-%m-%d')
    if unassigned and not Email.objects.filter(subject = subject):
        body = render('emails/unassigned.html', {'unassigned': unassigned})
        send_email(STAFF_EMAIL, STAFF_EMAIL, subject, body, format='html', model='n/a')
