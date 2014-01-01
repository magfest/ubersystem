from common import *

# TODO: mixin or decorator for getattr-on-MultiChoiceField
class MultiChoiceField(CommaSeparatedIntegerField):
    def __init__(self, *args, **kwargs):
        choices = kwargs.pop("choices")
        kwargs.setdefault("max_length", 255)
        CommaSeparatedIntegerField.__init__(self, *args, **kwargs)
        self._choices = choices

class UuidField(CharField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_length", 32)
        kwargs.setdefault("default", lambda: uuid4().hex)
        CharField.__init__(self, *args, **kwargs)

class MagModel(Model):
    class Meta:
        abstract = True
        app_label = ""
    
    def presave_adjustments(self):
        pass
    
    def save(self, *args, **kwargs):
        self.presave_adjustments()
        super(MagModel, self).save(*args, **kwargs)
    
    @classmethod
    def get_field(cls, name):
        [field] = [f for f in cls._meta.fields if f.name == name]
        return field
    
    def field_repr(self, name):
        try:
            field = self.get_field(name)
            val = getattr(self, name)
            s = repr(val)
            if isinstance(field, MultiChoiceField):
                opts = dict(field.choices)
                return repr("" if not val else ",".join(opts[int(opt)] for opt in val.split(",")))
            elif field.choices and val is not None:
                return repr(dict(field.choices)[int(val)])
            else:
                return s
        except Exception as e:
            raise ValueError("error formatting {} ({!r})".format(name, val)) from e
    
    def __repr__(self):
        display = getattr(self, "display", "name" if hasattr(self, "name") else "id")
        return "<{}>".format(" ".join(str(getattr(self, field)) for field in listify(display)))
    __str__ = __repr__
    
    def __eq__(self, m):
        return isinstance(m, self.__class__) and self.id == m.id and getattr(self, "secret_id", None) == getattr(m, "secret_id", None)
    
    def __getattr__(self, name):
        if name.endswith("_ints"):
            val = getattr(self, name[:-5])
            return [int(i) for i in val.split(",")] if val else []
        raise AttributeError(name)
    
    @classmethod
    def get(cls, params, bools=[], checkgroups=[], allowed=[], restricted=False, ignore_csrf=False):
        params = params.copy()
        id = params.pop("id", "None")
        if id == "None":
            model = cls()
        elif str(id).isdigit():
            model = cls.objects.get(id = id)
        else:
            model = cls.objects.get(secret_id = id)
        
        if not ignore_csrf:
            assert not {k for k in params if k not in allowed} or cherrypy.request.method == "POST", "POST required"
        model.apply(params, bools, checkgroups, allowed, restricted, ignore_csrf)
        return model
    
    def apply(self, params, bools=[], checkgroups=[], allowed=[], restricted=True, ignore_csrf=True):
        for field in self._meta.fields:
            if restricted and field.name in self.restricted:
                continue

            id_param = field.name + "_id"
            if isinstance(field, (ForeignKey, OneToOneField)) and id_param in params:
                setattr(self, id_param, params[id_param])

            elif field.name in params and field.name != "id":
                if isinstance(params[field.name], list):
                    value = ",".join(params[field.name])
                elif isinstance(params[field.name], bool):
                    value = params[field.name]
                else:
                    value = str(params[field.name]).strip()

                try:
                    if isinstance(field, IntegerField):
                        value = int(float(value))
                    elif isinstance(field, DateTimeField):
                        value = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
                except:
                    pass

                setattr(self, field.name, value)

        if cherrypy.request.method.upper() == "POST":
            for field in self._meta.fields:
                if field.name in bools:
                    setattr(self, field.name, field.name in params and bool(int(params[field.name])))
                elif field.name in checkgroups and field.name not in params:
                    setattr(self, field.name, "")

            if not ignore_csrf:
                check_csrf(params.get("csrf_token"))

class TakesPaymentMixin(object):
    @property
    def payment_deadline(self):
        return min(state.UBER_TAKEDOWN - timedelta(days = 2),
                   datetime.combine((self.registered + timedelta(days = 14)).date(), time(23, 59)))

def _night(name):
    import constants
    day = getattr(constants, name.upper())
    def lookup(self):
        return day if day in self.nights_ints else ""
    lookup.__name__ = name
    lookup = property(lookup)
    def setter(self, val):
        if val:
            self.nights = "{},{}".format(self.nights, day).strip(",")
        else:
            self.nights = ",".join([str(night) for night in self.nights_ints if night != day])
    setter.__name__ = name
    return lookup.setter(setter)

class NightsMixin(object):
    @property
    def nights_display(self):
        ordered = sorted(self.nights_ints, key=lambda i: ORDERED_NIGHTS.index(i))
        return " / ".join(dict(NIGHTS_OPTS)[val] for val in ordered)
    
    @property
    def setup_teardown(self):
        return self.wednesday or self.sunday
    
    locals().update({mutate(name): _night(mutate(name)) for name in NIGHT_NAMES for mutate in [str.upper, str.lower]})



class Account(MagModel):
    name   = CharField(max_length = 50)
    email  = CharField(max_length = 50)
    hashed = CharField(max_length = 128)
    access = MultiChoiceField(choices = ACCESS_OPTS)
    
    @staticmethod
    def is_nick():
        return Account.admin_name() in ["Nick Marinelli", "Matt Reid"]
    
    @staticmethod
    def admin_name():
        try:
            return Account.objects.get(id = cherrypy.session.get("account_id")).name
        except:
            return None
    
    @staticmethod
    def access_set(id = None):
        try:
            id = id or cherrypy.session.get("account_id")
            return {int(a) for a in Account.objects.get(id=id).access.split(",")}
        except:
            return set()

class PasswordReset(MagModel):
    account   = ForeignKey(Account)
    generated = DateTimeField(auto_now_add = True)
    hashed    = CharField(max_length = 128)



class MoneySource(MagModel):
    name = CharField(max_length = 50)

class MoneyDept(MagModel):
    name = CharField(max_length = 50)
    amount = IntegerField()
    
    @property
    def allocations(self):
        return self.money_set.order_by("-amount", "name")
    
    @property
    def allocated(self):
        return sum(m.amount for m in self.allocations)

class Money(MagModel):
    type        = IntegerField(choices = BUDGET_TYPE_OPTS)
    name        = CharField(max_length = 50)
    amount      = IntegerField()
    description = TextField()
    paid_by     = ForeignKey(MoneySource, null = True)
    dept        = ForeignKey(MoneyDept, null = True)
    pledged     = BooleanField()
    estimate    = BooleanField()
    pre_con     = BooleanField()
    
    @cached_property
    def payment_total(self):
        return sum(p.amount for p in self.payment_set.all())

class Payment(MagModel):
    money  = ForeignKey(Money)
    type   = IntegerField(choices = PAYMENT_TYPE_OPTS)
    amount = IntegerField()
    name   = CharField(max_length = 50)
    day    = DateField()



class Event(MagModel):
    location    = IntegerField(choices = EVENT_LOC_OPTS, null = True)
    start_time  = DateTimeField(null = True)
    duration    = IntegerField()
    name        = CharField(max_length = 99)
    description = TextField()
    
    @property
    def half_hours(self):
        half_hours = set()
        for i in range(self.duration):
            half_hours.add(self.start_time + timedelta(minutes = 30 * i))
        return half_hours
    
    @property
    def minutes(self):
        return self.duration * 30
    
    @property
    def start_slot(self):
        if self.start_time:
            return int((self.start_time - state.EPOCH).total_seconds() / (60 * 30))



class Group(MagModel, TakesPaymentMixin):
    secret_id     = UuidField()
    name          = CharField(max_length = 50)
    tables        = IntegerField()
    address       = TextField()
    website       = CharField(max_length = 255)
    wares         = TextField()
    description   = TextField()
    special_needs = TextField()
    amount_paid   = IntegerField(default = 0)
    amount_owed   = IntegerField(default = 0)
    auto_recalc   = BooleanField(default = True)
    status        = IntegerField(default = UNAPPROVED, choices = STATUS_OPTS)
    can_add       = BooleanField(default = False)
    admin_notes   = TextField()
    registered    = DateTimeField(auto_now_add = True)
    approved      = DateTimeField(null = True)
    
    restricted = ["amount_paid","amount_owed","auto_recalc","admin_notes","lockable","status","approved"]
    
    def presave_adjustments(self):
        self.__dict__.pop("_attendees", None)
        if self.auto_recalc:
            self.amount_owed = self.total_cost
        if self.status == APPROVED and not self.approved:
            self.approved = datetime.now()
    
    def prepare_prereg_badges(self, attendee, badges):
        self._badges = int(badges)
        self.preregisterer = attendee
    
    def assign_prereg_badges(self):
        self.save()
        self.preregisterer.group = self
        self.preregisterer.save()
        self.assign_badges(self.badges)
    
    def get_unsaved(self):
        attendee = deepcopy(self.preregisterer)
        attendee.badge_type = PSEUDO_GROUP_BADGE
        return attendee, self
    
    def assign_badges(self, new_badge_count):
        self.save()
        ribbon = self.get_new_ribbon()
        badge_type = self.get_new_badge_type()
        new_badge_count = int(new_badge_count)
        diff = new_badge_count - self.attendee_set.filter(paid = PAID_BY_GROUP).count()
        if diff > 0:
            for i in range(diff):
                Attendee.objects.create(group=self, badge_type=badge_type, ribbon=ribbon, paid=PAID_BY_GROUP)
        elif diff < 0:
            floating = list(self.attendee_set.filter(paid=PAID_BY_GROUP, first_name="", last_name=""))
            if len(floating) < abs(diff):
                return "You can't reduce the number of badges for a group to below the number of assigned badges"
            else:
                for i in range(abs(diff)):
                    floating[i].delete()
        self.save()
    
    def get_new_badge_type(self):
        if GUEST_BADGE in self.attendee_set.values_list("badge_type", flat=True):
            return GUEST_BADGE
        else:
            return ATTENDEE_BADGE
    
    def get_new_ribbon(self):
        ribbons = set(self.attendee_set.values_list("ribbon", flat=True))
        for ribbon in [DEALER_RIBBON, BAND_RIBBON, NO_RIBBON]:
            if ribbon in ribbons:
                return ribbon
        else:
            return DEALER_RIBBON if self.is_dealer else NO_RIBBON
    
    @staticmethod
    def everyone():
        attendees = Attendee.objects.select_related("group")
        groups = {g.id: g for g in Group.objects.all()}
        for g in groups.values():
            g._attendees = []
        for a in Attendee.objects.filter(group__isnull = False).select_related("group"):
            if a.group:
                groups[a.group_id]._attendees.append(a)
        return list(attendees), list(groups.values())
    
    @property
    def is_dealer(self):
        return bool(self.tables and (not self.id or self.amount_paid or self.amount_owed))
    
    @property
    def is_unpaid(self):
        return self.amount_owed > 0 and self.amount_paid == 0
    
    @property
    def email(self):
        return self.leader and self.leader.email
    
    @cached_property
    def leader(self):
        for a in sorted(self.attendees, key = lambda a: a.id):
            if a.email:
                return a
    
    @cached_property
    def attendees(self):
        return list(self.attendee_set.order_by("id"))
    
    @property
    def badges_purchased(self):
        return len([a for a in self.attendees if a.paid == PAID_BY_GROUP])
    
    @cached_property
    def badges(self):
        return len(self.attendees)
    
    @property
    def unregistered_badges(self):
        return len([a for a in self.attendees if not a.first_name])
    
    @property
    def table_cost(self):
        prices = {0: 0, 1: 125, 2: 175, 3: 225}
        total = 0
        for table in range(self.tables + 1):
            total += prices.get(table, 300)
        return total
    
    @property
    def badge_cost(self):
        if not self.id:
            return self.badges * state.GROUP_PRICE
        else:
            total = 0
            for attendee in self.attendees:
                if attendee.paid == PAID_BY_GROUP:
                    if attendee.ribbon == DEALER_RIBBON:
                        total += DEALER_BADGE_PRICE
                    elif attendee.registered <= state.PRICE_BUMP:
                        total += EARLY_GROUP_PRICE
                    elif attendee.registered < state.SECOND_GROUP_BUMP:
                        total += LATE_GROUP_PRICE
                    else:
                        total += LATER_GROUP_PRICE
            return total
    
    @property
    def total_cost(self):
        return self.table_cost + self.badge_cost
    
    @property
    def amount_unpaid(self):
        return (self.amount_owed - self.amount_paid) if self.id else self.badge_cost
    
    @property
    def min_badges_addable(self):
        return 1 if self.can_add else (
               0 if self.is_dealer else 5)



class Attendee(MagModel, TakesPaymentMixin):
    secret_id     = UuidField()
    group         = ForeignKey(Group, null = True)
    placeholder   = BooleanField(default = False)
    first_name    = CharField(max_length = 25)
    last_name     = CharField(max_length = 25)
    international = BooleanField(default = False)
    zip_code      = CharField(max_length = 20)
    ec_phone      = CharField(max_length = 20)
    phone         = CharField(max_length = 20)
    email         = CharField(max_length = 50)
    age_group     = IntegerField(default = AGE_UNKNOWN, choices = AGE_GROUP_OPTS)
    reg_station   = IntegerField(null = True)
    
    interests   = MultiChoiceField(choices = INTEREST_OPTS)
    found_how   = CharField(max_length = 100)
    comments    = CharField(max_length = 255)
    for_review  = TextField()
    admin_notes = TextField()
    
    badge_num  = IntegerField(default = 0)
    badge_type = IntegerField(choices = BADGE_OPTS)
    ribbon     = IntegerField(default = NO_RIBBON, choices = RIBBON_OPTS)
    
    affiliate    = CharField(max_length = 50, default = "")
    shirt        = IntegerField(choices = SHIRT_OPTS)
    can_spam     = BooleanField(default = False)
    regdesk_info = CharField(max_length = 255, default = "")
    extra_merch  = CharField(max_length = 255, default = "")
    got_merch    = BooleanField(default = False)
    
    registered = DateTimeField(auto_now_add = True)
    checked_in = DateTimeField(null = True)
    
    paid             = IntegerField(default = NOT_PAID, choices = PAID_OPTS)
    overridden_price = IntegerField(default = None, null = True)
    amount_paid      = IntegerField(default = 0)
    amount_extra     = IntegerField(default = 0, choices = DONATION_OPTS)
    amount_refunded  = IntegerField(default = 0)
    payment_method   = IntegerField(null = True, choices = PAYMENT_OPTIONS)
    
    badge_printed_name = CharField(max_length = 30, default = "")
    
    staffing         = BooleanField(default = False)
    fire_safety_cert = CharField(max_length = 50, default = "")
    requested_depts  = MultiChoiceField(choices = JOB_INTEREST_OPTS)
    assigned_depts   = MultiChoiceField(choices = JOB_LOC_OPTS)
    trusted          = BooleanField(default = False)
    nonshift_hours   = IntegerField(default = 0)
    past_years       = TextField(default = "")
    
    display = "full_name"
    restricted = ["group","admin_notes","badge_num","ribbon","regdesk_info","extra_merch","got_merch","paid","amount_paid","amount_refunded","assigned_depts","trusted","nonshift_hours"]
    
    def presave_adjustments(self):
        import badge_funcs
        
        if self.age_group == UNDER_18:
            self.staffing = False
            self.assigned_depts = self.requested_depts = ""
            if self.ribbon == VOLUNTEER_RIBBON:
                self.ribbon = NO_RIBBON
        
        if self.ribbon == DEPT_HEAD_RIBBON:
            if not state.CUSTOM_BADGES_REALLY_ORDERED:
                self.badge_type = STAFF_BADGE
            self.staffing = self.trusted = True
            if self.paid == NOT_PAID:
                self.paid = NEED_NOT_PAY
        
        with BADGE_LOCK:
            if not state.AT_THE_CON:
                if self.amount_extra >= SUPPORTER_LEVEL and not self.amount_unpaid and self.badge_type == ATTENDEE_BADGE and not state.CUSTOM_BADGES_REALLY_ORDERED:
                    self.badge_type = SUPPORTER_BADGE
                
                if self.paid == NOT_PAID or self.badge_type not in PREASSIGNED_BADGE_TYPES:
                    self.badge_num = 0
                elif self.badge_type in PREASSIGNED_BADGE_TYPES and not self.badge_num:
                    if state.CUSTOM_BADGES_REALLY_ORDERED:
                        self.ribbon = VOLUNTEER_RIBBON if self.badge_type == STAFF_BADGE else self.ribbon
                        self.badge_type, self.badge_num = ATTENDEE_BADGE, 0
                    elif self.paid != NOT_PAID:
                        self.badge_num = badge_funcs.next_badge_num(self.badge_type)
        
        if not self.amount_extra:
            self.affiliate = ""
        
        if self.amount_extra < SHIRT_LEVEL:
            self.shirt = NO_SHIRT
        
        if self.staffing and self.badge_type == ATTENDEE_BADGE and self.ribbon == NO_RIBBON:
            self.ribbon = VOLUNTEER_RIBBON
        elif self.staffing and self.badge_type == STAFF_BADGE and self.ribbon == VOLUNTEER_RIBBON:
            self.ribbon = NO_RIBBON
        
        if self.badge_type == STAFF_BADGE or self.ribbon == VOLUNTEER_RIBBON:
            self.staffing = True
        elif self.age_group == UNDER_18:
            self.staffing = False
        
        if not self.staffing:
            self.requested_depts = self.assigned_depts = ""
        
        if self.paid != REFUNDED:
            self.amount_refunded = 0
        
        if state.AT_THE_CON and self.badge_num and self.id is None:
            self.checked_in = datetime.now()
        
        for attr in ["first_name", "last_name"]:
            value = getattr(self, attr)
            if value.isupper() or value.islower():
                setattr(self, attr, value.title())
    
    def delete(self, *args, **kwargs):
        import badge_funcs
        with BADGE_LOCK:
            badge_num = Attendee.objects.get(id = self.id).badge_num
            super(Attendee, self).delete(*args, **kwargs)
            if self.badge_type not in PREASSIGNED_BADGE_TYPES or not state.CUSTOM_BADGES_REALLY_ORDERED:
                badge_funcs.shift_badges(self, down = True)
    
    def get_unsaved(self):
        return self, Group()
    
    @staticmethod
    def staffers():
        return Attendee.objects.filter(staffing = True).order_by("first_name","last_name")
    
    @property
    def badge_cost(self):
        registered = self.registered or datetime.now()
        if self.paid in [PAID_BY_GROUP, NEED_NOT_PAY]:
            return 0
        elif self.overridden_price is not None:
            return self.overridden_price
        elif self.badge_type == ONE_DAY_BADGE:
            return state.get_oneday_price(registered)
        elif registered < state.PRICE_BUMP:
            return EARLY_BADGE_PRICE
        elif registered < state.SECOND_PRICE_BUMP:
            return LATE_BADGE_PRICE
        elif registered > state.PREREG_TAKEDOWN:
            return DOOR_BADGE_PRICE
        else:
            return LATER_BADGE_PRICE
    
    @property
    def total_cost(self):
        return self.badge_cost + self.amount_extra
    
    @property
    def amount_unpaid(self):
        return max(0, self.total_cost - self.amount_paid)
    
    @property
    def is_unpaid(self):
        return self.paid == NOT_PAID
    
    @property
    def is_unassigned(self):
        return not self.first_name
    
    @property
    def is_dealer(self):
        return self.ribbon == DEALER_RIBBON or self.badge_type == PSEUDO_DEALER_BADGE
    
    @property
    def is_dept_head(self):
        return self.ribbon == DEPT_HEAD_RIBBON
    
    @property
    def unassigned_name(self):
        if self.group_id and self.is_unassigned:
            return "[Unassigned {self.badge}]".format(self = self)
    
    @property
    def full_name(self):
        return self.unassigned_name or "{self.first_name} {self.last_name}".format(self = self)
    
    @property
    def last_first(self):
        return self.unassigned_name or "{self.last_name}, {self.first_name}".format(self = self)
    
    @property
    def banned(self):
        return self.full_name in BANNED_ATTENDEES
    
    @property
    def badge(self):
        if self.paid == NOT_PAID:
            badge = "Unpaid " + self.get_badge_type_display()
        elif self.badge_num:
            badge = "{} #{}".format(self.get_badge_type_display(), self.badge_num)
        else:
            badge = self.get_badge_type_display()
        
        if self.ribbon != NO_RIBBON:
            badge += " ({})".format(self.get_ribbon_display())
        
        return badge
    
    @property
    def transferrable(self):
        return self.paid in [HAS_PAID, PAID_BY_GROUP] and self.badge_type not in [STAFF_BADGE, GUEST_BADGE]
    
    @property
    def tshirt(self):
        return self.badge_type in [STAFF_BADGE, SUPPORTER_BADGE] or self.worked_hours >= 6
    
    # TODO: change this to has_personalized_badge
    @property
    def personalized_badge(self):
        return self.badge_type in [STAFF_BADGE, SUPPORTER_BADGE]
    
    @property
    def donation_swag(self):
        extra = self.amount_extra
        if self.badge_type == SUPPORTER_BADGE and extra == 0:
            extra = SUPPORTER_LEVEL
        return [desc for amount,desc in sorted(DONATION_TIERS.items()) if amount and extra >= amount]
    
    @property
    def merch(self):
        merch = []
        if self.badge_type == SUPPORTER_BADGE:
            merch.extend(["a supporter pack", "a $10 M-Point coin"])
        if self.tshirt:
            merch.append("a tshirt")
        if self.extra_merch:
            merch.append(self.extra_merch)
        return comma_and(merch)
    
    @property
    def accoutrements(self):
        stuff = [] if self.ribbon == NO_RIBBON else ["a " + self.get_ribbon_display() + " ribbon"]
        stuff.append("a {} wristband".format(WRISTBAND_COLORS[self.age_group]))
        if self.regdesk_info:
            stuff.append(self.regdesk_info)
        return comma_and(stuff)
    
    @property
    def multiply_assigned(self):
        return len(self.assigned) > 1
    
    @property
    def takes_shifts(self):
        return self.staffing and set(self.assigned) - {ARTEMIS, CONCERT, CON_OPS, MARKETPLACE,
                                                       CCG_TABLETOP, DORSAI, CONTRACTORS}
    
    @property
    def hotel_shifts_required(self):
        return bool(self.hotel_nights and self.ribbon != DEPT_HEAD_RIBBON and self.takes_shifts)
    
    @property
    def interests_list(self):
        return [int(i) for i in self.interests.split(",")] if self.interests else []
    
    @property
    def assigned(self):
        return [int(i) for i in self.assigned_depts.split(",")] if self.assigned_depts else []
    
    @property
    def assigned_display(self):
        return [dict(JOB_LOC_OPTS)[loc] for loc in self.assigned]
    
    @cached_property
    def shifts(self):
        return list(self.shift_set.select_related().order_by("job__start_time"))
    
    @cached_property
    def hours(self):
        all_hours = set()
        for shift in self.shifts:
            all_hours.update(shift.job.hours)
        return all_hours
    
    @cached_property
    def hour_map(self):
        all_hours = {}
        for shift in self.shifts:
            for hour in shift.job.hours:
                all_hours[hour] = shift.job
        return all_hours
    
    # TODO: make this efficient
    @cached_property
    def possible(self):
        if not self.assigned and not state.AT_THE_CON:
            return []
        else:
            jobs = {job.id: job for job in Job.objects.filter(**{} if state.AT_THE_CON else {"location__in": self.assigned})}
            for job in jobs.values():
                job._shifts = []
            for shift in Shift.objects.filter(job__location__in = self.assigned).select_related():
                jobs[shift.job_id]._shifts.append(shift)
            return [job for job in sorted(jobs.values(), key = lambda j: j.start_time)
                        if job.slots > len(job.shifts)
                           and job.no_overlap(self)
                           and (not job.restricted or self.trusted)]
    
    @property
    def possible_opts(self):
        return [(job.id,"(%s) [%s] %s" % (hour_day_format(job.start_time), job.get_location_display(), job.name))
                for job in self.possible if datetime.now() < job.start_time + timedelta(hours=job.duration)]
    
    @property
    def possible_and_current(self):
        jobs = [s.job for s in self.shifts]
        for job in jobs:
            job.already_signed_up = True
        jobs.extend(self.possible)
        return sorted(jobs, key=lambda j: j.start_time)
    
    @cached_property
    def shifts(self):
        return list(self.shift_set.order_by("job__start_time").select_related())
    
    @property
    def worked_shifts(self):
        return [shift for shift in self.shifts if shift.worked == SHIFT_WORKED]
    
    @property
    def weighted_hours(self):
        wh = sum((shift.job.real_duration * shift.job.weight for shift in self.shifts), 0.0)
        return wh + self.nonshift_hours
    
    @property
    def worked_hours(self):
        wh = sum((shift.job.real_duration * shift.job.weight for shift in self.worked_shifts), 0.0)
        return wh + self.nonshift_hours
    
    def has_shifts_in(self, department):
        return any(shift.job.location == department for shift in self.shifts)
    
    @property
    def shift_prereqs_complete(self):
        return not self.placeholder \
           and self.fire_safety_cert \
           and (self.badge_type != STAFF_BADGE or self.hotel_requests is not None or not state.ROOMS_AVAILABLE)
    
    @property
    def past_years_json(self):
        return [] if not self.past_years else json.loads(self.past_years)
    
    @property
    def hotel_eligible(self):
        return self.badge_type == STAFF_BADGE
    
    @cached_property
    def hotel_requests(self):
        try:
            return self.hotelrequests
        except:
            return None
    
    @cached_property
    def hotel_nights(self):
        try:
            return [dict(NIGHTS_OPTS)[night] for night in map(int, self.hotel_requests.nights.split(","))]
        except:
            return []
    
    @cached_property
    def room_assignment(self):
        try:
            return self.roomassignment
        except:
            return None
    
    @cached_property
    def hotel_status(self):
        hr = self.hotel_requests
        if not hr:
            return 'Has not filled out volunteer checklist'
        elif not hr.nights:
            return 'Declined hotel space'
        elif hr.setup_teardown:
            return 'Hotel nights: {} ({})'.format(hr.nights_display, 'approved' if hr.approved else 'not yet approved')
        else:
            return 'Hotel nights: ' + hr.nights_display
    
    @cached_property
    def food_restrictions(self):
        try:
            return self.foodrestrictions
        except:
            return None

class HotelRequests(MagModel, NightsMixin):
    attendee           = OneToOneField(Attendee)
    nights             = MultiChoiceField(choices = NIGHTS_OPTS)
    wanted_roommates   = TextField()
    unwanted_roommates = TextField()
    special_needs      = TextField()
    approved           = BooleanField(default = False)
    
    restricted = ["approved"]
    
    @classmethod
    def in_dept(cls, department):
        return HotelRequests.objects.filter(attendee__assigned_depts__contains = department) \
                                    .exclude(nights="") \
                                    .order_by("attendee__first_name", "attendee__last_name") \
                                    .select_related()
    
    def decline(self):
        self.nights = ",".join(night for night in self.nights.split(",") if int(night) in {THURSDAY,FRIDAY,SATURDAY})
    
    def __repr__(self):
        return "<{self.attendee.full_name} Hotel Requests>".format(self = self)

class FoodRestrictions(MagModel):
    attendee = OneToOneField(Attendee)
    standard = MultiChoiceField(choices = FOOD_RESTRICTION_OPTS)
    freeform = TextField()
    
    def __getattr__(self, name):
        import constants
        restriction = getattr(constants, name.upper())
        if restriction not in dict(FOOD_RESTRICTION_OPTS):
            raise AttributeError()
        elif restriction == VEGETARIAN and str(VEGAN) in self.standard.split(","):
            return False
        else:
            return str(restriction) in self.standard.split(",")

class AssignedPanelist(MagModel):
    attendee = ForeignKey(Attendee)
    event = ForeignKey(Event)
    
    def __repr__(self):
        return "<{self.attendee.full_name} panelisting {self.event.name}>".format(self = self)

class SeasonPassTicket(MagModel):
    attendee = ForeignKey(Attendee)
    slug = CharField(max_length = 99)

class Room(MagModel, NightsMixin):
    department = IntegerField(choices = JOB_LOC_OPTS)
    notes      = CharField(max_length = 255, default = "")
    nights     = MultiChoiceField(choices = NIGHTS_OPTS)
    
    def to_dict(self):
        return {
            "department": self.get_department_display(),
            "notes": self.notes,
            "nights": self.nights_display,
            "people": [ra.attendee.full_name for ra in self.roomassignment_set.all()]
        }

class RoomAssignment(MagModel):
    room     = ForeignKey(Room)
    attendee = OneToOneField(Attendee)



class Job(MagModel):
    name        = CharField(max_length = 100)
    description = CharField(max_length = 100)
    location    = IntegerField(choices = JOB_LOC_OPTS)
    start_time  = DateTimeField()
    duration    = IntegerField()
    weight      = FloatField()
    slots       = IntegerField()
    restricted  = BooleanField(default = False)
    extra15     = BooleanField(default = False)
    
    @staticmethod
    def everything(location = None):
        shifts = Shift.objects.filter(**{"job__location": location} if location else {}).order_by("job__start_time").select_related()

        by_job, by_attendee = defaultdict(list), defaultdict(list)
        for shift in shifts:
            by_job[shift.job].append(shift)
            by_attendee[shift.attendee].append(shift)

        attendees = [a for a in Attendee.staffers() if state.AT_THE_CON or not location or int(location) in a.assigned]
        for attendee in attendees:
            attendee._shifts = by_attendee[attendee]

        jobs = list(Job.objects.filter(**{"location": location} if location else {}).order_by("start_time","duration","name"))
        for job in jobs:
            job._shifts = by_job[job]
            job._available_staffers = [s for s in attendees if not job.restricted or s.trusted]
            # TODO: make this correct for both the con and during the year

        return jobs, shifts, attendees
    
    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "duration": self.duration,
            "location": self.location,
            "weight": self.weight,
            "extra15": self.extra15,
            "weighted_hours": self.weighted_hours,
            "location_display": self.get_location_display(),
            "start_time": self.start_time.timestamp(),
            "taken": any(int(cherrypy.session.get("staffer_id", 0)) == shift.attendee_id for shift in self.shift_set.all())
        }
    
    @cached_property
    def shifts(self):
        return list(self.shift_set.order_by("job__start_time").select_related())
    
    @property
    def hours(self):
        hours = set()
        for i in range(self.duration):
            hours.add(self.start_time + timedelta(hours=i))
        return hours
    
    def no_overlap(self, attendee):
        before = self.start_time - timedelta(hours = 1)
        after  = self.start_time + timedelta(hours = self.duration)
        return (not self.hours.intersection(attendee.hours)
            and (before not in attendee.hour_map
                or not attendee.hour_map[before].extra15
                or self.location == attendee.hour_map[before].location)
            and (after not in attendee.hour_map
                or not self.extra15
                or self.location == attendee.hour_map[after].location))
    
    @cached_property
    def all_staffers(self):
        return list(Attendee.objects.order_by("last_name","first_name"))
    
    @cached_property
    def available_staffers(self):
        return [s for s in self.all_staffers
                if self.location in s.assigned
                   and self.no_overlap(s)
                   and (s.trusted or not self.restricted)]
    
    @property
    def real_duration(self):
        return self.duration + (0.25 if self.extra15 else 0)
    
    @property
    def weighted_hours(self):
        return self.weight * self.real_duration
    
    @property
    def total_hours(self):
        return self.weighted_hours * self.slots

