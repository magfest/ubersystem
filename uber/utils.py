from uber.common import *


class HTTPRedirect(cherrypy.HTTPRedirect):
    """
    CherryPy uses exceptions to indicate things like HTTP 303 redirects.  This
    subclasses the standard CherryPy exception to add string formatting and
    automatic quoting.  So instead of saying
        raise HTTPRedirect('foo?message={}'.format(quote(bar)))
    we can say
        raise HTTPRedirect('foo?message={}', bar)

    EXTREMELY IMPORTANT: If you pass in a relative URL, this class will use the
    current querystring to build an absolute URL.  Therefore it's EXTREMELY IMPORTANT
    that the only time you create this class is in the context of a pageload.

    Do not persist this class, only create it when needed.
    """
    def __init__(self, page, *args, **kwargs):
        args = [self.quote(s) for s in args]
        kwargs = {k: self.quote(v) for k, v in kwargs.items()}
        cherrypy.HTTPRedirect.__init__(self, page.format(*args, **kwargs))

    def quote(self, s):
        return quote(s) if isinstance(s, str) else str(s)


def localized_now():
    """Returns datetime.now() but localized to the event's configured timezone."""
    utc_now = datetime.utcnow().replace(tzinfo=UTC)
    return utc_now.astimezone(c.EVENT_TIMEZONE)


def comma_and(xs):
    """
    Accepts a list of strings and separates them with commas as grammatically
    appropriate with an "and" before the final entry.  For example:
        ['foo']               => 'foo'
        ['foo', 'bar']        => 'foo and bar'
        ['foo', 'bar', 'baz'] => 'foo, bar, and baz'
    """
    if len(xs) > 1:
        xs[-1] = 'and ' + xs[-1]
    return (', ' if len(xs) > 2 else ' ').join(xs)


def check_csrf(csrf_token):
    """
    Accepts a csrf token (and checks the request headers if None is provided)
    and compares it to the token stored in the session.  An exception is raised
    if the values do not match or if no token is found.
    """
    if csrf_token is None:
        csrf_token = cherrypy.request.headers.get('CSRF-Token')
    assert csrf_token, 'CSRF token missing'
    if csrf_token != cherrypy.session['csrf_token']:
        log.error("csrf tokens don't match: {!r} != {!r}", csrf_token, cherrypy.session['csrf_token'])
        raise AssertionError('CSRF check failed')
    else:
        cherrypy.request.headers['CSRF-Token'] = csrf_token


def check(model, *, prereg=False):
    """
    Runs all default validations against the supplied model instance.  Returns
    either a string error message if any validation fails and returns None if
    all validations passed.
    """
    for field, name in model.required:
        if not str(getattr(model, field)).strip():
            return name + ' is a required field'

    for v in [sa.validation.validations] + ([sa.prereg_validation.validations] if prereg else []):
        for validator in v[model.__class__.__name__].values():
            message = validator(model)
            if message:
                return message


class Order:
    def __init__(self, order):
        self.order = order

    def __getitem__(self, field):
        return ('-' + field) if field == self.order else field

    def __str__(self):
        return self.order


class Registry:
    """
    Base class for configurable registries such as the Dept Head Checklist and
    event-specific features such as MAGFest Season Pass events.
    """
    @classmethod
    def register(cls, slug, kwargs):
        cls.instances[slug] = cls(slug, **kwargs)


class DeptChecklistConf(Registry):
    instances = OrderedDict()

    def __init__(self, slug, description, deadline, name=None, path=None):
        assert re.match('^[a-z0-9_]+$', slug), 'Dept Head checklist item sections must have separated_by_underscore names'
        self.slug, self.description = slug, description
        self.name = name or slug.replace('_', ' ').title()
        self._path = path or '/dept_checklist/form?slug={slug}'
        self.deadline = c.EVENT_TIMEZONE.localize(datetime.strptime(deadline, '%Y-%m-%d')).replace(hour=23, minute=59)

    def path(self, attendee):
        dept = attendee and attendee.assigned_depts and attendee.assigned_depts_ints[0]
        return self._path.format(slug=self.slug, department=dept)

    def completed(self, attendee):
        matches = [item for item in attendee.dept_checklist_items if self.slug == item.slug]
        return matches[0] if matches else None


for _slug, _conf in sorted(c.DEPT_HEAD_CHECKLIST.items(), key=lambda tup: tup[1]['deadline']):
    DeptChecklistConf.register(_slug, _conf)


def hour_day_format(dt):
    """
    Accepts a localized datetime object and returns a formatted string showing
    only the day and hour, e.g "7pm Thu" or "10am Sun".
    """
    return dt.astimezone(c.EVENT_TIMEZONE).strftime('%I%p ').strip('0').lower() + dt.astimezone(c.EVENT_TIMEZONE).strftime('%a')


