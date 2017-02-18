from uber.common import *


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
                        key=lambda g: [getattr(g, order.lstrip('-')), g.tables])
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
        group = session.group(params, checkgroups=Group.all_checkgroups, bools=Group.all_bools,)
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
                .filter(or_(Email.dest == group.leader.email, and_(Email.model == 'Attendee', Email.fk_id == id)))\
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
            message = 'Group declined'
            for attendee in group.attendees:
                if attendee.is_unassigned or not convert:
                    session.delete(attendee)
                else:
                    message = 'Group declined and emails sent to attendees'
                    attendee.paid = c.NOT_PAID
                    attendee.badge_status = c.NEW_STATUS
                    attendee.ribbon = c.NO_RIBBON
                    try:
                        send_email(c.REGDESK_EMAIL, attendee.email, 'Do you still want to come to {EVENT_NAME}?',
                                   render('emails/dealers/badge_converted.html', {
                                       'attendee': attendee,
                                       'group': group
                                   }), model=attendee)
                    except:
                        message = 'Group declined (but the emails could not be sent)'
                    group.attendees.remove(attendee)
                    group.leader = None
            session.delete(group)
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
