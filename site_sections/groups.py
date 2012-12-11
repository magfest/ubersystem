from common import *

@all_renderable(PEOPLE)
class Root:
    def index(self, message="", order="name", show="all"):
        which = {
            "all":    {},
            "tables": {"tables__gt": 0},
            "groups": {"tables": 0}
        }[show]
        
        groups = sorted(Group.objects.filter(**which),
                        reverse = "-" in order,
                        key = lambda g: [getattr(g, order.strip("-")), g.tables])
        by_id = {g.id: g for g in groups}
        for g in groups:
            g._attendees = []
        for a in Attendee.objects.filter(group_id__isnull = False).all():
            if a.group_id in by_id:
                by_id[a.group_id]._attendees.append(a)
        
        return {
            "message": message,
            "groups":  groups,
            "order":   Order(order),
            "show":    show,
            "total_badges":    Attendee.objects.filter(group__isnull = False).count(),
            "tabled_badges":   Attendee.objects.filter(group__tables__gt = 0).count(),
            "untabled_badges": Attendee.objects.filter(group__tables = 0).count(),
            "total_groups":    Group.objects.count(),
            "tabled_groups":   Group.objects.filter(tables__gt = 0).count(),
            "untabled_groups": Group.objects.filter(tables = 0).count(),
            "tables":          Group.objects.aggregate(tables = Sum("tables"))["tables"]
        }
    
    def form(self, message="", **params):
        group = get_model(Group, params, bools=["auto_recalc","can_add"])
        if "name" in params:
            message = check(group)
            if not message:
                message = assign_group_badges(group, params["badges"])
                if not message:
                    raise HTTPRedirect("index?message={}", "Group info uploaded")
        
        return {
            "message": message,
            "group":   group
        }
    
    def unapprove(self, id, action, email):
        assert action in ["waitlisted", "declined"]
        group = Group.objects.get(id = id)
        subject = "Your MAGFest Dealer registration has been " + action
        Email.objects.create(fk_tab = "Group", fk_id = group.id, dest = group.email, subject = subject, body = email)
        send_email(MARKETPLACE_EMAIL, group.email, subject, email)
        if action == "waitlisted":
            group.status = WAITLISTED
            group.save()
        else:
            group.attendee_set.all().delete()
            group.delete()
        return "ok"
    
    def delete(self, id):
        group = Group.objects.get(id=id)
        if group.badges - group.unregistered_badges:
            raise HTTPRedirect("form?id={}&message={}", id, "You can't delete a group without first unassigning its badges.")
        
        for attendee in group.attendee_set.all():
            attendee.delete()
        group.delete()
        raise HTTPRedirect("index?message={}", "Group deleted")
