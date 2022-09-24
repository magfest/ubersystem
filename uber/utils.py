import importlib
import math
import os
import random
import re
import string
import traceback
from typing import Iterable
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
from authlib.integrations.requests_client import OAuth2Session
from phonenumbers import PhoneNumberFormat
from pockets import cached_property, classproperty, floor_datetime, is_listy, listify
from pockets.autolog import log
from sideboard.lib import threadlocal
from pytz import UTC

import uber
from uber.config import c, _config, signnow_sdk
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


def normalize_email(email):
    return email.strip().lower().replace('.', '')


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
    errors = []
    for field, name in model.required:
        if not getattr(model, field) or not str(getattr(model, field)).strip():
            errors.append(name + ' is a required field')

    validations = [uber.model_checks.validation.validations]
    prereg_validations = [uber.model_checks.prereg_validation.validations] if prereg else []
    for v in validations + prereg_validations:
        for validator in v[model.__class__.__name__].values():
            message = validator(model)
            if message:
                errors.append(message)
    return "ERROR: " + "<br>".join(errors) if errors else None


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


def genpasswd(short=False):
    """
    Admin accounts have passwords auto-generated; this function tries to combine
    three random dictionary words but returns a string of 8 random characters if
    no dictionary is installed.
    """
    import glob
    words = []
    # Word lists source: https://bitbucket.org/jvdl/correcthorsebatterystaple/src/master/data/
    word_lists = glob.glob(c.ROOT + '/uber/static/correcthorsebatterystaple/*.txt')
    for word_list in word_lists:
        words.extend(open(word_list).read().strip().split(','))
    else:
        if words and not short:
            words = [s.strip() for s in words if "'" not in s and s.islower() and 3 < len(s) < 8]
            return ' '.join(random.choice(words) for i in range(4))
        characters = string.ascii_letters + string.digits
        return ''.join(random.choice(characters) for i in range(8))


# ======================================================================
# Miscellaneous helpers
# ======================================================================

def redirect_to_allowed_dept(session, department_id, page):
    error_msg = 'You have been given admin access to this page, but you are not in any departments that you can admin. ' \
                'Please contact STOPS to remedy this.'
                
    if c.DEFAULT_DEPARTMENT_ID == -1:
        raise HTTPRedirect('../accounts/homepage?message={}', "Please add at least one department to manage staffers.")
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


def valid_email(email):
    from email_validator import validate_email, EmailNotValidError
    if len(email) > 255:
        return 'Email addresses cannot be longer than 255 characters.'
    elif not email:
        return 'Please enter an email address.'
    
    try:
        validate_email(email)
    except EmailNotValidError as e:
        message = str(e)
        return 'Enter a valid email address. ' + message


def valid_password(password):
    import re

    if not password:
        return 'Please enter a password.'

    if len(password) < c.MINIMUM_PASSWORD_LENGTH:
        return 'Password must be at least {} characters long.'.format(c.MINIMUM_PASSWORD_LENGTH)
    if re.search("[^a-zA-Z0-9{}]".format(c.PASSWORD_SPECIAL_CHARS), password):
        return 'Password must contain only letters, numbers, and the following symbols: {}'.format(c.PASSWORD_SPECIAL_CHARS)
    if 'lowercase_char' in c.PASSWORD_CONDITIONS and not re.search("[a-z]", password):
        return 'Password must contain at least one lowercase letter.'
    if 'uppercase_char' in c.PASSWORD_CONDITIONS and not re.search("[A-Z]", password):
        return 'Password must contain at least one uppercase letter.'
    if 'number' in c.PASSWORD_CONDITIONS and not re.search("[0-9]", password):
        return 'Password must contain at least one number.'
    if 'special_char' in c.PASSWORD_CONDITIONS and not re.search("[{}]".format(c.PASSWORD_SPECIAL_CHARS), password):
        return 'Password must contain at least one of the following symbols: {}'.format(c.PASSWORD_SPECIAL_CHARS)


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

    def __init__(self, slug, description, deadline, full_description='', name=None, path=None, email_post_con=False):
        assert re.match('^[a-z0-9_]+$', slug), \
            'Dept Head checklist item sections must have separated_by_underscore names'

        self.slug, self.description, self.full_description = slug, description, full_description
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


