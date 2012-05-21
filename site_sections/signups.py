from common import *

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
    def index(self):
        raise HTTPRedirect("possible")  # TODO: which page should be the default?
    
    def schedule(self, message=""):
        return {
            "message": message,
            "attendee": Attendee.objects.get(id = cherrypy.session["staffer_id"])
        }
    
    def possible(self, message=""):
        return {
            "message": message,
            "attendee": Attendee.objects.get(id = cherrypy.session["staffer_id"])
        }
    
    def sign_up(self, job_id):
        message = assign(cherrypy.session["staffer_id"], job_id) or "Signup successful"
        raise HTTPRedirect("possible?message={}", message)
    
    def drop(self, shift_id):
        Shift.objects.filter(id=shift_id, attendee = cherrypy.session["staffer_id"]).delete()
        raise HTTPRedirect("schedule?message={}", "Shift dropped")
    
    @unrestricted
    def login(self, message="", full_name="", email="", zip_code=""):
        if full_name or email or zip_code:
            try:
                attendee = get_attendee(full_name, email, zip_code)
                if not attendee.staffing:
                    message = "You are not signed up as a volunteer!  Email {} if you are interested in volunteering.".format(STAFF_EMAIL)
                elif not attendee.assigned:
                    message = "You have not been assigned to any departmemts; an admin must assign you to a department before you can log in"
            except:
                message = "No attendee matches that name and email address and zip code"
            
            if not message:
                cherrypy.session["staffer_id"] = attendee.id
                raise HTTPRedirect("index")
        
        return {
            "message":   message,
            "full_name": full_name,
            "email":     email,
            "zip_code":  zip_code
        }