class Shift(MagModel):
    job      = ForeignKey(Job)
    attendee = ForeignKey(Attendee)
    worked   = IntegerField(choices = WORKED_OPTS, default = SHIFT_UNMARKED)
    rating   = IntegerField(choices = RATING_OPTS, default = UNRATED)
    comment  = CharField(max_length = 255)
    
    @classmethod
    def serialize(cls, shifts):
        return {shift.id: {attr: getattr(shift, attr) for attr in ["id","worked","rating","comment"]}
                           for shift in shifts}
    
    @property
    def name(self):
        return "{self.attendee.full_name}'s {self.job.name!r} shift".format(self = self)



class Challenge(MagModel):
    game   = CharField(max_length = 100)
    normal = BooleanField()
    hard   = BooleanField()
    expert = BooleanField()
    unfair = BooleanField()
    
    display = "game"
    
    def has_level(self, level):
        return {NORMAL:self.normal, HARD:self.hard, EXPERT:self.expert, UNFAIR:self.unfair}[int(level)]

class Success(MagModel):
    challenge = ForeignKey(Challenge)
    attendee  = ForeignKey(Attendee)
    level     = IntegerField(choices = LEVEL_OPTS)



class MPointUse(MagModel):
    attendee = ForeignKey(Attendee)
    amount   = IntegerField()
    when     = DateTimeField(auto_now_add = True)

