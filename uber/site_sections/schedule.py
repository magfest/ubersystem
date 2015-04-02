from uber.common import *
from django.utils.text import normalize_newlines

@all_renderable(STUFF)
class Root:
    @unrestricted
    @cached
    def index(self, session, message=''):
        if HIDE_SCHEDULE and not AdminAccount.access_set() and not cherrypy.session.get('staffer_id'):
            return "The " + EVENT_NAME + " schedule is being developed and will be made public when it's closer to being finalized."

        schedule = defaultdict(lambda: defaultdict(list))
        for event in session.query(Event).all():
            schedule[event.start_time_local][event.location].append(event)
            for i in range(1, event.duration):
                half_hour = event.start_time_local + timedelta(minutes = 30 * i)
                schedule[half_hour][event.location].append(EVENT_BOOKED)

        max_simul = {}
        for id,name in EVENT_LOCATION_OPTS:
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
            for id, name in EVENT_LOCATION_OPTS:
                span_sum = sum(getattr(e,'colspan',e) for e in schedule[half_hour][id])
                for i in range(max_simul[id] - span_sum):
                    schedule[half_hour][id].append(EVENT_OPEN)

            schedule[half_hour] = sorted(schedule[half_hour].items(), key=lambda tup: ORDERED_EVENT_LOCS.index(tup[0]))

        max_simul = [(id, EVENT_LOCATIONS[id], colspan) for id,colspan in max_simul.items()]
        return {
            'message':   message,
            'schedule':  sorted(schedule.items()),
            'max_simul': sorted(max_simul, key=lambda tup: ORDERED_EVENT_LOCS.index(tup[0]))
        }

    @unrestricted
    @csv_file
    def time_ordered(self, out, session):
        for event in session.query(Event).order_by('start_time', 'duration', 'location').all():
            out.writerow([custom_tags.timespan.pretty(event, 30), event.name, event.location_label])

    @unrestricted
    def xml(self, session):
        cherrypy.response.headers['Content-type'] = 'text/xml'
        schedule = defaultdict(list)
        for event in session.query(Event).order_by('start_time').all():
            schedule[event.location_label].append(event)
        return render('schedule/schedule.xml', {
            'schedule': sorted(schedule.items(), key=lambda tup: ORDERED_EVENT_LOCS.index(tup[1][0].location))
        })

    @unrestricted
    def schedule_tsv(self, session):
        cherrypy.response.headers['Content-Type'] = 'text/tsv'
        cherrypy.response.headers['Content-Disposition'] = 'attachment;filename=Schedule-{}.tsv'.format(int(localized_now().timestamp()))
        schedule = defaultdict(list)
        for event in session.query(Event).order_by('start_time').all():
            schedule[event.location_label].append(dict(event.to_dict(), **{
                'date': event.start_time_local.strftime('%m/%d/%Y'),
                'start_time': event.start_time_local.strftime('%I:%M:%S %p'),
                'end_time': (event.start_time_local + timedelta(minutes=event.minutes)).strftime('%I:%M:%S %p'),
                'description': normalize_newlines(event.description).replace('\n', ' ')
            }))

        return render('schedule/schedule.tsv', {
            'schedule': sorted(schedule.items(), key=lambda tup: ORDERED_EVENT_LOCS.index(tup[1][0]['location']))
        })

    @csv_file
    def panels(self, out, session):
        out.writerow(['Panel','Time','Duration','Room','Description','Panelists'])
        for event in sorted(session.query(Event).all(), key = lambda e: [e.start_time, e.location_label]):
            if 'Panel' in event.location_label or 'Autograph' in event.location_label:
                out.writerow([event.name,
                              event.start_time_local.strftime('%I%p %a').lstrip('0'),
                              '{} minutes'.format(event.minutes),
                              event.location_label,
                              event.description,
                              ' / '.join(ap.attendee.full_name for ap in sorted(event.assigned_panelists, key=lambda ap: ap.attendee.full_name))])

    @unrestricted
    def now(self, session, when=None):
        if when:
            now = EVENT_TIMEZONE.localize(datetime(*map(int, when.split(','))))
        else:
            now = EVENT_TIMEZONE.localize(datetime.combine(localized_now().date(), time(localized_now().hour)))

        current, upcoming = [], []
        for loc,desc in EVENT_LOCATION_OPTS:
            approx = session.query(Event).filter(Event.location == loc,
                                                 Event.start_time >= now - timedelta(hours=6),
                                                 Event.start_time <= now).all()
            for event in approx:
                if now in event.half_hours:
                    current.append(event)

            next = session.query(Event) \
                          .filter(Event.location == loc,
                                  Event.start_time >= now + timedelta(minutes=30),
                                  Event.start_time <= now + timedelta(hours=4)) \
                                .order_by('start_time').all()
            if next:
                upcoming.extend(event for event in next if event.start_time == next[0].start_time)

        return {
            'now':      now if when else localized_now(),
            'current':  current,
            'upcoming': upcoming
        }

    def form(self, session, message='', panelists=(), **params):
        event = session.event(params, allowed=['location', 'start_time'])
        if 'name' in params:
            session.add(event)
            message = check(event)
            if not message:
                new_panelist_ids = set(listify(panelists))
                old_panelist_ids = {ap.attendee_id for ap in event.assigned_panelists}
                for ap in event.assigned_panelists:
                    if ap.attendee_id not in new_panelist_ids:
                        session.delete(ap)
                for attendee_id in new_panelist_ids:
                    if attendee_id not in old_panelist_ids:
                        session.add(AssignedPanelist(event=event, attendee_id=attendee_id))
                raise HTTPRedirect('edit#{}', event.start_slot and (event.start_slot - 1))

        return {
            'message': message,
            'event':   event,
            'assigned': [ap.attendee_id for ap in sorted(event.assigned_panelists, reverse=True, key=lambda a: a.attendee.first_name)],
            'panelists': [(a.id, a.full_name)
                          for a in session.query(Attendee)
                                          .filter(or_(Attendee.ribbon == PANELIST_RIBBON,
                                                      Attendee.badge_type == GUEST_BADGE))
                                          .order_by(Attendee.full_name).all()]
        }

    @csrf_protected
    def delete(self, session, id):
        event = session.delete(session.event(id))
        raise HTTPRedirect('edit?message={}', 'Event successfully deleted')

    @ajax
    def move(self, session, id, location, start_slot):
        event = session.event(id)
        event.location = int(location)
        event.start_time = EPOCH + timedelta(minutes = 30 * int(start_slot))
        resp = {'error': check(event)}
        if not resp['error']:
            session.commit()
        return resp

    @ajax
    def swap(self, session, id1, id2):
        e1, e2 = session.event(id1), session.event(id2)
        (e1.location, e1.start_time), (e2.location, e2.start_time) = (e2.location, e2.start_time), (e1.location, e1.start_time)
        resp = {'error': model_checks.event_overlaps(e1, e2.id) or model_checks.event_overlaps(e2, e1.id)}
        if not resp['error']:
            session.commit()
        return resp

    def edit(self, session, message=''):
        panelists = defaultdict(dict)
        for ap in session.query(AssignedPanelist) \
                         .options(joinedload(AssignedPanelist.event), joinedload(AssignedPanelist.attendee)).all():
            panelists[ap.event.id][ap.attendee.id] = ap.attendee.full_name

        events = []
        for e in session.query(Event).order_by('start_time').all():
            d = {attr: getattr(e, attr) for attr in ['id','name','duration','start_slot','location','description']}
            d['panelists'] = panelists[e.id]
            events.append(d)

        return {
            'events':  events,
            'message': message
        }
