import bcrypt
import cherrypy
import importlib
import math
import os
import phonenumbers
import random
import re
import string
import textwrap
import traceback
import uber
import urllib

from collections import defaultdict, OrderedDict
from datetime import date, datetime, timedelta
from glob import glob
from os.path import basename
from rpctools.jsonrpc import ServerProxy
from urllib.parse import urlparse, urljoin
from uuid import uuid4
from phonenumbers import PhoneNumberFormat
from pockets import floor_datetime, listify
from pockets.autolog import log
from pytz import UTC
from sqlalchemy import func

from uber.config import c, _config, signnow_sdk, threadlocal
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


def normalize_email(email, split_address=False):
    from email_validator import validate_email
    response = validate_email(email, check_deliverability=False)
    if split_address:
        return response.local_part, response.domain
    return response.normalized


def normalize_email_legacy(email):
    # We're trialing a new way to normalize email for attendee accounts
    # This is for attendee records themselves
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


def extract_urls(text):
    """
    Extract all URLs from a block of text and returns them in a list.
    Designed for use with attendee-submitted URLs, e.g., URLs inside
    seller application fields.

    This is a simplified version of https://stackoverflow.com/a/50790119.
    We don't look for IP addresses of any kind, and we assume that
    attendees put whitespace after each URL so we can match complex
    resources paths with a wide variety of characters.
    """
    if not text:
        return

    regex = (r"\b((?:https?:\/\/)?(?:(?:www\.)?(?:[\da-z\.-]+)\.(?:[a-z]{2,6}))"
             r"(?::[0-9]{1,4}|[1-5][0-9]{4}|6[0-4][0-9]{3}|65[0-4][0-9]{2}|655[0-2][0-9]|6553[0-5])?(?:\/\S*)*\/?)\b")
    return re.findall(regex, text, re.IGNORECASE)


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


def get_age_conf_from_birthday(birthdate, today=None):
    """
    Combines get_age_from_birthday with our age configuration groups
    to allow easy access to age-related config when doing validations.
    """
    if not birthdate:
        return c.AGE_GROUP_CONFIGS[c.AGE_UNKNOWN]

    age = get_age_from_birthday(birthdate, today)

    for val, age_group in c.AGE_GROUP_CONFIGS.items():
        if val != c.AGE_UNKNOWN and age_group['min_age'] <= age and age <= age_group['max_age']:
            return age_group

    return c.AGE_GROUP_CONFIGS[c.AGE_UNKNOWN]


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
            raise ValueError("'days' parameter must be >= 0. days={}".format(days))

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
            raise ValueError("'days' parameter must be > 0. days={}".format(days))

        if until and days <= until:
            raise ValueError("'days' parameter must be less than 'until'. days={}, until={}".format(days, until))

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


class days_between(DateBase):
    """
    Returns true if today is between two deadlines, with optional values for days before and after each deadline.

    :param: days - number of days before deadline to start
    :param: deadline - datetime of the deadline
    :param: until - (optional) number of days prior to deadline to end (default: 0)

    Examples:
        days_between((14, c.POSITRON_BEAM_DEADLINE), (5, c.EPOCH))():
            True if it's 14 days before c.POSITRON_BEAM_DEADLINE and 5 days before c.EPOCH
        days_between((c.WARP_COIL_DEADLINE, 5), c.EPOCH)():
            True if it's 5 days after c.WARP_COIL_DEADLINE up to c.EPOCH
    """
    def __init__(self, first_deadline_tuple, second_deadline_tuple):
        self.errors = []

        self.starting_date = self.process_deadline_tuple(first_deadline_tuple)
        self.ending_date = self.process_deadline_tuple(second_deadline_tuple)

        if self.errors:
            raise ValueError(f"{' '.join(self.errors)} Please use the following format: "
                             "optional days_before(int), deadline(datetime), optional days_after(int). "
                             "Note that you cannot set both days_before and days_after.")

        assert self.starting_date < self.ending_date

    def process_deadline_tuple(self, deadline_tuple):
        days_before, deadline, days_after = None, None, None

        try:
            first_val, second_val = deadline_tuple
            if isinstance(first_val, int) and isinstance(second_val, int):
                self.errors.append(f"Couldn't find a deadline in the tuple: {deadline_tuple}.")
                return
            elif isinstance(first_val, int):
                days_before, deadline, days_after = first_val, second_val, 0
            elif isinstance(second_val, int):
                days_before, deadline, days_after = 0, first_val, second_val
            else:
                self.errors.append(f"Malformed tuple: {deadline_tuple}.")
                return
        except TypeError:
            days_before, deadline, days_after = 0, deadline_tuple, 0

        if days_before:
            return deadline - timedelta(days=days_before)
        else:
            return deadline + timedelta(days=days_after)

    def __call__(self):
        if not self.starting_date or not self.ending_date:
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
        if not self.starting_date or not self.ending_date:
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
                if isinstance(message, tuple):
                    message = message[1]
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


