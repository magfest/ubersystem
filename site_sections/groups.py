from common import *

@all_renderable(PEOPLE)
class Root:
    def index(self, message="", order="name", show="all"):
        which = {
            "all":    {},
            "tables": {"tables__gt": 0},
            "groups": {"tables": 0}
        }[show]
        
        return {
            "message": message,
            "groups":  sorted(Group.objects.filter(**which),
                              reverse=("-" in order),
                              key=lambda g: [getattr(g, order.strip("-")), g.tables]),
            "order":   Order(order),
            "show":    show,
            
            "total_badges":    Attendee.objects.filter(group__isnull=False).count(),
            "tabled_badges":   Attendee.objects.filter(group__tables__gt=0).count(),
            "untabled_badges": Attendee.objects.filter(group__tables=0).count(),
            "total_groups":    Group.objects.count(),
            "tabled_groups":   Group.objects.filter(tables__gt=0).count(),
            "untabled_groups": Group.objects.filter(tables=0).count(),
            "tables":          Group.objects.aggregate(tables=Sum("tables"))["tables"]
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
    
    def delete(self, id):
        group = Group.objects.get(id=id)
        if group.attendee_set.count():
            raise HTTPRedirect("form?id={}&message={}", id, "You can't delete a group without first unassigning its badges.")
        
        group.delete()
        raise HTTPRedirect("index?message={}", "Group deleted")
