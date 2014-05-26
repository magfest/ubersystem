from uber.common import *

@all_renderable(PEOPLE)
class Root:
    def index(self, message='', order='name', show='all'):
        which = {
            'all':    {},
            'tables': {'tables__gt': 0},
            'groups': {'tables': 0}
        }[show]
        
        groups = sorted(Group.objects.filter(**which),
                        reverse = '-' in order,
                        key = lambda g: [getattr(g, order.strip('-')), g.tables])
        by_id = {g.id: g for g in groups}
        for g in groups:
            g._attendees = []
        for a in Attendee.objects.filter(group_id__isnull = False).all():
            if a.group_id in by_id:
                by_id[a.group_id]._attendees.append(a)
        
        return {
            'message': message,
            'groups':  groups,
            'order':   Order(order),
            'show':    show,
            'total_badges':    Attendee.objects.filter(group__isnull = False).count(),
            'tabled_badges':   Attendee.objects.filter(group__tables__gt = 0).count(),
            'untabled_badges': Attendee.objects.filter(group__tables = 0).count(),
            'total_groups':    Group.objects.count(),
            'tabled_groups':   Group.objects.filter(tables__gt = 0).count(),
            'untabled_groups': Group.objects.filter(tables = 0).count(),
            'tables':            Group.objects.aggregate(tables = Sum('tables'))['tables'],
            'unapproved_tables': Group.objects.filter(status = UNAPPROVED).aggregate(tables = Sum('tables'))['tables'] or 0,
            'waitlisted_tables': Group.objects.filter(status = WAITLISTED).aggregate(tables = Sum('tables'))['tables'] or 0,
            'approved_tables':   Group.objects.filter(status = APPROVED).aggregate(tables = Sum('tables'))['tables'] or 0
        }
    
    def form(self, message='', **params):
        group = Group.get(params, bools=['auto_recalc','can_add'])
        if 'name' in params:
            message = check(group)
            if not message:
                message = group.assign_badges(params['badges'])
                if not message:
                    if 'redirect' in params:
                        raise HTTPRedirect('../preregistration/group_members?id={}', group.secret_id)
                    else:
                        raise HTTPRedirect('form?id={}&message={}', group.id, 'Group info uploaded')
        
        return {
            'message': message,
            'group':   group
        }
    
    def unapprove(self, id, action, email):
        assert action in ['waitlisted', 'declined']
        group = Group.get(id)
        subject = 'Your '+ EVENT_NAME +' Dealer registration has been ' + action
        send_email(MARKETPLACE_EMAIL, group.email, subject, email, model = group)
        if action == 'waitlisted':
            group.status = WAITLISTED
            group.save()
        else:
            group.attendee_set.all().delete()
            group.delete()
        return 'ok'
    
    @csrf_protected
    def delete(self, id):
        group = Group.get(id)
        if group.badges - group.unregistered_badges:
            raise HTTPRedirect('form?id={}&message={}', id, "You can't delete a group without first unassigning its badges.")
        
        group.attendee_set.all().delete()
        group.delete()
        raise HTTPRedirect('index?message={}', 'Group deleted')
