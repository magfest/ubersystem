from common import *

if __name__ == "__main__":
    preassigned = list(Attendee.objects.filter(badge_type__in = PREASSIGNED_BADGE_TYPES).order_by("badge_num"))
    Attendee.objects.update(badge_num = 0)
    for a in preassigned:
        a.badge_num = next_badge_num(a.badge_type)
        a.save()
