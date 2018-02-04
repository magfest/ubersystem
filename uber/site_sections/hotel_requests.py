from uber.common import *


@all_renderable(c.SIGNUPS)
class Root:
    def index(self, session, message='', decline=None, **params):
        if c.AFTER_ROOM_DEADLINE and c.STAFF_ROOMS not in AdminAccount.access_set():
            raise HTTPRedirect('../signups/index?message={}', 'The room deadline has passed')
        attendee = session.logged_in_volunteer()
        if not attendee.hotel_eligible:
            raise HTTPRedirect('../signups/index?message={}', 'You have not been marked as eligible for hotel space')
        requests = session.hotel_requests(params, checkgroups=['nights'], restricted=True)
        if 'attendee_id' in params:
            requests.attendee = attendee  # foreign keys are automatically admin-only
            session.add(requests)
            if decline or not requests.nights:
                requests.nights = ''
                raise HTTPRedirect('../signups/index?message={}', "We've recorded that you've declined hotel room space")
            else:
                if requests.setup_teardown:
                    days = ' / '.join(c.NIGHTS[day] for day in sorted(requests.nights_ints, key=c.NIGHT_DISPLAY_ORDER.index)
                                                    if day not in c.CORE_NIGHTS)
                    message = "Your hotel room request has been submitted.  We'll let you know whether your offer to help on {} is accepted, and who your roommates will be, a few weeks after the deadline.".format(days)
                else:
                    message = "You've accepted hotel room space for {}.  We'll let you know your roommates a few weeks after the deadline.".format(requests.nights_display)
                raise HTTPRedirect('../signups/index?message={}', message)
        else:
            requests = attendee.hotel_requests or requests
            if requests.is_new:
                requests.nights = ','.join(map(str, c.CORE_NIGHTS))

        nights = []
        two_day_before = (c.EPOCH - timedelta(days=2)).strftime('%A')
        day_before = (c.EPOCH - timedelta(days=1)).strftime('%A')
        last_day = c.ESCHATON.strftime('%A').upper()
        day_after = (c.ESCHATON + timedelta(days=1)).strftime('%A')
        nights.append([getattr(c, two_day_before.upper()), getattr(requests, two_day_before.upper()),
                       "I'd like to help set up on " + two_day_before])
        nights.append([getattr(c, day_before.upper()), getattr(requests, day_before.upper()),
                       "I'd like to help set up on " + day_before])
        for night in c.CORE_NIGHTS:
            nights.append([night, night in requests.nights_ints, c.NIGHTS[night]])
        nights.append([getattr(c, last_day), getattr(requests, last_day),
                       "I'd like to help tear down on {} / {}".format(c.ESCHATON.strftime('%A'), day_after)])

        return {
            'nights':   nights,
            'message':  message,
            'requests': requests,
            'attendee': attendee
        }
