from common import *

if __name__ == "__main__":
    all = list(Attendee.objects.order_by("badge_num"))
    Attendee.objects.update(badge_num=0)
    for a in all:
        a.badge_num = 0
        set_badge_and_save(a)
