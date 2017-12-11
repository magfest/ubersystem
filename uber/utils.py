from uber.common import *


class CSRFException(Exception):
    """
    This class will raise a custom exception to help catch a specific error in later functions.
    """


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

    Do not save copies this class, only create it on-demand when needed as part of a 'raise' statement.
    """
    def __init__(self, page, *args, **kwargs):
        save_location = kwargs.pop('save_location', False)

        args = [self.quote(s) for s in args]
        kwargs = {k: self.quote(v) for k, v in kwargs.items()}
        query = page.format(*args, **kwargs)

        if save_location and cherrypy.request.method == 'GET':
            # remember the original URI the user was trying to reach.
            # useful if we want to redirect the user back to the same page after
            # they complete an action, such as logging in
            # example URI: '/uber/registration/form?id=786534'
            original_location = cherrypy.request.wsgi_environ['REQUEST_URI']

            # note: python does have utility functions for this. if this gets any more complex, use the urllib module
            qs_char = '?' if '?' not in query else '&'
            query += "{sep}original_location={loc}".format(sep=qs_char, loc=self.quote(original_location))

        cherrypy.HTTPRedirect.__init__(self, query)

    def quote(self, s):
        return quote(s) if isinstance(s, str) else str(s)


def create_valid_user_supplied_redirect_url(url, default_url):
    """
    Create a valid redirect from user-supplied data.

    If there is invalid data, or a security issue is detected, then ignore and redirect to the homepage

    :param url: user-supplied URL that is being requested to redirect to
    :param default_url: the name of the URL we should redirect to if there's an issue
    :return: a secure and valid URL that we allow a redirect to be made to
    """

    # security: ignore cross-site redirects that aren't for local pages.
    # i.e. if an attacker passes in 'original_location=https://badsite.com/stuff/" then just ignore it
    parsed_url = urlparse(url)
    security_issue = parsed_url.scheme or parsed_url.netloc

    if not url or 'login' in url or security_issue:
        return default_url

    return url


def localized_now():
    """Returns datetime.now() but localized to the event's configured timezone."""
    return localize_datetime(datetime.utcnow())


def localize_datetime(dt):
    return dt.replace(tzinfo=UTC).astimezone(c.EVENT_TIMEZONE)


def ceil_datetime(dt, delta):
    """Only works in Python 3"""
    dt_min = datetime.min.replace(tzinfo=dt.tzinfo)
    dt += (dt_min - dt) % delta
    return dt


def floor_datetime(dt, delta):
    """Only works in Python 3"""
    dt_min = datetime.min.replace(tzinfo=dt.tzinfo)
    dt -= (dt - dt_min) % delta
    return dt


def noon_datetime(dt):
    """Only works in Python 3"""
    return floor_datetime(dt, timedelta(days=1)) + timedelta(hours=12)


def evening_datetime(dt):
    """Only works in Python 3"""
    return floor_datetime(dt, timedelta(days=1)) + timedelta(hours=17)


@JinjaEnv.jinja_filter
def comma_and(xs, conjunction='and'):
    """
    Accepts a list of strings and separates them with commas as grammatically
    appropriate with a conjunction before the final entry. For example::

        >>> comma_and(['foo'])
        'foo'
        >>> comma_and(['foo', 'bar'])
        'foo and bar'
        >>> comma_and(['foo', 'bar', 'baz'])
        'foo, bar, and baz'
        >>> comma_and(['foo', 'bar', 'baz'], 'or')
        'foo, bar, or baz'
        >>> comma_and(['foo', 'bar', 'baz'], 'but never')
        'foo, bar, but never baz'
    """
    if len(xs) > 1:
        xs = list(xs)
        xs[-1] = conjunction + ' ' + xs[-1]
    return (', ' if len(xs) > 2 else ' ').join(xs)


def check_csrf(csrf_token=None):
    """
    Accepts a csrf token (and checks the request headers if None is provided)
    and compares it to the token stored in the session.  An exception is raised
    if the values do not match or if no token is found.
    """
    if csrf_token is None:
        csrf_token = cherrypy.request.headers.get('CSRF-Token')

    if not csrf_token:
        raise CSRFException("CSRF token missing")

    if csrf_token != cherrypy.session['csrf_token']:
        raise CSRFException("CSRF check failed: csrf tokens don't match: {!r} != {!r}"
                            .format(csrf_token, cherrypy.session['csrf_token']))
    else:
        cherrypy.request.headers['CSRF-Token'] = csrf_token


