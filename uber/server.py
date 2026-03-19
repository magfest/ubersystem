import json
import mimetypes
import os
import sys
import ctypes
import ctypes.util
import traceback
import threading
import importlib
from pprint import pformat

import cherrypy
import sentry_sdk
import jinja2
import logging
from cherrypy import HTTPError

from uber.config import c, Config
from uber.decorators import all_renderable, render
from uber.errors import HTTPRedirect
from uber.utils import mount_site_sections, static_overrides
from uber.redis_session import RedisSession

log = logging.getLogger(__name__)

cherrypy.lib.sessions.RedisSession = RedisSession

mimetypes.init()

if c.SENTRY['enabled']:
    sentry_sdk.init(
        dsn=c.SENTRY['dsn'],
        environment=c.SENTRY['environment'],
        release=c.SENTRY['release'],

        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for performance monitoring.
        # We recommend adjusting this value in production.
        traces_sample_rate=c.SENTRY['sample_rate'] / 100
    )

def sentry_start_transaction():
    cherrypy.request.sentry_transaction = sentry_sdk.start_transaction(
        name=f"{cherrypy.request.method} {cherrypy.request.path_info}",
        op=f"{cherrypy.request.method} {cherrypy.request.path_info}",
    )
    cherrypy.request.sentry_transaction.__enter__()


cherrypy.tools.sentry_start_transaction = cherrypy.Tool('on_start_resource', sentry_start_transaction)


def sentry_end_transaction():
    cherrypy.request.sentry_transaction.__exit__(None, None, None)


cherrypy.tools.sentry_end_transaction = cherrypy.Tool('on_end_request', sentry_end_transaction)


@cherrypy.tools.register('before_finalize', priority=60)
def secureheaders():
    headers = cherrypy.response.headers
    hsts_header = 'max-age=' + str(c.HSTS['max_age'])
    if c.HSTS['include_subdomains']:
        hsts_header += '; includeSubDomains'
    if c.HSTS['preload']:
        if c.HSTS['max_age'] < 31536000:
            log.error('HSTS only supports preloading if max-age > 31536000')
        elif not c.HSTS['include_subdomains']:
            log.error('HSTS only supports preloading if subdomains are included')
        else:
            hsts_header += '; preload'
    headers['Strict-Transport-Security'] = hsts_header


def _add_email():
    [body] = cherrypy.response.body
    body = body.replace(b'<body>', (
        b'<body>Please contact us via <a href="CONTACT_URL">CONTACT_URL</a> if you\'re not sure why '
        b'you\'re seeing this page.').replace(b'CONTACT_URL', c.CONTACT_URL.encode('utf-8')))
    cherrypy.response.headers['Content-Length'] = len(body)
    cherrypy.response.body = [body]


cherrypy.tools.add_email_to_error_page = cherrypy.Tool('after_error_response', _add_email)


def get_verbose_request_context():
    """
    Return a string with lots of information about the current cherrypy request such as
    request headers, session params, and page location.

    Returns:

    """
    from uber.models.admin import AdminAccount

    page_location = 'Request: ' + cherrypy.request.request_line

    admin_name = AdminAccount.admin_name()
    admin_txt = 'Current admin user is: {}'.format(admin_name if admin_name else '[non-admin user]')

    max_reporting_length = 1000   # truncate to reasonably large size in case they uploaded attachments

    p = ["  %s: %s" % (k, str(v)[:max_reporting_length]) for k, v in cherrypy.request.params.items()]
    post_txt = 'Request Params:\n' + '\n'.join(p)

    session_txt = ''
    if hasattr(cherrypy, 'session'):
        session_txt = 'Session Params:\n' + pformat(cherrypy.session.items(), width=40)

    h = ["  %s: %s" % (k, v) for k, v in cherrypy.request.header_list]
    headers_txt = 'Request Headers:\n' + '\n'.join(h)

    return '\n'.join([page_location, admin_txt, post_txt, session_txt, headers_txt])


def log_with_verbose_context(msg, exc_info=False):
    full_msg = '\n'.join([msg, get_verbose_request_context()])
    log.error(full_msg, exc_info=exc_info)


def log_exception_with_verbose_context(debug=False, msg=''):
    """
    Write the request headers, session params, page location, and the last error's traceback to the cherrypy error log.
    Do this all one line so all the information can be collected by external log collectors and easily displayed.

    Debug param is there to play nice with the cherrypy logger
    """
    log_with_verbose_context('\n'.join([msg, 'Exception encountered']), exc_info=True)


def redirect_site_section(original, redirect, new_page='', *path, **params):
    path = cherrypy.request.path_info.replace(original, redirect)
    if new_page:
        path = path.replace(c.PAGE, new_page)
    if cherrypy.request.query_string:
        path += '?' + cherrypy.request.query_string
    raise HTTPRedirect(path)


