from uber.common import *


def check_range(badge_num, badge_type):
    if badge_num is not None:
        try:
            badge_num = int(badge_num)
        except:
            return '"{}" is not a valid badge number (should be an integer)'.format(badge_num)

        if badge_num:
            min_num, max_num = c.BADGE_RANGES[int(badge_type)]
            if not min_num <= badge_num <= max_num:
                return '{} badge numbers must fall within the range {} - {}'.format(dict(c.BADGE_OPTS)[badge_type], min_num, max_num)


# TODO: returning (result, error) is not a convention we're using anywhere else,
#       so maybe change this to be more idiomatic if convenient, but not a big deal
def get_badge_type(badge_num):
    if not c.NUMBERED_BADGES:
        return c.ATTENDEE_BADGE, ''
    else:
        try:
            for (badge_type, (lowest, highest)) in c.BADGE_RANGES.items():
                if int(badge_num) in range(lowest, highest + 1):
                    return badge_type, ''
            return None, "{0!r} isn't a valid badge number; it's not in the range of any badge type".format(badge_num)
        except:
            return None, '{0!r} is not a valid integer'.format(badge_num)


def detect_duplicates():
    if c.PRE_CON and (c.DEV_BOX or c.SEND_EMAILS):
        subject = c.EVENT_NAME + ' Duplicates Report for ' + localized_now().strftime('%Y-%m-%d')
        with Session() as session:
            if session.no_email(subject):
                grouped = defaultdict(list)
                for a in session.query(Attendee).filter(Attendee.first_name != '').options(joinedload(Attendee.group)).order_by(Attendee.registered):
                    if not a.group or a.group.status != c.WAITLISTED:
                        grouped[a.full_name, a.email.lower()].append(a)

                dupes = {k: v for k, v in grouped.items() if len(v) > 1}

                for who, attendees in dupes.items():
                    paid = [a for a in attendees if a.paid == c.HAS_PAID]
                    unpaid = [a for a in attendees if a.paid == c.NOT_PAID]
                    if len(paid) == 1 and len(attendees) == 1 + len(unpaid):
                        for a in unpaid:
                            session.delete(a)
                        del dupes[who]

                if dupes:
                    body = render('emails/daily_checks/duplicates.html', {'dupes': sorted(dupes.items())})
                    send_email(c.ADMIN_EMAIL, c.REGDESK_EMAIL, subject, body, format='html', model='n/a')


def check_placeholders():
    if c.PRE_CON and c.CHECK_PLACEHOLDERS and (c.DEV_BOX or c.SEND_EMAILS):
        emails = [
            ['Staff', c.STAFF_EMAIL, Attendee.staffing == True],
            ['Panelist', c.PANELS_EMAIL, or_(Attendee.badge_type == c.GUEST_BADGE, Attendee.ribbon == c.PANELIST_RIBBON)],
            ['Attendee', c.REGDESK_EMAIL, not_(or_(Attendee.staffing == True, Attendee.badge_type == c.GUEST_BADGE, Attendee.ribbon == c.PANELIST_RIBBON))]
        ]
        with Session() as session:
            for badge_type, dest, per_email_filter in emails:
                weeks_until = (c.EPOCH - localized_now()).days // 7
                subject = '{} {} Placeholder Badge Report ({} weeks to go)'.format(c.EVENT_NAME, badge_type, weeks_until)
                if session.no_email(subject):
                    placeholders = (session.query(Attendee)
                                           .filter(Attendee.placeholder == True,
                                                   Attendee.registered < localized_now() - timedelta(days=3),
                                                   per_email_filter)
                                           .options(joinedload(Attendee.group))
                                           .order_by(Attendee.registered, Attendee.full_name).all())
                    if placeholders:
                        body = render('emails/daily_checks/placeholders.html', {'placeholders': placeholders})
                        send_email(c.ADMIN_EMAIL, dest, subject, body, format='html', model='n/a')


def check_unassigned():
    if c.PRE_CON and (c.DEV_BOX or c.SEND_EMAILS):
        with Session() as session:
            unassigned = session.query(Attendee).filter_by(staffing=True, assigned_depts='').order_by(Attendee.full_name).all()
            subject = c.EVENT_NAME + ' Unassigned Volunteer Report for ' + localized_now().strftime('%Y-%m-%d')
            if unassigned and session.no_email(subject):
                body = render('emails/daily_checks/unassigned.html', {'unassigned': unassigned})
                send_email(c.STAFF_EMAIL, c.STAFF_EMAIL, subject, body, format='html', model='n/a')


# TODO: perhaps a check_leaderless() for checking for leaderless groups, since those don't get emails