def ensure_csrf_token_exists():
    """
    Generate a new CSRF token if none exists in our session already.
    """
    if not cherrypy.session.get('csrf_token'):
        cherrypy.session['csrf_token'] = uuid4().hex


def check(model, *, prereg=False):
    """
    Runs all default validations against the supplied model instance.

    Args:
        model (sqlalchemy.Model): A single model instance.
        prereg (bool): True if this is an ephemeral model used in the
            preregistration workflow.

    Returns:
        str: None for success, or a failure message if any validation fails.
    """
    for field, name in model.required:
        if not str(getattr(model, field)).strip():
            return name + ' is a required field'

    for v in [sa.validation.validations] + ([sa.prereg_validation.validations] if prereg else []):
        for validator in v[model.__class__.__name__].values():
            message = validator(model)
            if message:
                return message


def check_all(models, *, prereg=False):
    """
    Runs all default validations against multiple model instances.

    Args:
        models (list): A single model instance or a list of model instances.
        prereg (bool): True if this is an ephemeral model used in the
            preregistration workflow.

    Returns:
        str: None for success, or the first failure message encountered.
    """
    models = listify(models) if models else []
    for model in models:
        message = check(model, prereg=prereg)
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

    def __init__(self, slug, description, deadline, name=None, path=None, email_post_con=False):
        assert re.match('^[a-z0-9_]+$', slug), 'Dept Head checklist item sections must have separated_by_underscore names'
        self.slug, self.description = slug, description
        self.name = name or slug.replace('_', ' ').title()
        self._path = path or '/dept_checklist/form?slug={slug}&department_id={department_id}'
        self.email_post_con = email_post_con
        self.deadline = c.EVENT_TIMEZONE.localize(datetime.strptime(deadline, '%Y-%m-%d')).replace(hour=23, minute=59)

    def path(self, department_id):
        from uber.models.department import Department
        department_id = Department.to_id(department_id)
        for arg in ('department_id', 'department', 'location'):
            try:
                return self._path.format(slug=self.slug, **{arg: department_id})
            except KeyError:
                pass
        raise KeyError('department_id')

for _slug, _conf in sorted(c.DEPT_HEAD_CHECKLIST.items(), key=lambda tup: tup[1]['deadline']):
    DeptChecklistConf.register(_slug, _conf)


def hour_day_format(dt):
    """
    Accepts a localized datetime object and returns a formatted string showing
    only the day and hour, e.g "7pm Thu" or "10am Sun".
    """
    return dt.astimezone(c.EVENT_TIMEZONE).strftime('%I%p ').strip('0').lower() + dt.astimezone(c.EVENT_TIMEZONE).strftime('%a')


def send_email(source, dest, subject, body, format='text', cc=(), bcc=(), model=None, ident=None):
    subject = subject.format(EVENT_NAME=c.EVENT_NAME)
    to, cc, bcc = map(listify, [dest, cc, bcc])
    ident = ident or subject
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
        _record_email_sent(sa.Email(subject=subject, dest=','.join(listify(dest)), body=body, ident=ident, **fk))


def _record_email_sent(email):
    """
    Save in our database the contents of the Email model passed in.
    We'll use this for history tracking, and to know that we shouldn't re-send this email because it already exists

    note: This is in a separate function so we can unit test it
    """
    with sa.Session() as session:
        session.add(email)