def send_email(source, dest, subject, body, format='text', cc=(), bcc=(), model=None):
    subject = subject.format(EVENT_NAME=c.EVENT_NAME)
    to, cc, bcc = map(listify, [dest, cc, bcc])
    if c.DEV_BOX:
        for xs in [to, cc, bcc]:
            xs[:] = [email for email in xs if email.endswith('mailinator.com') or c.DEVELOPER_EMAIL in email]

    if c.SEND_EMAILS and to:
        message = EmailMessage(subject=subject, **{'bodyText' if format == 'text' else 'bodyHtml': body})
        AmazonSES(c.AWS_ACCESS_KEY, c.AWS_SECRET_KEY).sendEmail(
            source=source,
            toAddresses=to,
            ccAddresses=cc,
            bccAddresses=bcc,
            message=message
        )
        sleep(0.1)  # avoid hitting rate limit
    else:
        log.error('email sending turned off, so unable to send {}', locals())

    if model and dest:
        body = body.decode('utf-8') if isinstance(body, bytes) else body
        fk = {'model': 'n/a'} if model == 'n/a' else {'fk_id': model.id, 'model': model.__class__.__name__}
        with sa.Session() as session:
            session.add(sa.Email(subject=subject, dest=','.join(listify(dest)), body=body, **fk))


class Charge:
    def __init__(self, targets=(), amount=None, description=None):
        self.targets = [self.to_sessionized(m) for m in listify(targets)]
        self.amount = amount or self.total_cost
        self.description = description or self.names

    @staticmethod
    def to_sessionized(m):
        if isinstance(m, dict):
            return m
        elif isinstance(m, sa.Attendee):
            return m.to_dict()
        elif isinstance(m, sa.Group):
            return m.to_dict(sa.Group.to_dict_default_attrs + ['attendees'])
        else:
            raise AssertionError('{} is not an attendee or group'.format(m))

    @staticmethod
    def from_sessionized(d):
        assert d['_model'] in {'Attendee', 'Group'}
        if d['_model'] == 'Group':
            d = dict(d, attendees=[sa.Attendee(**a) for a in d.get('attendees', [])])
        return sa.Session.resolve_model(d['_model'])(**d)

    @staticmethod
    def get(payment_id):
        charge = cherrypy.session.pop(payment_id, None)
        if charge:
            return Charge(**charge)
        else:
            raise HTTPRedirect('../preregistration/credit_card_retry')

    def to_dict(self):
        return {
            'targets': self.targets,
            'amount': self.amount,
            'description': self.description
        }

    @property
    def models(self):
        return [self.from_sessionized(d) for d in self.targets]

    @property
    def total_cost(self):
        return 100 * sum(m.amount_unpaid for m in self.models)

    @property
    def dollar_amount(self):
        return self.amount // 100

    @property
    def names(self):
        return ', '.join(getattr(m, 'name', getattr(m, 'full_name', None)) for m in self.models)

    @property
    def attendees(self):
        return [m for m in self.models if isinstance(m, sa.Attendee)]

    @property
    def groups(self):
        return [m for m in self.models if isinstance(m, sa.Group)]

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


def get_page(page, queryset):
    return queryset[(int(page) - 1) * 100: int(page) * 100]


def genpasswd():
    """
    Admin accounts have passwords auto-generated; this function tries to combine
    three random dictionary words but returns a string of 8 random characters if
    no dictionary is installed.
    """
    try:
        with open('/usr/share/dict/words') as f:
            words = [s.strip() for s in f.readlines() if "'" not in s and s.islower() and 3 < len(s) < 8]
            return ' '.join(random.choice(words) for i in range(4))
    except:
        return ''.join(chr(randrange(33, 127)) for i in range(8))


def template_overrides(dirname):
    """
    Each event can have its own plugin and override our default templates with
    its own by calling this method and passing its templates directory.
    """
    django.conf.settings.TEMPLATE_DIRS.insert(0, dirname)


def static_overrides(dirname):
    """
    We want plugins to be able to specify their own static files to override the
    ones which we provide by default.  The main files we expect to be overridden
    are the theme image files, but theoretically a plugin can override anything
    it wants by calling this method and passing its static directory.
    """
    appconf = cherrypy.tree.apps[c.PATH].config
    basedir = os.path.abspath(dirname).rstrip('/')
    for dpath, dirs, files in os.walk(basedir):
        relpath = dpath[len(basedir):]
        for fname in files:
            appconf['/static' + relpath + '/' + fname] = {
                'tools.staticfile.on': True,
                'tools.staticfile.filename': os.path.join(dpath, fname)
            }


def mount_site_sections(module_root):
    from uber.server import Root
    sections = [path.split('/')[-1][:-3] for path in glob(os.path.join(module_root, 'site_sections', '*.py'))
                                         if not path.endswith('__init__.py')]
    for section in sections:
        module = importlib.import_module(basename(module_root) + '.site_sections.' + section)
        setattr(Root, section, module.Root())


def convert_to_absolute_url(relative_uber_page_url):
    """
    In ubersystem, we always use relative url's of the form "../{some_site_section}/{somepage}"
    We use relative URLs so that no matter what proxy server we are behind on the web, it always works.

    We normally avoid using absolute URLs at al costs, but sometimes it's needed when creating URLs for
    use with emails or CSV exports.  In that case, we need to take a relative URL and turn it into
    an absolute URL.

    Do not use this function unless you absolutely need to, instead use relative URLs as much as possible.
    """

    assert relative_uber_page_url[:3] == '../', "relative url MUST start with '../'"
    return urljoin(c.URL_BASE + "/", relative_uber_page_url[3:])
