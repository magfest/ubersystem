from common import *

def weighted_hours(staffer, location):
    shifts = Shift.objects.filter(attendee = staffer).select_related()
    return sum([shift.job.real_duration * shift.job.weight
                for shift in shifts
                if shift.job.location == int(location)],
               0.0)

@all_renderable(PEOPLE)
class Root:
    def index(self, location = "1"):
        by_id = {}
        jobs = defaultdict(list)
        for job in Job.objects.filter(location = location):
            by_id[job.id] = job
            jobs[job.start_time if not job.start_time.minute else job.start_time - timedelta(minutes = 30)].append(job)
        
        for job in by_id.values():
            job._shifts = []
        for shift in Shift.objects.filter(job__location = location):
            by_id[shift.job_id]._shifts.append(shift)
        
        times = [state.EPOCH + timedelta(hours = i) for i in range(CON_LENGTH)]
        times = [(t, (times[i+1] if i + 1 < len(times) else None),
                  sorted(jobs.get(t, []), reverse = True, key = lambda j: j.name))
                 for i,t in enumerate(times)]
        return {
            "location": location,
            "times":    times
        }
    
    def signups(self, location = "0"):
        shifts = Shift.objects.filter(job__location = location).select_related()
        
        by_job, by_attendee = defaultdict(list), defaultdict(list)
        for shift in shifts:
            by_job[shift.job].append(shift)
            by_attendee[shift.attendee].append(shift)
        
        attendees = [a for a in Attendee.staffers() if int(location) in a.assigned]
        for attendee in attendees:
            attendee._shifts = by_attendee[attendee]
        
        jobs = list(Job.objects.filter(location = location).order_by("start_time","duration"))
        for job in jobs:
            job._shifts = by_job[job]
            job._available_staffers = [s for s in attendees if (not job.restricted or s.trusted)
                                                            and not job.hours.intersection(s.hours)]
        
        return {
            "location": location,
            "jobs":     jobs,
            "shifts":   Shift.serialize(shifts)
        }
    
    def staffers(self, location="0"):
        attendees = {}
        for attendee in Attendee.staffers():
            if int(location) in attendee.assigned:
                attendee._shifts = []
                attendees[attendee.id] = attendee
        for shift in Shift.objects.filter(job__location = location).select_related():
            attendees[shift.attendee_id]._shifts.append(shift)
        attendees = attendees.values()
        return {
            "location":       location,
            "attendees":      attendees,
            "emails":         ",".join(a.email for a in attendees),
            "total_existing": sum(j.slots * j.weighted_hours for j in Job.objects.filter(location = location)),
            "total_signups":  sum(attendee.weighted_hours for attendee in attendees)
        }
    
    def form(self, message="", **params):
        if params["id"] == "None" and cherrypy.request.method != "POST":
            defaults = cherrypy.session.get("job_defaults", defaultdict(dict))[params["location"]]
            params.update(defaults)
        
        job = get_model(Job, params, bools=["restricted","extra15"])
        if cherrypy.request.method == "POST":
            message = check(job)
            if not message:
                job.save()
                
                if params["id"] == "None":
                    defaults = cherrypy.session.get("job_defaults", defaultdict(dict))
                    defaults[params["location"]] = {field: getattr(job,field) for field in JOB_DEFAULTS}
                    cherrypy.session["job_defaults"] = defaults
                
                raise HTTPRedirect("index?location={}#{}", job.location, job.start_time)
        
        return {
            "job":      job,
            "message":  message,
            "defaults": "defaults" in locals() and defaults
        }
    
    def staffers_by_job(self, id, message = ""):
        attendees = {a.id: a for a in Attendee.staffers()}
        for attendee in attendees.values():
            attendee._shifts = []
        for shift in Shift.objects.select_related():
            attendees[shift.attendee_id]._shifts.append(shift)
        
        job = Job.objects.get(id = id)
        job._all_staffers = sorted(attendees.values(), key = lambda a: a.full_name)
        return {
            "job":     job,
            "message": message
        }
    
    def delete(self, id):
        job = Job.objects.get(id=id)
        job.shift_set.all().delete()
        job.delete()
        raise HTTPRedirect("index?location={}#{}", job.location, job.start_time)
    
    def assign_from_job(self, job_id, staffer_id):
        message = assign(staffer_id, job_id) or "Staffer assigned to shift"
        raise HTTPRedirect("staffers_by_job?id={}&message={}", job_id, message)
    
    def assign_from_list(self, job_id, staffer_id):
        location = Job.objects.get(id = job_id).location
        message = assign(staffer_id, job_id)
        if message:
            raise HTTPRedirect("signups?location={}&message={}", location, message)
        else:
            raise HTTPRedirect("signups?location={}#{}", location, job_id)
    
    def unassign_from_job(self, id):
        shift = Shift.objects.get(id=id)
        shift.delete()
        raise HTTPRedirect("staffers_by_job?id={}&message={}", shift.job.id, "Staffer unassigned")
    
    def unassign_from_list(self, id):
        shift = Shift.objects.get(id=id)
        shift.delete()
        raise HTTPRedirect("signups?location={}#{}", shift.job.location, shift.job.id)
    
    def set_worked(self, id, worked):
        try:
            shift = Shift.objects.get(id=id)
            shift.worked = int(worked)
            shift.save()
            return shift.get_worked_display()
        except:
            return "an unexpected error occured"
    
    def undo_worked(self, id):
        shift = Shift.objects.get(id=id)
        shift.worked = SHIFT_UNMARKED
        shift.save()
        raise HTTPRedirect(cherrypy.request.headers["Referer"])
    
    @ajax
    def rate(self, shift_id, rating, comment = ""):
        shift = Shift.objects.get(id = shift_id)
        shift.rating, shift.comment = int(rating), comment
        shift.save()
        return {}
