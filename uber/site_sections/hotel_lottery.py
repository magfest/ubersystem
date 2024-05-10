from datetime import datetime

from uber.config import c
from uber.decorators import ajax, all_renderable
from uber.errors import HTTPRedirect
from uber.models import Attendee, Room, RoomAssignment, Shift


@all_renderable()
class Root:
    def index(self, session):
        print(c.HOTEL_LOTTERY, flush=True)
        return {
            "checkin_start": c.HOTEL_LOTTERY_CHECKIN_START,
            "checkin_end": c.HOTEL_LOTTERY_CHECKIN_END,
            "checkout_start": c.HOTEL_LOTTERY_CHECKOUT_START,
            "checkout_end": c.HOTEL_LOTTERY_CHECKOUT_END,
            "hotels": c.HOTEL_LOTTERY
        }