def validate_model(forms, model, preview_model=None, is_admin=False):
    from wtforms import validators

    all_errors = defaultdict(list)

    if not preview_model:
        preview_model = model
    else:
        for form in forms.values():
            form.populate_obj(preview_model)  # We need a populated model BEFORE we get its optional fields below
        if not model.is_new:
            preview_model.is_actually_old = True

    for form in forms.values():
        extra_validators = defaultdict(list)
        for field_name in form.get_optional_fields(preview_model, is_admin):
            field = getattr(form, field_name)
            if field:
                field.validators = (
                    [validators.Optional()] +
                    [validator for validator in field.validators
                     if not isinstance(validator, (validators.DataRequired, validators.InputRequired))])

        # TODO: Do we need to check for custom validations or is this code performant enough to skip that?
        for key, field in form.field_list:
            if key == 'badge_num' and field.data:
                field_data = int(field.data)  # Badge number box is a string to accept encrypted barcodes
            else:
                field_data = field.data
            extra_validators[key].extend(form.field_validation.get_validations_by_field(key))
            if field and (model.is_new or getattr(model, key, None) != field_data):
                extra_validators[key].extend(form.new_or_changed_validation.get_validations_by_field(key))
        valid = form.validate(extra_validators=extra_validators)
        if not valid:
            for key, val in form.errors.items():
                all_errors[key].extend(map(str, val))

    validations = [uber.model_checks.validation.validations]
    prereg_validations = [uber.model_checks.prereg_validation.validations] if not is_admin else []
    for v in validations + prereg_validations:
        for validator in v[model.__class__.__name__].values():
            error = validator(preview_model)
            if error and isinstance(error, tuple):
                all_errors[error[0]].append(error[1])
            elif error:
                all_errors[''].append(error)

    if all_errors:
        return all_errors


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


