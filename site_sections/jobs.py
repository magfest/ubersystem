from common import *

def weighted_hours(staffer, location):
    shifts = Shift.objects.filter(attendee = staffer).select_related()
    return sum([shift.job.real_duration * shift.job.weight
                for shift in shifts
                if shift.job.location == int(location)],
               0.0)

@all_renderable(PEOPLE)
class Root:
    def index(self, location = ARCADE):
        by_id = {}
        jobs = defaultdict(list)
        for job in Job.objects.filter(location = location):
            by_id[job.id] = job
            jobs[job.start_time if not job.start_time.minute else job.start_time - timedelta(minutes = 30)].append(job)
        
        for job in by_id.values():
            job._shifts = []
        for shift in Shift.objects.filter(job__location = location):
            by_id[shift.job_id]._shifts.append(shift)
        
        jobs, shifts, attendees = Job.everything(location)
        by_start = defaultdict(list)
        for job in jobs:
            by_start[job.start_time].append(job)
        times = [state.EPOCH + timedelta(hours = i) for i in range(CON_LENGTH)]
        times = [(t, t + timedelta(hours = 1), by_start[t]) for i,t in enumerate(times)]
        return {
            "location": location,
            "times":    times
        }
    
    def signups(self, location = ARCADE):
        jobs, shifts, attendees = Job.everything(location)
        return {
            "location": location,
            "jobs":     jobs,
            "shifts":   Shift.serialize(shifts)
        }
    
    def everywhere(self, message=""):
        jobs, shifts, attendees = Job.everything()
        return {
            "message":  message,
            "shifts":   Shift.serialize(shifts),
            "jobs":     [job for job in jobs if not job.restricted
                                            and datetime.now() < job.start_time + timedelta(hours = job.duration)]
        }
    
    def staffers(self, location = ARCADE):
        jobs, shifts, attendees = Job.everything()
        return {
            "location":           location,
            "attendees":          attendees,
            "emails":             ",".join(a.email for a in attendees),
            "regular_total":      sum(j.total_hours for j in jobs if not j.restricted),
            "restricted_total":   sum(j.total_hours for j in jobs if j.restricted),
            "all_total":          sum(j.total_hours for j in jobs),
            "regular_signups":    sum(s.job.weighted_hours for s in shifts if not s.job.restricted),
            "restricted_signups": sum(s.job.weighted_hours for s in shifts if s.job.restricted),
            "all_signups":        sum(s.job.weighted_hours for s in shifts)
        }
    
    def form(self, message="", **params):
        defaults = {}
        if params["id"] == "None" and cherrypy.request.method != "POST":
            defaults = cherrypy.session.get("job_defaults", defaultdict(dict))[params["location"]]
            params.update(defaults)
        
        job = get_model(Job, params, bools=["restricted", "extra15"],
                                     allowed=["location", "start_time"] + list(defaults.keys()))
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
        jobs, shifts, attendees = Job.everything()
        [job] = [job for job in jobs if job.id == int(id)]
        job._all_staffers = attendees                       # TODO: is this needed?
        return {
            "job":     job,
            "message": message
        }
    
    @csrf_protected
    def delete(self, id):
        job = Job.objects.get(id=id)
        job.shift_set.all().delete()
        job.delete()
        raise HTTPRedirect("index?location={}#{}", job.location, job.start_time)
    
    @csrf_protected
    def assign_from_job(self, job_id, staffer_id):
        message = assign(staffer_id, job_id) or "Staffer assigned to shift"
        raise HTTPRedirect("staffers_by_job?id={}&message={}", job_id, message)
    
    @csrf_protected
    def assign_from_everywhere(self, job_id, staffer_id):
        message = assign(staffer_id, job_id) or "Staffer assigned to shift"
        raise HTTPRedirect("everywhere?message={}", message)
    
    @csrf_protected
    def assign_from_list(self, job_id, staffer_id):
        location = Job.objects.get(id = job_id).location
        message = assign(staffer_id, job_id)
        if message:
            raise HTTPRedirect("signups?location={}&message={}", location, message)
        else:
            raise HTTPRedirect("signups?location={}#{}", location, job_id)
    
    @csrf_protected
    def unassign_from_job(self, id):
        shift = Shift.objects.get(id = id)
        shift.delete()
        raise HTTPRedirect("staffers_by_job?id={}&message={}", shift.job.id, "Staffer unassigned")
    
    @csrf_protected
    def unassign_from_list(self, id):
        shift = Shift.objects.get(id = id)
        shift.delete()
        raise HTTPRedirect("signups?location={}#{}", shift.job.location, shift.job.id)
    
    @csrf_protected
    def unassign_from_everywhere(self, id):
        shift = Shift.objects.get(id = id)
        shift.delete()
        raise HTTPRedirect("everywhere?#{}", shift.job.id)
    
    @ajax
    def set_worked(self, id, worked):
        try:
            shift = Shift.objects.get(id = id)
            shift.worked = int(worked)
            shift.save()
            return shift.get_worked_display()
        except:
            return "an unexpected error occured"
    
    @ajax
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
    
    def summary(self):
        all_jobs = list(Job.objects.all())
        all_shifts = list(Shift.objects.select_related())
        locations = {}
        for loc,name in JOB_LOC_OPTS:
            jobs = [j for j in all_jobs if j.location == loc]
            shifts = [s for s in all_shifts if s.job.location == loc]
            locations[name] = {
                "regular_total":      sum(j.total_hours for j in jobs if not j.restricted),
                "restricted_total":   sum(j.total_hours for j in jobs if j.restricted),
                "all_total":          sum(j.total_hours for j in jobs),
                "regular_signups":    sum(s.job.weighted_hours for s in shifts if not s.job.restricted),
                "restricted_signups": sum(s.job.weighted_hours for s in shifts if s.job.restricted),
                "all_signups":        sum(s.job.weighted_hours for s in shifts)
            }
        return {"locations": sorted(locations.items(), key = lambda loc: loc[1]["regular_signups"] - loc[1]["regular_total"])}
    
    @csv_file
    def all_shifts(self, out):
        for loc,name in JOB_LOC_OPTS:
            out.writerow([name])
            for shift in Shift.objects.filter(job__location = loc).order_by("job__start_time","job__name").select_related():
                out.writerow([shift.job.start_time.strftime("%I%p %a").lstrip("0"),
                              "{} hours".format(shift.job.real_duration),
                              shift.job.name,
                              shift.attendee.full_name])
            out.writerow([])
