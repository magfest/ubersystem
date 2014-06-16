from uber.common import *
from django.utils.text import normalize_newlines

@all_renderable(STUFF)
class Root:
    @unrestricted
    def index(self, message=''):
        if HIDE_SCHEDULE and not AdminAccount.access_set() and not cherrypy.session.get('staffer_id'):
            return "The MAGFest schedule is being developed and will be made public when it's closer to being finalized."
        
        schedule = defaultdict(lambda: defaultdict(list))
        for event in Event.objects.all():
            schedule[event.start_time][event.location].append(event)
            for i in range(1, event.duration):
                half_hour = event.start_time + timedelta(minutes = 30 * i)
                schedule[half_hour][event.location].append(EVENT_BOOKED)
        
        max_simul = {}
        for id,name in EVENT_LOC_OPTS:
            max_events = 1
            for i in range(2 * CON_LENGTH):
                half_hour = EPOCH + timedelta(minutes = 30 * i)
                max_events = max(max_events, len(schedule[half_hour][id]))
            max_simul[id] = max_events
        
        for half_hour in schedule:
            for location in schedule[half_hour]:
                for event in schedule[half_hour][location]:
                    if isinstance(event, Event):
                        simul = max(len(schedule[half_hour][event.location]) for half_hour in event.half_hours)
                        event.colspan = 1 if simul > 1 else max_simul[event.location]
                        for i in range(1, event.duration):
                            schedule[half_hour + timedelta(minutes=30*i)][event.location].remove(EVENT_BOOKED)
                            schedule[half_hour + timedelta(minutes=30*i)][event.location].append(event.colspan)
        
        for half_hour in schedule:
            for id,name in EVENT_LOC_OPTS:
                span_sum = sum(getattr(e,'colspan',e) for e in schedule[half_hour][id])
                for i in range(max_simul[id] - span_sum):
                    schedule[half_hour][id].append(EVENT_OPEN)
            
            schedule[half_hour] = sorted(schedule[half_hour].items(), key=lambda tup: EVENT_LOCS.index(tup[0]))
        
        max_simul = [(id,dict(EVENT_LOC_OPTS)[id],colspan) for id,colspan in max_simul.items()]
        return {
            'message':   message,
            'schedule':  sorted(schedule.items()),
            'max_simul': sorted(max_simul, key=lambda tup: EVENT_LOCS.index(tup[0]))
        }
    
    @unrestricted
    @csv_file
    def time_ordered(self, out):
        for event in Event.objects.order_by('start_time', 'duration', 'location'):
            out.writerow([custom_tags.timespan.pretty(event, 30), event.name, event.get_location_display()])
    
    @unrestricted
    def xml(self):
        cherrypy.response.headers['Content-type'] = 'text/xml'
        schedule = defaultdict(list)
        for event in Event.objects.order_by('start_time'):
            schedule[event.get_location_display()].append(event)
        return render('schedule/schedule.xml', {
            'schedule': sorted(schedule.items(), key=lambda tup: EVENT_LOCS.index(tup[1][0].location))
        })

    @unrestricted
    def schedule_tsv(self):
        cherrypy.response.headers['Content-Type'] = 'text/tsv'
        cherrypy.response.headers['Content-Disposition'] = 'attachment;filename=Schedule-{}.tsv'.format(int(datetime.now(EVENT_TIMEZONE).timestamp()))
        schedule = defaultdict(list)
        for event in Event.objects.order_by('start_time'):
            # strip newlines from event descriptions
            event.description = normalize_newlines(event.description)
            event.description = event.description.replace('\n', ' ')

            # Guidebook wants a date
            event.date = event.start_time.strftime('%m/%d/%Y')

            # Guidebook wants an end time, not duration.
            # also, duration is in half hours. duration=1 means 30 minutes.
            event.end_time = event.start_time + timedelta(minutes = 30 * event.duration)
            
            # now just display the times in these fields, not dates
            event.end_time = event.end_time.strftime('%I:%M:%S %p')
            event.start_time = event.start_time.strftime('%I:%M:%S %p')

            schedule[event.get_location_display()].append(event)

        return render('schedule/schedule.tsv', {
            'schedule': sorted(schedule.items(), key=lambda tup: EVENT_LOCS.index(tup[1][0].location))
        })
    
    @csv_file
    def panels(self, out):
        out.writerow(['Panel','Time','Duration','Room','Description','Panelists'])
        for event in sorted(list(Event.objects.order_by('start_time')), key = lambda e: (e.start_time, e.get_location_display())):
            if 'Panel' in event.get_location_display() or 'Autograph' in event.get_location_display():
                out.writerow([event.name,
                              event.start_time.strftime('%I%p %a').lstrip('0'),
                              '{} minutes'.format(event.minutes),
                              event.get_location_display(),
                              event.description,
                              ' / '.join(ap.attendee.full_name for ap in event.assignedpanelist_set.order_by('attendee__first_name'))])
    
    @unrestricted
    def now(self, when=None):
        if when:
            now = datetime(*map(int, when.split(',')))
        else:
            now = datetime.combine(date.today(), time(datetime.now(EVENT_TIMEZONE).hour))
        
        current, upcoming = [], []
        for loc,desc in EVENT_LOC_OPTS:
            approx = Event.objects.filter(location=loc,
                                          start_time__range=(now-timedelta(hours=6), now))
            for event in approx:
                if now in event.half_hours:
                    current.append(event)
            
            next = Event.objects.filter(location=loc,
                                        start_time__range=(now + timedelta(minutes=30),
                                                           now + timedelta(hours=4))) \
                                .order_by('start_time')
            if next:
                upcoming.extend(event for event in next if event.start_time==next[0].start_time)
        
        return {
            'now':      now if when else datetime.now(EVENT_TIMEZONE),
            'current':  current,
            'upcoming': upcoming
        }
    
    def form(self, message='', panelists=[], **params):
        event = Event.get(params, allowed=['location', 'start_time'])
        if 'name' in params:
            message = check(event)
            if not message:
                event.save()
                event.assignedpanelist_set.all().delete()
                for id in set(listify(panelists)):
                    AssignedPanelist.objects.create(event_id = event.id, attendee_id = id)
                raise HTTPRedirect('edit#{}', event.start_slot and (event.start_slot - 1))
        
        return {
            'message': message,
            'event':   event,
            'assigned': [ap.attendee_id for ap in event.assignedpanelist_set.order_by('-attendee__first_name')],
            'panelists': [(a.id, a.full_name) for a in Attendee.objects.filter(Q(ribbon = PANELIST_RIBBON) | Q(badge_type = GUEST_BADGE)).order_by('first_name')]
        }
    
    @csrf_protected
    def delete(self, id):
        event = Event.objects.filter(id=id).delete()
        raise HTTPRedirect('edit?message={}', 'Event successfully deleted')
    
    @ajax
    def move(self, id, location, start_slot):
        event = Event.get(id)
        event.location = int(location)
        event.start_time = EPOCH + timedelta(minutes = 30 * int(start_slot))
        resp = {'error': check(event)}
        if not resp['error']:
            event.save()
        return resp
    
    @ajax
    def swap(self, id1, id2):
        e1, e2 = Event.get(id1), Event.get(id2)
        (e1.location,e1.start_time),(e2.location,e2.start_time) = (e2.location,e2.start_time),(e1.location,e1.start_time)
        resp = {'error': model_checks.event_overlaps(e1, e2.id) or model_checks.event_overlaps(e2, e1.id)}
        if not resp['error']:
            e1.save()
            e2.save()
        return resp
    
    def edit(self, message=''):
        panelists = defaultdict(dict)
        for ap in AssignedPanelist.objects.select_related():
            panelists[ap.event.id][ap.attendee.id] = ap.attendee.full_name
        
        events = []
        for e in Event.objects.order_by('start_time'):
            d = {attr: getattr(e, attr) for attr in ['id','name','duration','start_slot','location','description']}
            d['panelists'] = panelists[e.id]
            events.append(d)
        
        return {
            'events':  events,
            'message': message
        }
