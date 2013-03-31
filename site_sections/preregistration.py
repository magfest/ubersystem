from common import *

def check_prereg_reqs(attendee):
    if attendee.age_group == AGE_UNKNOWN:
        return "You must select an age category"
    elif attendee.badge_type == PSEUDO_DEALER_BADGE and not attendee.phone:
        return "Your phone number is required"

def check_payment(qs):
    resp = urlopen(PAYPAL_ACTION + "?cmd=_notify-validate&" + qs).read().lower()
    if resp != "verified":
        return "Paypal response {!r} != 'verified'".format(resp)

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


def cost_and_names(preregs):
    total, names = 0, []
    for attendee in preregs:
        if attendee.paid == NOT_PAID:
            total += attendee.total_cost
            names.append(attendee.full_name)
        elif attendee.group and attendee.group.amount_paid == 0:
            total += attendee.group.total_cost
            names.append(attendee.group.name)
    return (total, ", ".join(names)) if len(names) > 1 else (0, [])

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

def keep_body():
    if cherrypy.request.method == "POST":
        cherrypy.request.process_request_body = False
cherrypy.tools.keep_body = cherrypy.Tool('before_request_body', keep_body)



def send_callback_email(subject, params):
    send_email(REGDESK_EMAIL, REGDESK_EMAIL, subject, repr(params))

def parse_ids(item_num):
    ids = defaultdict(list)
    for id in item_num.strip().split(","):
        if re.match(r"a\d+", id):
            ids["attendees"].append( int(id[1:]) )
        elif re.match(r"g\d+", id):
            ids["groups"].append( int(id[1:]) )
        else:
            ids["unknown"].append(id)
    return ids

def mark_group_paid(id):
    group = Group.objects.get(id=id)
    paid = group.amount_unpaid
    group.amount_paid = group.amount_owed
    group.save()
    return paid

def mark_attendee_paid(id):
    attendee = Attendee.objects.get(id=id)
    amount_paid_before = attendee.amount_paid
    attendee.amount_paid = attendee.total_cost
    if attendee.paid in [NOT_PAID, NEED_NOT_PAY]:
        attendee.paid = HAS_PAID
    attendee.save()
    if amount_paid_before == attendee.total_cost:
        Tracking.objects.create(model = "Attendee", fk_id = id, who = "Paypal callback", action = UPDATED, links = "",
                                which = repr(attendee), data = "amount_paid ='{0} -> {0}'".format(attendee.total_cost))
    return max(attendee.total_cost - amount_paid_before, 0)

def get_prereg_ids(preregs):
    ids = []
    for attendee in preregs:
        if attendee.group:
            ids += ["g{}".format(attendee.group.id)]
        else:
            ids += ["a{}".format(attendee.id)]
    return ",".join(ids)