cherrypy.tools.custom_verbose_logger = cherrypy.Tool('before_error_response', log_exception_with_verbose_context)


class StaticViews:
    @classmethod
    def path_args_to_string(cls, path_args):
        return '/'.join(path_args)

    @classmethod
    def get_full_path_from_path_args(cls, path_args):
        return 'static_views/' + cls.path_args_to_string(path_args)

    @classmethod
    def get_filename_from_path_args(cls, path_args):
        return path_args[-1]

    @classmethod
    def raise_not_found(cls, path, e=None):
        raise cherrypy.HTTPError(404, "The path '{}' was not found.".format(path)) from e

    @cherrypy.expose
    def index(self):
        self.raise_not_found('static_views/')

    @cherrypy.expose
    def default(self, *path_args, **kwargs):
        content_filename = self.get_filename_from_path_args(path_args)

        template_name = self.get_full_path_from_path_args(path_args)
        try:
            content = render(template_name)
        except jinja2.exceptions.TemplateNotFound as e:
            self.raise_not_found(template_name, e)

        guessed_content_type = mimetypes.guess_type(content_filename)[0]
        return cherrypy.lib.static.serve_fileobj(content, name=content_filename, content_type=guessed_content_type)

@all_renderable(public=True)
class Root:
    def index(self):
        raise HTTPRedirect('landing/')

    def uber(self, *path, **params):
        """
        Some old browsers bookmark all urls as starting with /uber but Nginx
        automatically prepends this.  For backwards-compatibility, if someone
        comes to a url that starts with /uber then we redirect them to the
        same URL with that bit stripped out.

        For example, old laptops which have
            https://onsite.uber.magfest.org/uber/registration/register
        bookmarked as their homepage will automatically get redirected to
            https://onsite.uber.magfest.org/registration/register
        and so forth.
        """
        path = cherrypy.request.path_info[len('/uber'):]
        if cherrypy.request.query_string:
            path += '?' + cherrypy.request.query_string
        raise HTTPRedirect(path)

    static_views = StaticViews()


mount_site_sections(c.MODULE_ROOT)


def error_page_404(status, message, traceback, version):
    return "Sorry, page not found!<br/><br/>{}<br/>{}".format(status, message)


c.APPCONF['/']['error_page.404'] = error_page_404

cherrypy.tree.mount(Root(), c.CHERRYPY_MOUNT_PATH, c.APPCONF)
static_overrides(os.path.join(c.MODULE_ROOT, 'static'))

cherrypy_config = {}
for setting, value in c.CHERRYPY.items():
    if isinstance(value, str):
        if value.isdigit():
            value = int(value)
        elif value.lower() in ['true', 'false']:
            value = value.lower() == 'true'
    cherrypy_config[setting] = value
storage_type = c.CHERRYPY.get("tools.sessions.storage_class", "RedisSession")
if isinstance(storage_type, str):
    cherrypy_config['tools.sessions.storage_class'] = getattr(cherrypy.lib.sessions, storage_type)
cherrypy.config.update(cherrypy_config)

libpthread_path = ctypes.util.find_library("pthread")
pthread_setname_np = None
if libpthread_path:
    libpthread = ctypes.CDLL(libpthread_path)
    if hasattr(libpthread, "pthread_setname_np"):
        pthread_setname_np = libpthread.pthread_setname_np
        pthread_setname_np.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        pthread_setname_np.restype = ctypes.c_int


def _set_current_thread_ids_from(thread):
    # thread ID part 1: set externally visible thread name in /proc/[pid]/tasks/[tid]/comm to our internal name
    if pthread_setname_np and thread.name:
        # linux doesn't allow thread names > 15 chars, and we ideally want to see the end of the name.
        # attempt to shorten the name if we need to.
        shorter_name = thread.name if len(thread.name) < 15 else thread.name.replace('CP Server Thread', 'CPServ')
        if thread.ident is not None:
            pthread_setname_np(thread.ident, shorter_name.encode('ASCII'))


# inject our own code at the start of every thread's start() method which sets the thread name via pthread().
# Python thread names will now be shown in external system tools like 'top', '/proc', etc.
def _thread_name_insert(self):
    _set_current_thread_ids_from(self)
    threading.Thread._bootstrap_inner_original(self)

    threading.Thread._bootstrap_inner_original = threading.Thread._bootstrap_inner
    threading.Thread._bootstrap_inner = _thread_name_insert

# set the ID's of the main thread
threading.current_thread().name = 'ubersystem_main'
_set_current_thread_ids_from(threading.current_thread())

log.info("Loading plugins")
for plugin_name in c.PLUGINS:
    log.info(f"Loading plugin {plugin_name}")
    sys.path.append(f"/app/plugins/{plugin_name}")
    plugin = importlib.import_module(plugin_name)
    if callable(getattr(plugin, 'on_load', None)):
        plugin.on_load()