def get_static_file_path(filename):
    for item in cherrypy.tree.apps[c.CHERRYPY_MOUNT_PATH].config:
        if filename in item:
            return cherrypy.tree.apps[c.CHERRYPY_MOUNT_PATH].config[item]['tools.staticfile.filename']


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
    host, _, path = urllib.parse.unquote(server).replace('http://', '').replace('https://', '').rstrip('/').partition('/')
    if path.startswith('reggie'):
        return 'https://{}/reggie'.format(host)
    elif path.startswith('uber'):
        return 'https://{}/uber'.format(host)
    elif path in ['uber', 'rams']:
        return 'https://{}/{}'.format(host, path)
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

    def writecell(self, data, url=None, format={}, last_cell=False):
        if url:
            self.worksheet.write_url(self.next_row, self.next_col, url, self.workbook.add_format(format), data)
        else:
            self.worksheet.write(self.next_row, self.next_col, data, self.workbook.add_format(format))

        if last_cell:
            self.next_col = 0
            self.next_row += 1
        else:
            self.next_col += 1


class OAuthRequest:

    def __init__(self, scope='openid profile email', state=None):
        self.redirect_uri = (c.REDIRECT_URL_BASE or c.URL_BASE) + "/accounts/"
        self.client = OAuth2Session(c.AUTH_CLIENT_ID, c.AUTH_CLIENT_SECRET, scope=scope, state=state, redirect_uri=self.redirect_uri + "process_login")
        self.state = state if state else None

    def set_auth_url(self):
        self.auth_uri, self.state = self.client.create_authorization_url("https://{}/authorize".format(c.AUTH_DOMAIN), self.state)

    def set_token(self, code, state):
        self.auth_token = self.client.fetch_token("https://{}/oauth/token".format(c.AUTH_DOMAIN), code=code, state=state).get('access_token')

    def get_email(self):
        profile = self.client.get("https://{}/userinfo".format(c.AUTH_DOMAIN)).json()
        if not profile.get('email', ''):
            log.error("Tried to authenticate a user but we couldn't retrieve their email. Did we use the right scope?")
        else:
            return profile['email']

    @property
    def logout_uri(self):
        return "https://{}/v2/logout?client_id={}&returnTo={}".format(
                    c.AUTH_DOMAIN,
                    c.AUTH_CLIENT_ID,
                    self.redirect_uri + "process_logout")


