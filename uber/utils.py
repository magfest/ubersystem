import importlib
import math
import os
import random
import re
import string
import traceback
import urllib
from collections import defaultdict, OrderedDict
from datetime import date, datetime, timedelta
from glob import glob
from os.path import basename
from random import randrange
from rpctools.jsonrpc import ServerProxy
from urllib.parse import urlparse, urljoin
from uuid import uuid4

import cherrypy
import phonenumbers
import stripe
from phonenumbers import PhoneNumberFormat
from pockets import cached_property, classproperty, floor_datetime, is_listy, listify
from pockets.autolog import log
from sideboard.lib import threadlocal
from pytz import UTC

import uber
from uber.config import c, _config
from uber.errors import CSRFException, HTTPRedirect


# ======================================================================
# String manipulation
# ======================================================================

def filename_extension(s):
    """
    Extract the extension portion of a filename, lowercased.
    """
    return s.split('.')[-1].lower()


def filename_safe(s):
    """
    Adapted from https://gist.github.com/seanh/93666

    Take a string and return a valid filename constructed from the
    string. Uses a whitelist approach: any characters not present in
    valid_chars are removed. Also spaces are replaced with underscores.

    Note:
        This method may produce invalid filenames such as
        ``, `.`, or `..`. When using this method on unknown data,
        consider prepending a date string like '2009_01_15_19_46_32_',
        and appending a file extension like '.txt', to avoid the
        potential of generating an invalid filename.

    """
    valid_chars = '-_.() {}{}'.format(string.ascii_letters, string.digits)
    filename = ''.join(c for c in s if c in valid_chars)
    return filename.replace(' ', '_')


def mask_string(s, mask_char='*', min_unmask=1, max_unmask=2):
    """
    Masks the trailing portion of the given string with asterisks.

    The number of unmasked characters will never be less than
    `min_unmask` or greater than `max_unmask`. Within those bounds, the
    number of unmasked characters always be smaller than half the
    length of `s`.

    Example::

        >>> for i in range(0, 12):
        ...     mask('A' * i, min_unmask=1, max_unmask=4)
        ... ''
        ... 'A'
        ... 'A*'
        ... 'A**'
        ... 'A***'
        ... 'AA***'
        ... 'AA****'
        ... 'AAA****'
        ... 'AAA*****'
        ... 'AAAA*****'
        ... 'AAAA******'
        ... 'AAAA*******'
        >>>

    Arguments:
        s (str): The string to be masked.
        mask_char (str): The character that should be used as the mask.
            Defaults to an asterisk "*".
        min_unmask (int): Defines the minimum number of characters that
            are allowed to be unmasked. If the length of `s` is less
            than or equal to `min_unmask`, then `s` is returned
            unmodified. Defaults to 1.
        max_unmask (int): Defines the maximum number of characters that
            are allowed to be unmasked. Defaults to 2.

    Returns:
        str: A copy of `s` with a portion of the string masked
            by `mask_char`.

    """
    s_len = len(s)
    if s_len <= min_unmask:
        return s
    elif s_len <= (2 * max_unmask):
        unmask = max(min_unmask, math.ceil(s_len / 2) - 1)
        return s[:unmask] + (mask_char * (s_len - unmask))
    return s[:max_unmask] + (mask_char * (s_len - max_unmask))


def normalize_newlines(text):
    """
    Replaces instances of "\r\n" and "\r" with "\n" in the given string.
    """
    if text:
        return re.sub(r'\r\n|\r|\n', '\n', str(text))
    else:
        return ''


def convert_to_absolute_url(relative_uber_page_url):
    """
    In ubersystem, we always use relative url's of the form
    "../{some_site_section}/{somepage}" or
    "/{c.PATH}/{some_site_section}/{somepage}". We use relative URLs so that no
    matter what proxy server we are behind on the web, it always works.

    We normally avoid using absolute URLs at all costs, but sometimes
    it's needed when creating URLs for use with emails or CSV exports.
    In that case, we need to take a relative URL and turn it into
    an absolute URL.

    Note:
        Do not use this function unless you absolutely need to, instead
        use relative URLs as much as possible.
    """

    if not relative_uber_page_url:
        return ''

    if relative_uber_page_url.startswith('../'):
        return urljoin(c.URL_BASE + '/', relative_uber_page_url[3:])

    if relative_uber_page_url.startswith(c.PATH):
        return urljoin(c.URL_ROOT, relative_uber_page_url)

    if relative_uber_page_url.startswith(c.URL_BASE):
        return relative_uber_page_url

    raise ValueError("relative url MUST start with '../' or '{}'".format(c.PATH))


