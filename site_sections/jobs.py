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
        jobs = defaultdict(list)
        for job in Job.objects.filter(location = location):
            jobs[job.start_time if not job.start_time.minute else job.start_time - timedelta(minutes = 30)].append(job)
        
        times = [state.EPOCH + timedelta(hours = i) for i in range(CON_LENGTH)]
        times = [(t, (times[i+1] if i + 1 < len(times) else None),
                     sorted(jobs.get(t, []), reverse=True, key = lambda j: j.name))
                 for i,t in enumerate(times)]
        return {
            "location": location,
            "times":    times
        }
    
    def signups(self, location = "0"):
        staffers = [a for a in Attendee.staffers() if int(location) in a.assigned]
        
        assigned = defaultdict(list)
        shifts = Shift.objects.filter(job__location = location).select_related()
        for shift in shifts:
            shift.attendee.shift = shift                # TODO: figure out why we're doing this (efficiency?)
            assigned[shift.job].append(shift.attendee)
        
        jobs = []
        for job in Job.objects.filter(location = location).order_by("start_time","duration"):
            available = [s for s in staffers if (not job.restricted or s.trusted)
                                                and not job.hours.intersection(s.hours)]
            jobs.append( (job, assigned[job], available, len(assigned[job])) )
        
        return {
            "location": location,
            "jobs":     jobs,
            "shifts":   Shift.serialize(shifts)
        }
    
    def staffers(self, location="0"):
        staffers = [s for s in Attendee.staffers() if int(location) in s.assigned]
        return {
            "location":       location,
            "emails":         ",".join(s.email for s in staffers),
            "staffers":       [(s,weighted_hours(s, location)) for s in staffers],
            "total_existing": sum(j.slots * j.weighted_hours for j in Job.objects.filter(location = location)),
            "total_signups":  sum(weighted_hours(s, location) for s in staffers)
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
        return {
            "message": message,
            "job":     Job.objects.get(id = id)
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
