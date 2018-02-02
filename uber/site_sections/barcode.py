from uber.barcode.utils import get_badge_num_from_barcode
from uber.config import c
from uber.decorators import all_renderable, ajax


@all_renderable(c.PEOPLE, c.REG_AT_CON)
class Root:
    def index(self):
        return {}

    @ajax
    def get_badge_num_from_barcode(self, session, barcode):
        badge_num = -1
        msg = "Success."
        attendee = None
        try:
            # Important note: a barcode encodes just a badge_number. However,
            # that doesn't mean that this badge number has been assigned to an
            # attendee yet, so Attendee may come back as None if they aren't
            # checked in yet.
            badge_num = get_badge_num_from_barcode(barcode)['badge_num']
            attendee = session.attendee(badge_num=badge_num)
        except Exception as e:
            msg = "Failed: " + str(e)

        return {
            'message': msg,
            'badge_num': badge_num,
            'attendee_name': attendee.full_name if attendee else '',
            'attendee_id': attendee.id if attendee else -1,
        }
