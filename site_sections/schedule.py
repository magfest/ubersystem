from common import *
from django.utils.text import normalize_newlines

@all_renderable(STUFF)
class Root:
    @unrestricted
    def index(self, message=""):
        if state.HIDE_SCHEDULE and not Account.access_set() and not cherrypy.session.get("staffer_id"):
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
                half_hour = state.EPOCH + timedelta(minutes = 30 * i)
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
                span_sum = sum(getattr(e,"colspan",e) for e in schedule[half_hour][id])
                for i in range(max_simul[id] - span_sum):
                    schedule[half_hour][id].append(EVENT_OPEN)
            
            schedule[half_hour] = sorted(schedule[half_hour].items(), key=lambda tup: EVENT_LOCS.index(tup[0]))
        
        max_simul = [(id,dict(EVENT_LOC_OPTS)[id],colspan) for id,colspan in max_simul.items()]
        return {
            "message":   message,
            "schedule":  sorted(schedule.items()),
            "max_simul": sorted(max_simul, key=lambda tup: EVENT_LOCS.index(tup[0]))
        }
    
    @unrestricted
    def xml(self):
        cherrypy.response.headers["Content-type"] = "text/xml"
        schedule = defaultdict(list)
        for event in Event.objects.order_by("start_time"):
            schedule[event.get_location_display()].append(event)
        return render("schedule/schedule.xml", {
            "schedule": sorted(schedule.items(), key=lambda tup: EVENT_LOCS.index(tup[1][0].location))
        })

    @unrestricted
    def schedule_tsv(self):
        #cherrypy.response.headers["Content-type"] = "text/html" # debug
        cherrypy.response.headers["Content-type"] = "plain/text"
        schedule = defaultdict(list)
        for event in Event.objects.order_by("start_time"):
            
            # strip newlines from event descriptions
            event.description = normalize_newlines(event.description)
            event.description = event.description.replace('\n', ' ')

            # Guidebook wants a date
            event.date = event.start_time.strftime("%m/%d/%Y")

            # Guidebook wants an end time, not duration.
            # also, duration is in half hours. duration=1 means 30 minutes.
            event.end_time = event.start_time + timedelta(minutes=event.duration*30)
            
            # now just display the times in these fields, not dates
            event.end_time = event.end_time.strftime("%I:%M:%S %p")
            event.start_time = event.start_time.strftime("%I:%M:%S %p")

            schedule[event.get_location_display()].append(event)
        return render("schedule/schedule.tsv", {
            "schedule": sorted(schedule.items(), key=lambda tup: EVENT_LOCS.index(tup[1][0].location))
        })
    
    @unrestricted
    def now(self, when=None):
        if when:
            now = datetime(*map(int, when.split(",")))
        else:
            now = datetime.combine(date.today(), time(datetime.now().hour))
        
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
                                .order_by("start_time")
            if next:
                upcoming.extend(event for event in next if event.start_time==next[0].start_time)
        
        return {
            "now":      now if when else datetime.now(),
            "current":  current,
            "upcoming": upcoming
        }
    
    def form(self, message="", **params):
        event = get_model(Event, params)
        
        if "name" in params:
            message = check(event)
            if not message:
                event.save()
                for job in event.job_set.all():
                    job.start_time = event.start_time
                    job.duration = event.duration
                    job.save()
                raise HTTPRedirect("index#{}", event.start_time - timedelta(minutes=30))
        
        return {
            "message": message,
            "event":   event
        }
    
    def inventory(self, id, message=""):
        event = Event.objects.get(id=id)
        return {
            "message":       message,
            "event":         event
        }
    
    def assign(self, id, item_id, quantity, location=None, event_id=None):
        item = Item.objects.get(id=item_id)
        event = Event.objects.get(id=id)
        
        existing = event.assigneditem_set.filter(item=item)
        existing.delete()
        
        tosave = AssignedItem()
        tosave.item = item
        tosave.event = event
        tosave.quantity = int(quantity)
        
        message = check(tosave)
        if message:
            if existing:
                existing[0].save()
            raise HTTPRedirect("inventory?id={}&message={}", id, message)
        
        tosave.save()
        raise HTTPRedirect("inventory?id={}&message{}", id, "Assignment uploaded")
    
    def unassign(self, id, todelete):
        AssignedItem.objects.filter(id=todelete).delete()
        raise HTTPRedirect("inventory?id={}&message={}", id, "Item unassigned")
    
    def set_needed(self, id, needed):
        event = Event.objects.get(id=id)
        event.needed = needed.strip()
        event.save()
        raise HTTPRedirect("inventory?id={}&message={}", id, "Requirements updated")
    
    def jobs(self, id, message=""):
        return {
            "message":  message,
            "event":    Event.objects.get(id=id)
        }
    
    def remove_job(self, job_id):
        job = Job.objects.get(id=job_id)
        job.delete()
        raise HTTPRedirect("jobs?id={}&message={}", job.event.id, "Job deleted")
    
    def delete(self, id):
        event = Event.objects.filter(id=id).delete()
        raise HTTPRedirect("index?message={}", "Event successfully deleted")
    
    def events(self, location, **params):
        cherrypy.response.headers["Content-Type"] = "application/json"
        events = defaultdict(lambda: {"name": "_blank"})
        for event in Event.objects.filter(location = location):
            events[event.start_time] = {
                "name":        event.name,
                "description": event.description,
                "duration":    event.duration
            }
            for i in range(1, event.duration):
                events[event.start_time + timedelta(minutes = 30 * i)] = None
        return json.dumps([events[when] for when,_ in START_TIME_OPTS if events[when]])
    
    def panelists(self, **params):
        return json.dumps({"panelists": [
            {
                "id": a.id,
                "full_name": a.full_name
            } for a in Attendee.objects.filter(ribbon = PANELIST_RIBBON).order_by("first_name", "last_name")
        ]})
    
    def panelists(self, **params):
        return json.dumps([
            {
                "id": a.id,
                "full_name": a.full_name
            } for a in Attendee.objects.filter(ribbon = PANELIST_RIBBON).order_by("first_name", "last_name")
        ])
    
    def available_events(self, **params):
        return json.dumps({"events": [
            {"id": e.id, "name": e.name, "duration": e.duration} for e in Event.objects.all()
        ]})
    
    def event(self, panelists = [], **params):
        event = get_model(Event, params)
        message = check(event)
        if message:
            return json.dumps({
                "success": False,
                "msg": message
            })
        else:
            event.save()
            event.assignedpanelist_set.all().delete()
            for attendee_id in listify(panelists):
                if attendee_id:
                    AssignedPanelist.objects.create(attendee_id = attendee_id, event = event)
            
            return json.dumps({
                "success": True,
                "msg": "Event Uploaded"
            })
    
    def testing(self):
        return {}
    
    def js(self, *path, **params):
        cherrypy.response.headers["Content-Type"] = "text/javascript"
        fname = os.path.join("schedule", "js", *path)
        return render(fname, {})
    
    def jqtesting(self):
        dump = lambda e: {attr: getattr(e, attr) for attr in ["name","duration","start_slot","location","description"]}
        return {
            "assigned": map(dump, Event.objects.filter(location__isnull = False).order_by("start_time")),
            "unassigned": map(dump, Event.objects.filter(location__isnull = True))
        }
