from uber.common import *

def get_attendee(full_name, email, zip_code):
    words = full_name.split()
    for i in range(1, len(words)):
        first, last = " ".join(words[:i]), " ".join(words[i:])
        attendee = Attendee.objects.filter(first_name__iexact=first, last_name__iexact=last,
                                           email__iexact=email, zip_code=zip_code)
        if attendee:
            return attendee[0]
    raise ValueError("attendee not found")

@all_renderable(SIGNUPS)
class Root:
    @property
    def staffer(self):
        return Attendee.objects.get(id = cherrypy.session["staffer_id"])
    
    if UBER_SHUT_DOWN:
        def index(self):
            return render("signups/printable.html", {"attendee": self.staffer})
    else:
        def index(self, message = ""):
            return {
                "message": message,
                "attendee": self.staffer
            }
        
    if not UBER_SHUT_DOWN:
        def fire_safety(self, message = "", fire_safety_cert = None, csrf_token = None):
            attendee = self.staffer
            if fire_safety_cert is not None:
                check_csrf(csrf_token)
                if not re.match(r"^\d{5}\.\d{5,11}$", fire_safety_cert):
                    message = "That is not a valid certification number"
                else:
                    attendee.fire_safety_cert = fire_safety_cert
                    attendee.save()
                    raise HTTPRedirect("index?message={}", "Your fire safety certification has been received")
            
            return {
                "message": message,
                "attendee": attendee,
                "fire_safety_cert": fire_safety_cert or ""
            }
        
        def food_restrictions(self, message="", **params):
            if params:
                FoodRestrictions.get(dict(params, attendee_id = self.staffer.id), 
                                     allowed = ["attendee_id", "freeform"], checkgroups = ["standard"]).save()
                if self.staffer.badge_type == GUEST_BADGE:
                    raise HTTPRedirect("food_restrictions?message={}", "Your info has been recorded, thanks a bunch!")
                else:
                    raise HTTPRedirect("index?message={}", "Your dietary restrictions have been recorded")
            else:
                return {
                    "message": message,
                    "attendee": self.staffer,
                    "fr": self.staffer.food_restrictions or FoodRestrictions()
                }
        
        def hotel_requests(self, message = "", decline = None, **params):
            attendee = self.staffer
            requests = HotelRequests.get(params, checkgroups = ["nights"], restricted = True)
            if "attendee_id" in params:
                if decline or not requests.nights:
                    requests.nights = ""
                    requests.save()
                    raise HTTPRedirect("index?message={}", "We've recorded that you've declined hotel room space")
                else:
                    requests.save()
                    nondefault = set(map(int, requests.nights.split(","))) - {THURSDAY, FRIDAY, SATURDAY}
                    if nondefault:
                        days = " / ".join(dict(NIGHTS_OPTS)[day] for day in sorted(nondefault))
                        message = "Your hotel room request has been submitted.  We'll let you know whether your offer to help on {} is accepted, and who your roommates will be, in the first week of December.".format(days)
                    else:
                        message = "You've accepted hotel room space for Thursday / Friday / Saturday.  We'll let you know your roommates in the first week of December."
                    raise HTTPRedirect("index?message={}", message)
            else:
                requests = attendee.hotel_requests or requests
            
            return {
                "message":  message,
                "requests": requests,
                "attendee": attendee
            }
        
        @unrestricted
        def volunteer(self, id, csrf_token = None, requested_depts = "", message = "Select which departments interest you as a volunteer."):
            attendee = Attendee.objects.get(secret_id = id)
            if requested_depts:
                check_csrf(csrf_token)
                attendee.staffing = True
                attendee.requested_depts = ",".join(listify(requested_depts))
                attendee.save()
                raise HTTPRedirect("login?message={}", "Thanks for signing up as a volunteer; you'll be emailed as soon as you are assigned to one or more departments.")
            
            return {
                "message": message,
                "attendee": attendee,
                "requested_depts": requested_depts
            }
        
        @ng_renderable
        def shifts(self):
            return {
                "jobs": self._jobs(),
                "name": self.staffer.full_name
            }

        def _jobs(self):
            return json.dumps([job.to_dict() for job in self.staffer.possible_and_current])

        def jobs(self):
            return json.dumps({"jobs": json.loads(self._jobs())})

        @ajax
        def sign_up(self, job_id):
            return {
                "error": assign(self.staffer.id, job_id),
                "jobs": json.loads(self._jobs())
            }

        @ajax
        def drop(self, job_id):
            try:
                Shift.objects.get(job_id=job_id, attendee=self.staffer).delete()
            except:
                pass
            finally:
                return {"jobs": json.loads(self._jobs())}

        def templates(self, template):
            return ng_render(os.path.join("signups", template))
    
    @unrestricted
    def login(self, message="", full_name="", email="", zip_code=""):
        if full_name or email or zip_code:
            try:
                attendee = get_attendee(full_name, email, zip_code)
                if not attendee.staffing:
                    message = SafeString('You are not signed up as a volunteer.  <a href="volunteer?id={}">Click Here</a> to sign up.'.format(attendee.secret_id))
                elif not attendee.assigned:
                    message = "You have not been assigned to any departmemts; an admin must assign you to a department before you can log in"
            except:
                message = "No attendee matches that name and email address and zip code"
            
            if not message:
                cherrypy.session["csrf_token"] = uuid4().hex
                cherrypy.session["staffer_id"] = attendee.id
                raise HTTPRedirect("index")
        
        return {
            "message":   message,
            "full_name": full_name,
            "email":     email,
            "zip_code":  zip_code
        }
