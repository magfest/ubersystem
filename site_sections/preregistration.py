from common import *

def check_prereg_reqs(attendee):
    if attendee.age_group == AGE_UNKNOWN:
        return "You must select an age category"
    elif attendee.badge_type == PSEUDO_DEALER_BADGE and not attendee.phone:
        return "Your phone number is required"

def check_tables(attendee, group, params):
    if attendee.badge_type == PSEUDO_DEALER_BADGE and group.tables < int(params["badges"]) // 3:
        return "You must get 1 table per 3 badges"

def check_dealer(group):
    if not group.address:
        return "Dealers are required to provide an address for tax purposes"
    elif not group.wares:
        return "You must provide a detail explanation of what you sell for us to evaluate your submission"
    elif not group.website:
        return "Please enter your business' website address"
    elif not group.description:
        return "Please provide a brief description of your business for our website's Confirmed Vendors page"



def send_prereg_emails(attendee):
    try:
        sender = REGDESK_EMAIL
        subject = "MAGFest Preregistration"
        message = "Your preregistration will be complete when you pay below"
        if attendee.group:
            if attendee.group.tables:
                sender = MARKETPLACE_EMAIL
                template = "dealer_email.html"
                subject = "MAGFest Dealer Request Submitted"
                if state.DEALER_REG_FULL:
                    message = "Although dealer registration is closed, your dealer request has been added to our waitlist"
                else:
                    message = "Your dealer request has been submitted, we'll email you after your submission is reviewed"
            else:
                template = "group_email.html"
        else:
            template = "attendee_email.html"
        body = render("emails/" + template, {"attendee": attendee})
        send_email(sender, attendee.email, subject, body, format = "html", model = attendee)
        return message
    except:
        log.warning("unable to send prereg confirmation email to {}", attendee.email, exc_info = True)
        return message + ", but the automated confirmation email could not be sent."



