from uber.common import *

class HTTPRedirect(cherrypy.HTTPRedirect):
    def __init__(self, page, *args, **kwargs):
        args = [self.quote(s) for s in args]
        kwargs = {k:self.quote(v) for k,v in kwargs.items()}
        cherrypy.HTTPRedirect.__init__(self, page.format(*args, **kwargs))
        if URL_BASE.startswith('https'):
            self.urls[0] = self.urls[0].replace('http://', 'https://')

    def quote(self, s):
        return quote(s) if isinstance(s, str) else str(s)


def listify(x):
    return list(x) if isinstance(x, (list, tuple, set, frozenset)) else [x]


def comma_and(xs):
    if len(xs) > 1:
        xs[-1] = 'and ' + xs[-1]
    return (', ' if len(xs) > 2 else ' ').join(xs)


def check_csrf(csrf_token):
    if csrf_token is None:
        csrf_token = cherrypy.request.headers.get('CSRF-Token')
    assert csrf_token, 'CSRF token missing'
    if csrf_token != cherrypy.session['csrf_token']:
        log.error("csrf tokens don't match: {!r} != {!r}", csrf_token, cherrypy.session['csrf_token'])
        raise AssertionError('CSRF check failed')
    else:
        cherrypy.request.headers['CSRF-Token'] = csrf_token

def check(model):
    prefix = model.__class__.__name__.lower() + '_'

    for field,name in getattr(model_checks, prefix + 'required', []):
        if not str(getattr(model,field)).strip():
            return name + ' is a required field'

    for name,attr in model_checks.__dict__.items():
        if name.startswith(prefix) and hasattr(attr, '__call__'):
            message = attr(model)
            if message:
                return message


class Order:
    def __init__(self, order):
        self.order = order

    def __getitem__(self, field):
        return ('-' + field) if field==self.order else field

    def __str__(self):
        return self.order


class SeasonEvent:
    instances = []

    def __init__(self, slug, **kwargs):
        assert re.match('^[a-z0-9_]+$', slug), 'Season Event sections must have separated_by_underscore names'
        for opt in ['url', 'location']:
            assert kwargs.get(opt), '{!r} is a required option for Season Event subsections'.format(opt)

        self.slug = slug
        self.name = kwargs['name'] or slug.replace('_', ' ').title()
        self.day = datetime.strptime('%Y-%m-%d', kwargs['day'])
        self.url = kwargs['url']
        self.location = kwargs['location']
        if kwargs['deadline']:
            self.deadline = datetime.strptime('%Y-%m-%d', kwargs['day'])
        else:
            self.deadline = datetime.combine((self.day - timedelta(days = 7)).date(), time(23, 59))

    @classmethod
    def register(cls, slug, kwargs):
        cls.instances.append(cls(slug, **kwargs))

for _slug, _conf in conf['season_events'].items():
    SeasonEvent.register(_slug, _conf)


def assign(attendee_id, job_id):
    job = Job.get(job_id)
    attendee = Attendee.get(attendee_id)

    if job.restricted and not attendee.trusted:
        return 'You cannot assign an untrusted attendee to a restricted shift'

    if job.slots <= job.shift_set.count():
        return 'All slots for this job have already been filled'

    if not job.no_overlap(attendee):
        return 'This volunteer is already signed up for a shift during that time'

    Shift.objects.create(attendee=attendee, job=job)


def hour_day_format(dt):
    return dt.strftime('%I%p ').strip('0').lower() + dt.strftime('%a')


def underscorize(s):
    s = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', s)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s).lower()


def send_email(source, dest, subject, body, format = 'text', cc = [], bcc = [], model = None):
    to, cc, bcc = map(listify, [dest, cc, bcc])
    if DEV_BOX:
        for xs in [to, cc, bcc]:
            xs[:] = [email for email in xs if email.endswith('mailinator.com') or 'eli@courtwright.org' in email]

    if SEND_EMAILS and to:
        message = EmailMessage(subject = subject, **{'bodyText' if format == 'text' else 'bodyHtml': body})
        AmazonSES(AWS_ACCESS_KEY_ID, AWS_SECRET_KEY).sendEmail(
            source = source,
            toAddresses = to,
            ccAddresses = cc,
            bccAddresses = bcc,
            message = message
        )
        sleep(0.1)  # avoid hitting rate limit
    else:
        log.error('email sending turned off, so unable to send {}', locals())

    if model and dest:
        fk = {'fk_id': 0, 'model': 'n/a'} if model == 'n/a' else {'fk_id': model.id, 'model': model.__class__.__name__}
        Email.objects.create(subject = subject, dest = ','.join(listify(dest)), body = body, **fk)