def make_url(s):
    """
    Prepends "http://" to a string, if it doesn't already start with it.
    """
    return ('http://' + s) if s and not s.startswith('http') else s


def url_domain(url):
    """
    Extract the domain portion of a URL.

    Note:
        Omits "www.", but does not omit other subdomains.

    """
    url = url.strip().replace('//', '/')
    url = re.sub(r'^https?:/', '', url)
    url = re.sub(r'^www\.', '', url)
    return url.split('/', 1)[0].strip('@#?=. ')


def create_valid_user_supplied_redirect_url(url, default_url):
    """
    Create a valid redirect from user-supplied data.

    If there is invalid data, or a security issue is detected, then
    ignore and redirect to the homepage.

    Ignores cross-site redirects that aren't for local pages, i.e. if
    an attacker passes in something like:
    "original_location=https://badsite.com/stuff/".

    Args:
        url (str): User-supplied URL that is requested as a redirect.
        default_url (str): The URL we should use if there's an issue
            with `url`.

    Returns:
        str: A secure and valid URL that we allow for redirects.

    """
    parsed_url = urlparse(url)
    security_issue = parsed_url.scheme or parsed_url.netloc

    if not url or 'login' in url or security_issue:
        return default_url

    return url


def normalize_phone(phone_number, country='US'):
    return phonenumbers.format_number(
        phonenumbers.parse(phone_number, country),
        PhoneNumberFormat.E164)


# ======================================================================
# Datetime functions
# ======================================================================

def localized_now():
    """
    Returns datetime.now() but localized to the event's timezone.
    """
    return localize_datetime(datetime.utcnow())


def localize_datetime(dt):
    """
    Converts `dt` to the event's timezone.
    """
    return dt.replace(tzinfo=UTC).astimezone(c.EVENT_TIMEZONE)


def hour_day_format(dt):
    """
    Accepts a datetime object and returns a formatted string showing
    only the localized day and hour, e.g "7pm Thu" or "10am Sun".
    """
    hour = dt.astimezone(c.EVENT_TIMEZONE).strftime('%I%p ').strip('0').lower()
    day = dt.astimezone(c.EVENT_TIMEZONE).strftime('%a')
    return hour + day


def evening_datetime(dt):
    """
    Returns a datetime object for 5pm on the day specified by `dt`.
    """
    return floor_datetime(dt, timedelta(days=1)) + timedelta(hours=17)


def noon_datetime(dt):
    """
    Returns a datetime object for noon on the day given by `dt`.
    """
    return floor_datetime(dt, timedelta(days=1)) + timedelta(hours=12)


def get_age_from_birthday(birthdate, today=None):
    """
    Determines a person's age in the US.

    DO NOT use this to find other timespans, like the duration of an
    event. This function does not calculate a fully accurate timespan
    between two datetimes. This function assumes that a person's age
    begins at zero, and increments when `today.day == birthdate.day`.
    This will not be accurate for cultures which calculate age
    differently than the US, such as Korea.

    Args:
        birthdate: A date, should be earlier than the second parameter
        today:  Optional, age will be found as of this date

    Returns: An integer indicating the age.

    """

    if not today:
        today = date.today()

    # int(True) == 1 and int(False) == 0
    upcoming_birthday = int(
        (today.month, today.day) < (birthdate.month, birthdate.day))
    return today.year - birthdate.year - upcoming_birthday


class DateBase:
    _when_dateformat = '%m/%d'

    @staticmethod
    def now():
        # This exists so we can patch this in unit tests
        return localized_now()

    @property
    def active_after(self):
        return None

    @property
    def active_before(self):
        return None