class Charge:

    def __init__(self, targets=(), amount=None, description=None, receipt_email=None):
        self._targets = listify(targets)
        self._amount = amount
        self._description = description
        self._receipt_email = receipt_email

    @classproperty
    def paid_preregs(cls):
        return cherrypy.session.setdefault('paid_preregs', [])

    @classproperty
    def unpaid_preregs(cls):
        return cherrypy.session.setdefault('unpaid_preregs', OrderedDict())

    @classmethod
    def get_unpaid_promo_code_uses_count(cls, id, already_counted_attendee_ids=None):
        attendees_with_promo_code = set()
        if already_counted_attendee_ids:
            attendees_with_promo_code.update(listify(already_counted_attendee_ids))

        promo_code_count = 0

        targets = [t for t in cls.unpaid_preregs.values() if '_model' in t]
        for target in targets:
            if target['_model'] == 'Attendee':
                if target.get('id') not in attendees_with_promo_code \
                        and target.get('promo_code') \
                        and target['promo_code'].get('id') == id:
                    attendees_with_promo_code.add(target.get('id'))
                    promo_code_count += 1

            elif target['_model'] == 'Group':
                for attendee in target.get('attendees', []):
                    if attendee.get('id') not in attendees_with_promo_code \
                            and attendee.get('promo_code') \
                            and attendee['promo_code'].get('id') == id:
                        attendees_with_promo_code.add(attendee.get('id'))
                        promo_code_count += 1

            elif target['_model'] == 'PromoCode' and target.get('id') == id:
                # Should never get here
                promo_code_count += 1

        return promo_code_count

    @classmethod
    def to_sessionized(cls, m):
        if is_listy(m):
            return [cls.to_sessionized(t) for t in m]
        elif isinstance(m, dict):
            return m
        elif isinstance(m, sa.Attendee):
            return m.to_dict(sa.Attendee.to_dict_default_attrs
                + ['promo_code']
                + list(sa.Attendee.extra_apply_attrs_restricted))
        elif isinstance(m, sa.Group):
            return m.to_dict(sa.Group.to_dict_default_attrs
                + ['attendees']
                + list(sa.Group.extra_apply_attrs_restricted))
        else:
            raise AssertionError('{} is not an attendee or group'.format(m))

    @classmethod
    def from_sessionized(cls, d):
        if is_listy(d):
            return [cls.from_sessionized(t) for t in d]
        elif isinstance(d, dict):
            assert d['_model'] in {'Attendee', 'Group'}
            if d['_model'] == 'Group':
                return cls.from_sessionized_group(d)
            else:
                return cls.from_sessionized_attendee(d)
        else:
            return d

    @classmethod
    def from_sessionized_group(cls, d):
        d = dict(d, attendees=[cls.from_sessionized_attendee(a) for a in d.get('attendees', [])])
        return sa.Group(**d)

    @classmethod
    def from_sessionized_attendee(cls, d):
        # Fix for attendees that were sessionized while the "requested_any_dept" column existed
        if 'requested_any_dept' in d:
            del d['requested_any_dept']

        if d.get('promo_code'):
            d = dict(d, promo_code=sa.PromoCode(**d['promo_code']))
        return sa.Attendee(**d)

    @classmethod
    def get(cls, payment_id):
        charge = cherrypy.session.pop(payment_id, None)
        if charge:
            return cls(**charge)
        else:
            raise HTTPRedirect('../preregistration/credit_card_retry')

    def to_dict(self):
        return {
            'targets': self.targets,
            'amount': self.amount,
            'description': self.description,
            'receipt_email': self.receipt_email
        }

    @property
    def has_targets(self):
        return not not self._targets

    @cached_property
    def total_cost(self):
        return 100 * sum(m.amount_unpaid for m in self.models)

    @cached_property
    def dollar_amount(self):
        return self.amount // 100

    @cached_property
    def amount(self):
        return self._amount or self.total_cost or 0

    @cached_property
    def description(self):
        return self._description or self.names

    @cached_property
    def receipt_email(self):
        return self.models[0].email if self.models and self.models[0].email else self._receipt_email

    @cached_property
    def names(self):
        return ', '.join(getattr(m, 'name', getattr(m, 'full_name', None)) for m in self.models)

    @cached_property
    def targets(self):
        return self.to_sessionized(self._targets)

    @cached_property
    def models(self):
        return self.from_sessionized(self._targets)

    @cached_property
    def attendees(self):
        return [m for m in self.models if isinstance(m, sa.Attendee)]

    @cached_property
    def groups(self):
        return [m for m in self.models if isinstance(m, sa.Group)]

    def charge_cc(self, session, token):
        try:
            log.debug('PAYMENT: !!! attempting to charge stripeToken {} {} cents for {}',
                      token, self.amount, self.description)

            self.response = stripe.Charge.create(
                card=token,
                currency='usd',
                amount=self.amount,
                description=self.description,
                receipt_email=self.receipt_email
            )

            log.info('PAYMENT: !!! SUCCESS: charged stripeToken {} {} cents for {}, responseID={}',
                     token, self.amount, self.description, getattr(self.response, 'id', None))

        except stripe.CardError as e:
            msg = 'Your card was declined with the following error from our processor: ' + str(e)
            log.error('PAYMENT: !!! FAIL: {}', msg)
            return msg
        except stripe.StripeError as e:
            error_txt = 'Got an error while calling charge_cc(self, token={!r})'.format(token)
            report_critical_exception(msg=error_txt, subject='ERROR: MAGFest Stripe invalid request error')
            return 'An unexpected problem occurred while processing your card: ' + str(e)
        else:
            if self.models:
                session.add(self.stripe_transaction_from_charge())

    def stripe_transaction_from_charge(self, type=c.PAYMENT):
        return sa.StripeTransaction(
            stripe_id=self.response.id or None,
            amount=self.amount,
            desc=self.description,
            type=type,
            who=sa.AdminAccount.admin_name() or 'non-admin',
            fk_id=self.models[0].id,
            fk_model=self.models[0].__class__.__name__
        )