class Charge:
    def __init__(self, targets=(), amount=None, description=None):
        self.targets = [self._sessionize(m) for m in listify(targets)]
        self.amount = amount or self.total_cost
        self.description = description or self.names

    @staticmethod
    def _sessionize(m):
        if isinstance(m, dict):
            return m
        elif isinstance(m, MagModel):
            return m.sessionize()
        else:
            raise AssertionError('{} is not an attendee or group'.format(m))

    @staticmethod
    def get(payment_id):
        return Charge(**cherrypy.session.pop(payment_id))

    def to_dict(self):
        return {
            'targets': self.targets,
            'amount': self.amount,
            'description': self.description
        }

    @property
    def models(self):
        return [MagModel.from_sessionized(d) for d in self.targets]

    @property
    def total_cost(self):
        return 100 * sum(m.amount_unpaid for m in self.models)

    @property
    def dollar_amount(self):
        return self.amount // 100

    @property
    def names(self):
        return ', '.join(repr(m).strip('<>') for m in self.models)

    @property
    def attendees(self):
        return [m for m in self.models if isinstance(m, Attendee)]

    @property
    def groups(self):
        return [m for m in self.models if isinstance(m, Group)]

    def charge_cc(self, token):
        try:
            self.response = stripe.Charge.create(
                card=token,
                currency='usd',
                amount=self.amount,
                description=self.description
            )
        except stripe.CardError as e:
            return 'Your card was declined with the following error from our processor: ' + str(e)
        except stripe.StripeError as e:
            log.error('unexpected stripe error', exc_info=True)
            return 'An unexpected problem occured while processing your card: ' + str(e)


def affiliates():
    amounts = defaultdict(int, {a:-i for i,a in enumerate(DEFAULT_AFFILIATES)})
    for aff,amt in Attendee.objects.exclude(Q(amount_extra=0) | Q(affiliate='')).values_list('affiliate','amount_extra'):
        amounts[aff] += amt
    return [{"id": aff, "text": aff} for aff, amt in sorted(amounts.items(), key=lambda tup: -tup[1])]


def get_page(page, queryset):
    return queryset[(int(page) - 1) * 100 : int(page) * 100]


def search(text, **filters):
    attendees = Attendee.objects.filter(**filters)
    if ':' in text:
        target, term = text.lower().split(':', 1)
        if target in ['group', 'email']:
            target = {'group': 'group__name'}.get(target, target)
            return attendees.filter(**{target + '__icontains': term.strip()})

    terms = text.split()
    if len(terms) == 2:
        first, last = terms
        if first.endswith(','):
            last, first = first.strip(','), last
        return attendees.filter(first_name__icontains = first, last_name__icontains = last)
    elif len(terms) == 1 and terms[0].endswith(','):
        return attendees.filter(last_name__icontains = terms[0].rstrip(','))
    elif len(terms) == 1 and terms[0].isdigit():
        return attendees.filter(badge_num = terms[0])
    else:
        q = Q()
        for attr in ['first_name','last_name','badge_num','badge_printed_name','email','comments','admin_notes','for_review','secret_id','group__name','group__secret_id']:
            q |= Q(**{attr + '__icontains': text})
        return attendees.filter(q)


stopped = threading.Event()
cherrypy.engine.subscribe('start', stopped.clear)
cherrypy.engine.subscribe('stop', stopped.set, priority=98)

class DaemonTask:
    def __init__(self, func, name='DaemonTask', interval=300, threads=1):
        self.threads = []
        self.name, self.func, self.interval, self.thread_count = name, func, interval, threads
        cherrypy.engine.subscribe('start', self.start)
        cherrypy.engine.subscribe('stop', self.stop, priority=99)

    @property
    def running(self):
        return any(t.is_alive() for t in self.threads)

    def start(self):
        assert not self.threads, '{} was already started and has not yet stopped'.format(self.name)
        for i in range(self.thread_count):
            t = Thread(target = self.func, name = self.name)
            t.daemon = True
            t.start()
            self.threads.append(t)

    def stop(self):
        for i in range(20):
            if self.running:
                sleep(0.1)
            else:
                break
        else:
            log.warn('{} is still running, so it will just be killed when the Python interpreter exits', self.name)
        del self.threads[:]

    def run(self):
        while not stopped.is_set():
            try:
                self.func()
            except:
                log.warning('ignoring unexpected error in {}', self.name, exc_info=True)

            if self.interval:
                stopped.wait(self.interval)