class after(DateBase):
    """
    Returns true if today is anytime after a deadline.

    :param: deadline - datetime of the deadline

    Examples:
        after(c.POSITRON_BEAM_DEADLINE)() - True if it's after c.POSITRON_BEAM_DEADLINE
    """
    def __init__(self, deadline):
        self.deadline = deadline

    def __call__(self):
        return bool(self.deadline) and self.now() > self.deadline

    @property
    def active_after(self):
        return self.deadline

    @property
    def active_when(self):
        return 'after {}'.format(self.deadline.strftime(self._when_dateformat)) if self.deadline else ''


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
    def active_before(self):
        return self.deadline

    @property
    def active_when(self):
        return 'before {}'.format(self.deadline.strftime(self._when_dateformat)) if self.deadline else ''


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
    def active_after(self):
        return self.starting_date

    @property
    def active_when(self):
        return 'after {}'.format(self.starting_date.strftime(self._when_dateformat)) if self.starting_date else ''


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
        else:
            self.starting_date = None
            self.ending_date = None

    def __call__(self):
        if not self.deadline:
            return False

        return self.starting_date < self.now() < self.ending_date

    @property
    def active_after(self):
        return self.starting_date

    @property
    def active_before(self):
        return self.ending_date

    @property
    def active_when(self):
        if not self.deadline:
            return ''

        start_txt = self.starting_date.strftime(self._when_dateformat)
        end_txt = self.ending_date.strftime(self._when_dateformat)

        return 'between {} and {}'.format(start_txt, end_txt)


# ======================================================================
# Security
# ======================================================================

def check(model, *, prereg=False):
    """
    Runs all default validations against the supplied model instance.

    Args:
        model (sqlalchemy.Model): A single model instance.
        prereg (bool): True if this is an ephemeral model used in the
            preregistration workflow.

    Returns:
        str: None for success, or a failure message if validation fails.
    """
    for field, name in model.required:
        if not str(getattr(model, field)).strip():
            return name + ' is a required field'

    validations = [uber.model_checks.validation.validations]
    prereg_validations = [uber.model_checks.prereg_validation.validations] if prereg else []
    for v in validations + prereg_validations:
        for validator in v[model.__class__.__name__].values():
            message = validator(model)
            if message:
                return message