def report_critical_exception(msg, subject="Critical Error"):
    """
    Report an exception to the loggers with as much context (request params/etc) as possible, and send an email.

    Call this function when you really want to make some noise about something going really badly wrong.

    :param msg: message to prepend to output
    :param subject: optional: subject for emails going out
    """

    # log with lots of cherrypy context in here
    uber.server.log_exception_with_verbose_context(msg)

    # also attempt to email the admins
    # TODO: Don't hardcode emails here.
    send_email(c.ADMIN_EMAIL, [c.ADMIN_EMAIL], subject, msg + '\n{}'.format(traceback.format_exc()))


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

    if not relative_uber_page_url:
        return ''

    if relative_uber_page_url[:3] != '../':
        raise ValueError("relative url MUST start with '../'")

    return urljoin(c.URL_BASE + "/", relative_uber_page_url[3:])


def get_real_badge_type(badge_type):
    return c.ATTENDEE_BADGE if badge_type in [c.PSEUDO_DEALER_BADGE, c.PSEUDO_GROUP_BADGE] else badge_type


def add_opt(opts, other):
    """
    Add an option to an integer or list of integers, converting it to a comma-separated string.
    This is for use with our MultiChoice columns.

    Args:
        opts: An integer or list of integers, such as when using attendee.ribbon_ints
        other: An integer to add, such as c.VOLUNTEER_RIBBON

    Returns: A comma-separated string representing all options in the list, with the new
    option added.

    """
    other = listify(other) if other else []
    opts.extend(other)
    return ','.join(set(map(str, opts)))


def remove_opt(opts, other):
    """
    Remove an option from an _ints property, converting it to a comma-separated string.
    This is for use with our MultiChoice columns.

    Args:
        opts: An integer or list of integers, such as when using attendee.ribbon_ints
        other: An integer to remove, such as c.VOLUNTEER_RIBBON

    Returns: A comma-separated string representing all options in the list, with the option
    removed.

    """
    other = listify(other) if other else []

    return ','.join(map(str, set(opts).difference(other)))


def get_age_from_birthday(birthdate, today=None):
    """
    Determines a person's age in the US. DO NOT use this to find other timespans, like the duration of an event.
    This function does not calculate a fully accurate timespan between two datetimes.
    This function assumes that a person's age begins at zero, and increments when `today.day == birthdate.day`.
    This will not be accurate for cultures which calculate age differently than the US, such as Korea.

    Args:
        birthdate: A date, should be earlier than the second parameter
        today:  Optional, age will be found as of this date

    Returns: An integer indicating the age.

    """

    if today == None:
        today = date.today()

    # Hint: int(True) == 1 and int(False) == 0
    return today.year - birthdate.year - ((today.month, today.day) < (birthdate.month, birthdate.day))


_when_dateformat = "%m/%d"


class DateBase:
    @staticmethod
    def now():
        # This exists so we can patch this in unit tests
        return localized_now()


class days_before(DateBase):
    """
    Returns true if today is # days before a deadline.

    :param: days - number of days before deadline to start
    :param: deadline - datetime of the deadline
    :param: until - (optional) number of days prior to deadline to end (default: 0)

    Examples:
        days_before(45, c.POSITRON_BEAM_DEADLINE)() - True if it's 45 days before c.POSITRON_BEAM_DEADLINE
        days_before(10, c.WARP_COIL_DEADLINE, 2)() - True if it's between 10 and 2 days before c.WARP_COIL_DEADLINE
    """
    def __init__(self, days, deadline, until=None):
        if days <= 0:
            raise ValueError("'days' paramater must be > 0. days={}".format(days))

        if until and days <= until:
            raise ValueError("'days' paramater must be less than 'until'. days={}, until={}".format(days, until))

        self.days, self.deadline, self.until = days, deadline, until

        if deadline:
            self.starting_date = self.deadline - timedelta(days=self.days)
            self.ending_date = deadline if not until else (deadline - timedelta(days=until))

            assert self.starting_date < self.ending_date

    def __call__(self):
        if not self.deadline:
            return False

        return self.starting_date < self.now() < self.ending_date

    @property
    def active_when(self):
        if not self.deadline:
            return ''

        start_txt = self.starting_date.strftime(_when_dateformat)
        end_txt = self.ending_date.strftime(_when_dateformat)

        return 'between {} and {}'.format(start_txt, end_txt)