class MPointExchange(MagModel):
    attendee = ForeignKey(Attendee)
    mpoints  = IntegerField()
    when     = DateTimeField(auto_now_add = True)

class Sale(MagModel):
    attendee = ForeignKey(Attendee, null = True)
    what     = CharField(max_length = 50)
    cash     = IntegerField()
    mpoints  = IntegerField()
    when     = DateTimeField(auto_now_add = True)
    reg_station = IntegerField(null = True)
    payment_method = IntegerField(default = MERCH, choices = SALE_OPTS)

class ArbitraryCharge(MagModel):
    amount = IntegerField()
    what   = CharField(max_length = 255)
    when   = DateTimeField(auto_now_add = True)
    reg_station = IntegerField(null = True)
    
    display = "what"


class Game(MagModel):
    code = CharField(max_length = 6)
    name = CharField(max_length = 50)
    attendee = ForeignKey(Attendee)
    returned = BooleanField(default = False)

    @property
    def checked_out(self):
        try:
            return self.checkout
        except:
            return None

    def to_dict(self):
        attendee = lambda a: {
            "id": a.id,
            "name": a.full_name,
            "badge": a.badge_num
        }
        checkout = lambda c: c and dict(attendee(c.attendee), when=c.when.strftime("%I:%M%p %A"))
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "returned": self.returned,
            "checked_out": checkout(self.checked_out),
            "attendee": attendee(self.attendee)
        }