def check_all(models, *, prereg=False):
    """
    Runs all default validations against multiple model instances.

    Args:
        models (list): A single model instance or a list of instances.
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


def check_pii_consent(params, attendee=None):
    """
    Checks that the "pii_consent" field was passed up in the POST params if consent is needed.

    Returns:
        Empty string if "pii_consent" was given or not needed, or an error message otherwise.
    """
    if cherrypy.request.method == 'POST':
        has_pii_consent = params.get('pii_consent') == '1'
        needs_pii_consent = not attendee or attendee.needs_pii_consent
        if needs_pii_consent and not has_pii_consent:
            return 'You must agree to allow us to store your personal information in order to register.'
    return ''


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

    session_csrf_token = cherrypy.session.get('csrf_token', None)
    if csrf_token != session_csrf_token:
        raise CSRFException(
            "CSRF check failed: csrf tokens don't match: {!r} != {!r}".format(
                csrf_token, session_csrf_token))
    else:
        cherrypy.request.headers['CSRF-Token'] = csrf_token


def ensure_csrf_token_exists():
    """
    Generate a new CSRF token if none exists in our session already.
    """
    if not cherrypy.session.get('csrf_token'):
        cherrypy.session['csrf_token'] = uuid4().hex


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
    except Exception:
        return ''.join(chr(randrange(33, 127)) for i in range(8))


# ======================================================================
# Miscellaneous helpers
# ======================================================================

def redirect_to_allowed_dept(session, department_id, page):
    error_msg = 'You have been given admin access to this page, but you are not in any departments that you can admin. ' \
                'Please contact STOPS to remedy this.'
                
    if c.DEFAULT_DEPARTMENT_ID == 0:
        raise HTTPRedirect('../accounts/homepage?message={}', error_msg)
    
    if department_id == 'All':
        if len(c.ADMIN_DEPARTMENT_OPTS) == 1:
            raise HTTPRedirect('{}?department_id={}', page, c.DEFAULT_DEPARTMENT_ID)
        return

    if not department_id:
        raise HTTPRedirect('{}?department_id=All', page, department_id)
    if 'shifts_admin' in c.PAGE_PATH:
        can_access = session.admin_attendee().can_admin_shifts_for(department_id)
    elif 'dept_checklist' in c.PAGE_PATH:
        can_access = session.admin_attendee().can_admin_checklist_for(department_id)
    else:
        can_access = session.admin_attendee().can_admin_dept_for(department_id)

    if not can_access:
        if department_id == c.DEFAULT_DEPARTMENT_ID:
            raise HTTPRedirect('../accounts/homepage?message={}', error_msg)
        raise HTTPRedirect('{}?department_id={}', page, c.DEFAULT_DEPARTMENT_ID)


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
        assert re.match('^[a-z0-9_]+$', slug), \
            'Dept Head checklist item sections must have separated_by_underscore names'

        self.slug, self.description = slug, description
        self.name = name or slug.replace('_', ' ').title()
        self._path = path or '/dept_checklist/form?slug={slug}&department_id={department_id}'
        self.email_post_con = bool(email_post_con)
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


def report_critical_exception(msg, subject="Critical Error"):
    """
    Log an exception with as much context as possible and send an email.

    Call this function when you really want to make some noise about
    something going really badly wrong.

    Args:
        msg (str): Message to prepend to output.
        subject (str): Subject for alert emails. Defaults
            to "Critical Error".

    """
    from uber.tasks.email import send_email

    # Log with lots of cherrypy context in here
    uber.server.log_exception_with_verbose_context(msg=msg)

    # Also attempt to email the admins
    send_email.delay(c.ADMIN_EMAIL, [c.ADMIN_EMAIL], subject, msg + '\n{}'.format(traceback.format_exc()))


def get_page(page, queryset):
    return queryset[(int(page) - 1) * 100: int(page) * 100]


def static_overrides(dirname):
    """
    We want plugins to be able to specify their own static files to override the
    ones which we provide by default.  The main files we expect to be overridden
    are the theme image files, but theoretically a plugin can override anything
    it wants by calling this method and passing its static directory.
    """
    appconf = cherrypy.tree.apps[c.CHERRYPY_MOUNT_PATH].config
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

    python_files = glob(os.path.join(module_root, 'site_sections', '*.py'))
    site_sections = [path.split('/')[-1][:-3] for path in python_files if not path.endswith('__init__.py')]
    for site_section in site_sections:
        module = importlib.import_module(basename(module_root) + '.site_sections.' + site_section)
        setattr(Root, site_section, module.Root())


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


def _server_to_url(server):
    if not server:
        return ''
    host, _, path = urllib.parse.unquote(server).replace('http://', '').replace('https://', '').partition('/')
    if path.startswith('reggie'):
        return 'https://{}/reggie'.format(host)
    elif path.startswith('uber'):
        return 'https://{}/uber'.format(host)
    elif c.PATH == '/uber':
        return 'https://{}{}'.format(host, c.PATH)
    return 'https://{}'.format(host)


def _server_to_host(server):
    if not server:
        return ''
    return urllib.parse.unquote(server).replace('http://', '').replace('https://', '').split('/')[0]


def _format_import_params(target_server, api_token):
    target_url = _server_to_url(target_server)
    target_host = _server_to_host(target_server)
    remote_api_token = api_token.strip()
    if not remote_api_token:
        remote_api_tokens = _config.get('secret', {}).get('remote_api_tokens', {})
        remote_api_token = remote_api_tokens.get(target_host, remote_api_tokens.get('default', ''))
    return target_url, target_host, remote_api_token.strip()


def get_api_service_from_server(target_server, api_token):
    """
    Helper method that gets a service that can be used for API calls between servers.
    Returns the service or None, an error message or '', and a JSON-RPC URI
    """
    target_url, target_host, remote_api_token = _format_import_params(target_server, api_token)
    uri = '{}/jsonrpc/'.format(target_url)

    message, service = '', None
    if target_server or api_token:
        if not remote_api_token:
            message = 'No API token given and could not find a token for: {}'.format(target_host)
        elif not target_url:
            message = 'Unrecognized hostname: {}'.format(target_server)

        if not message:
            service = ServerProxy(uri=uri, extra_headers={'X-Auth-Token': remote_api_token})

    return service, message, target_url


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
        self.next_col = 0

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

    def writecell(self, data, format={}, last_cell=False):
        self.worksheet.write(self.next_row, self.next_col, data, self.workbook.add_format(format))

        if last_cell:
            self.next_col = 0
            self.next_row += 1
        else:
            self.next_col += 1


class Charge:

    def __init__(self, targets=(), amount=None, description=None, receipt_email=None):
        self._targets = listify(targets)
        self._amount = amount
        self._description = description
        self._receipt_email = receipt_email
        self._stripe_transaction = None

    @classproperty
    def paid_preregs(cls):
        return cherrypy.session.setdefault('paid_preregs', [])

    @classproperty
    def unpaid_preregs(cls):
        return cherrypy.session.setdefault('unpaid_preregs', OrderedDict())
    
    @classproperty
    def universal_promo_codes(cls):
        return cherrypy.session.setdefault('universal_promo_codes', {})

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
    def to_sessionized(cls, m, name='', badges=0):
        from uber.models import Attendee, Group
        if is_listy(m):
            return [cls.to_sessionized(t) for t in m]
        elif isinstance(m, dict):
            return m
        elif isinstance(m, Attendee):
            d = m.to_dict(
                Attendee.to_dict_default_attrs
                + ['promo_code']
                + list(Attendee._extra_apply_attrs_restricted))
            d['name'] = name
            d['badges'] = badges
            return d
        elif isinstance(m, Group):
            return m.to_dict(
                Group.to_dict_default_attrs
                + ['attendees']
                + list(Group._extra_apply_attrs_restricted))
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
        return uber.models.Group(_defer_defaults_=True, **d)

    @classmethod
    def from_sessionized_attendee(cls, d):
        if d.get('promo_code'):
            d = dict(d, promo_code=uber.models.PromoCode(_defer_defaults_=True, **d['promo_code']))

        # These aren't valid properties on the model, so they're removed and re-added
        name = d.pop('name', '')
        badges = d.pop('badges', 0)
        a = uber.models.Attendee(_defer_defaults_=True, **d)
        a.name = d['name'] = name
        a.badges = d['badges'] = badges

        return a

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
        costs = []

        for m in self.models:
            if isinstance(m, uber.models.Attendee) and getattr(m, 'badges', None):
                costs.append(c.get_group_price() * int(m.badges))
                costs.append(m.amount_extra_unpaid)
            else:
                costs.append(m.amount_unpaid)
        return 100 * sum(costs)

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
        names = []

        for m in self.models:
            if getattr(m, 'badges', None) and getattr(m, 'name') and isinstance(m, uber.models.Attendee):
                names.append("{} plus {} badges ({})".format(getattr(m, 'full_name', None), int(m.badges) - 1, m.name))
            else:
                group_name = getattr(m, 'name', None)
                names.append(group_name or getattr(m, 'full_name', None))

        return ', '.join(names)

    @cached_property
    def targets(self):
        return self.to_sessionized(self._targets)

    @cached_property
    def models(self):
        return self.from_sessionized(self._targets)

    @cached_property
    def attendees(self):
        return [m for m in self.models if isinstance(m, uber.models.Attendee)]

    @cached_property
    def groups(self):
        return [m for m in self.models if isinstance(m, uber.models.Group)]

    @property
    def stripe_transaction(self):
        return self._stripe_transaction

    def charge_cc(self, session, token):
        try:
            log.debug('PAYMENT: !!! attempting to charge stripeToken {} {} cents for {}',
                      token, self.amount, self.description)

            self.response = stripe.Charge.create(
                card=token,
                currency='usd',
                amount=int(self.amount),
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
                self._stripe_transaction = self.stripe_transaction_from_charge()
                session.add(self._stripe_transaction)
                for model in self.models:
                    multi = len(self.models) > 1
                    session.add(self.stripe_transaction_for_model(model, self._stripe_transaction, multi))

    def stripe_transaction_from_charge(self, type=c.PAYMENT):
        return uber.models.StripeTransaction(
            stripe_id=self.response.id or None,
            amount=self.amount,
            desc=self.description,
            type=type,
            who=uber.models.AdminAccount.admin_name() or 'non-admin'
        )

    def stripe_transaction_for_model(self, model, txn, multi=False):
        if model.__class__.__name__ == "Attendee":
            return uber.models.commerce.StripeTransactionAttendee(
                txn_id=txn.id,
                attendee_id=model.id,
                share=self.amount if not multi else model.amount_unpaid * 100
            )
        elif model.__class__.__name__ == "Group":
            return uber.models.commerce.StripeTransactionGroup(
                txn_id=txn.id,
                group_id=model.id,
                share=self.amount if not multi else model.amount_unpaid * 100
            )