class before(DateBase):
    """
    Returns true if today is anytime before a deadline.

    :param: deadline - datetime of the deadline

    Examples:
        before(c.POSITRON_BEAM_DEADLINE)() - True if it's before c.POSITRON_BEAM_DEADLINE
    """
    def __init__(self, deadline):
        self.deadline = deadline

    def __call__(self):
        return bool(self.deadline) and self.now() < self.deadline

    @property
    def active_when(self):
        return 'before {}'.format(self.deadline.strftime(_when_dateformat)) if self.deadline else ''


class days_after(DateBase):
    """
    Returns true if today is at least a certain number of days after a deadline.

    :param: days - number of days after deadline to start
    :param: deadline - datetime of the deadline

    Examples:
        days_after(6, c.TRANSPORTER_ROOM_DEADLINE)() - True if it's at least 6 days after c.TRANSPORTER_ROOM_DEADLINE
    """
    def __init__(self, days, deadline):
        if days is None:
            days = 0

        if days < 0:
            raise ValueError("'days' paramater must be >= 0. days={}".format(days))

        self.starting_date = None if not deadline else deadline + timedelta(days=days)

    def __call__(self):
        return bool(self.starting_date) and (self.now() > self.starting_date)

    @property
    def active_when(self):
        return 'after {}'.format(self.starting_date.strftime(_when_dateformat)) if self.starting_date else ''


class request_cached_context:
    """
    We cache certain variables (like c.BADGES_SOLD) on a per-cherrypy.request basis.
    There are situation situations, like unit tests or non-HTTP request contexts (like daemons) where we want to
    carefully control this behavior, or where the cache will never be reset.

    When this class is finished it will clear the per-request cache.

    example of how to use:
    with request_cached_context():
        # do things that use the cached values, and after this block is done, the values won't be cached anymore.
    """

    def __init__(self, clear_cache_on_start=False):
        self.clear_cache_on_start = clear_cache_on_start

    def __enter__(self):
        if self.clear_cache_on_start:
            request_cached_context._clear_cache()

    def __exit__(self, type, value, traceback):
        request_cached_context._clear_cache()

    @staticmethod
    def _clear_cache():
        threadlocal.clear()


class ExcelWorksheetStreamWriter:
    """
    Wrapper for xlsxwriter which treats it more like a stream where we append rows to it

    xlswriter only supports addressing rows/columns using absolute indices, but sometimes we
    only care about appending a new row of data to the end of the excel file.

    This track internally keeps track of the indices and increments appropriately

    NOTE: This class doesn't allow formulas in cells.
    Any cell starting with an '=' will be treated as a string, NOT a formula
    """

    def __init__(self, workbook, worksheet):
        self.workbook = workbook
        self.worksheet = worksheet
        self.next_row = 0

    def calculate_column_widths(self, rows):
        column_widths = defaultdict(int)
        for row in rows:
            for index, col in enumerate(row):
                length = len(max(col.split('\n'), key=len))
                column_widths[index] = max(column_widths[index], length)
        return [column_widths[i] + 2 for i in sorted(column_widths.keys())]

    def set_column_widths(self, rows):
        column_widths = self.calculate_column_widths(rows)
        for i, width in enumerate(column_widths):
            self.worksheet.set_column(i, i, width)

    def writerows(self, header_row, rows, header_format={'bold': True}):
        if header_row:
            self.set_column_widths([header_row] + rows)
            if header_format:
                header_format = self.workbook.add_format(header_format)
            self.writerow(header_row, header_format)
        else:
            self.set_column_widths(rows)
        for row in rows:
            self.writerow(row)

    def writerow(self, row_items, row_format=None):
        assert self.worksheet

        col = 0
        for item in row_items:
            # work around our excel library thinking anything starting with an equal sign is a formula.
            # pick the right function to call to avoid this special case.
            if item and isinstance(item, str) and len(item) > 0 and item[0] == '=':
                write_row = getattr(self.worksheet.__class__, 'write_string')
            else:
                write_row = getattr(self.worksheet.__class__, 'write')

            write_row(self.worksheet, self.next_row, col, item, *[row_format])

            col += 1

        self.next_row += 1