class Charge:

    def __init__(self, targets=(), amount=0, description=None, receipt_email=''):
        self._targets = listify(targets)
        self._description = description
        self._receipt_email = receipt_email
        self._current_cost = amount

    @classproperty
    def paid_preregs(cls):
        return cherrypy.session.setdefault('paid_preregs', [])

    @classproperty
    def unpaid_preregs(cls):
        return cherrypy.session.setdefault('unpaid_preregs', OrderedDict())

    @classproperty
    def pending_preregs(cls):
        return cherrypy.session.setdefault('pending_preregs', OrderedDict())
    
    @classproperty
    def stripe_intent_id(cls):
        return cherrypy.session.get('stripe_intent_id', '')
    
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

    @classmethod
    def create_new_receipt(cls, model, create_model=False, items=None):
        """
        Iterates through the cost_calculations for this model and returns a list containing all non-null cost and credit items.
        This function is for use with new models to grab all their initial costs for creating or previewing a receipt.
        """
        from uber.models import AdminAccount, ModelReceipt, ReceiptItem
        if not items:
            items = [uber.receipt_items.cost_calculation.items] + [uber.receipt_items.credit_calculation.items]
        receipt_items = []
        receipt = ModelReceipt(owner_id=model.id, owner_model=model.__class__.__name__) if create_model else None
        
        for i in items:
            for calculation in i[model.__class__.__name__].values():
                item = calculation(model)
                if item:
                    try:
                        desc, cost, count = item
                    except ValueError:
                        # Unpack list of wrong size (no quantity provided).
                        desc, cost = item
                        count = 1
                    if isinstance(cost, Iterable):
                        # A list of the same item at different prices, e.g., group badges
                        for price in cost:
                            if receipt:
                                receipt_items.append(ReceiptItem(receipt_id=receipt.id,
                                                                desc=desc,
                                                                amount=price,
                                                                count=cost[price],
                                                                who=AdminAccount.admin_name() or 'non-admin'
                                                                ))
                            else:
                                receipt_items.append((desc, price, cost[price]))
                    elif receipt:
                        receipt_items.append(ReceiptItem(receipt_id=receipt.id,
                                                          desc=desc,
                                                          amount=cost,
                                                          count=count,
                                                          who=AdminAccount.admin_name() or 'non-admin'
                                                        ))
                    else:
                        receipt_items.append((desc, cost, count))
        
        return receipt, receipt_items

    @classmethod
    def calc_simple_cost_change(cls, model, col_name, new_val):
        """
        Takes an instance of a model and attempts to calculate a simple cost change
        based on a column name. Used for columns where the cost is the column, e.g.,
        extra_donation and amount_extra.
        """
        model_dict = model.to_dict()

        if model_dict.get(col_name) == None:
            return None, None
        
        return (model_dict[col_name] * 100, (int(new_val) - model_dict[col_name]) * 100)

    @classmethod
    def process_receipt_upgrade_item(cls, model, col_name, new_val, receipt=None, count=1):
        """
        Finds the cost of a receipt item to add to an existing receipt.
        This uses the cost_changes dictionary defined on each model in receipt_items.py,
        calling it with the extra keyword arguments provided. If no function is specified,
        we use calc_simple_cost_change instead.
        
        If a ModelReceipt is provided, a new ReceiptItem is created and returned.
        Otherwise, the raw values are returned so attendees can preview their receipt 
        changes.
        """
        from uber.models import AdminAccount, ReceiptItem
        from uber.models.types import Choice

        try:
            new_val = int(new_val)
        except Exception:
            pass # It's fine if this is not a number

        if isinstance(model.__table__.columns.get(col_name).type, Choice):
            increase_term, decrease_term = "Upgrading", "Downgrading"
        else:
            increase_term, decrease_term = "Increasing", "Decreasing"

        cost_change_tuple = model.cost_changes.get(col_name)
        if not cost_change_tuple:
            cost_change_name = col_name.replace('_', ' ').title()
            old_cost, cost_change = cls.calc_simple_cost_change(model, col_name, new_val)
        else:
            cost_change_name = cost_change_tuple[0]
            cost_change_func = cost_change_tuple[1]
            if len(cost_change_tuple) > 2:
                cost_change_name = cost_change_name.format(*[dictionary.get(new_val) for dictionary in cost_change_tuple[2:]])
            
            if not cost_change_func:
                old_cost, cost_change = cls.calc_simple_cost_change(model, col_name, new_val)
            else:
                change_func = getattr(model, cost_change_func)
                old_cost, cost_change = change_func(**{col_name: new_val})

        is_removable_item = col_name != 'badge_type'
        if not old_cost and is_removable_item:
            cost_desc = "Adding {}".format(cost_change_name)
        elif cost_change * -1 == old_cost and is_removable_item: # We're crediting the full amount of the item
            cost_desc = "Removing {}".format(cost_change_name)
        elif cost_change > 0:
            cost_desc = "{} {}".format(increase_term, cost_change_name)
        else:
            cost_desc = "{} {}".format(decrease_term, cost_change_name)

        if receipt:
            return ReceiptItem(receipt_id=receipt.id,
                                desc=cost_desc,
                                amount=cost_change,
                                count=count,
                                who=AdminAccount.admin_name() or 'non-admin',
                                revert_change={col_name: getattr(model, col_name)},
                            )
        else:
            return (cost_desc, cost_change, count)

    def prereg_receipt_preview(self):
        """
        Returns a list of tuples where tuple[0] is the name of a group of items,
        and tuple[1] is a list of cost item tuples from create_new_receipt
        
        This lets us show the attendee a nice display of what they're buying
        ... whenever we get around to actually using it that way
        """
        from uber.models import PromoCodeGroup

        items_preview = []
        for model in self.models:
            if getattr(model, 'badges', None) and getattr(model, 'name') and isinstance(model, uber.models.Attendee):
                items_group = ("{} plus {} badges ({})".format(getattr(model, 'full_name', None), int(model.badges) - 1, model.name), [])
                x, receipt_items = Charge.create_new_receipt(PromoCodeGroup())
            else:
                group_name = getattr(model, 'name', None)
                items_group = (group_name or getattr(model, 'full_name', None), [])
            
            x, receipt_items = Charge.create_new_receipt(model)
            items_group[1].extend(receipt_items)
            
            items_preview.append(items_group)

        return items_preview

    def set_total_cost(self):
        preview_receipt_groups = self.prereg_receipt_preview()
        for group in preview_receipt_groups:
            self._current_cost += sum([(item[1] * item[2]) for item in group[1]])

    @property
    def has_targets(self):
        return not not self._targets

    @cached_property
    def total_cost(self):
        return self._current_cost

    @cached_property
    def dollar_amount(self):
        return self.total_cost // 100

    @cached_property
    def description(self):
        return self._description or self.names

    @cached_property
    def receipt_email(self):
        email = self.models[0].email if self.models and self.models[0].email else self._receipt_email
        return email[0] if isinstance(email, list) else email  

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

    def create_stripe_intent(self, amount=0, receipt_email='', description=''):
        """
        Creates a Stripe Intent, which is what Stripe uses to process payments.
        After calling this, call create_receipt_transaction with the Stripe Intent's ID
        and the receipt to add the new transaction to the receipt.
        """
        from uber.custom_tags import format_currency

        amount = amount or self.total_cost
        receipt_email = receipt_email or self.receipt_email
        description = description or self.description

        if not amount or amount <= 0:
            log.error('Was asked for a Stripe Intent but the currently owed amount is invalid: {}'.format(amount))
            return "There was an error calculating the amount. Please refresh the page or contact the system admin."

        if amount > 999999:
            return "We cannot charge {}. Please make sure your total is below $999,999.".format(format_currency(amount / 100))

        log.debug('Creating Stripe Intent to charge {} cents for {}', amount, description)
        try:
            customer = None
            if receipt_email:
                customer_list = stripe.Customer.list(
                    email=receipt_email,
                    limit=1,
                )
                if customer_list:
                    customer = customer_list.data[0]
                else:
                    customer = stripe.Customer.create(
                        description=receipt_email,
                        email=receipt_email,
                    )

            stripe_intent = stripe.PaymentIntent.create(
                payment_method_types=['card'],
                amount=int(amount),
                currency='usd',
                description=description,
                receipt_email=customer.email if receipt_email else None,
                customer=customer.id if customer else None,
            )

            return stripe_intent
        except Exception as e:
            error_txt = 'Got an error while calling create_stripe_intent()'
            report_critical_exception(msg=error_txt, subject='ERROR: MAGFest Stripe invalid request error')
            return 'An unexpected problem occurred while setting up payment: ' + str(e)

    @classmethod
    def create_receipt_transaction(self, receipt, desc='', intent_id='', amount=0):
        if not amount and intent_id:
            intent = stripe.PaymentIntent.retrieve(intent_id)
            log.debug(intent)
            amount = intent.amount
        
        if not amount:
            amount = receipt.current_amount_owed
        
        if not amount > 0:
            return "There was an issue recording your payment."

        return uber.models.ReceiptTransaction(
            receipt_id=receipt.id,
            intent_id=intent_id,
            amount=receipt.current_amount_owed,
            desc=desc,
            who=uber.models.AdminAccount.admin_name() or 'non-admin'
        )

    @staticmethod
    def mark_paid_from_intent_id(intent_id, charge_id):
        from uber.models import Attendee, ArtShowApplication, Group, Session
        from uber.tasks.email import send_email
        from uber.decorators import render
        
        with Session() as session:
            matching_txns = session.query(uber.models.ReceiptTransaction).filter_by(intent_id=intent_id).all()

            for txn in matching_txns:
                txn.charge_id = charge_id
                session.add(txn)
                txn_receipt = txn.receipt

                for item in txn_receipt.open_receipt_items:
                    if item.added < txn.added:
                        item.closed = datetime.now()
                        session.add(item)

                session.commit()

                model = session.get_model_by_receipt(txn_receipt)
                if isinstance(model, Attendee) and not model.amount_pending:
                    if model.badge_status == c.PENDING_STATUS:
                        model.badge_status = c.NEW_STATUS
                    if model.paid in [c.NOT_PAID, c.PENDING]:
                        model.paid = c.HAS_PAID
                if isinstance(model, Group) and not model.amount_pending:
                    model.paid = c.HAS_PAID
                session.add(model)

                session.commit()

                if model and isinstance(model, Group) and model.is_dealer and not txn.receipt.open_receipt_items:
                    try:
                        send_email.delay(
                            c.MARKETPLACE_EMAIL,
                            c.MARKETPLACE_EMAIL,
                            '{} Payment Completed'.format(c.DEALER_TERM.title()),
                            render('emails/dealers/payment_notification.txt', {'group': model}, encoding=None),
                            model=model.to_dict('id'))
                    except Exception:
                        log.error('Unable to send {} payment confirmation email'.format(c.DEALER_TERM), exc_info=True)
                if model and isinstance(model, ArtShowApplication) and not txn.receipt.open_receipt_items:
                    try:
                        send_email.delay(
                            c.ART_SHOW_EMAIL,
                            c.ART_SHOW_EMAIL,
                            'Art Show Payment Received',
                            render('emails/art_show/payment_notification.txt',
                                {'app': model}, encoding=None),
                            model=model.to_dict('id'))
                    except Exception:
                        log.error('Unable to send Art Show payment confirmation email', exc_info=True)

            return matching_txns