class Checkout(MagModel):
    game = OneToOneField(Game)
    attendee = ForeignKey(Attendee)
    when = DateTimeField(auto_now_add = True)



class Email(MagModel):
    fk_id   = IntegerField()
    model   = CharField(max_length = 50)
    subject = CharField(max_length = 255)
    dest    = CharField(max_length = 100)
    when    = DateTimeField(auto_now_add = True)
    body    = TextField()
    
    display = "subject"
    
    @cached_property
    def fk(self):
        try:
            return globals()[self.model].objects.get(id = self.fk_id)
        except:
            return None
    
    @property
    def rcpt_name(self):
        if self.model == "Group":
            return self.fk.leader.full_name
        else:
            return self.fk.full_name
    
    @property
    def html(self):
        if "<body>" in self.body:
            return SafeString(self.body.split("<body>")[1].split("</body>")[0])
        else:
            return SafeString(self.body.replace("\n", "<br/>"))


class Tracking(MagModel):
    fk_id  = IntegerField()
    model  = CharField(max_length = 25)
    when   = DateTimeField(auto_now_add = True)
    who    = CharField(max_length = 75)
    which  = CharField(max_length = 125)
    links  = CharField(max_length = 75)
    action = IntegerField(choices = TRACKING_OPTS)
    data   = TextField()
    
    @classmethod
    def values(cls, instance):
        return {field.name: getattr(instance, field.name) for field in instance._meta.fields}
    
    @classmethod
    def format(cls, values):
        return ", ".join("{}={}".format(k, v) for k,v in values.items())
    
    @classmethod
    def track(cls, action, instance):
        if action in [CREATED, UNPAID_PREREG, EDITED_PREREG]:
            values = cls.values(instance)
            data = cls.format({k: instance.field_repr(k) for k in values})
        elif action == UPDATED:
            curr = cls.values(instance)
            orig = instance.__class__.objects.get(id = instance.id)
            diff = {name: '"{} -> {}"'.format(orig.field_repr(name), instance.field_repr(name))
                    for name,val in curr.items() if val != getattr(orig, name)}
            data = cls.format(diff)
            if len(diff) == 1 and "badge_num" in diff:  # TODO: check for badge number only being different by 1
                action = AUTO_BADGE_SHIFT
            elif not data:
                return
        else:
            data = "id={}".format(instance.id)
        
        links = ", ".join(
            "{}({})".format(field.rel.to.__name__, getattr(instance, field.attname))
            for field in instance._meta.fields
            if isinstance(field, ForeignKey) and getattr(instance, field.name)
        )
        
        try:
            who = Account.objects.get(id = cherrypy.session.get("account_id")).name
        except:
            if current_thread().daemon:
                who = current_thread().name
            elif cherrypy.request.path_info.endswith("/preregistration/callback"):
                who = "Paypal callback"
            else:
                who = "non-admin"
        
        return Tracking.objects.create(
            model = instance.__class__.__name__,
            fk_id = 0 if action in [UNPAID_PREREG, EDITED_PREREG] else instance.id,
            which = repr(instance),
            who = who,
            links = links,
            action = action,
            data = data,
        )

Tracking.UNTRACKED = [Tracking, Email]

@receiver(pre_save)
def update_hook(sender, instance, **kwargs):
    if instance.id is not None and sender not in Tracking.UNTRACKED:
        Tracking.track(UPDATED, instance)

@receiver(post_save)
def create_hook(sender, instance, created, **kwargs):
    if created and sender not in Tracking.UNTRACKED:
        Tracking.track(CREATED, instance)

@receiver(pre_delete)
def delete_hook(sender, instance, **kwargs):
    if sender not in Tracking.UNTRACKED:
        Tracking.track(DELETED, instance)


def ismodel(x):
    return getattr(x, "__base__", None) is MagModel

def all_models():
    return [m for m in globals().values() if ismodel(m)]

for _model in all_models():
    _model._meta.db_table = _model.__name__
