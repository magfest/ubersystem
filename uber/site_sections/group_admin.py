import cherrypy
from pockets import readable_join
from sqlalchemy import and_, or_
from sqlalchemy.orm import subqueryload

from uber.config import c
from uber.decorators import ajax, all_renderable, csrf_protected, log_pageview, site_mappable
from uber.errors import HTTPRedirect
from uber.models import Attendee, Email, Event, Group, GuestGroup, GuestMerch, PageViewTracking, Tracking
from uber.utils import check, convert_to_absolute_url


@all_renderable()
class Root:
    def _required_message(self, params, fields):
        missing = [s for s in fields if not params.get(s, '').strip() or params.get(s, '') == "0"]
        if missing:
            return '{} {} required field{}'.format(
                readable_join([s.replace('_', ' ').title() for s in missing]),
                'is a' if len(missing) == 1 else 'are',
                's' if len(missing) > 1 else '')
        return ''

    def index(self, session, message='', show_all=None):
        groups = session.viewable_groups().limit(c.ROW_LOAD_LIMIT)
        dealer_groups = [group for group in groups if group.is_dealer]
        return {
            'message': message,
            'groups': groups.all(),
            'guest_checklist_items': GuestGroup(group_type=c.GUEST).sorted_checklist_items,
            'band_checklist_items': GuestGroup(group_type=c.BAND).sorted_checklist_items,
            'dealer_groups':      len(dealer_groups),
            'dealer_badges':      sum(g.badges for g in dealer_groups),
            'tables':            sum(g.tables for g in dealer_groups),
            'show_all': show_all,
            'unapproved_tables': sum(g.tables for g in dealer_groups if g.status == c.UNAPPROVED),
            'waitlisted_tables': sum(g.tables for g in dealer_groups if g.status == c.WAITLISTED),
            'approved_tables':   sum(g.tables for g in dealer_groups if g.status == c.APPROVED)
        }

    @log_pageview
    def form(self, session, new_dealer='', message='', **params):
        group = session.group(params, checkgroups=Group.all_checkgroups, bools=Group.all_bools)

        if cherrypy.request.method == 'POST':
            new_with_leader = any(params.get(info) for info in ['first_name', 'last_name', 'email'])
            message = self._required_message(params, ['name'])
            
            if not message and group.is_new and (params.get('group_type') or new_dealer or group.is_dealer):
                message = self._required_message(params, ['first_name', 'last_name', 'email'])

            if not message:
                message = check(group)

            if not message:
                if group.is_new and params.get('group_type'):
                    group.auto_recalc = False
                session.add(group)
                new_ribbon = params.get('ribbon', c.BAND if params.get('group_type') == str(c.BAND) else None)
                new_badge_type = params.get('badge_type', c.ATTENDEE_BADGE)
                test_permissions = Attendee(badge_type=new_badge_type, ribbon=new_ribbon, paid=c.PAID_BY_GROUP)
                new_badge_status = c.PENDING_STATUS if not session.admin_can_create_attendee(test_permissions) else c.NEW_STATUS
                message = session.assign_badges(
                    group,
                    int(params.get('badges', 0)) or int(new_with_leader),
                    new_badge_type=new_badge_type,
                    new_ribbon_type=new_ribbon,
                    badge_status=new_badge_status,
                    )

            if not message:
                if group.is_new and new_with_leader:
                    session.commit()
                    leader = group.leader = group.attendees[0]
                    leader.first_name = params.get('first_name')
                    leader.last_name = params.get('last_name')
                    leader.email = params.get('email')
                    leader.placeholder = True
                    message = check(leader)
                    if message:
                        session.delete(group)
                        session.commit()

                if not message:
                    if params.get('group_type'):
                        group.guest = group.guest or GuestGroup()
                        group.guest.group_type = params.get('group_type')
                    
                    if group.is_new and group.is_dealer:
                        if group.status == c.APPROVED and group.amount_unpaid:
                            raise HTTPRedirect('../preregistration/group_members?id={}', group.id)
                        elif group.status == c.APPROVED:
                            raise HTTPRedirect(
                                'index?message={}', group.name + ' has been uploaded and approved')
                        else:
                            raise HTTPRedirect(
                                'index?message={}', group.name + ' is uploaded as ' + group.status_label)
                     
                    raise HTTPRedirect('form?id={}&message={} has been saved', group.id, group.name)

        return {
            'message': message,
            'group': group,
            'group_type': params.get('group_type', ''),
            'badges': params.get('badges', ''),
            'first_name': params.get('first_name', ''),
            'last_name': params.get('last_name', ''),
            'email': params.get('email', ''),
            'new_dealer': new_dealer,
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
        
    def checklist_info(self, session, message='', event_id=None, **params):
        guest = session.guest_group(params)
        if not session.admin_can_see_guest_group(guest):
            raise HTTPRedirect('index?message={}', 'You cannot view {} groups'.format(guest.group_type_label.lower()))
        
        if cherrypy.request.method == 'POST':
            if event_id:
                guest.event_id = event_id
            message = check(guest)
            if not message:
                for field in ['estimated_loadin_minutes', 'estimated_performance_minutes']:
                    if field in params:
                        field_name = "load-in" if field == 'estimated_loadin_minutes' else 'performance'
                        if not params.get(field):
                            message = "Please enter more than 0 estimated {} minutes".format(field_name)
                        elif not str(params.get(field, '')).isdigit():
                            message = "Please enter a whole number for estimated {} minutes".format(field_name)
            if not message:
                raise HTTPRedirect('index?message={}{}', guest.group.name, ' data uploaded')

        events = session.query(Event).filter_by(location=c.CONCERTS).order_by(Event.start_time).all()
        return {
            'guest': guest,
            'message': message,
            'events': [(event.id, event.name) for event in events]
        }
