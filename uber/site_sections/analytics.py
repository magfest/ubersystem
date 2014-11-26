# -*- coding: utf-8 *-*
# Magfest ubersystem analytics
# Dominic Cerquetti, Aug 2012

from uber.common import *
import copy

@all_renderable(PEOPLE, STATS)
class Root:
    def index(self):
        return {'test': 'test'}

    # display last 2 minutes worth of registrations, to be used by alerting services
    @ajax_gettable
    @unrestricted
    def recent_regs_json(self):
        restrict_to = {'registered__gte': datetime.datetime.now() - timedelta(minutes=2)}
        attendees = Attendee.objects.order_by('registered').filter(**restrict_to)

        att = []
        for attendee in attendees:
            id_hash = hash(attendee.first_name + ' ' + str(attendee.id))
            unix_timestamp = int(attendee.registered.strftime('%s'))
            item = [unix_timestamp, id_hash]
            att.append(item)

        return att

    # display the page that calls the AJAX above
    @unrestricted
    def recent_regs_live(self):
        return {}
