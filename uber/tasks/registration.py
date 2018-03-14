from collections import defaultdict
from datetime import timedelta

from celery.schedules import crontab
from sqlalchemy import not_, or_
from sqlalchemy.orm import joinedload

from uber.config import c
from uber.decorators import render
from uber.models import Attendee, Session
from uber.tasks.email import send_email
from uber.tasks import celery
from uber.utils import localized_now


__all__ = ['check_duplicate_registrations', 'check_placeholder_registrations', 'check_unassigned_volunteers']


@celery.schedule(crontab(hour='*/6'))
def check_duplicate_registrations():
    """
    This function looks through registered attendees for attendees with the
    same names and email addresses. It first deletes any unpaid duplicates,
    then sets paid duplicates from "Completed" to "New" and sends an email to
    the registration email address. This allows us to see new duplicate
    attendees without repetitive emails.
    """
    if c.PRE_CON and (c.DEV_BOX or c.SEND_EMAILS):
        subject = c.EVENT_NAME + ' Duplicates Report for ' + localized_now().strftime('%Y-%m-%d')
        with Session() as session:
            if session.no_email(subject):
                grouped = defaultdict(list)
                for a in session.query(Attendee).filter(Attendee.first_name != '') \
                        .filter(Attendee.badge_status == c.COMPLETED_STATUS).options(joinedload(Attendee.group)) \
                        .order_by(Attendee.registered):
                    if not a.group or a.group.status not in [c.WAITLISTED, c.UNAPPROVED]:
                        grouped[a.full_name, a.email.lower()].append(a)

                dupes = {k: v for k, v in grouped.items() if len(v) > 1}

                for who, attendees in dupes.items():
                    paid = [a for a in attendees if a.paid == c.HAS_PAID]
                    unpaid = [a for a in attendees if a.paid == c.NOT_PAID]
                    if len(paid) == 1 and len(attendees) == 1 + len(unpaid):
                        for a in unpaid:
                            session.delete(a)
                        del dupes[who]
                    for a in paid:
                        a.badge_status = c.NEW_STATUS

                if dupes:
                    body = render('emails/daily_checks/duplicates.html', {'dupes': sorted(dupes.items())})
                    send_email(c.ADMIN_EMAIL, c.REGDESK_EMAIL, subject, body, format='html', model='n/a')


@celery.schedule(crontab(hour='*/6'))
def check_placeholder_registrations():
    if c.PRE_CON and c.CHECK_PLACEHOLDERS and (c.DEV_BOX or c.SEND_EMAILS):
        emails = [[
            'Staff',
            c.STAFF_EMAIL,
            Attendee.staffing == True
        ], [
            'Panelist',
            c.PANELS_EMAIL,
            or_(Attendee.badge_type == c.GUEST_BADGE, Attendee.ribbon.contains(c.PANELIST_RIBBON))
        ], [
            'Attendee',
            c.REGDESK_EMAIL,
            not_(or_(
                Attendee.staffing == True,
                Attendee.badge_type == c.GUEST_BADGE,
                Attendee.ribbon.contains(c.PANELIST_RIBBON)))
        ]]  # noqa: E712

        with Session() as session:
            for badge_type, to, per_email_filter in emails:
                weeks_until = (c.EPOCH - localized_now()).days // 7
                subject = '{} {} Placeholder Badge Report ({} weeks to go)'.format(
                    c.EVENT_NAME, badge_type, weeks_until)

                if session.no_email(subject):
                    placeholders = (session.query(Attendee)
                                           .filter(Attendee.placeholder == True,
                                                   Attendee.registered < localized_now() - timedelta(days=3),
                                                   Attendee.badge_status.in_([c.NEW_STATUS, c.COMPLETED_STATUS]),
                                                   per_email_filter)
                                           .options(joinedload(Attendee.group))
                                           .order_by(Attendee.registered, Attendee.full_name).all())  # noqa: E712
                    if placeholders:
                        body = render('emails/daily_checks/placeholders.html', {'placeholders': placeholders})
                        send_email(c.ADMIN_EMAIL, to, subject, body, format='html', model='n/a')


@celery.schedule(crontab(hour='*/6'))
def check_unassigned_volunteers():
    if c.PRE_CON and (c.DEV_BOX or c.SEND_EMAILS):
        with Session() as session:
            unassigned = session.query(Attendee).filter(
                Attendee.staffing == True,
                not_(Attendee.dept_memberships.any())).order_by(Attendee.full_name).all()  # noqa: E712
            subject = c.EVENT_NAME + ' Unassigned Volunteer Report for ' + localized_now().strftime('%Y-%m-%d')
            if unassigned and session.no_email(subject):
                body = render('emails/daily_checks/unassigned.html', {'unassigned': unassigned})
                send_email(c.STAFF_EMAIL, c.STAFF_EMAIL, subject, body, format='html', model='n/a')