@all_renderable()
class Root:
    def index(self, message="", *args, **params):
        if params.get("id") is None and "preregs" in cherrypy.session:
            preregs = Attendee.objects.filter(id__in = cherrypy.session["preregs"])
            if preregs:
                data = {
                    "ids": get_prereg_ids(preregs),
                    "message": message,
                    "preregs": preregs
                }
                data["total"], data["names"] = cost_and_names(preregs)
                return render("preregistration/index.html", data)
        
        if "badge_type" not in params:
            if cherrypy.request.method == "POST":
                message = "You must choose a badge type"
            return render("preregistration/badge_choice.html", {"message": message})
        
        params["id"] = "None"
        params["affiliate"] = params.get("aff_select") or params.get("aff_text") or ""
        attendee = get_model(Attendee, params, bools = ["staffing","can_spam","international"], restricted = True)
        group = get_model(Group, params, restricted = True)
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
                    else:
                        group.status = WAITLISTED if state.DEALER_REG_FULL else UNAPPROVED
                        attendee.ribbon = DEALER_RIBBON
                    
                    group.save()
                    attendee.badge_type = ATTENDEE_BADGE
                    attendee.paid = PAID_BY_GROUP
                    attendee.group = group
                    attendee.save()
                    assign_group_badges(group, params["badges"])
                else:
                    attendee.save()
                
                if not attendee.group or not attendee.group.is_dealer:
                    cherrypy.session.setdefault("preregs", []).append(attendee.id)
                else:
                    send_email(MARKETPLACE_EMAIL, MARKETPLACE_EMAIL, "Dealer application received",
                               render("emails/dealer_reg_notification.txt", {"group": group}))
                
                message = send_prereg_emails(attendee)
                raise HTTPRedirect("index?message={}", message)
        else:
            attendee.can_spam = True    # only defaults to true for these forms
        
        data = {
            "message":    message,
            "attendee":   attendee,
            "group":      group,
            "badges":     params.get("badges"),
            "affiliates": affiliates()
        }
        return render("preregistration/form.html", data)
    
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
    
    @cherrypy.tools.keep_body()
    def callback(self):
        try:
            body = cherrypy.request.rfile.read()
            log.debug("paypal callback: {}", body)
            params = dict(tup for tup in parse_qsl(body))
        except:
            log.error("invalid invocation of paypal callback", exc_info = True)
            return "error"
        
        try:
            payment_error = check_payment(body)
            status = params.get(PAYPAL_STATUS, "").lower()
            if payment_error:
                send_callback_email("Paypal callback unverified", dict(params, payment_error = payment_error))
            elif status != "completed":
                subject = "Paypal callback incomplete: " + status
                if status == "pending" and params.get(PAYPAL_REASON, "").lower() == "paymentreview":
                    subject += " payment review"
                send_callback_email(subject, params)
            else:
                ids = parse_ids(params.get(PAYPAL_ITEM, ""))
                if not ids or ids["unknown"]:
                    send_callback_email("Paypal callback with unknown item number", params)
                else:
                    total_cost = 0
                    for key,func in [("groups",mark_group_paid), ("attendees",mark_attendee_paid)]:
                        for id in ids[key]:
                            total_cost += func(id)
                    if total_cost != float(params[PAYPAL_COST]):
                        send_callback_email("Paypal callback with non-matching payment amount: {} != {}".format(total_cost, float(params[PAYPAL_COST])), params)
                    else:
                        send_callback_email("Paypal callback payments marked", params)
        except:
            error = traceback.format_exc() + "\n" + str(params)
            log.error("unexpected paypal callback error: {}", error)
            send_callback_email("Paypal callback error", error)
            return "error"
        else:
            return "ok"
    
    def check(self, message="", **params):
        attendee = None
        if params.get("first_name"):
            matching = Attendee.objects.filter(first_name__iexact=params["first_name"],
                                               last_name__iexact=params["last_name"],
                                               zip_code=params["zip_code"])
            if matching.count():
                message = "You are registered!"
                a = matching[0]
                if a.placeholder or a.paid == NOT_PAID or (a.paid == PAID_BY_GROUP and a.group.amount_paid != a.group.amount_owed):
                    attendee = matching[0]
            else:
                message = "No attendee matching that name and zip code is in the database (try nicknames before giving up)"
        
        return {
            "message":    message,
            "attendee":   attendee,
            "first_name": params.get("first_name", ""),
            "last_name":  params.get("last_name",  ""),
            "zip_code":   params.get("zip_code",   "")
        }
    
    def paypal(self, id, amount = None):
        attendee = Attendee.objects.get(secret_id = id)
        return {
            "attendee": attendee,
            "amount":   amount or attendee.total_cost
        }
    
    def group_members(self, id, message=""):
        group = Group.objects.get(secret_id = id)
        return {
            "group":   group,
            "message": message
        }
    
    def register_group_member(self, message="", **params):
        attendee = get_model(Attendee, params, bools = ["staffing","can_spam","international"], restricted = True)
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
        assign_group_badges(group, group.badges + int(count))
        raise HTTPRedirect("group_members?id={}&message={}", id, "The requested badges have been added to your group; you must pay for them using the Paypal link below to prevent them from being deleted before the start of MAGFest")
    
    def transfer_badge(self, message = "", **params):
        old = Attendee.objects.get(secret_id = params["id"])
        attendee = get_model(Attendee, params, bools = ["staffing","international"], restricted = True)
        
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
        attendee = get_model(Attendee, params, bools = ["staffing","international"], restricted = True)
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
