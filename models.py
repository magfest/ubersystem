from common import *

@property
def payment_deadline(self):
    return datetime.combine((self.registered + timedelta(days = 14)).date(), time(23, 59))

def __repr__(self):
    display = getattr(self, "display", "name" if hasattr(self, "name") else "id")
    return "<{}>".format(" ".join(str(getattr(self, field)) for field in listify(display)))

def field_repr(self, name):
    [field] = [f for f in self._meta.fields if f.name == name]
    val = getattr(self, name)
    s = repr(val)
    if field.choices and val is not None:
        return repr(dict(field.choices)[val])
    elif isinstance(field, CommaSeparatedIntegerField): # TODO: standardize naming convention to make this automatic
        opts = dict({
            "nights": NIGHTS_OPTS,
            "access": ACCESS_OPTS,
            "interests": INTEREST_OPTS,
            "requested_depts": JOB_INTEREST_OPTS,
            "assigned_depts": JOB_LOC_OPTS,
        }[name])
        return repr(val and ",".join(opts[int(opt)] for opt in val.split(",")))
    elif isinstance(val, long):
        return s[:-1]
    elif isinstance(val, unicode):
        return s[1:]
    else:
        return s

class MagModelMeta(base.ModelBase):
    def __new__(cls, name, bases, attrs):
        attrs["Meta"] = type("Meta", (), {"app_label": "", "db_table": name})
        attrs["__repr__"] = __repr__
        attrs["field_repr"] = field_repr
        if name in ["Group", "Attendee"]:
            attrs["payment_deadline"] = payment_deadline
        return base.ModelBase.__new__(cls, name, (Model,), attrs)

MagModel = type.__new__(MagModelMeta, "MagModel", (), {})


class Account(MagModel):
    name   = CharField(max_length = 50)
    email  = CharField(max_length = 50)
    hashed = CharField(max_length = 128)
    access = CommaSeparatedIntegerField(max_length = 50)
    
    @staticmethod
    def access_set(id=None):
        try:
            id = id or cherrypy.session.get("account_id")
            return set(int(a) for a in Account.objects.get(id=id).access.split(","))
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
    def start_slot(self):
        if self.start_time:
            return int((self.start_time - state.EPOCH).total_seconds() / (60 * 30))



class Group(MagModel):
    name          = CharField(max_length = 50)
    tables        = IntegerField()
    address       = TextField()
    website       = CharField(max_length = 255)
    wares         = TextField()
    description   = TextField()
    special_needs = TextField()
    amount_paid   = IntegerField(default = 0)
    amount_owed   = IntegerField(default = 0)
    status        = IntegerField(default = UNAPPROVED, choices = STATUS_OPTS)
    auto_recalc   = BooleanField(default = True)
    can_add       = BooleanField(default = False)
    admin_notes   = TextField()
    registered    = DateTimeField(auto_now_add = True)
    approved      = DateTimeField(null = True)
    
    restricted = ["amount_paid","amount_owed","auto_recalc","admin_notes","lockable","status","approved"]
    
    def save(self, *args, **kwargs):
        if self.auto_recalc:
            self.amount_owed = self.total_cost
        if self.status == APPROVED and not self.approved:
            self.approved = datetime.now()
        super(Group, self).save(*args, **kwargs)
    
    @property
    def is_dealer(self):
        return bool(self.tables and (self.amount_paid or self.amount_owed))
    
    @property
    def email(self):
        return self.leader and self.leader.email
    
    @cached_property
    def leader(self):
        for a in self.attendee_set.order_by("id"):
            if a.email:
                return a
    
    @property
    def badges_purchased(self):
        return self.attendee_set.filter(paid = PAID_BY_GROUP).count()
    
    @property
    def badges(self):
        return self.attendee_set.count()
    
    @property
    def unregistered_badges(self):
        return self.attendee_set.filter(first_name = "").count()
    
    @property
    def table_cost(self):
        return {
            0: 0,
            1: 120,
            2: 120 + 160
        }.get(self.tables, 120 + 160 + 200 * (self.tables - 2))
    
    @property
    def badge_cost(self):
        total = 0
        for attendee in self.attendee_set.filter(paid = PAID_BY_GROUP):
            if attendee.ribbon == DEALER_RIBBON:
                total += DEALER_BADGE_PRICE
            elif attendee.registered <= state.PRICE_BUMP:
                total += EARLY_GROUP_PRICE
            else:
                total += LATE_GROUP_PRICE
        return total
    
    @property
    def total_cost(self):
        return self.table_cost + self.badge_cost
    
    @property
    def amount_unpaid(self):
        return self.amount_owed - self.amount_paid
    
    @property
    def can_add_badges(self):
        return self.can_add or (not self.is_dealer and self.total_cost and not self.amount_paid)



