from uber.common import *
from uber.custom_tags import pluralize


_entangled_ribbons = set(
    getattr(c, r, -1) for r in ['BAND', 'DEPT_HEAD_RIBBON', 'PANELIST_RIBBON'])


def _is_attendee_disentangled(attendee):
    """
    Returns True if the attendee has an unpaid badge and does not have any
    other roles in the system.
    """
    return attendee.paid not in [c.HAS_PAID, c.NEED_NOT_PAY] \
        and _entangled_ribbons.isdisjoint(attendee.ribbon_ints) \
        and not attendee.admin_account \
        and not attendee.shifts


def _is_dealer_convertable(attendee):
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
        # and c.DEALER_RIBBON in attendee.ribbon_ints


def _decline_and_convert_dealer_group(session, group, convert=False):
    """
    Deletes the waitlisted dealer group and converts all of the group members
    to the appropriate badge type. Unassigned, unpaid badges will be deleted.
    """
    admin_note = 'Converted badge from waitlisted dealer group "{}".'.format(
        group.name)

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
        if (not convert or attendee.is_unassigned) \
                and _is_attendee_disentangled(attendee):
            session.delete(attendee)
            badges_deleted += 1

        else:
            if _is_dealer_convertable(attendee):
                attendee.badge_status = c.NEW_STATUS
                attendee.overridden_price = attendee.new_badge_cost

                try:
                    send_email(c.REGDESK_EMAIL,
                               attendee.email,
                               'Do you still want to come to {EVENT_NAME}?',
                               render('emails/dealers/badge_converted.html', {
                                   'attendee': attendee,
                                   'group': group
                               }), model=attendee)
                    emails_sent += 1
                except:
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
                    message = 'When registering a new Dealer, you must enter the name and email address of the group leader and must allocate at least one badge'
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
                                raise HTTPRedirect('index?message={}', group.name + ' has been uploaded, approved, and marked as paid')
                        else:
                            raise HTTPRedirect('index?message={}', group.name + ' is uploaded and ' + group.status_label)
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
            emails = session.query(Email)\
                .filter(or_(Email.dest == group.leader.email, Email.fk_id == id))\
                .order_by(Email.when).all()
        else:
            emails = {}

        return {
            'group': group,
            'emails': emails,
            'changes': session.query(Tracking)
                .filter(or_(Tracking.links.like('%group({})%'.format(id)),
                            and_(Tracking.model == 'Group', Tracking.fk_id == id)))
                .order_by(Tracking.when).all(),
            'pageviews': session.query(PageViewTracking).filter(PageViewTracking.what == "Group id={}".format(id))
        }

    def waitlist(self, session, decline_and_convert=False):
        if cherrypy.request.method == 'POST':
            groups = session.query(Group).filter(
                    Group.tables > 0,
                    Group.status == c.WAITLISTED) \
                .options(subqueryload(Group.attendees)
                         .subqueryload(Attendee.admin_account),
                         subqueryload(Group.attendees)
                         .subqueryload(Attendee.shifts)) \
                .order_by(Group.name, Group.id).all()

            message = ''
            if decline_and_convert:
                for group in groups:
                    _decline_and_convert_dealer_group(session, group, True)
                message = 'All waitlisted dealers have been declined and converted to regular attendee badges'
            raise HTTPRedirect('index?order=name&show=tables&message={}', message)

        groups = session.query(Group).filter(
                Group.tables > 0,
                Group.status == c.WAITLISTED) \
            .order_by(Group.name, Group.id).all()
        return {'groups': groups}

    @ajax
    def unapprove(self, session, id, action, email, convert=None, message=''):
        assert action in ['waitlisted', 'declined']
        group = session.group(id)
        subject = 'Your {EVENT_NAME} Dealer registration has been ' + action
        if group.email:
            send_email(c.MARKETPLACE_EMAIL, group.email, subject, email, bcc=c.MARKETPLACE_EMAIL, model=group)
        if action == 'waitlisted':
            group.status = c.WAITLISTED
        else:
            message = _decline_and_convert_dealer_group(session, group, convert)
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
