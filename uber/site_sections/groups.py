import cherrypy
from sqlalchemy import and_, or_
from sqlalchemy.orm import joinedload, subqueryload

from uber.config import c
from uber.custom_tags import pluralize
from uber.decorators import ajax, all_renderable, csrf_protected, log_pageview, render
from uber.errors import HTTPRedirect
from uber.models import Attendee, Email, Group, PageViewTracking, PromoCodeGroup, Tracking
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


def _decline_and_convert_dealer_group(session, group, delete_when_able=False):
    """
    Deletes the waitlisted dealer group and converts all of the group members
    to the appropriate badge type. Unassigned, unpaid badges will be deleted.
    """
    admin_note = 'Converted badge from waitlisted dealer group "{}".'.format(group.name)

    if not group.is_unpaid:
        group.tables = 0
        for attendee in group.attendees:
            attendee.append_admin_note(admin_note)
            attendee.ribbon = remove_opt(attendee.ribbon_ints, c.DEALER_RIBBON)
        return 'Group dealer status removed'

    message = ['Group declined']
    emails_failed = 0
    emails_sent = 0
    badges_converted = 0
    badges_deleted = 0

    group.leader = None
    for attendee in list(group.attendees):
        if (delete_when_able or attendee.is_unassigned) and _is_attendee_disentangled(attendee):
            session.delete(attendee)
            badges_deleted += 1

        else:
            if _is_dealer_convertible(attendee):
                attendee.badge_status = c.NEW_STATUS

                try:
                    send_email.delay(
                        c.REGDESK_EMAIL,
                        attendee.email,
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

            if attendee.paid not in [c.HAS_PAID, c.NEED_NOT_PAY]:
                attendee.paid = c.NOT_PAID

            attendee.append_admin_note(admin_note)
            attendee.ribbon = remove_opt(attendee.ribbon_ints, c.DEALER_RIBBON)
            group.attendees.remove(attendee)

    session.delete(group)

    for count, template in [
            (badges_converted, '{} badge{} converted'),
            (emails_sent, '{} email{} sent'),
            (emails_failed, '{} email{} failed to send'),
            (badges_deleted, '{} badge{} deleted')]:

        if count > 0:
            message.append(template.format(count, pluralize(count)))

    return ', '.join(message)


@all_renderable(c.PEOPLE, c.REG_AT_CON)
class Root:
    def index(self, session, message='', order='name', show='all'):
        which = {
            'all':    [],
            'tables': [Group.tables > 0],
            'groups': [Group.tables == 0]
        }[show]
        # TODO: think about using a SQLAlchemy column property for .badges and then just use .order()
        groups = sorted(session.query(Group).filter(*which).options(joinedload('attendees')).all(),
                        reverse=order.startswith('-'),
                        key=lambda g: [getattr(g, order.lstrip('-')).lower(), g.tables])

        return {
            'show':              show,
            'groups':            groups,
            'message':           message,
            'order':             Order(order),
            'total_groups':      len(groups),
            'total_badges':      sum(g.badges for g in groups),
            'tabled_badges':     sum(g.badges for g in groups if g.tables),
            'untabled_badges':   sum(g.badges for g in groups if not g.tables),
            'tabled_groups':     len([g for g in groups if g.tables]),
            'untabled_groups':   len([g for g in groups if not g.tables]),
            'tables':            sum(g.tables for g in groups),
            'unapproved_tables': sum(g.tables for g in groups if g.status == c.UNAPPROVED),
            'waitlisted_tables': sum(g.tables for g in groups if g.status == c.WAITLISTED),
            'approved_tables':   sum(g.tables for g in groups if g.status == c.APPROVED)
        }

    def promo_code_groups(self, session, message=''):
        groups = sorted(session.query(PromoCodeGroup).options(joinedload('buyer')).all(),
                        key=lambda g: g.name)
        return {
            'groups': groups,
            'message': message,
        }

    @log_pageview
    def promo_code_group_form(self, session, id, message='', **params):
        group = session.promo_code_group(id)
        if cherrypy.request.method == 'POST':
            group.apply(params)
            session.commit()

        return {
            'group': group,
            'message': message,
        }

    @log_pageview
    def form(self, session, new_dealer='', first_name='', last_name='', email='', message='', **params):
        group = session.group(params, checkgroups=Group.all_checkgroups, bools=Group.all_bools)
        if 'name' in params:
            message = check(group)
            if not message:
                session.add(group)
                ribbon_to_use = None if 'ribbon' not in params else params['ribbon']
                message = session.assign_badges(group, params['badges'], params['badge_type'], ribbon_to_use)
                if not message and new_dealer and not (first_name and last_name and email and group.badges):
                    message = 'When registering a new Dealer, you must enter the name and email address ' \
                        'of the group leader and must allocate at least one badge'
                if not message:
                    if new_dealer:
                        session.commit()
                        leader = group.leader = group.attendees[0]
                        leader.first_name, leader.last_name, leader.email = first_name, last_name, email
                        leader.placeholder = True
                        if group.status == c.APPROVED:
                            if group.amount_unpaid:
                                raise HTTPRedirect('../preregistration/group_members?id={}', group.id)
                            else:
                                raise HTTPRedirect(
                                    'index?message={}', group.name + ' has been uploaded, approved, and marked as paid')
                        else:
                            raise HTTPRedirect(
                                'index?message={}', group.name + ' is uploaded and ' + group.status_label)
                    else:
                        raise HTTPRedirect('form?id={}&message={}', group.id, 'Group info uploaded')
        return {
            'group': group,
            'message': message,
            'new_dealer': new_dealer,
            'first_name': first_name,
            'last_name': last_name,
            'email': email
        }

    def history(self, session, id):
        group = session.group(id)

        if group.leader:
            emails = session.query(Email).filter(
                or_(Email.to == group.leader.email, Email.fk_id == id)).order_by(Email.when).all()
        else:
            emails = {}

        return {
            'group': group,
            'emails': emails,
            'changes': session.query(Tracking).filter(or_(
                Tracking.links.like('%group({})%'.format(id)),
                and_(Tracking.model == 'Group', Tracking.fk_id == id))).order_by(Tracking.when).all(),
            'pageviews': session.query(PageViewTracking).filter(PageViewTracking.what == "Group id={}".format(id))
        }

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
                    _decline_and_convert_dealer_group(session, group, False)
                message = 'All waitlisted dealers have been declined and converted to regular attendee badges'
            raise HTTPRedirect('index?order=name&show=tables&message={}', message)

        return {'groups': query.all()}

    @ajax
    def unapprove(self, session, id, action, email, convert=None, message=''):
        assert action in ['waitlisted', 'declined']
        group = session.group(id)
        subject = 'Your {} Dealer registration has been {}'.format(c.EVENT_NAME, action)
        if group.email:
            send_email.delay(
                c.MARKETPLACE_EMAIL,
                group.email,
                subject,
                email,
                bcc=c.MARKETPLACE_EMAIL,
                model=group.to_dict('id'))
        if action == 'waitlisted':
            group.status = c.WAITLISTED
        else:
            message = _decline_and_convert_dealer_group(session, group, not convert)
        session.commit()
        return {'success': True,
                'message': message}

    @csrf_protected
    def delete(self, session, id, confirmed=None):
        group = session.group(id)
        if group.badges - group.unregistered_badges and not confirmed:
            raise HTTPRedirect('deletion_confirmation?id={}', id)
        else:
            for attendee in group.attendees:
                session.delete(attendee)
            session.delete(group)
            raise HTTPRedirect('index?message={}', 'Group deleted')

    def deletion_confirmation(self, session, id):
        return {'group': session.group(id)}

    @csrf_protected
    def assign_leader(self, session, group_id, attendee_id):
        group = session.group(group_id)
        attendee = session.attendee(attendee_id)
        if attendee not in group.attendees:
            raise HTTPRedirect('form?id={}&message={}', group_id, 'That attendee has been removed from the group')
        else:
            group.leader_id = attendee_id
            raise HTTPRedirect('form?id={}&message={}', group_id, 'Group leader set')
