from uber.common import *

@all_renderable(PEOPLE)
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
            'unapproved_tables': sum(g.tables for g in groups if g.status == UNAPPROVED),
            'waitlisted_tables': sum(g.tables for g in groups if g.status == WAITLISTED),
            'approved_tables':   sum(g.tables for g in groups if g.status == APPROVED)
        }

    @log_pageview
    def form(self, session, new_dealer='', first_name='', last_name='', email='', message='', **params):
        group = session.group(params, bools=['auto_recalc','can_add'])
        if 'name' in params:
            message = check(group)
            if not message:
                session.add(group)
                message = session.assign_badges(group, params['badges'], params['badge_type'])
                if not message and new_dealer and not (first_name and last_name and email and group.badges):
                    message = 'When registering a new Dealer, you must enter the name and email address of the group leader and must allocate at least one badge'
                if not message:
                    if new_dealer:
                        session.commit()
                        leader = group.leader = group.attendees[0]
                        leader.first_name, leader.last_name, leader.email = first_name, last_name, email
                        leader.placeholder = True
                        if group.status == APPROVED:
                            raise HTTPRedirect('../preregistration/group_members?id={}', group.id)
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

    @ajax
    def unapprove(self, session, id, action, email):
        assert action in ['waitlisted', 'declined']
        group = session.group(id)
        subject = 'Your {EVENT_NAME} Dealer registration has been ' + action
        if group.email:
            send_email(MARKETPLACE_EMAIL, group.email, subject, email, model = group)
        if action == 'waitlisted':
            group.status = WAITLISTED
        #else:
            #for attendee in group.attendees:
                #session.delete(attendee)
            #session.delete(group)
        session.commit()
        return {'success': True}

    @csrf_protected
    def delete(self, session, id, confirmed = None):
        group = session.group(id)
        if group.badges - group.unregistered_badges and not confirmed:
            raise HTTPRedirect('deletion_confirmation?id={}', id)
        else:
            Tracking.track(INVALIDATED, group)
            #for attendee in group.attendees:
                #session.delete(attendee)
            #session.delete(group)
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
