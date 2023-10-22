import cherrypy
from pockets.autolog import log
from sqlalchemy import and_, or_
from sqlalchemy.orm import joinedload, subqueryload

from uber.config import c
from uber.custom_tags import pluralize
from uber.decorators import ajax, all_renderable, csrf_protected, log_pageview, render
from uber.errors import HTTPRedirect
from uber.models import Attendee, Email, Group, PageViewTracking, Tracking
from uber.payments import ReceiptManager
from uber.tasks.email import send_email
from uber.utils import check, remove_opt, Order


def convert_dealer_badge(session, attendee, admin_note=''):
    """
    Takes a dealer badge and converts it to an attendee badge. This does NOT remove the badge from the group, as
    keeping the badge with the group is important if the group is still waitlisted or for events that import badges.
    Instead, it removes their Dealer ribbon and sets them to no longer being paid by group, then updates or creates
    their receipt accordingly.
    """
    
    receipt = session.get_receipt_by_model(attendee)
    receipt_items = []

    if attendee.paid not in [c.HAS_PAID, c.NEED_NOT_PAY]:
        receipt_item = ReceiptManager.process_receipt_credit_change(attendee, 'paid', c.NOT_PAID, receipt)
        receipt_items += [receipt_item] if receipt_item else []
        attendee.paid = c.NOT_PAID
        attendee.badge_status = c.NEW_STATUS
        session.add(attendee)
        session.commit()

    receipt_item = ReceiptManager.process_receipt_credit_change(attendee, 'ribbon', remove_opt(attendee.ribbon_ints, c.DEALER_RIBBON), receipt)
    receipt_items += [receipt_item] if receipt_item else []
    attendee.ribbon = remove_opt(attendee.ribbon_ints, c.DEALER_RIBBON)
    if admin_note:
        attendee.append_admin_note(admin_note)
    attendee.badge_cost = None # Triggers re-calculating the base badge price on save

    if receipt and receipt.item_total != int(attendee.default_cost * 100):
        session.add_all(receipt_items)
    else:
        session.get_receipt_by_model(attendee, create_if_none="DEFAULT")


def decline_and_convert_dealer_group(session, group, status=c.DECLINED, admin_note='', email_leader=True, delete_group=False):
    from uber.models import AdminAccount
    """
    Cancels a dealer group and converts its assigned badges to individual badges that can be purchased for 
    the attendee price at the time they registered.
    `group` is the group to convert.
    `status` sets the status for the group. If `delete_group` is true, this is ignored.
    `admin_note` defines the admin note to append to every converted attendee. If blank, a note is generated 
        based on the current logged-in admin.
    `email_leader` controls whether or not the group leader is emailed. Set to False for any calls to this function generated
        by the group leader, e.g., the Cancel Application button on the group members page.
    `delete_group` removes all assigned attendees from the group and deletes it instead of changing its status. This is best
        for cases where the number of declined groups fed to this function is enormous and you are very sure you will never 
        need to look at them again.
    """
    if not admin_note:
        if delete_group:
            admin_note = f'Converted badge from {AdminAccount.admin_name()} declining and converting {c.DEALER_REG_TERM} "{group.name}.'
        else:
            admin_note = f'Converted badge from {AdminAccount.admin_name()} setting {c.DEALER_REG_TERM} "{group.name}" to {c.DEALER_STATUS[status]}.'

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
        if not attendee.is_unassigned:
            convert_dealer_badge(session, attendee, admin_note)
            if email_leader or attendee != group.leader:
                try:
                    send_email.delay(
                        c.MARKETPLACE_EMAIL,
                        attendee.email_to_address,
                        'Do you still want to come to {}?'.format(c.EVENT_NAME),
                        render('emails/dealers/badge_converted.html', {
                            'attendee': attendee,
                            'group': group}, encoding=None),
                        format='html',
                        model=attendee.to_dict('id'))
                    emails_sent += 1
                except Exception:
                    emails_failed += 1

            badges_converted += 1
        elif not delete_group:
            attendee.badge_status = c.INVALID_GROUP_STATUS

        if delete_group:
            group.attendees.remove(attendee)

        session.add(attendee)
        session.commit()

    if delete_group:
        session.delete(group)
    else:
        group.status = status

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
                    decline_and_convert_dealer_group(session, group, delete_group=True)
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
                group.email_to_address,
                subject,
                email_text,
                bcc=c.MARKETPLACE_NOTIFICATIONS_EMAIL,
                model=group.to_dict('id'))
        if action == 'waitlisted':
            group.status = c.WAITLISTED
        else:
            message = decline_and_convert_dealer_group(session, group)
        session.commit()
        return {'success': True,
                'message': message}