class Attendee(MagModel):
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
    
    interests   = CommaSeparatedIntegerField(max_length = 50)
    found_how   = CharField(max_length = 100)
    comments    = CharField(max_length = 255)
    admin_notes = TextField()
    
    badge_num  = IntegerField(default = 0)
    badge_type = IntegerField(choices = BADGE_OPTS)
    ribbon     = IntegerField(default = NO_RIBBON, choices = RIBBON_OPTS)
    
    affiliate    = CharField(max_length = 50, default = "")
    can_spam     = BooleanField(default = False)
    regdesk_info = CharField(max_length = 255, default = "")
    extra_merch  = CharField(max_length = 255, default = "")
    got_merch    = BooleanField(default = False)
    
    registered = DateTimeField(auto_now_add = True)
    checked_in = DateTimeField(null = True)
    
    paid            = IntegerField(default = NOT_PAID, choices = PAID_OPTS)
    amount_paid     = IntegerField(default = 0)
    amount_refunded = IntegerField(default = 0)
    
    badge_printed_name = CharField(max_length = 30, default = "")
    
    staffing         = BooleanField(default = False)
    fire_safety_cert = CharField(max_length = 50, default = "")
    requested_depts  = CommaSeparatedIntegerField(max_length = 50)
    assigned_depts   = CommaSeparatedIntegerField(max_length = 50)
    trusted          = BooleanField(default = False)
    nonshift_hours   = IntegerField(default = 0)
    
    display = "full_name"
    restricted = ["group","admin_notes","badge_num","ribbon","regdesk_info","extra_merch","got_merch","paid","amount_paid","amount_refunded","assigned_depts","trusted","nonshift_hours"]
    
    def save(self, *args, **kwargs):
        import badge_funcs
        
        if self.ribbon == DEPT_HEAD_RIBBON:
            self.badge_type = STAFF_BADGE
            self.staffing = self.trusted = True
            if self.paid == NOT_PAID:
                self.paid = NEED_NOT_PAY
        
        with BADGE_LOCK:
            if not state.AT_THE_CON:
                if self.paid == NOT_PAID or self.badge_type not in PREASSIGNED_BADGE_TYPES:
                    self.badge_num = 0
                elif self.paid != NOT_PAID and not self.badge_num and self.badge_type in PREASSIGNED_BADGE_TYPES:
                    self.badge_num = badge_funcs.next_badge_num(self.badge_type)
        
        if self.badge_type != SUPPORTER_BADGE:
            self.affiliate = ""
        
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
        
        if self.paid == NEED_NOT_PAY:
            self.amount_paid = 0
        
        if self.paid != REFUNDED:
            self.amount_refunded = 0
        
        if state.AT_THE_CON and self.badge_num and self.id is None:
            self.checked_in = datetime.now()
        
        for attr in ["first_name", "last_name"]:
            value = getattr(self, attr)
            if value.isupper() or value.islower():
                setattr(self, attr, value.title())
        
        super(Attendee, self).save(*args, **kwargs)
    
    def delete(self, *args, **kwargs):
        import badge_funcs
        with BADGE_LOCK:
            badge_num = Attendee.objects.get(id = self.id).badge_num
            super(Attendee, self).delete(*args, **kwargs)
            badge_funcs.shift_badges(self, down = True)
    
    @classmethod
    def staffers(cls):
        return cls.objects.filter(staffing = True).order_by("first_name","last_name")
    
    @property
    def total_cost(self):
        if self.badge_type == SUPPORTER_BADGE:
            return SUPPORTER_BADGE_PRICE
        elif self.badge_type == ONE_DAY_BADGE:
            return ONEDAY_BADGE_PRICE
        elif datetime.now() < state.PRICE_BUMP:
            return EARLY_BADGE_PRICE
        elif datetime.now() < state.EPOCH:
            return LATE_BADGE_PRICE
        else:
            return DOOR_BADGE_PRICE
    
    @property
    def is_unassigned(self):
        return not self.first_name
    
    @property
    def is_dealer(self):
        return self.ribbon == DEALER_RIBBON
    
    @property
    def unassigned_name(self):
        if self.group and self.is_unassigned:
            return "[Unassigned {self.badge}]".format(self = self)
    
    @property
    def full_name(self):
        return self.unassigned_name or "{self.first_name} {self.last_name}".format(self = self)
    
    @property
    def last_first(self):
        return self.unassigned_name or "{self.last_name}, {self.first_name}".format(self = self)
    
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
    
    def comma_and(self, xs):
        if len(xs) > 1:
            xs[-1] = "and " + xs[-1]
        return (", " if len(xs) > 2 else " ").join(xs)
    
    @property
    def merch(self):
        merch = []
        if self.badge_type == SUPPORTER_BADGE:
            merch.extend(["a tshirt", "a supporter pack", "a $10 M-Point coin"])
        if self.extra_merch:
            stuff.append(self.extra_merch)
        return self.comma_and(merch)
    
    @property
    def accoutrements(self):
        stuff = [] if self.ribbon == NO_RIBBON else ["a " + self.get_ribbon_display() + " ribbon"]
        stuff.append("a {} wristband".format(WRISTBAND_COLORS[self.age_group]))
        if self.regdesk_info:
            stuff.append(self.regdesk_info)
        return self.comma_and(stuff)
    
    @property
    def multiply_assigned(self):
        return "," in self.assigned
    
    @property
    def takes_shifts(self):
        return (self.staffing and not self.placeholder
                              and self.ribbon != DEPT_HEAD_RIBBON
                              and set(self.assigned) - {CONCERT, MARKETPLACE})
    
    @property
    def assigned(self):
        return map(int, self.assigned_depts.split(",")) if self.assigned_depts else []
    
    @property
    def assigned_display(self):
        return [dict(JOB_LOC_OPTS)[loc] for loc in self.assigned]
    
    @property
    def signups(self):
        return self.shift_set.select_related().order_by("job__start_time")
    
    @cached_property
    def hours(self):
        all_hours = set()
        for shift in self.shift_set.select_related():
            all_hours.update(shift.job.hours)
        return all_hours
    
    @cached_property
    def hour_map(self):
        all_hours = {}
        for shift in self.shift_set.select_related():
            for hour in shift.job.hours:
                all_hours[hour] = shift.job
        return all_hours
    
    # TODO: make this efficient
    @cached_property
    def possible(self):
        if not self.assigned:
            return []
        else:
            return [job for job in Job.objects.filter(location__in = self.assigned).order_by("start_time")
                        if job.slots > job.shift_set.count()
                           and job.no_overlap(self)
                           and (not job.restricted or self.trusted)]
    
    @property
    def possible_opts(self):
        return [(job.id,"%s (%s)" % (job.name, hour_day_format(job.start_time))) for job in self.possible]
    
    @property
    def possible_and_current(self):
        all = [s.job for s in self.signups]
        for job in all:
            job.already_signed_up = True
        all.extend(self.possible)
        return sorted(all, key=lambda j: j.start_time)
    
    @cached_property
    def shifts(self):
        return list(self.shift_set.select_related())
    
    @cached_property
    def worked_shifts(self):
        return list(self.shift_set.filter(worked=SHIFT_WORKED).select_related())
    
    @cached_property
    def weighted_hours(self):
        wh = sum((shift.job.real_duration * shift.job.weight for shift in self.shifts), 0.0)
        return wh + self.nonshift_hours
    
    @cached_property
    def worked_hours(self):
        wh = sum((shift.job.real_duration * shift.job.weight for shift in self.worked_shifts), 0.0)
        return wh + self.nonshift_hours
    
    @property
    def shift_prereqs_complete(self):
        return not self.placeholder  \
           and self.fire_safety_cert \
           and (self.badge_type != STAFF_BADGE or self.hotel_nights is not None)
    
    @property
    def hotel_requests(self):
        try:
            return self.hotelrequests
        except:
            return None
    
    @cached_property
    def hotel_nights(self):
        try:
            return [dict(NIGHTS_OPTS)[night] for night in map(int, self.hotelrequests.nights.split(","))]
        except:
            return None

