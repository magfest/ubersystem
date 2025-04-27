from datetime import timedelta

import cherrypy
from sqlalchemy.orm import subqueryload

from uber.config import c
from uber.decorators import all_renderable
from uber.models import Attendee, Shift


@all_renderable()
class Root:

    def mark_hotel_eligible(self, session, id):
        """
        Force mark a non-staffer as eligible for hotel space.
        This is outside the normal workflow, used for when we have a staffer
        that only has an attendee badge for some reason, and we want to mark
        them as being OK to crash in a room.
        """
        attendee = session.attendee(id)
        attendee.hotel_eligible = True
        session.commit()
        return '{} has now been overridden as being hotel eligible'.format(
            attendee.full_name)
