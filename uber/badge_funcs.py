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
    subject = EVENT_NAME + ' Duplicates Report for ' + localized_now().strftime('%Y-%m-%d')
    with Session() as session:
        if session.no_email(subject):
            grouped = defaultdict(list)
            for a in session.query(Attendee).filter(Attendee.first_name != '').options(joinedload(Attendee.group)).order_by(Attendee.registered):
                if not a.group or a.group.status not in [WAITLISTED, DECLINED]:
                    grouped[a.full_name, a.email.lower()].append(a)

            dupes = {k: v for k, v in grouped.items() if len(v) > 1}

            for who, attendees in dupes.items():
                paid = [a for a in attendees if a.paid == HAS_PAID]
                unpaid = [a for a in attendees if a.paid == NOT_PAID]
                if len(paid) == 1 and len(attendees) == 1 + len(unpaid):
                    for a in unpaid:
                        session.delete(a)
                    del dupes[who]

            if dupes:
                body = render('emails/daily_checks/duplicates.html', {'dupes': sorted(dupes.items())})
                send_email(ADMIN_EMAIL, REGDESK_EMAIL, subject, body, format='html', model='n/a')


def check_placeholders():
    emails = [
        ['Staff', STAFF_EMAIL, Attendee.staffing == True],
        ['Panelist', PANELS_EMAIL, or_(Attendee.badge_type == GUEST_BADGE, Attendee.ribbon == PANELIST_RIBBON)],
        ['Attendee', REGDESK_EMAIL, not_(or_(Attendee.staffing == True, Attendee.badge_type == GUEST_BADGE, Attendee.ribbon == PANELIST_RIBBON))]
    ]
    with Session() as session:
        for badge_type, dest, per_email_filter in emails:
            weeks_until = (EPOCH - localized_now()).days // 7
            subject = '{} {} Placeholder Badge Report ({} weeks to go)'.format(EVENT_NAME, badge_type, weeks_until)
            if session.no_email(subject):
                placeholders = (session.query(Attendee)
                                       .filter(Attendee.placeholder == True,
                                               Attendee.registered < localized_now() - timedelta(days=3),
                                               per_email_filter)
                                       .options(joinedload(Attendee.group))
                                       .order_by(Attendee.registered, Attendee.full_name).all())
                if placeholders:
                    body = render('emails/daily_checks/placeholders.html', {'placeholders': placeholders})
                    send_email(ADMIN_EMAIL, dest, subject, body, format='html', model='n/a')


def check_unassigned():
    with Session() as session:
        unassigned = session.query(Attendee).filter_by(staffing=True, assigned_depts='').order_by(Attendee.full_name).all()
        subject = EVENT_NAME + ' Unassigned Volunteer Report for ' + localized_now().strftime('%Y-%m-%d')
        if unassigned and session.no_email(subject):
            body = render('emails/daily_checks/unassigned.html', {'unassigned': unassigned})
            send_email(STAFF_EMAIL, STAFF_EMAIL, subject, body, format='html', model='n/a')


# TODO: perhaps a check_leaderless() for checking for leaderless groups, since those don't get emails
