import cgi
import csv
import functools
import inspect
import json
import os
import re
import threading
import traceback
import uuid
import zipfile
from collections import defaultdict, OrderedDict
from datetime import datetime
from functools import wraps
from io import StringIO, BytesIO
from itertools import count
from threading import RLock

import cherrypy
import six
import xlsxwriter
from pockets import argmod, unwrap
from pockets.autolog import log
from sideboard.lib import profile, serializer

import uber
from uber.barcode import get_badge_num_from_barcode
from uber.config import c
from uber.errors import CSRFException, HTTPRedirect
from uber.jinja import JinjaEnv
from uber.utils import check_csrf, report_critical_exception, ExcelWorksheetStreamWriter


def swallow_exceptions(func):
    """
    Don't allow ANY Exceptions to be raised from this.
    Use this ONLY where it's absolutely needed, such as dealing with locking functionality.
    WARNING: DO NOT USE THIS UNLESS YOU KNOW WHAT YOU'RE DOING :)
    """
    @wraps(func)
    def swallow_exception(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception:
            log.error('Unexpected error', exc_info=True)
    return swallow_exception


def log_pageview(func):
    @wraps(func)
    def with_check(*args, **kwargs):
        with uber.models.Session() as session:
            try:
                session.admin_account(cherrypy.session.get('account_id'))
            except Exception:
                pass  # we don't care about public pages for this version
            else:
                uber.models.PageViewTracking.track_pageview()
        return func(*args, **kwargs)
    return with_check


def redirect_if_at_con_to_kiosk(func):
    @wraps(func)
    def with_check(*args, **kwargs):
        if c.AT_THE_CON and c.KIOSK_REDIRECT_URL:
            raise HTTPRedirect(c.KIOSK_REDIRECT_URL)
        return func(*args, **kwargs)
    return with_check


def check_if_can_reg(func):
    @wraps(func)
    def with_check(*args, **kwargs):
        is_dealer_get = c.HTTP_METHOD == 'GET' \
                        and c.PAGE_PATH in ['/preregistration/dealer_registration', '/preregistration/post_dealer']
        is_dealer_post = c.HTTP_METHOD == 'POST' and \
            int(kwargs.get('badge_type', 0)) == c.PSEUDO_DEALER_BADGE and \
            int(kwargs.get('tables', 0)) > 0
        is_dealer_reg = is_dealer_get or is_dealer_post

        if c.DEV_BOX:
            pass  # Don't redirect to any of the pages below.
        elif is_dealer_reg and not c.DEALER_REG_OPEN:
            if c.AFTER_DEALER_REG_START:
                return render('static_views/dealer_reg_closed.html')
            else:
                return render('static_views/dealer_reg_not_open.html')
        elif not c.ATTENDEE_BADGE_AVAILABLE:
            return render('static_views/prereg_soldout.html')
        elif c.BEFORE_PREREG_OPEN and not is_dealer_reg:
            return render('static_views/prereg_not_yet_open.html')
        elif c.AFTER_PREREG_TAKEDOWN and not c.AT_THE_CON:
            return render('static_views/prereg_closed.html')
        return func(*args, **kwargs)
    return with_check


def check_for_encrypted_badge_num(func):
    """
    On some pages, we pass a 'badge_num' parameter that might EITHER be a literal
    badge number or an encrypted value (i.e., from a barcode scanner). This
    decorator searches for a 'badge_num' parameter and decrypts it if necessary.
    """

    @wraps(func)
    def with_check(*args, **kwargs):
        if kwargs.get('badge_num', None):
            try:
                int(kwargs['badge_num'])
            except Exception:
                kwargs['badge_num'] = get_badge_num_from_barcode(barcode_num=kwargs['badge_num'])['badge_num']
        return func(*args, **kwargs)

    return with_check


def site_mappable(func):
    func.site_mappable = True
    return func


def suffix_property(func):
    func._is_suffix_property = True
    return func


def _suffix_property_check(inst, name):
    if not name.startswith('_'):
        suffix = '_' + name.rsplit('_', 1)[-1]
        prop_func = getattr(inst, suffix, None)
        if getattr(prop_func, '_is_suffix_property', False):
            field_name = name[:-len(suffix)]
            field_val = getattr(inst, field_name)
            return prop_func(field_name, field_val)


suffix_property.check = _suffix_property_check


department_id_adapter = argmod(['location', 'department', 'department_id'], lambda d: uber.models.Department.to_id(d))


@department_id_adapter
def check_can_edit_dept(session, department_id=None, inherent_role=None, override_access=None):
    from uber.models import AdminAccount, DeptMembership, Department
    account_id = cherrypy.session.get('account_id')
    admin_account = session.query(AdminAccount).get(account_id)
    if not getattr(admin_account, override_access, None):
        dh_filter = [
            AdminAccount.id == account_id,
            AdminAccount.attendee_id == DeptMembership.attendee_id]
        if inherent_role in ('dept_head', 'poc', 'checklist_admin'):
            role_attr = 'is_{}'.format(inherent_role)
            dh_filter.append(getattr(DeptMembership, role_attr) == True)  # noqa: E712
        else:
            dh_filter.append(DeptMembership.has_inherent_role)

        if department_id:
            dh_filter.append(DeptMembership.department_id == department_id)

        is_dept_admin = session.query(AdminAccount).filter(*dh_filter).first()
        if not is_dept_admin:
            if department_id:
                department = session.query(Department).get(department_id)
                dept_msg = ' of {}'.format(department.name)
            else:
                dept_msg = ''
            return 'You must be a department admin{} to complete that action.'.format(dept_msg)


def check_dept_admin(session, department_id=None, inherent_role=None):
    return check_can_edit_dept(session, department_id, inherent_role, override_access='full_dept_admin')


def requires_admin(func=None, inherent_role=None, override_access=None):
    def _decorator(func, inherent_role=inherent_role):
        @wraps(func)
        def _protected(*args, **kwargs):
            if cherrypy.request.method == 'POST':
                department_id = kwargs.get(
                    'department_id', kwargs.get('department', kwargs.get('location', kwargs.get('id'))))

                with uber.models.Session() as session:
                    message = check_can_edit_dept(session, department_id, inherent_role, override_access)
                    if message:
                        raise HTTPRedirect('../landing/invalid?message={}'.format(message))
            return func(*args, **kwargs)
        return _protected

    if func is None or isinstance(func, six.string_types):
        return functools.partial(_decorator, inherent_role=func)
    else:
        return _decorator(func)


def requires_dept_admin(func=None, inherent_role=None):
    return requires_admin(func, inherent_role, override_access='full_dept_admin')


def requires_shifts_admin(func=None, inherent_role=None):
    return requires_admin(func, inherent_role, override_access='full_shifts_admin')


def csrf_protected(func):
    @wraps(func)
    def protected(*args, csrf_token, **kwargs):
        check_csrf(csrf_token)
        return func(*args, **kwargs)
    return protected


def ajax(func):
    """decorator for Ajax POST requests which require a CSRF token and return JSON"""
    @wraps(func)
    def returns_json(*args, **kwargs):
        cherrypy.response.headers['Content-Type'] = 'application/json'
        assert cherrypy.request.method == 'POST', 'POST required, got {}'.format(cherrypy.request.method)
        check_csrf(kwargs.pop('csrf_token', None))
        return json.dumps(func(*args, **kwargs), cls=serializer).encode('utf-8')
    returns_json.ajax = True
    return returns_json


def ajax_gettable(func):
    """
    Decorator for page handlers which return JSON.  Unlike the above @ajax decorator,
    this allows either GET or POST and does not check for a CSRF token, so this can
    be used for pages which supply data to external APIs as well as pages used for
    periodically polling the server for new data by our own Javascript code.
    """
    @wraps(func)
    def returns_json(*args, **kwargs):
        cherrypy.response.headers['Content-Type'] = 'application/json'
        return json.dumps(func(*args, **kwargs), cls=serializer).encode('utf-8')
    return returns_json


def multifile_zipfile(func):
    parameters = inspect.getargspec(func)
    if len(parameters[0]) == 3:
        func.site_mappable = True

    @wraps(func)
    def zipfile_out(self, session, **kwargs):
        zipfile_writer = BytesIO()
        with zipfile.ZipFile(zipfile_writer, mode='w') as zip_file:
            func(self, zip_file, session, **kwargs)

        # must do this after creating the zip file as other decorators may have changed this
        # for example, if a .zip file is created from several .csv files, they may each set content-type.
        cherrypy.response.headers['Content-Type'] = 'application/zip'
        cherrypy.response.headers['Content-Disposition'] = 'attachment; filename=' + func.__name__ + '.zip'

        return zipfile_writer.getvalue()
    return zipfile_out


def _set_response_filename(base_filename):
    """
    Set the correct headers when outputting CSV files to specify the filename the browser should use
    """
    header = cherrypy.response.headers.get('Content-Disposition', '')
    if not header or 'filename=' not in header:
        cherrypy.response.headers['Content-Disposition'] = 'attachment; filename=' + base_filename


def xlsx_file(func):
    parameters = inspect.getargspec(func)
    if len(parameters[0]) == 3:
        func.site_mappable = True

    func.output_file_extension = 'xlsx'

    @wraps(func)
    def xlsx_out(self, session, set_headers=True, **kwargs):
        rawoutput = BytesIO()

        # Even though the final file will be in memory the module uses temp
        # files during assembly for efficiency. To avoid this on servers that
        # don't allow temp files, for example the Google APP Engine, set the
        # 'in_memory' constructor option to True:
        with xlsxwriter.Workbook(rawoutput, {'in_memory': False}) as workbook:
            worksheet = workbook.add_worksheet()

            writer = ExcelWorksheetStreamWriter(workbook, worksheet)

            # right now we just pass in the first worksheet.
            # in the future, could pass in the workbook too
            func(self, writer, session, **kwargs)

        output = rawoutput.getvalue()

        # set headers last in case there were errors, so end user still see error page
        if set_headers:
            cherrypy.response.headers['Content-Type'] = \
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            _set_response_filename(func.__name__ + '.xlsx')

        return output
    return xlsx_out


def csv_file(func):
    parameters = inspect.getargspec(func)
    if len(parameters[0]) == 3:
        func.site_mappable = True

    func.output_file_extension = 'csv'

    @wraps(func)
    def csvout(self, session, set_headers=True, **kwargs):
        writer = StringIO()
        func(self, csv.writer(writer), session, **kwargs)
        output = writer.getvalue().encode('utf-8')

        # set headers last in case there were errors, so end user still see error page
        if set_headers:
            cherrypy.response.headers['Content-Type'] = 'application/csv'
            _set_response_filename(func.__name__ + '.csv')

        return output
    return csvout


def set_csv_filename(func):
    """
    Use this to override CSV filenames, useful when working with aliases and redirects to make it print the correct name
    """
    @wraps(func)
    def change_filename(self, override_filename=None, *args, **kwargs):
        out = func(self, *args, **kwargs)
        _set_response_filename((override_filename or func.__name__) + '.csv')
        return out
    return change_filename


def check_shutdown(func):
    @wraps(func)
    def with_check(self, *args, **kwargs):
        if c.UBER_SHUT_DOWN or c.AT_THE_CON:
            raise HTTPRedirect('index?message={}', 'The page you requested is only available pre-event.')
        else:
            return func(self, *args, **kwargs)
    return with_check


def credit_card(func):
    @wraps(func)
    def charge(self, session, payment_id=None, stripeToken=None, stripeEmail='ignored', **ignored):
        log.debug('PAYMENT: payment_id={}, stripeToken={}', payment_id or 'NONE', stripeToken or 'NONE')

        if ignored:
            log.debug('PAYMENT: received unexpected stripe parameters: {}', ignored)

        try:
            try:
                return func(self, session=session, payment_id=payment_id, stripeToken=stripeToken)
            except HTTPRedirect:
                # Paranoia: we want to try commiting while we're INSIDE of the
                # @credit_card decorator to ensure that we catch any database
                # errors (like unique constraint violations). We have to wrap
                # this try-except inside another try-except because we want
                # to re-raise the HTTPRedirect, and also have unexpected DB
                # exceptions caught by the outermost exception handler.
                session.commit()
                raise
        except HTTPRedirect:
            raise
        except Exception:
            error_text = \
                'Got an error while calling charge' \
                '(self, payment_id={!r}, stripeToken={!r}, ignored={}):\n{}\n\n' \
                'IMPORTANT: This could have resulted in an attendee paying and not being ' \
                'marked as paid in the database. Definitely double check this.'\
                .format(payment_id, stripeToken, ignored, traceback.format_exc())

            report_critical_exception(msg=error_text, subject='ERROR: MAGFest Stripe error (Automated Message)')
            return traceback.format_exc()
    return charge


def cached(func):
    func.cached = True
    return func


def cached_page(func):
    innermost = unwrap(func)
    if hasattr(innermost, 'cached'):
        from sideboard.lib import config as sideboard_config
        func.lock = RLock()

        @wraps(func)
        def with_caching(*args, **kwargs):
            fpath = os.path.join(sideboard_config['root'], 'data', func.__module__ + '.' + func.__name__)
            with func.lock:
                if not os.path.exists(fpath) or datetime.now().timestamp() - os.stat(fpath).st_mtime > 60 * 15:
                    contents = func(*args, **kwargs)
                    with open(fpath, 'wb') as f:
                        # Try to write assuming content is a byte first, then try it as a string
                        try:
                            f.write(contents)
                        except Exception:
                            f.write(bytes(contents, 'UTF-8'))
                with open(fpath, 'rb') as f:
                    return f.read()
        return with_caching
    else:
        return func


def run_threaded(thread_name='', lock=None, blocking=True, timeout=-1):
    """
    Decorate a function to run in a new thread and return immediately.

    The thread name can be passed in as an argument::

        @run_threaded('My Background Task')
        def background_task():
            # do some stuff ...
            pass

    Or it can be used as a bare decorator, and the function name will be used
    as the thread name::

        @run_threaded
        def background_task():
            # do some stuff ...
            pass

    Additionally, a lock can be passed in to lock the thread during the
    function call, for example::

        @run_threaded('My Background Task', lock=threading.RLock(), blocking=False)
        def background_task():
            # do some stuff ...
            pass

    """
    def run_threaded_decorator(func):
        name = thread_name if thread_name else '{}.{}'.format(func.__module__, func.__name__)

        @wraps(func)
        def with_run_threaded(*args, **kwargs):
            if lock:
                @wraps(func)
                def locked_func(*a, **kw):
                    if lock.acquire(blocking=blocking, timeout=timeout):
                        try:
                            return func(*a, **kw)
                        finally:
                            lock.release()
                    else:
                        log.warn("Can't acquire lock, skipping background thread: {}".format(name))
                thread = threading.Thread(target=locked_func, *args, **kwargs)
            else:
                thread = threading.Thread(target=func, *args, **kwargs)
            thread.name = name
            log.debug('Starting background thread: {}'.format(name))
            thread.start()
        return with_run_threaded

    if callable(thread_name):
        func = thread_name
        thread_name = '{}.{}'.format(func.__module__, func.__name__)
        return run_threaded_decorator(func)
    else:
        return run_threaded_decorator


def timed(prepend_text=''):
    def timed_decorator(func):
        @wraps(func)
        def with_timed(*args, **kwargs):
            before = datetime.now()
            try:
                return func(*args, **kwargs)
            finally:
                log.debug('{}{}.{} loaded in {} seconds'.format(
                    prepend_text,
                    func.__module__,
                    func.__name__,
                    (datetime.now() - before).total_seconds()))
        return with_timed

    if callable(prepend_text):
        func = prepend_text
        prepend_text = ''
        return timed_decorator(func)
    else:
        return timed_decorator


def sessionized(func):
    innermost = unwrap(func)
    if 'session' not in inspect.getfullargspec(innermost).args:
        return func

    @wraps(func)
    def with_session(*args, **kwargs):
        with uber.models.Session() as session:
            try:
                retval = func(*args, session=session, **kwargs)
                session.expunge_all()
                return retval
            except HTTPRedirect:
                session.commit()
                raise
    return with_session


def renderable_data(data=None):
    data = data or {}
    data['c'] = c
    data.update({m.__name__: m for m in uber.models.Session.all_models()})
    return data


# render using the first template that actually exists in template_name_list
def render(template_name_list, data=None, encoding='utf-8'):
    data = renderable_data(data)
    env = JinjaEnv.env()
    template = env.get_or_select_template(template_name_list)
    rendered = template.render(data)
    if encoding:
        return rendered.encode(encoding)
    return rendered


def render_empty(template_name_list):
    env = JinjaEnv.env()
    template = env.get_or_select_template(template_name_list, use_request_cache=False)
    return open(template.filename, 'rb').read().decode('utf-8')


def get_module_name(class_or_func):
    return class_or_func.__module__.split('.')[-1]


def _get_template_filename(func):
    return os.path.join(get_module_name(func), func.__name__ + '.html')


def prettify_breadcrumb(str):
    return str.replace('_', ' ').title()


def _remove_tracking_params(kwargs):
    for param in c.TRACKING_PARAMS:
        kwargs.pop(param, None)


def renderable(func):
    @wraps(func)
    def with_rendering(*args, **kwargs):
        _remove_tracking_params(kwargs)
        try:
            result = func(*args, **kwargs)
        except CSRFException as e:
            message = "Your CSRF token is invalid. Please go back and try again."
            uber.server.log_exception_with_verbose_context(msg=str(e))
            raise HTTPRedirect("../landing/invalid?message={}", message)
        except (AssertionError, ValueError) as e:
            message = str(e)
            uber.server.log_exception_with_verbose_context(msg=message)
            raise HTTPRedirect("../landing/invalid?message={}", message)
        except TypeError as e:
            # Very restrictive pattern so we don't accidentally match legit errors
            pattern = r"^{}\(\) missing 1 required positional argument: '\S*?id'$".format(func.__name__)
            if re.fullmatch(pattern, str(e)):
                # NOTE: We are NOT logging the exception if the user entered an invalid URL
                message = 'Looks like you tried to access a page without all the query parameters. '\
                          'Please go back and try again.'
                raise HTTPRedirect("../landing/invalid?message={}", message)
            else:
                raise

        else:
            try:
                func_name = func.__name__
                result['breadcrumb_page_pretty_'] = prettify_breadcrumb(func_name) if func_name != 'index' else 'Home'
                result['breadcrumb_page_'] = func_name if func_name != 'index' else ''
            except Exception:
                pass

            try:
                result['breadcrumb_section_pretty_'] = prettify_breadcrumb(get_module_name(func))
                result['breadcrumb_section_'] = get_module_name(func)
            except Exception:
                pass

            if c.UBER_SHUT_DOWN and not cherrypy.request.path_info.startswith('/schedule'):
                return render('closed.html')
            elif isinstance(result, dict):
                return render(_get_template_filename(func), result)
            else:
                return result

    return with_rendering


def public(func):
    func.public = True
    return func

def attendee_view(func):
    func.public = True
    @wraps(func)
    def with_check(*args, **kwargs):
        if cherrypy.session.get('account_id') is None:
                raise HTTPRedirect('../accounts/login?message=You+are+not+logged+in', save_location=True)
            
        if kwargs.get('id') != "None":
            with uber.models.Session() as session:
                attendee = session.attendee(kwargs.get('id'), allow_invalid=True)
                if not session.admin_can_see_staffer(attendee) and attendee not in session.viewable_attendees():
                    return "<div id='attendeeData' style='padding: 10px;'>" \
                           "You are not allowed to view this attendee. If you think this is an error, " \
                           "please email us at {}.</div>".format(cgi.escape(c.DEVELOPER_EMAIL))
        return func(*args, **kwargs)
    return with_check

def schedule_view(func):
    func.public = True
    @wraps(func)
    def with_check(*args, **kwargs):
        if c.HIDE_SCHEDULE and not c.HAS_READ_ACCESS:
            return "The {} schedule is being developed and will be made public " \
                   "when it's closer to being finalized.".format(c.EVENT_NAME)
        return func(*args, **kwargs)
    return with_check

def restricted(func):
    @wraps(func)
    def with_restrictions(*args, **kwargs):
        if not func.public:
            if c.PATH == 'staffing':
                if not cherrypy.session.get('staffer_id'):
                    raise HTTPRedirect('../staffing/login?message=You+are+not+logged+in', save_location=True)

            elif cherrypy.session.get('account_id') is None:
                raise HTTPRedirect('../accounts/login?message=You+are+not+logged+in', save_location=True)

            elif c.PATH == 'mivs_judging':
                if not uber.models.AdminAccount.is_mivs_judge_or_admin:
                    return 'You need to be a MIVS Judge or have access for either {} or {}'.format(c.PATH, c.PAGE_PATH)

            else:
                if not c.has_section_or_page_access(include_read_only=True):
                    return 'You need access for either {} or {}.'.format(c.PATH, c.PAGE_PATH)

        return func(*args, **kwargs)
    return with_restrictions


def set_renderable(func, public):
    """
    Return a function that is flagged correctly and is ready to be called by cherrypy as a request
    """
    func.public = getattr(func, 'public', public)
    new_func = profile(timed(cached_page(sessionized(restricted(renderable(func))))))
    new_func.exposed = True
    return new_func


class all_renderable:
    def __init__(self, public=False):
        self.public = public

    def __call__(self, klass):
        if self.public:
            klass = public(klass)
        for name, func in klass.__dict__.items():
            if hasattr(func, '__call__'):
                new_func = set_renderable(func, self.public)
                setattr(klass, name, new_func)
        return klass


class Validation:
    def __init__(self):
        self.validations = defaultdict(OrderedDict)

    def __getattr__(self, model_name):
        def wrapper(func):
            self.validations[model_name][func.__name__] = func
            return func
        return wrapper


validation, prereg_validation = Validation(), Validation()


adjustment_counter = count().__next__


def presave_adjustment(func):
    """
    Decorate methods on a model class with this decorator to ensure that the
    method is called immediately before the model is saved so that you can
    make any adjustments, e.g. setting a ribbon based on other information.
    """
    func.presave_adjustment = adjustment_counter()
    return func


def predelete_adjustment(func):
    """
    Decorate methods on a model class with this decorator to ensure that the
    method is called immediately before the model is deleted, e.g. to shift
    badges around the now-open slot.
    """
    func.predelete_adjustment = adjustment_counter()
    return func


class cost_property(property):
    """
    Different events have extra things they charge money for to attendees and
    groups.  Those events can use the @Session.model_mixin decorator and then
    define a @cost_property which returns the amount added.  For example, we
    have code in the MAGStock repo which looks vaguely like this:

        @Session.model_mixin
        class Attendee:
            purchased_food = Column(Boolean, default=False)

            @cost_property
            def food_price(self):
                return c.FOOD_PRICE if self.purchased_food else 0
    """


def create_redirect(url, public=False):
    """
    Return a function which redirects to the given url when called.
    """
    def redirect(self):
        raise HTTPRedirect(url)
    renderable_func = set_renderable(redirect, public)
    return renderable_func


class alias_to_site_section(object):
    """
    Inject a URL redirect from another page to the decorated function.
    This is useful for downstream plugins to add or change functions in upstream plugins to modify their behavior.

    Example: if you move the explode_kittens() function from the core's site_section/summary.py page to a plugin,
    in that plugin you can create an alias back to the original function like this:

    @alias_to_site_section('summary')
    def explode_kittens(...):
        ...

    Please note that this doesn't preserve arguments, it just causes a redirect.  It's most useful for pages without
    arguments like reports and landing pages.
    """
    def __init__(self, site_section_name, alias_name=None, url=None):
        self.site_section_name = site_section_name
        self.alias_name = alias_name
        self.url = url

    def __call__(self, func):
        root = getattr(uber.site_sections, self.site_section_name).Root
        redirect_func = create_redirect(self.url or '../' + get_module_name(func) + '/' + func.__name__)
        setattr(root, self.alias_name or func.__name__, redirect_func)
        return func


def id_required(model):
    def model_id_required(func):
        @wraps(func)
        def check_id(*args, **params):
            check_id_for_model(model=model, **params)
            return func(*args, **params)
        return check_id
    return model_id_required


def check_id_for_model(model, **params):
    message = None
    session = params['session']
    model_id = params.get('id')

    if not model_id:
        message = "No ID provided. Try using a different link or going back."
    elif model_id == 'None':
        # Some pages use the string 'None' is indicate that a new model should be created, so this is a valid ID
        pass
    else:
        try:
            if not isinstance(model_id, uuid.UUID):
                uuid.UUID(model_id)
        except ValueError:
            message = "That ID is not a valid format. Did you enter or edit it manually or paste it incorrectly?"
        else:
            if not session.query(model).filter(model.id == model_id).first():
                message = "The ID provided was not found in our database."

    if message:
        log.error("check_id {} error: {}: id={}", model.__name__, message, model_id)
        raise HTTPRedirect('../preregistration/not_found?id={}&message={}', model_id, message)
