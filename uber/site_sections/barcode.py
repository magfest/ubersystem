from uber.barcode import get_badge_num_from_barcode
from uber.decorators import all_renderable, ajax, any_admin_access
from uber.models import BadgeInfo


@all_renderable()
class Root:
    def index(self):
        return {}

    @ajax
    @any_admin_access
    def get_badge_num_from_barcode(self, session, barcode):
        badge_num = -1
        msg = "Success."
        attendee = None

        badge_num = get_badge_num_from_barcode(barcode)['badge_num']
        badge = session.query(BadgeInfo).filter(BadgeInfo.ident == badge_num).first()
        if not badge:
            msg = "Failed: this badge number does not exist."
        elif not badge.attendee:
            msg = "Failed: no attendee associated with this badge number."
        else:
            attendee = badge.attendee

        return {
            'message': msg,
            'badge_num': badge_num,
            'attendee_name': attendee.full_name if attendee else '',
            'attendee_id': attendee.id if attendee else -1,
        }
