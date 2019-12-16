import cherrypy
from sqlalchemy import and_, or_
from sqlalchemy.orm import joinedload, subqueryload

from uber.config import c
from uber.custom_tags import pluralize
from uber.decorators import ajax, all_renderable, csrf_protected, log_pageview, render
from uber.errors import HTTPRedirect
from uber.models import Attendee, Email, Group, PageViewTracking, Tracking
from uber.tasks.email import send_email
from uber.utils import check, remove_opt, Order


def _is_attendee_disentangled(attendee):
    """
    Returns True if the attendee has an unpaid badge and does not have any
    other roles in the system.
    """
    entangled_ribbons = set(
        getattr(c, r, -1)
        for r in ['BAND', 'DEPT_HEAD_RIBBON', 'PANELIST_RIBBON'])
    return attendee.paid not in [c.HAS_PAID, c.NEED_NOT_PAY, c.REFUNDED] \
        and entangled_ribbons.isdisjoint(attendee.ribbon_ints) \
        and not attendee.admin_account \
        and not attendee.shifts


def _is_dealer_convertible(attendee):
    """
    Returns True if a waitlisted dealer can be converted into a new, unpaid
    attendee badge.
    """
    return attendee.badge_type == c.ATTENDEE_BADGE \
        and _is_attendee_disentangled(attendee)
    # It looks like a lot of dealers have helpers that didn't get assigned
    # a dealer ribbon. We still want to convert those badges, so we can't
    # trust they'll have a dealer ribbon. I think this is safe because we
    # won't even get this far if it isn't a dealer group in the first place
    #     and c.DEALER_RIBBON in attendee.ribbon_ints


def _decline_and_convert_dealer_group(session, group, status=c.DECLINED):
    """
    Deletes the waitlisted dealer group and converts all of the group members
    to the appropriate badge type. Unassigned, unpaid badges will be deleted.
    """
    admin_note = 'Converted badge from waitlisted {} "{}".'.format(c.DEALER_REG_TERM, group.name)
    group.status = status

    if not group.is_unpaid:
        group.tables = 0
        for attendee in group.attendees:
            attendee.append_admin_note(admin_note)
            attendee.ribbon = remove_opt(attendee.ribbon_ints, c.DEALER_RIBBON)
        return 'Group {} status removed'.format(c.DEALER_TERM)

    message = ['Group declined']
    emails_failed = 0
    emails_sent = 0
    badges_converted = 0

    for attendee in list(group.attendees):
        if _is_dealer_convertible(attendee):
            attendee.badge_status = c.INVALID_STATUS

            if not attendee.is_unassigned:
                new_attendee = Attendee()
                for attr in c.UNTRANSFERABLE_ATTRS:
                    setattr(new_attendee, attr, getattr(attendee, attr))
                new_attendee.overridden_price = attendee.base_badge_price - c.GROUP_DISCOUNT
                new_attendee.base_badge_price = attendee.base_badge_price
                new_attendee.append_admin_note(admin_note)
                session.add(new_attendee)

                try:
                    send_email.delay(
                        c.MARKETPLACE_EMAIL,
                        new_attendee.email,
                        'Do you still want to come to {}?'.format(c.EVENT_NAME),
                        render('emails/dealers/badge_converted.html', {
                            'attendee': new_attendee,
                            'group': group}, encoding=None),
                        format='html',
                        model=attendee.to_dict('id'))
                    emails_sent += 1
                except Exception:
                    emails_failed += 1

                badges_converted += 1
        else:
            if attendee.paid not in [c.HAS_PAID, c.NEED_NOT_PAY]:
                attendee.paid = c.NOT_PAID

            attendee.append_admin_note(admin_note)
            attendee.ribbon = remove_opt(attendee.ribbon_ints, c.DEALER_RIBBON)

    for count, template in [
            (badges_converted, '{} badge{} converted'),
            (emails_sent, '{} email{} sent'),
            (emails_failed, '{} email{} failed to send')]:

        if count > 0:
            message.append(template.format(count, pluralize(count)))

    return ', '.join(message)


@all_renderable()
class Root:
    def index(self, session, message=''):
        HTTPRedirect('../group_admin/index#dealers?message={}', message)

    def waitlist(self, session, decline_and_convert=False):
        query = session.query(Group).filter(
            Group.tables > 0,
            Group.status == c.WAITLISTED).order_by(Group.name, Group.id)

        if cherrypy.request.method == 'POST':
            groups = query.options(
                subqueryload(Group.attendees).subqueryload(Attendee.admin_account),
                subqueryload(Group.attendees).subqueryload(Attendee.shifts)).all()

            message = ''
            if decline_and_convert:
                for group in groups:
                    _decline_and_convert_dealer_group(session, group)
                message = 'All waitlisted {}s have been declined and converted to regular attendee badges'\
                    .format(c.DEALER_TERM)
            raise HTTPRedirect('../group_admin/index?message={}#dealers', message)

        return {'groups': query.all()}

    @ajax
    def unapprove(self, session, id, action, email_text, message=''):
        assert action in ['waitlisted', 'declined']
        group = session.group(id)
        subject = 'Your {} {} has been {}'.format(c.EVENT_NAME, c.DEALER_REG_TERM, action)
        if group.email:
            send_email.delay(
                c.MARKETPLACE_EMAIL,
                group.email,
                subject,
                email_text,
                bcc=c.MARKETPLACE_EMAIL,
                model=group.to_dict('id'))
        if action == 'waitlisted':
            group.status = c.WAITLISTED
        else:
            message = _decline_and_convert_dealer_group(session, group)
        session.commit()
        return {'success': True,
                'message': message}

    def cancel_dealer(self, session, id):
        group = session.group(id)
        _decline_and_convert_dealer_group(session, group, c.CANCELLED)
        message = "Sorry you couldn't make it! Group members have been emailed confirmations for individual badges."

        raise HTTPRedirect('../preregistration/group_members?id={}&message={}', group.id, message)