@all_renderable()
class Root:
    def index(self, message=""):
        preregs = cherrypy.session.get("preregs")
        if not preregs:
            raise HTTPRedirect("badge_choice?message={}", message) if message else HTTPRedirect("badge_choice")
        else:
            return {
                "message": message,
                "charge": Charge(preregs)
            }
    
    def badge_choice(self, message=""):
        return {"message": message}
    
    def form(self, message="", **params):
        if "badge_type" not in params:
            raise HTTPRedirect("badge_choice?message={}", "You must select a badge type")
        
        params["id"] = "None"   # security!
        params["affiliate"] = params.get("aff_select") or params.get("aff_text") or ""
        attendee = Attendee.get(params, bools=["staffing","can_spam","international"], ignore_csrf=True, restricted=True)
        group = Group.get(params, ignore_csrf=True, restricted=True)
        if "first_name" in params:
            assert attendee.badge_type in state.PREREG_BADGE_TYPES, "No hacking allowed!"
            message = check(attendee) or check_prereg_reqs(attendee)
            if not message and attendee.badge_type in [PSEUDO_DEALER_BADGE, PSEUDO_GROUP_BADGE]:
                message = check(group) or check_tables(attendee, group, params)
            if not message and attendee.badge_type == PSEUDO_DEALER_BADGE:
                message = check_dealer(group)
            
            if not message:
                if attendee.badge_type in [PSEUDO_DEALER_BADGE, PSEUDO_GROUP_BADGE]:
                    if attendee.badge_type == PSEUDO_GROUP_BADGE:
                        group.tables = 0
                        group.prepare_prereg_badges(attendee, params["badges"])
                    else:
                        group.status = WAITLISTED if state.DEALER_REG_FULL else UNAPPROVED
                        attendee.ribbon = DEALER_RIBBON
                    
                    attendee.badge_type = ATTENDEE_BADGE
                    attendee.paid = PAID_BY_GROUP
                
                if attendee.is_dealer:
                    group.save()
                    attendee.group = group
                    attendee.save()
                    group.assign_badges(params["badges"])
                    send_email(MARKETPLACE_EMAIL, MARKETPLACE_EMAIL, "Dealer application received",
                               render("emails/dealer_reg_notification.txt", {"group": group}))
                    raise HTTPRedirect("dealer_confirmation?id={}", group.id)
                else:
                    cherrypy.session.setdefault("preregs", []).append(group if group.badges else attendee)
                    Tracking.track(UNPAID_PREREG, attendee)
                    if group.badges:
                        Tracking.track(UNPAID_PREREG, group)
                
                # TODO: duplicate check here, as well as banned list check here
                raise HTTPRedirect("index")
        else:
            attendee.can_spam = True    # only defaults to true for these forms
        
        return {
            "message":    message,
            "attendee":   attendee,
            "group":      group,
            "badges":     params.get("badges"),
            "affiliates": affiliates()
        }
    
    @credit_card
    def prereg_payment(self, payment_id, stripeToken):
        charge = Charge.get(payment_id)
        if not charge.total_cost:
            message = "Your preregistration has already been paid for, so your credit card has not been charged"
        elif charge.amount != charge.total_cost:
            message = "Our preregistration price has gone up; please fill out the payment form again at the higher price"
        else:
            message = charge.charge_cc(stripeToken)
        
        if message:
            raise HTTPRedirect("index?message={}", message)
        
        for attendee in charge.attendees:
            attendee.paid = HAS_PAID
            attendee.amount_paid = attendee.total_cost
            attendee.save()
        
        for group in charge.groups:
            group.assign_prereg_badges()
            group.amount_paid = group.total_cost
            group.save()
        
        cherrypy.session.pop("preregs", None)
        preregs = cherrypy.session.setdefault("paid_preregs", {})
        preregs.setdefault("attendees", []).extend(charge.attendees)
        preregs.setdefault("groups", []).extend(charge.groups)
        raise HTTPRedirect("paid_preregs")
    
    def paid_preregs(self):
        preregs = cherrypy.session.get("paid_preregs")
        if preregs:
            return {"preregs": preregs}
        else:
            raise HTTPRedirect("index")
    
    def dealer_confirmation(self, id):
        return {"group": Group.objects.get(id=id)}
    
    if not DEV_BOX and state.PREREG_NOT_OPEN_YET:
        def index(self, message="", *args, **params):
            return """
                <html><head></head><body style="color:red ; text-align:center">
                    <h2>Preregistration is not yet open.</h2>
                    We will announce preregistration opening on magfest.org, check there for updates.
                </body></html>
            """
    
    if not DEV_BOX and state.PREREG_CLOSED:
        def index(self, message="", *args, **params):
            return """
                <html><head></head><body style="color:red ; text-align:center">
                    <h2>Preregistration has closed.</h2>
                    We'll see everyone on January 3 - 6.
                    Full weekend passes will be available at the door for $60,
                    and single day passes will be $35.
                </body></html>
            """
        
    def group_members(self, id, message=""):
        group = Group.objects.get(secret_id = id)
        return {
            "group":   group,
            "message": message
        }
    
    def register_group_member(self, message="", **params):
        attendee = Attendee.get(params, bools=["staffing","can_spam","international"], restricted=True)
        if "first_name" in params:
            message = check(attendee) or check_prereg_reqs(attendee)
            if not message and not params["first_name"]:
                message = "First and Last Name are required fields"
            if not message:
                attendee.save()
                raise HTTPRedirect("group_members?id={}&message={}", attendee.group.secret_id, "Badge registered successfully")
        else:
            attendee.can_spam = True    # only defaults to true for these forms
        
        return {
            "attendee": attendee,
            "message":  message
        }
    
    @csrf_protected
    def unset_group_member(self, id):
        attendee = Attendee.objects.get(secret_id = id)
        for attr in ["first_name","last_name","email","zip_code","ec_phone","phone","interests","found_how","comments"]:
            setattr(attendee, attr, "")
        attendee.age_group = AGE_UNKNOWN
        attendee.save()
        raise HTTPRedirect("group_members?id={}&message={}", attendee.group.secret_id, "Attendee unset; you may now assign their badge to someone else")
    
    @csrf_protected
    def add_group_members(self, id, count):
        group = Group.objects.get(secret_id = id)
        group.assign_badges(group.badges + int(count))
        raise HTTPRedirect("group_members?id={}&message={}", id, "The requested badges have been added to your group; you must pay for them using the Paypal link below to prevent them from being deleted before the start of MAGFest")
    
    def transfer_badge(self, message = "", **params):
        old = Attendee.objects.get(secret_id = params["id"])
        attendee = Attendee.get(params, bools = ["staffing","international"], restricted = True)
        
        if "first_name" in params:
            message = check(attendee) or check_prereg_reqs(attendee)
            if not message:
                attendee.save()
                subject, body = "MAGFest Registration Transferred", render("emails/transfer_badge.txt", {"new": attendee, "old": old})
                try:
                    send_email(REGDESK_EMAIL, [old.email, attendee.email, REGDESK_EMAIL], subject, body, model = attendee)
                except:
                    log.error("unable to send badge change email", exc_info = True)
                raise HTTPRedirect("confirm?id={}&message={}", attendee.secret_id, "Your registration has been transferred")
        else:
            for attr in ["first_name","last_name","email","zip_code","international","ec_phone","phone","interests","age_group","staffing","requested_depts"]:
                setattr(attendee, attr, getattr(Attendee(), attr))
        
        return {
            "old":      old,
            "attendee": attendee,
            "message":  message
        }
    
    def confirm(self, message = "", return_to = "confirm", **params):
        attendee = Attendee.get(params, bools = ["staffing","international"], restricted = True)
        placeholder = attendee.placeholder
        
        if "email" in params:
            attendee.placeholder = False
            message = check(attendee) or check_prereg_reqs(attendee)
            if not message:
                attendee.save()
                if placeholder:
                    message = "Your registeration has been confirmed."
                else:
                    message = "Your information has been updated."
                
                page = ("confirm?id=" + attendee.secret_id + "&") if return_to == "confirm" else (return_to + "?")
                raise HTTPRedirect(page + "message={}", message)
        
        attendee.placeholder = placeholder
        if not message and attendee.placeholder:
            message = "You are not yet registered!  You must fill out this form to complete your registration."
        elif not message:
            message = "You are already registered but you may update your information with this form."
        
        return {
            "return_to": return_to,
            "attendee":  attendee,
            "message":   message
        }

if state.UBER_SHUT_DOWN:
    Root = type("Root", (), {"index": Root.index.im_func})