class SignNowDocument:    
    def __init__(self):
        self.access_token = None
        self.error_message = ''
        self.set_access_token()

    @property
    def api_call_headers(self):
        """
        SignNow's Python SDK is very limited, so we often have to make our own calls instead.
        """
        return {
                "Authorization": "Bearer " + self.access_token,
                "Content-Type": "application/json",
                "Accept": "application/json"
            }

    def set_access_token(self, refresh=False):
        from uber.config import aws_secrets_client

        self.access_token = c.SIGNNOW_ACCESS_TOKEN

        if self.access_token and not refresh:
            return

        if not self.access_token and c.DEV_BOX and c.SIGNNOW_USERNAME and c.SIGNNOW_PASSWORD:
            access_request = signnow_sdk.OAuth2.request_token(c.SIGNNOW_USERNAME, c.SIGNNOW_PASSWORD, '*')
            if 'error' in access_request:
                self.error_message = "Error getting access token from SignNow using username and passsword: " + access_request['error']
            else:
                self.access_token = access_request['access_token']
        elif not aws_secrets_client:
            self.error_message = "Couldn't get a SignNow access token because there was no AWS Secrets client. If you're on a development box, you can instead use a username and password."
        elif not c.AWS_SIGNNOW_SECRET_NAME:
            self.error_message = "Couldn't get a SignNow access token because the secret name is not set. If you're on a development box, you can instead use a username and password."
        else:
            aws_secrets_client.get_signnow_secret()
            self.access_token = c.SIGNNOW_ACCESS_TOKEN
        
        if not self.access_token and not self.error_message:
            self.error_message = "We tried to set an access token, but for some reason it failed."

    def create_document(self, template_id, doc_title, folder_id='', uneditable_texts_list=None, fields={}):
        from requests import post, put
        from json import dumps, loads

        self.set_access_token(refresh=True)
        if not self.error_message:
            document_request = signnow_sdk.Template.copy(self.access_token, template_id, doc_title)
        
            if 'error' in document_request:
                self.error_message = "Error creating document from template with token {}: {}".format(self.access_token, document_request['error'])
                return None

        if self.error_message:
            return None
        
        if uneditable_texts_list:
            response = put(signnow_sdk.Config().get_base_url() + '/document/' + document_request.get('id'), headers=self.api_call_headers,
            data=dumps({
                "texts": uneditable_texts_list,
            }))
            edit_request = loads(response.content)

            if 'errors' in edit_request:
                self.error_message = "Error setting up uneditable text fields: " + '; '.join([e['message'] for e in edit_request['errors']])
                return None
        
        if fields:
            response = put(signnow_sdk.Config().get_base_url() + '/v2/documents/' + document_request.get('id') + '/prefill-texts', headers=self.api_call_headers,
            data=dumps({
                "fields": [{"field_name": field, "prefilled_text": name} for field, name in fields.items()],
            }))
            if response.status_code != 204:
                fields_request = response.json()

                if 'errors' in fields_request:
                    self.error_message = "Error setting up text fields: " + '; '.join([e['message'] for e in fields_request['errors']])
                    return None

        if folder_id:
            result = signnow_sdk.Document.move(self.access_token,
                                               document_request.get('id', ''),
                                               folder_id)
            if 'error' in result:
                self.error_message = "Error moving document into folder: " + result['error']
                # Give the document request back anyway
        
        return document_request.get('id')
    
    def get_signing_link(self, document_id, first_name="", last_name="", redirect_uri=""):
        from requests import post
        from json import dumps, loads

        """Creates shortened signing link urls that can be clicked be opened in a browser to sign the document
        Based on SignNow's Python SDK, which is horribly out of date.
        Args:
            access_token (str): The access token of an account that has access to the document.
            document_id (str): The unique id of the document you want to create the links for.
            redirect_uri (str): The URL to redirect the user when they are done signing the document.
        Returns:
            dict: A dictionary representing the JSON response containing the signing links for the document.
        """

        self.set_access_token(refresh=True)

        response = post(signnow_sdk.Config().get_base_url() + '/link', headers=self.api_call_headers,
        data=dumps({
            "document_id": document_id,
            "firstname": first_name,
            "lastname": last_name,
            "redirect_uri": redirect_uri
        }))
        signing_request = loads(response.content)
        if 'errors' in signing_request:
            self.error_message = "Error getting signing link: " + '; '.join([e['message'] for e in signing_request['errors']])
        else:
            return signing_request.get('url_no_signup')

    def get_download_link(self, document_id):
        self.set_access_token(refresh=True)
        download_request = signnow_sdk.Document.download_link(self.access_token, document_id)

        if 'error' in download_request:
            self.error_message = "Error getting download link: " + download_request['error']
        else:
            return download_request.get('link')
    
    def get_document_details(self, document_id):
        self.set_access_token(refresh=True)
        document_request = signnow_sdk.Document.get(self.access_token, document_id)

        if 'error' in document_request:
            self.error_message = "Error getting document: " + document_request['error']
        else:
            return document_request