def create_new_hash(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


# ======================================================================
# Miscellaneous helpers
# ======================================================================

def redirect_to_allowed_dept(session, department_id, page):
    error_msg = ('You have been given admin access to this page, but you are not in any departments '
                 'that you can admin. Please contact STOPS to remedy this.')

    if c.DEFAULT_DEPARTMENT_ID == -1:
        raise HTTPRedirect('../accounts/homepage?message={}', "Please add at least one department to manage staffers.")
    if c.DEFAULT_DEPARTMENT_ID == 0:
        raise HTTPRedirect('../accounts/homepage?message={}', error_msg)

    if department_id == 'All':
        if len(c.ADMIN_DEPARTMENT_OPTS) == 1:
            raise HTTPRedirect('{}?department_id={}', page, c.DEFAULT_DEPARTMENT_ID)
        return

    if department_id is None and c.DEFAULT_DEPARTMENT_ID and len(c.ADMIN_DEPARTMENTS) < 5:
        raise HTTPRedirect('{}?department_id={}', page, c.DEFAULT_DEPARTMENT_ID)

    if not department_id:
        raise HTTPRedirect('{}?department_id=None', page)
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
        return 'Password must contain only letters, numbers, and the following symbols: ' + c.PASSWORD_SPECIAL_CHARS
    if 'lowercase_char' in c.PASSWORD_CONDITIONS and not re.search("[a-z]", password):
        return 'Password must contain at least one lowercase letter.'
    if 'uppercase_char' in c.PASSWORD_CONDITIONS and not re.search("[A-Z]", password):
        return 'Password must contain at least one uppercase letter.'
    if 'letter' in c.PASSWORD_CONDITIONS and not re.search("[A-Za-z]", password):
        return 'Password must contain at least one letter.'
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

class RegistrationCode():
    """
    A class that provides functions to manage human-readable unique codes that
    attendees can enter at registration, e.g., promo codes.
    """

    _AMBIGUOUS_CHARS = {
        '0': 'OQD',
        '1': 'IL',
        '2': 'Z',
        '5': 'S',
        '6': 'G',
        '8': 'B'}

    _UNAMBIGUOUS_CHARS = string.digits + string.ascii_uppercase
    for _, s in _AMBIGUOUS_CHARS.items():
        _UNAMBIGUOUS_CHARS = re.sub('[{}]'.format(s), '', _UNAMBIGUOUS_CHARS)
    
    @classmethod
    def sql_normalized_code(cls, code):
        return func.replace(func.replace(func.lower(code), '-', ''), ' ', '')
    
    @classmethod
    def _generate_code(cls, generator, model, count=None):
        """
        Helper method to limit collisions for the other generate() methods.

        Arguments:
            generator (callable): Function that returns a newly generated code.
            count (int): The number of codes to generate. If `count` is `None`,
                then a single code will be generated. Defaults to `None`.

        Returns:
            If an `int` value was passed for `count`, then a `list` of newly
            generated codes is returned. If `count` is `None`, then a single
            `str` is returned.
        """
        from uber.models import Session
        with Session() as session:
            # Kind of inefficient, but doing one big query for all the existing
            # codes will be faster than a separate query for each new code.
            old_codes = set(s for (s,) in session.query(model.code).all())

        # Set an upper limit on the number of collisions we'll allow,
        # otherwise this loop could potentially run forever.
        max_collisions = 100
        collisions = 0
        codes = set()
        while len(codes) < (1 if count is None else count):
            code = generator().strip()
            if not code:
                break
            if code in codes or code in old_codes:
                collisions += 1
                if collisions >= max_collisions:
                    break
            else:
                codes.add(code)
        return (codes.pop() if codes else None) if count is None else codes

    @classmethod
    def generate_random_code(cls, model, count=None, length=9, segment_length=3):
        """
        Generates a random promo code.

        With `length` = 12 and `segment_length` = 3::

            XXX-XXX-XXX-XXX

        With `length` = 6 and `segment_length` = 2::

            XX-XX-XX

        Arguments:
            count (int): The number of codes to generate. If `count` is `None`,
                then a single code will be generated. Defaults to `None`.
            length (int): The number of characters to use for the code.
            segment_length (int): The length of each segment within the code.

        Returns:
            If an `int` value was passed for `count`, then a `list` of newly
            generated codes is returned. If `count` is `None`, then a single
            `str` is returned.
        """

        # The actual generator function, called repeatedly by `_generate_code`
        def _generate_random_code():
            letters = ''.join(random.choice(cls._UNAMBIGUOUS_CHARS) for _ in range(length))
            return '-'.join(textwrap.wrap(letters, segment_length))

        return cls._generate_code(_generate_random_code, model, count=count)

    @classmethod
    def generate_word_code(cls, count=None):
        """
        Generates a promo code consisting of words from `PromoCodeWord`.

        Arguments:
            count (int): The number of codes to generate. If `count` is `None`,
                then a single code will be generated. Defaults to `None`.

        Returns:
            If an `int` value was passed for `count`, then a `list` of newly
            generated codes is returned. If `count` is `None`, then a single
            `str` is returned.
        """
        from uber.models import Session, PromoCodeWord
        with Session() as session:
            words = PromoCodeWord.group_by_parts_of_speech(
                session.query(PromoCodeWord).order_by(PromoCodeWord.normalized_word).all())

        # The actual generator function, called repeatedly by `_generate_code`
        def _generate_word_code():
            code_words = []
            for part_of_speech, _ in PromoCodeWord._PART_OF_SPEECH_OPTS:
                if words[part_of_speech]:
                    code_words.append(random.choice(words[part_of_speech]))
            return ' '.join(code_words)

        return cls._generate_code(_generate_word_code, count=count)

    @classmethod
    def disambiguate_code(cls, code):
        """
        Removes ambiguous characters in a promo code supplied by an attendee.

        Arguments:
            code (str): A promo code as typed by an attendee.

        Returns:
            str: A copy of `code` with all ambiguous characters replaced by
                their unambiguous equivalent.
        """
        code = cls.normalize_code(code)
        if not code:
            return ''
        for unambiguous, ambiguous in cls._AMBIGUOUS_CHARS.items():
            ambiguous_pattern = '[{}]'.format(ambiguous.lower())
            code = re.sub(ambiguous_pattern, unambiguous.lower(), code)
        return code

    @classmethod
    def normalize_code(cls, code):
        """
        Normalizes a promo code supplied by an attendee.

        Arguments:
            code (str): A promo code as typed by an attendee.

        Returns:
            str: A copy of `code` converted to all lowercase, with dashes ("-")
                and whitespace characters removed.
        """
        if not code:
            return ''
        return re.sub(r'[\s\-]+', '', code.lower())

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

    def __init__(self, slug, description, deadline, full_description='', name=None, path=None,
                 email_post_con=False, external_form_url=''):
        assert re.match('^[a-z0-9_]+$', slug), \
            'Dept Head checklist item sections must have separated_by_underscore names'

        self.slug, self.description = slug, description
        self.full_description, self.external_form_url = full_description, external_form_url
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
    if c.SEND_EMAILS and not c.DEV_BOX:
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
    protocol = 'https' if 'https' in server or 'http' not in server else 'http'
    host, _, path = urllib.parse.unquote(server
                                         ).replace('http://', '').replace('https://', '').rstrip('/').partition('/')
    if path.startswith('reggie'):
        return f'{protocol}://{host}/reggie'
    elif path.startswith('uber'):
        return f'{protocol}://{host}/uber'
    elif path in ['uber', 'rams']:
        f'{protocol}://{host}/{path}'
    return f'{protocol}://{host}'


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
    import ssl

    target_url, target_host, remote_api_token = _format_import_params(target_server, api_token)
    uri = '{}/jsonrpc/'.format(target_url)

    message, service = '', None
    if target_server or api_token:
        if not remote_api_token:
            message = 'No API token given and could not find a token for: {}'.format(target_host)
        elif not target_url:
            message = 'Unrecognized hostname: {}'.format(target_server)

        if not message:
            service = ServerProxy(uri=uri, extra_headers={'X-Auth-Token': remote_api_token},
                                  ssl_opts={'ssl_version': ssl.PROTOCOL_SSLv23})

    return service, message, target_url


def prepare_saml_request(request):
    saml_request = {
        'http_host': request.headers.get('Host', ''),
        'script_name': request.script_name + request.path_info,
        'get_data': request.params.copy() if request.method == 'GET' else {},
        'post_data': request.params.copy() if request.method == 'POST' else {},
    }

    if c.FORCE_SAML_HTTPS:
        saml_request['https'] = 'on'
    return saml_request


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
        rows = [list(map(str, row)) for row in rows]

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


"""
class OAuthRequest:
    This class is not currently in use, but kept in case we want to re-add integration with Auth0.
    If we need it, re-add the Authlib library so you can import OAuth2Session.

    def __init__(self, scope='openid profile email', state=None):
        self.redirect_uri = (c.REDIRECT_URL_BASE or c.URL_BASE) + "/accounts/"
        self.client = OAuth2Session(c.AUTH_CLIENT_ID, c.AUTH_CLIENT_SECRET, scope=scope, state=state,
                                    redirect_uri=self.redirect_uri + "process_login")
        self.state = state if state else None

    def set_auth_url(self):
        self.auth_uri, self.state = self.client.create_authorization_url("https://{}/authorize".format(c.AUTH_DOMAIN),
                                                                         self.state)

    def set_token(self, code, state):
        self.auth_token = self.client.fetch_token("https://{}/oauth/token".format(c.AUTH_DOMAIN),
                                                  code=code, state=state).get('access_token')

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
"""


class SignNowRequest:
    def __init__(self, session, group=None, ident='', create_if_none=False):
        self.group = group
        self.group_leader_name = ''
        self.document = None
        self.access_token = None
        self.error_message = ''

        self.set_access_token()
        if self.error_message:
            log.error(self.error_message)
            return

        from uber.models import SignedDocument

        if group:
            self.document = session.query(SignedDocument).filter_by(model="Group", fk_id=group.id).first()

            if not self.document and create_if_none:
                self.document = SignedDocument(fk_id=group.id, model="Group", ident=ident)
                first_name = group.leader.first_name if group.leader else ''
                last_name = group.leader.last_name if group.leader else ''
                self.group_leader_name = first_name + ' ' + last_name

            if self.document and not self.document.document_id:
                self.document.document_id = self.create_document(
                    template_id=c.SIGNNOW_DEALER_TEMPLATE_ID,
                    doc_title="MFF {} Dealer Terms - {}".format(c.EVENT_YEAR, group.name),
                    folder_id=c.SIGNNOW_DEALER_FOLDER_ID,
                    uneditable_texts_list=group.signnow_texts_list,
                    fields={} if c.SIGNNOW_ENV == 'eval' else {'printed_name': self.group_leader_name})

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

        if c.DEV_BOX and c.SIGNNOW_USERNAME and c.SIGNNOW_PASSWORD:
            access_request = signnow_sdk.OAuth2.request_token(c.SIGNNOW_USERNAME, c.SIGNNOW_PASSWORD, '*')
            if 'error' in access_request:
                self.error_message = ("Error getting access token from SignNow using username and passsword: " +
                                      access_request['error'])
            else:
                self.access_token = access_request['access_token']
                return
        elif not aws_secrets_client:
            self.error_message = ("Couldn't get a SignNow access token because there was no AWS Secrets client. "
                                  "If you're on a development box, you can instead use a username and password.")
        elif not c.AWS_SIGNNOW_SECRET_NAME:
            self.error_message = ("Couldn't get a SignNow access token because the secret name is not set. "
                                  "If you're on a development box, you can instead use a username and password.")
        else:
            aws_secrets_client.get_signnow_secret()
            self.access_token = c.SIGNNOW_ACCESS_TOKEN
            return

    def create_document(self, template_id, doc_title, folder_id='', uneditable_texts_list=None, fields={}):
        from requests import put
        from json import dumps, loads

        self.set_access_token(refresh=True)
        if not self.error_message:
            document_request = signnow_sdk.Template.copy(self.access_token, template_id, doc_title)

            if 'error' in document_request:
                self.error_message = (f"Error creating document from template with token {self.access_token}: " +
                                      document_request['error'])

        if self.error_message:
            return None

        if uneditable_texts_list:
            response = put(signnow_sdk.Config().get_base_url() + '/document/' +
                           document_request.get('id'), headers=self.api_call_headers,
                           data=dumps({
                               "texts": uneditable_texts_list,
                               }))
            edit_request = loads(response.content)

            if 'errors' in edit_request:
                self.error_message = "Error setting up uneditable text fields: " + '; '.join(
                    [e['message'] for e in edit_request['errors']])
                return None

        if fields:
            response = put(signnow_sdk.Config().get_base_url() + '/v2/documents/' +
                           document_request.get('id') + '/prefill-texts', headers=self.api_call_headers,
                           data=dumps({
                               "fields": [{"field_name": field, "prefilled_text": name}
                                          for field, name in fields.items()],
                                          }))
            if response.status_code != 204:
                fields_request = response.json()

                if 'errors' in fields_request:
                    self.error_message = "Error setting up fields: " + '; '.join(
                        [e['message'] for e in fields_request['errors']])
                    return None

        if folder_id:
            result = signnow_sdk.Document.move(self.access_token,
                                               document_request.get('id', ''),
                                               folder_id)
            if 'error' in result:
                self.error_message = "Error moving document into folder: " + result['error']
                # Give the document request back anyway

        return document_request.get('id')

    def get_doc_signed_timestamp(self):
        if not self.document:
            self.error_message = "Tried to get a signed timestamp without a document attached to the request!"
            return

        details = self.get_document_details()
        if details and details.get('signatures'):
            return details['signatures'][0].get('created')

    def create_dealer_signing_link(self):
        if not self.group:
            self.error_message = "Tried to send a dealer signing link without a group attached to the request!"
            return
        if not self.document:
            self.error_message = "Tried to send a dealer signing link without a document attached to the request!"
            return

        first_name = self.group.leader.first_name if self.group.leader else ''
        last_name = self.group.leader.last_name if self.group.leader else ''

        if self.document.document_id and not self.document.signed:
            link = self.get_signing_link(first_name,
                                         last_name,
                                         (c.REDIRECT_URL_BASE or c.URL_BASE) + '/preregistration/group_members?id={}'
                                         .format(self.group.id))
            return link

    def get_signing_link(self, first_name="", last_name="", redirect_uri=""):
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

        if not self.document:
            self.error_message = "Tried to send a signing link without a document attached to the request!"
            return

        response = post(signnow_sdk.Config().get_base_url() + '/link', headers=self.api_call_headers,
                        data=dumps({
                            "document_id": self.document.document_id,
                            "firstname": first_name,
                            "lastname": last_name,
                            "redirect_uri": redirect_uri
                            }))
        signing_request = loads(response.content)
        if 'errors' in signing_request:
            self.error_message = "Error getting signing link: " + '; '.join(
                [e['message'] for e in signing_request['errors']])
        else:
            return signing_request.get('url_no_signup')

    def send_dealer_signing_invite(self):
        from uber.custom_tags import email_only
        if not self.group:
            self.error_message = "Tried to send a dealer signing invite without a group attached to the request!"
            return

        invite_payload = {
            "to": [
                {"email": self.group.email, "prefill_signature_name": self.group_leader_name,
                 "role": "Dealer", "order": 1}
            ],
            "from": email_only(c.MARKETPLACE_EMAIL),
            "cc": [],
            "subject": f"ACTION REQUIRED: {c.EVENT_NAME} {c.DEALER_TERM.title()} Terms and Conditions",
            "message": (f"Congratulations on being accepted into the {c.EVENT_NAME} {c.DEALER_LOC_TERM.title()}! "
                        "Please click the button below to review and sign the terms and conditions. "
                        "You MUST sign this in order to complete your registration."),
            "redirect_uri": "{}/preregistration/group_members?id={}".format(c.REDIRECT_URL_BASE or c.URL_BASE,
                                                                            self.group.id)
            }

        invite_request = signnow_sdk.Document.invite(self.access_token, self.document.document_id, invite_payload)

        if 'error' in invite_request:
            self.error_message = "Error sending invite to sign: " + invite_request['error']
        else:
            return invite_request

    def get_download_link(self):
        if not self.document:
            self.error_message = "Tried to get a download link from a request without a document!"
            return

        download_request = signnow_sdk.Document.download_link(self.access_token, self.document.document_id)

        if 'error' in download_request:
            self.error_message = "Error getting download link: " + download_request['error']
        else:
            return download_request.get('link')

    def get_document_details(self):
        if not self.document:
            self.error_message = "Tried to get document details from a request without a document!"
            return

        document_request = signnow_sdk.Document.get(self.access_token, self.document.document_id)

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
            badge_type = int(import_job.json_data.get('badge_type', c.ATTENDEE_BADGE))
            badge_status = int(import_job.json_data.get('badge_status', c.NEW_STATUS))
            extra_admin_notes = import_job.json_data.get('admin_notes', '')

            if badge_type not in c.BADGES:
                errors.append("ERROR: Attendee badge type not recognized: " + str(badge_type))

            try:
                results = service.attendee.export(import_job.query, True)
            except Exception as ex:
                errors.append(str(ex))
            else:
                num_attendees = len(results.get('attendees', []))
                if num_attendees != 1:
                    errors.append("ERROR: We expected one attendee for this query, "
                                  f"but got {str(num_attendees)} instead.")

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
            old_admin_notes = ('Old Admin Notes:\n{}\n'.format(attendee['admin_notes'])
                               if attendee['admin_notes'] else '')

            attendee.update({
                'badge_type': badge_type,
                'badge_status': badge_status,
                'paid': paid,
                'placeholder': True,
                'admin_notes': 'Imported {} from {}{}{}'.format(
                    badge_label, import_from_url, new_admin_notes, old_admin_notes),
                'past_years': attendee['all_years'],
            })
            if attendee['shirt'] not in c.SHIRT_OPTS:
                del attendee['shirt']

            del attendee['id']
            del attendee['all_years']
            del attendee['badge_num']

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
                requested_depts = {d[0]: d[1] for d in map(partial(TaskUtils._guess_dept, session),
                                                           requested_depts.items()) if d}

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

                account = session.query(AttendeeAccount).filter(
                    AttendeeAccount.normalized_email == normalize_email_legacy(account_to_import['email'])).first()
                if not account:
                    del account_to_import['id']
                    account = AttendeeAccount().apply(account_to_import, restricted=False)
                    account.email = normalize_email(account.email)
                    account.imported = True
                    session.add(account)
                attendee.managers.append(account)

            from sqlalchemy.exc import IntegrityError
            from psycopg2.errors import UniqueViolation

            try:
                session.commit()
            except IntegrityError as e:
                session.rollback()
                if isinstance(e.orig, UniqueViolation):
                    attendee.badge_num = None
                    session.add(attendee)
                    try:
                        session.commit()
                    except Exception as e:
                        session.rollback()
                        import_job.errors += "; {}".format(str(e)) if import_job.errors else str(e)
                else:
                    session.rollback()
                    import_job.errors += "; {}".format(str(e)) if import_job.errors else str(e)
            except Exception as e:
                session.rollback()
                import_job.errors += "; {}".format(str(e)) if import_job.errors else str(e)
            else:
                import_job.completed = datetime.now()
            session.commit()

    @staticmethod
    def get_attendee_account_by_id(account_id, service):
        try:
            results = service.attendee_account.export(account_id, False)
        except Exception as ex:
            raise ex
        else:
            num_accounts = len(results.get('accounts', []))
            if num_accounts != 1:
                raise Exception(f"ERROR: We expected one account for this query, but got {str(num_accounts)} instead.")

        return results.get('accounts', [])[0]

    @staticmethod
    def basic_attendee_import(attendee):
        from uber.models import Attendee
        attendee.update({
            'badge_status': c.IMPORTED_STATUS,
            'badge_num': None,
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

            try:
                account_to_import = TaskUtils.get_attendee_account_by_id(import_job.query, service)
            except Exception as ex:
                import_job.errors += "; {}".format("; ".join(str(ex))) if import_job.errors else "; ".join(str(ex))
                session.commit()
                return

            if c.SSO_EMAIL_DOMAINS:
                local, domain = normalize_email(account_to_import['email'], split_address=True)
                if domain in c.SSO_EMAIL_DOMAINS:
                    log.debug(f"Skipping account import for {account_to_import['email']} "
                              "as it matches the SSO email domain.")
                    import_job.completed = datetime.now()
                    return

            account = session.query(AttendeeAccount).filter(
                AttendeeAccount.normalized_email == normalize_email_legacy(account_to_import['email'])).first()
            if not account:
                del account_to_import['id']
                account = AttendeeAccount().apply(account_to_import, restricted=False)
                account.email = normalize_email(account.email)
                account.imported = True
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
            except Exception:
                pass

            for attendee in account_attendees:
                if attendee.get('badge_num', 0) in range(c.BADGE_RANGES[c.STAFF_BADGE][0],
                                                         c.BADGE_RANGES[c.STAFF_BADGE][1]):
                    if not c.SSO_EMAIL_DOMAINS:
                        # Try to match staff to their existing badge, which would be newer than the one we're importing
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
                    # If SSO is used for attendee accounts, we don't import staff at all
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

        from uber.models import AttendeeAccount, Group

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
                    errors.append(f"ERROR: We expected one group for this query, but got {str(num_groups)} instead.")

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
                        import_job.errors += "; {}".format("; ".join(str(ex)))\
                            if import_job.errors else "; ".join(str(ex))

                    account = session.query(AttendeeAccount).filter(
                        AttendeeAccount.normalized_email == normalize_email_legacy(account_to_import['email'])).first()
                    if not account:
                        del account_to_import['id']
                        account = AttendeeAccount().apply(account_to_import, restricted=False)
                        account.email = normalize_email(account.email)
                        account.imported = True
                        session.add(account)
                    new_attendee.managers.append(account)

                session.add(new_attendee)

                try:
                    session.commit()
                except Exception as ex:
                    import_job.errors += "; {}".format(str(ex)) if import_job.errors else str(ex)
                    session.rollback()

            session.assign_badges(new_group, group_to_import['badges'], group_results['unassigned_badge_type'],
                                  group_results['unassigned_ribbon'])
            session.commit()