class HotelRequests(MagModel):
    attendee           = OneToOneField(Attendee)
    nights             = CommaSeparatedIntegerField(max_length = 50)
    wanted_roommates   = TextField()
    unwanted_roommates = TextField()
    special_needs      = TextField()
    approved           = BooleanField(default = False)
    
    restricted = ["approved"]
    
    def __getattr__(self, name):
        day = getattr(constants, name.upper())
        if day not in dict(NIGHTS_OPTS):
            raise AttributeError()
        else:
            return str(day) in self.nights.split(",")
    
    def __repr__(self):
        return "<{self.attendee.full_name} Hotel Requests>".format(self = self)

class AssignedPanelist(MagModel):
    attendee = ForeignKey(Attendee)
    event = ForeignKey(Event)
    
    def __repr__(self):
        return "<{self.attendee.full_name} panelisting {self.event.name}>".format(self = self)


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
    
    # TODO: make this efficient
    @cached_property
    def available_staffers(self):
        return [s for s in Attendee.objects.order_by("last_name","first_name")
                if self.location in s.assigned
                   and self.no_overlap(s)
                   and (s.trusted or not self.restricted)]
        
    @property
    def real_duration(self):
        return self.duration + (0.25 if self.extra15 else 0)
    
    @property
    def weighted_hours(self):
        return self.weight * self.real_duration

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
    what    = CharField(max_length = 50)
    cash    = IntegerField()
    mpoints = IntegerField()
    when    = DateTimeField(auto_now_add = True)



class Email(MagModel):
    fk_id   = IntegerField()
    fk_tab  = CharField(max_length = 50)
    subject = CharField(max_length = 255)
    dest    = CharField(max_length = 100)
    when    = DateTimeField(auto_now_add = True)
    body    = TextField()
    
    display = "subject"
    
    @cached_property
    def fk(self):
        return globals()[self.fk_tab].objects.get(id = self.fk_id)
    
    @property
    def rcpt_name(self):
        if self.fk_tab == "Group":
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
    when   = DateTimeField(auto_now_add = True)
    who    = CharField(max_length = 75)
    which  = CharField(max_length = 125)
    model  = CharField(max_length = 25)
    links  = CharField(max_length = 25)
    fk_id  = IntegerField()
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
        if action == CREATED:
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
            which = repr(instance),
            who = who,
            links = links,
            fk_id = instance.id,
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