class TaskUtils:
    """
    Utility functions for use in celery tasks.
    """
    @staticmethod
    def _guess_dept(session, id_name):
        from uber.models import Department
        from sqlalchemy import or_

        id, name = id_name
        dept = session.query(Department).filter(or_(
            Department.id == id,
            Department.normalized_name == Department.normalize_name(name))).first()

        if dept:
            return (id, dept)
        return None

    @staticmethod
    def attendee_import(import_job):
        from uber.models import Attendee, AttendeeAccount, DeptMembership, DeptMembershipRequest
        from functools import partial

        with uber.models.Session() as session:
            service, message, target_url = get_api_service_from_server(import_job.target_server,
                                                                       import_job.api_token)

            import_job.queued = datetime.now()
            session.commit()

            errors = []
            badge_type = int(import_job.json_data.get('badge_type', 0))
            extra_admin_notes = import_job.json_data.get('admin_notes', '')

            if not badge_type:
                errors.append("ERROR: Attendee does not have a badge type.")
            elif badge_type not in c.BADGES:
                errors.append("ERROR: Attendee badge type not recognized: " + str(badge_type))

            try:
                results = service.attendee.export(import_job.query, True)
            except Exception as ex:
                errors.append(str(ex))
            else:
                num_attendees = len(results.get('attendees', []))
                if num_attendees != 1:
                    errors.append("ERROR: We expected one attendee for this query, but got " + str(num_attendees) + " instead.")
            
            if errors:
                import_job.errors += "; {}".format("; ".join(errors)) if import_job.errors else "; ".join(errors)
                session.commit()
                return
            
            attendee = results.get('attendees', [])[0]
            badge_label = c.BADGES[badge_type].lower()

            if badge_type == c.STAFF_BADGE:
                paid = c.NEED_NOT_PAY
            else:
                paid = c.NOT_PAID
        
            import_from_url = '{}/registration/form?id={}\n\n'.format(import_job.target_server, attendee['id'])
            new_admin_notes = '{}\n\n'.format(extra_admin_notes) if extra_admin_notes else ''
            old_admin_notes = 'Old Admin Notes:\n{}\n'.format(attendee['admin_notes']) if attendee['admin_notes'] else ''

            attendee.update({
                'badge_type': badge_type,
                'badge_status': c.NEW_STATUS if badge_type == c.STAFF_BADGE else c.IMPORTED_STATUS,
                'paid': paid,
                'placeholder': True,
                'requested_hotel_info': True,
                'admin_notes': 'Imported {} from {}{}{}'.format(
                    badge_label, import_from_url, new_admin_notes, old_admin_notes),
                'past_years': attendee['all_years'],
            })
            if attendee['shirt'] not in c.SHIRT_OPTS:
                del attendee['shirt']
                
            del attendee['id']
            del attendee['all_years']

            account_ids = attendee.get('attendee_account_ids', [])

            if badge_type != c.STAFF_BADGE:
                attendee = Attendee().apply(attendee, restricted=False)
            else:
                assigned_depts = {attendee[0]: 
                                  attendee[1] for attendee in map(partial(TaskUtils._guess_dept, session),
                                  attendee.pop('assigned_depts', {}).items()) if attendee}
                checklist_admin_depts = attendee.pop('checklist_admin_depts', {})
                dept_head_depts = attendee.pop('dept_head_depts', {})
                poc_depts = attendee.pop('poc_depts', {})
                requested_depts = attendee.pop('requested_depts', {})

                attendee.update({
                    'staffing': True,
                    'ribbon': str(c.DEPT_HEAD_RIBBON) if dept_head_depts else '',
                })

                attendee = Attendee().apply(attendee, restricted=False)

                for id, dept in assigned_depts.items():
                    attendee.dept_memberships.append(DeptMembership(
                        department=dept,
                        attendee=attendee,
                        is_checklist_admin=bool(id in checklist_admin_depts),
                        is_dept_head=bool(id in dept_head_depts),
                        is_poc=bool(id in poc_depts),
                    ))

                requested_anywhere = requested_depts.pop('All', False)
                requested_depts = {d[0]: d[1] for d in map(partial(TaskUtils._guess_dept, session), requested_depts.items()) if d}

                if requested_anywhere:
                    attendee.dept_membership_requests.append(DeptMembershipRequest(attendee=attendee))
                for id, dept in requested_depts.items():
                    attendee.dept_membership_requests.append(DeptMembershipRequest(
                        department=dept,
                        attendee=attendee,
                    ))

            session.add(attendee)

            for id in account_ids:
                try:
                    account_to_import = TaskUtils.get_attendee_account_by_id(id, service)
                except Exception as ex:
                    import_job.errors += "; {}".format("; ".join(str(ex))) if import_job.errors else "; ".join(str(ex))

                account = session.query(AttendeeAccount).filter(AttendeeAccount.normalized_email == normalize_email(account_to_import['email'])).first()
                if not account:
                    del account_to_import['id']
                    account = AttendeeAccount().apply(account_to_import, restricted=False)
                    session.add(account)
                attendee.managers.append(account)

            try:
                session.commit()
            except Exception as ex:
                session.rollback()
                import_job.errors += "; {}".format(str(ex)) if import_job.errors else str(ex)
            else:
                import_job.completed = datetime.now()
            session.commit()
    
    @staticmethod
    def get_attendee_account_by_id(account_id, service):
        from uber.models import AttendeeAccount

        try:
            results = service.attendee_account.export(account_id, False)
        except Exception as ex:
            raise ex
        else:
            num_accounts = len(results.get('accounts', []))
            if num_accounts != 1:
                raise Exception("ERROR: We expected one account for this query, but got " + str(num_accounts) + " instead.")
        
        return results.get('accounts', [])[0]

    @staticmethod
    def basic_attendee_import(attendee):
        from uber.models import Attendee
        attendee.update({
            'badge_status': c.IMPORTED_STATUS,
            'badge_num': None,
            'requested_hotel_info': True,
            'past_years': attendee['all_years'],
        })
        if attendee.get('shirt', '') and attendee['shirt'] not in c.SHIRT_OPTS:
            del attendee['shirt']
            
        del attendee['id']
        del attendee['all_years']

        return Attendee().apply(attendee, restricted=False)

    @staticmethod
    def attendee_account_import(import_job):
        from uber.models import Attendee, AttendeeAccount

        with uber.models.Session() as session:
            service, message, target_url = get_api_service_from_server(import_job.target_server,
                                                                       import_job.api_token)

            import_job.queued = datetime.now()
            session.commit()

            errors = []

            try:
                account_to_import = TaskUtils.get_attendee_account_by_id(import_job.query, service)
            except Exception as ex:
                import_job.errors += "; {}".format("; ".join(str(ex))) if import_job.errors else "; ".join(str(ex))
                session.commit()
                return

            account = session.query(AttendeeAccount).filter(AttendeeAccount.normalized_email == normalize_email(account_to_import['email'])).first()
            if not account:
                del account_to_import['id']
                account = AttendeeAccount().apply(account_to_import, restricted=False)
                session.add(account)

            try:
                session.commit()
            except Exception as ex:
                session.rollback()
                import_job.errors += "; {}".format(str(ex)) if import_job.errors else str(ex)
                return
            else:
                import_job.completed = datetime.now()

            account_attendees = {}

            try:
                account_attendees = service.attendee_account.export_attendees(import_job.query, True)['attendees']
            except Exception as ex:
                pass

            for attendee in account_attendees:
                # Try to match staff to their existing badge, which would be newer than the one we're importing
                if attendee.get('badge_num', 0) in range(c.BADGE_RANGES[c.STAFF_BADGE][0], c.BADGE_RANGES[c.STAFF_BADGE][1]):
                    old_badge_num = attendee['badge_num']
                    existing_staff = session.query(Attendee).filter_by(badge_num=old_badge_num).first()
                    if existing_staff:
                        existing_staff.managers.append(account)
                        session.add(existing_staff)
                    else:
                        new_staff = TaskUtils.basic_attendee_import(attendee)
                        new_staff.badge_num = old_badge_num
                        new_staff.managers.append(account)
                        session.add(new_staff)
                else:
                    new_attendee = TaskUtils.basic_attendee_import(attendee)
                    new_attendee.paid = c.NOT_PAID
                    
                    new_attendee.managers.append(account)
                    session.add(new_attendee)

                try:
                    session.commit()
                except Exception as ex:
                    import_job.errors += "; {}".format(str(ex)) if import_job.errors else str(ex)
                    session.rollback()
                session.commit()

    @staticmethod
    def group_import(import_job):
        # Import groups, then their attendees, then those attendee's accounts

        from uber.models import Attendee, AttendeeAccount, Group

        with uber.models.Session() as session:
            service, message, target_url = get_api_service_from_server(import_job.target_server,
                                                                       import_job.api_token)

            import_job.queued = datetime.now()
            session.commit()

            errors = []

            try:
                results = service.group.export(import_job.query, import_job.json_data.get('all', True))
            except Exception as ex:
                errors.append(str(ex))
            else:
                num_groups = len(results.get('groups', []))
                if num_groups != 1:
                    errors.append("ERROR: We expected one group for this query, but got " + str(num_groups) + " instead.")
            
            if errors:
                import_job.errors += "; {}".format("; ".join(errors)) if import_job.errors else "; ".join(errors)
                session.commit()
                return
            
            group_to_import = results.get('groups', [])[0]
            group_attendees = {}

            try:
                group_results = service.group.export_attendees(group_to_import['id'], True)
                group_attendees = group_results['attendees']
            except Exception as ex:
                attendee_warning = "Could not import attendees: {}".format(str(ex))
                import_job.errors += "; {}".format(attendee_warning) if import_job.errors else attendee_warning

            # Remove categories that don't exist this year
            current_categories = group_to_import.get('categories', '')
            if current_categories:
                current_categories = current_categories.split(',')
                for category in current_categories:
                    if int(category) not in c.DEALER_WARES.keys():
                        current_categories.remove(category)
                group_to_import['categories'] = ','.join(current_categories)

            group_to_import['status'] = c.IMPORTED

            new_group = Group().apply(group_to_import, restricted=False)
            session.add(new_group)
            try:
                session.commit()
            except Exception as ex:
                session.rollback()
                import_job.errors += "; {}".format(str(ex)) if import_job.errors else str(ex)
                return
            else:
                import_job.completed = datetime.now()

            for attendee in group_attendees:
                is_leader = attendee['id'] == group_results['group_leader_id']
                new_attendee = TaskUtils.basic_attendee_import(attendee)
                if not new_attendee.paid == c.PAID_BY_GROUP:
                    new_attendee.paid = c.NOT_PAID
                new_attendee.group = new_group
                if is_leader:
                    new_group.leader = new_attendee
                
                for id in attendee.get('attendee_account_ids', ''):
                    try:
                        account_to_import = TaskUtils.get_attendee_account_by_id(id, service)
                    except Exception as ex:
                        import_job.errors += "; {}".format("; ".join(str(ex))) if import_job.errors else "; ".join(str(ex))

                    account = session.query(AttendeeAccount).filter(AttendeeAccount.normalized_email == normalize_email(account_to_import['email'])).first()
                    if not account:
                        del account_to_import['id']
                        account = AttendeeAccount().apply(account_to_import, restricted=False)
                        session.add(account)
                    new_attendee.managers.append(account)

                session.add(new_attendee)

                try:
                    session.commit()
                except Exception as ex:
                    import_job.errors += "; {}".format(str(ex)) if import_job.errors else str(ex)
                    session.rollback()

            session.assign_badges(new_group, group_to_import['badges'], group_results['unassigned_badge_type'], group_results['unassigned_ribbon'])
            session.commit()
