from common import *

def check_prereg_reqs(attendee):
    if attendee.age_group == AGE_UNKNOWN:
        return "You must select an age category"
    elif attendee.badge_type == PSEUDO_DEALER_BADGE and not attendee.phone:
        return "Your phone number is required"
    elif attendee.amount_extra >= SHIRT_LEVEL and attendee.shirt == NO_SHIRT:
        return "Your shirt size is required"

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

def get_unsaved(id, if_not_found = HTTPRedirect("index")):
    for model in cherrypy.session.setdefault("preregs", []):
        if model.secret_id == id:
            return model.get_unsaved()
    raise if_not_found

def send_banned_email(attendee):
    try:
        send_email(REGDESK_EMAIL, REGDESK_EMAIL, "Banned attendee registration",
                   render("emails/banned_attendee.txt", {"attendee": attendee}), model = "n/a")
    except:
        log.error("unable to send banned email about {}", attendee)


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
    
    def form(self, message="", edit_id=None, **params):
        if "badge_type" not in params and edit_id is None:
            raise HTTPRedirect("badge_choice?message={}", "You must select a badge type")
        
        params["id"] = "None"   # security!
        params["affiliate"] = params.get("aff_select") or params.get("aff_text") or ""
        if edit_id is not None:
            attendee, group = get_unsaved(edit_id, if_not_found = HTTPRedirect("badge_choice?message={}", "That preregistration has already been finalized"))
            attendee.apply(params, bools=["staffing","can_spam","international"])
            group.apply(params)
            params.setdefault("badges", group.badges)
        else:
            attendee = Attendee.get(params, bools=["staffing","can_spam","international"], ignore_csrf=True, restricted=True)
            group = Group.get(params, ignore_csrf=True, restricted=True)
        
        if attendee.badge_type not in state.PREREG_BADGE_TYPES:
            raise HTTPRedirect("badge_choice?message={}", "Dealer registration is not open" if attendee.is_dealer else "Invalid badge type")
        
        if "first_name" in params:
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
                    preregs = cherrypy.session.setdefault("preregs", [])
                    if attendee not in preregs and group not in preregs:
                        preregs.append(group if group.badges else attendee)
                        Tracking.track(UNPAID_PREREG, attendee)
                        if group.badges:
                            Tracking.track(UNPAID_PREREG, group)
                    else:
                        Tracking.track(EDITED_PREREG, attendee)
                        if group.badges:
                            Tracking.track(EDITED_PREREG, group)
                
                if Attendee.objects.filter(first_name = attendee.first_name, last_name = attendee.last_name, email = attendee.email):
                    raise HTTPRedirect("duplicate?id={}", group.secret_id if attendee.paid == PAID_BY_GROUP else attendee.secret_id)
                
                if attendee.full_name in BANNED_ATTENDEES:
                    raise HTTPRedirect("banned?id={}", group.secret_id if attendee.paid == PAID_BY_GROUP else attendee.secret_id)
                
                raise HTTPRedirect("index")
        else:
            attendee.can_spam = edit_id is None     # only defaults to true for these forms
        
        return {
            "message":    message,
            "attendee":   attendee,
            "group":      group,
            "edit_id":    edit_id,
            "badges":     params.get("badges"),
            "affiliates": affiliates()
        }
    
    def duplicate(self, id):
        attendee, group = get_unsaved(id)
        orig = Attendee.objects.filter(first_name=attendee.first_name, last_name=attendee.last_name, email=attendee.email)
        if not orig:
            raise HTTPRedirect("index")
        
        return {
            "duplicate": attendee,
            "attendee": orig[0]
        }
    
    def banned(self, id):
        attendee, group = get_unsaved(id)
        return {"attendee": attendee}
    
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
            if attendee.full_name in BANNED_ATTENDEES:
                send_banned_email(attendee)
        
        for group in charge.groups:
            group.assign_prereg_badges()
            group.amount_paid = group.total_cost
            group.save()
            if group.leader.full_name in BANNED_ATTENDEES:
                send_banned_email(group.leader)
        
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
    
    def delete(self, id):
        cherrypy.session["preregs"] = [m for m in cherrypy.session.setdefault("preregs", []) if m.secret_id != id]
        raise HTTPRedirect("index?message={}", "Preregistration deleted")
    
    def dealer_confirmation(self, id):
        return {"group": Group.objects.get(id=id)}
    
    def group_members(self, id, message=""):
        group = Group.objects.get(secret_id = id)
        return {
            "group":   group,
            "charge": Charge(group),
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
                if attendee.full_name in BANNED_ATTENDEES:
                    send_banned_email(attendee)
                
                if attendee.amount_unpaid:
                    raise HTTPRedirect("group_extra_payment_form?id={}", attendee.secret_id)
                else:
                    raise HTTPRedirect("group_members?id={}&message={}", attendee.group.secret_id, "Badge registered successfully")
        else:
            attendee.can_spam = True    # only defaults to true for these forms
        
        return {
            "attendee": attendee,
            "message":  message,
            "affiliates": affiliates()
        }
    
    def group_extra_payment_form(self, id):
        attendee = Attendee.objects.get(secret_id = id)
        return {
            "attendee": attendee,
            "charge": Charge(attendee, description = "{} kicking in extra".format(attendee.full_name))
        }
    
    def group_undo_extra_payment(self, id):
        attendee = Attendee.objects.get(secret_id = id)
        attendee.amount_extra -= attendee.amount_unpaid
        attendee.save()
        raise HTTPRedirect("group_members?id={}&message={}", attendee.group.secret_id, "Extra payment undone")
    
    @credit_card
    def process_group_payment(self, payment_id, stripeToken):
        charge = Charge.get(payment_id)
        [group] = charge.groups
        message = charge.charge_cc(stripeToken)
        if message:
            raise HTTPRedirect("group_members?id={}&message={}", group.secret_id, message)
        else:
            group.amount_paid += charge.dollar_amount
            group.save()
            raise HTTPRedirect("group_members?id={}&message={}", group.secret_id, "Your payment has been accepted!")
    
    @credit_card
    def process_group_member_payment(self, payment_id, stripeToken):
        charge = Charge.get(payment_id)
        [attendee] = charge.attendees
        message = charge.charge_cc(stripeToken)
        if message:
            attendee.amount_extra -= attendee.amount_unpaid
            attendee.save()
            raise HTTPRedirect("group_members?id={}&message={}", attendee.group.secret_id, message)
        else:
            attendee.amount_paid += charge.dollar_amount
            attendee.save()
            raise HTTPRedirect("group_members?id={}&message={}", attendee.group.secret_id, "Extra payment accepted")
    
    @csrf_protected
    def unset_group_member(self, id):
        attendee = Attendee.objects.get(secret_id = id)
        for attr in ["first_name","last_name","email","zip_code","ec_phone","phone","interests","found_how","comments"]:
            setattr(attendee, attr, "")
        attendee.age_group = AGE_UNKNOWN
        attendee.save()
        raise HTTPRedirect("group_members?id={}&message={}", attendee.group.secret_id, "Attendee unset; you may now assign their badge to someone else")
    
    def add_group_members(self, id, count):
        group = Group.objects.get(secret_id = id)
        if not group.can_add:
            raise HTTPRedirect("group_members?id={}&message={}", group.secret_id, "This group cannot add badges")
        
        charge = Charge(group, amount = 100 * int(count) * state.GROUP_PRICE, description = "{} extra badges for {}".format(count, group.name))
        charge.badges_to_add = int(count)
        return {
            "group": group,
            "charge": charge
        }
    
    @credit_card
    def pay_for_extra_members(self, payment_id, stripeToken):
        charge = Charge.get(payment_id)
        [group] = charge.groups
        if charge.dollar_amount != charge.badges_to_add * state.GROUP_PRICE:
            message = "Our preregistration price has gone up since you tried to add the bagdes; please try again"
        else:
            message = charge.charge_cc(stripeToken)
        
        if message:
            raise HTTPRedirect("group_members?id={}&message={}", group.secret_id, message)
        else:
            group.assign_badges(group.badges + charge.badges_to_add)
            group.amount_paid += charge.dollar_amount
            group.save()
            raise HTTPRedirect("group_members?id={}&message={}", group.secret_id, "You payment has been accepted and the badges have been added to your group")
    
    def transfer_badge(self, message = "", **params):
        old = Attendee.objects.get(secret_id = params["id"])
        attendee = Attendee.get(params, bools = ["staffing","international"], restricted = True)
        
        if "first_name" in params:
            message = check(attendee) or check_prereg_reqs(attendee)
            if not message and (not params["first_name"] and not params["last_name"]):
                message = "First and Last names are required."
            if not message:
                attendee.save()
                subject, body = "MAGFest Registration Transferred", render("emails/transfer_badge.txt", {"new": attendee, "old": old})
                try:
                    send_email(REGDESK_EMAIL, [old.email, attendee.email, REGDESK_EMAIL], subject, body, model = attendee)
                except:
                    log.error("unable to send badge change email", exc_info = True)
                
                if attendee.full_name in BANNED_ATTENDEES:
                    send_banned_email(attendee)
                
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
                    message = "Your registration has been confirmed."
                else:
                    message = "Your information has been updated."
                
                page = ("confirm?id=" + attendee.secret_id + "&") if return_to == "confirm" else (return_to + "?")
                if attendee.amount_unpaid:
                    cherrypy.session["return_to"] = page
                    raise HTTPRedirect("attendee_donation_form?id={}", attendee.secret_id)
                else:
                    raise HTTPRedirect(page + "message=" + message)
        elif attendee.amount_unpaid and attendee.zip_code:  # don't skip to payment until the form is filled out
            raise HTTPRedirect("attendee_donation_form?id={}", attendee.secret_id)
        
        attendee.placeholder = placeholder
        if not message and attendee.placeholder:
            message = "You are not yet registered!  You must fill out this form to complete your registration."
        elif not message:
            message = "You are already registered but you may update your information with this form."
        
        return {
            "return_to":  return_to,
            "attendee":   attendee,
            "message":    message,
            "affiliates": affiliates()
        }
    
    def attendee_donation_form(self, id):
        attendee = Attendee.objects.get(secret_id = id)
        return {
            "attendee": attendee,
            "charge": Charge(attendee, description = "{}{}".format(attendee.full_name, "" if attendee.overridden_price else " kicking in extra"))
        }
    
    def undo_attendee_donation(self, id):
        attendee = Attendee.objects.get(secret_id = id)
        attendee.amount_extra = max(0, attendee.amount_extra - attendee.amount_unpaid)
        attendee.save()
        raise HTTPRedirect(cherrypy.session.pop("return_to", "confirm?id=" + id))
    
    def process_attendee_donation(self, payment_id, stripeToken):
        charge = Charge.get(payment_id)
        [attendee] = charge.attendees
        message = charge.charge_cc(stripeToken)
        return_to = cherrypy.session.pop("return_to", "confirm?id=" + attendee.secret_id + "&") + "message={}"
        if message:
            raise HTTPRedirect(return_to, message)
        else:
            attendee.amount_paid += charge.dollar_amount
            attendee.save()
            raise HTTPRedirect(return_to, "Your payment has been accepted, thanks so much!")
    
    def event(self, slug, *, id, register=None):
        attendee = Attendee.objects.get(secret_id = id)
        event = SEASON_EVENTS[slug]
        deadline_passed = datetime.now() > event["deadline"]
        assert attendee.amount_extra >= SEASON_LEVEL
        if register and not deadline_passed:
            SeasonPassTicket.objects.get_or_create(attendee=attendee, slug=slug)
            raise HTTPRedirect(slug + "?id={}", id)
        
        return {
            "event": event,
            "attendee": attendee,
            "deadline_passed": deadline_passed,
            "registered": slug in [spt.slug for spt in attendee.seasonpassticket_set.all()]
        }
    
    def prereg_not_open_yet(self, *args, **kwargs):
        return """
            <html><head></head><body style="color:red ; text-align:center">
                <h2>Preregistration is not yet open.</h2>
                We will announce preregistration opening on magfest.org, check there for updates.
            </body></html>
        """
    
    def prereg_closed(self, *args, **kwargs):
        return """
            <html><head></head><body style="color:red ; text-align:center">
                <h2>Preregistration has closed.</h2>
                We'll see everyone on January 2 - 5.
                Full weekend passes will be available at the door for $60,
                and single day passes will be $35.
            </body></html>
        """
    
    def __getattribute__(self, name):
        if not DEV_BOX and state.PREREG_NOT_OPEN_YET:
            return object.__getattribute__(self, "prereg_not_open_yet")
        elif not DEV_BOX and state.PREREG_CLOSED:
            return object.__getattribute__(self, "prereg_closed")
        else:
            return object.__getattribute__(self, name)
