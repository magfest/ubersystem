from sideboard.jsonrpc import _make_jsonrpc_handler
from sideboard.server import jsonrpc_reset
from uber.common import *

mimetypes.init()


def _add_email():
    [body] = cherrypy.response.body
    body = body.replace(b'<body>', b'''<body>Please contact us via <a href="CONTACT_URL">CONTACT_URL</a> if you're not sure why you're seeing this page.'''.replace(b'CONTACT_URL', c.CONTACT_URL.encode('utf-8')))
    cherrypy.response.headers['Content-Length'] = len(body)
    cherrypy.response.body = [body]
cherrypy.tools.add_email_to_error_page = cherrypy.Tool('after_error_response', _add_email)


def get_verbose_request_context():
    """
    Return a string with lots of information about the current cherrypy request such as
    request headers, session params, and page location.

    Returns:

    """
    page_location = 'Request: ' + cherrypy.request.request_line

    admin_name = AdminAccount.admin_name()
    admin_txt = 'Current admin user is: {}'.format(admin_name if admin_name else '[non-admin user]')

    max_reporting_length = 1000   # truncate to reasonably large size in case they uploaded attachments

    p = ["  %s: %s" % (k, str(v)[:max_reporting_length]) for k, v in cherrypy.request.params.items()]
    post_txt = 'Request Params:\n' + '\n'.join(p)

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
    """
    log_with_verbose_context('\n'.join([msg, 'Exception encountered']), exc_info=True)


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


class AngularJavascript:
    @cherrypy.expose
    def magfest_js(self):
        """
        We have several Angular apps which need to be able to access our constants like c.ATTENDEE_BADGE and such.
        We also need those apps to be able to make HTTP requests with CSRF tokens, so we set that default.
        """
        cherrypy.response.headers['Content-Type'] = 'text/javascript'

        consts = {}
        for attr in dir(c):
            try:
                consts[attr] = getattr(c, attr, None)
            except:
                pass

        js_consts = json.dumps({k: v for k, v in consts.items() if isinstance(v, (bool, int, str))}, indent=4)
        return '\n'.join([
            'angular.module("magfest", [])',
            '.constant("c", {})'.format(js_consts),
            '.constant("magconsts", {})'.format(js_consts),
            '.run(function ($http) {',
            '   $http.defaults.headers.common["CSRF-Token"] = "{}";'.format(c.CSRF_TOKEN),
            '});'
        ])

    @cherrypy.expose
    def static_magfest_js(self):
        """
        We have several Angular apps which need to be able to access our constants like c.ATTENDEE_BADGE and such.
        We also need those apps to be able to make HTTP requests with CSRF tokens, so we set that default.

        The static_magfest_js() version of magfest_js() omits any config
        properties that generate database queries.
        """
        cherrypy.response.headers['Content-Type'] = 'text/javascript'

        consts = {}
        for attr in dir(c):
            try:
                prop = getattr(Config, attr, None)
                if prop:
                    fget = getattr(prop, 'fget', None)
                    if fget and getattr(fget, '_dynamic', None):
                        continue
                consts[attr] = getattr(c, attr, None)
            except Exception:
                pass

        js_consts = json.dumps({k: v for k, v in consts.items() if isinstance(v, (bool, int, str))}, indent=4)
        return '\n'.join([
            'angular.module("magfest", [])',
            '.constant("c", {})'.format(js_consts),
            '.constant("magconsts", {})'.format(js_consts),
            '.run(function ($http) {',
            '   $http.defaults.headers.common["CSRF-Token"] = "{}";'.format(c.CSRF_TOKEN),
            '});'
        ])


@all_renderable()
class Root:
    def index(self):
        raise HTTPRedirect('common/')

    static_views = StaticViews()
    angular = AngularJavascript()

mount_site_sections(c.MODULE_ROOT)


def error_page_404(status, message, traceback, version):
    return "Sorry, page not found!<br/><br/>{}<br/>{}".format(status, message)

c.APPCONF['/']['error_page.404'] = error_page_404

cherrypy.tree.mount(Root(), c.PATH, c.APPCONF)
static_overrides(join(c.MODULE_ROOT, 'static'))


jsonrpc_services = {}


def register_jsonrpc(service, name=None):
    name = name or service.__name__
    assert name not in jsonrpc_services, '{} has already been registered'.format(name)
    jsonrpc_services[name] = service

jsonrpc_handler = _make_jsonrpc_handler(jsonrpc_services, precall=jsonrpc_reset)
cherrypy.tree.mount(jsonrpc_handler, join(c.PATH, 'jsonrpc'), c.APPCONF)


def reg_checks():
    sleep(600)  # Delay by 10 minutes to give the system time to start up
    check_unassigned()
    detect_duplicates()
    check_placeholders()

# Registration checks are run every six hours
DaemonTask(reg_checks, interval=21600, name="mail reg checks")

DaemonTask(SendAllAutomatedEmailsJob.send_all_emails, interval=300, name="send emails")

# TODO: this should be replaced by something a little cleaner, but it can be a useful debugging tool
# DaemonTask(lambda: log.error(Session.engine.pool.status()), interval=5)
