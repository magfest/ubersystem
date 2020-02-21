import json
import mimetypes
import os
import traceback
from pprint import pformat

import cherrypy
import jinja2
from cherrypy import HTTPError
from pockets import is_listy
from pockets.autolog import log
from sideboard.jsonrpc import json_handler, ERR_INVALID_RPC, ERR_MISSING_FUNC, ERR_INVALID_PARAMS, \
    ERR_FUNC_EXCEPTION, ERR_INVALID_JSON
from sideboard.server import jsonrpc_reset
from sideboard.websockets import trigger_delayed_notifications

from uber.config import c, Config
from uber.decorators import all_renderable, render
from uber.errors import HTTPRedirect
from uber.utils import mount_site_sections, static_overrides


mimetypes.init()


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


    """
    In August 2019 we rearranged and refactored our site sections to be 
    more consistent and logical. Below are several redirects to help
    with the transition. We can remove all these when we're reasonably
    sure people won't have bookmarks with the old URLs.
    """

    def signups(self, *path, **params):
        redirect_site_section('signups', 'staffing')

    def common(self, *path, **params):
        redirect_site_section('common', 'landing')

    def departments(self, *path, **params):
        redirect_site_section('departments', 'dept_admin')

    def emails(self, *path, **params):
        redirect_site_section('emails', 'email_admin')

    def graphs(self, *path, **params):
        redirect_site_section('graphs', 'reg_reports')

    def groups(self, *path, **params):
        if 'promo_code' in c.PAGE:
            redirect_site_section('groups', 'registration')
        redirect_site_section('groups', 'dealer_admin')

    def jobs(self, *path, **params):
        redirect_site_section('jobs', 'shifts_admin')

    def panel_applications(self, *path, **params):
        redirect_site_section('panel_applications', 'panels')

    def panel_app_management(self, *path, **params):
        redirect_site_section('panel_app_management', 'panels_admin')

    def mivs_applications(self, *path, **params):
        redirect_site_section('mivs_applications', 'mivs')

    def mits_applications(self, *path, **params):
        redirect_site_section('mits_applications', 'mits')

    def export(self, *path, **params):
        new_page = 'csv_export' if c.PAGE == 'index' else ''
        redirect_site_section('export', 'devtools', new_page)

    @cherrypy.expose('import')  # import is a special name in Python
    def import_page(self, *path, **params):
        if c.PAGE in ['attendees', 'attendee']:
            redirect_site_section('import', 'reg_admin', 'import_attendees')
        elif c.PAGE in ['shift', 'shifts']:
            redirect_site_section('import', 'staffing_admin', 'import_shifts')

        redirect_site_section('import', 'devtools', 'csv_import')

    def hotel(self, *path, **params):
        if c.PAGE == 'index':
            new_page = 'hotel_eligible'
        elif c.PAGE == 'requests':
            new_page = 'hotel_requests'
        else:
            new_page = ''

        redirect_site_section('hotel', 'dept_checklist', new_page)

    def hotel_assignments(self, *path, **params):
        if c.PAGE == 'index':
            redirect_site_section('hotel_assignments', 'hotel_reports')
        redirect_site_section('hotel_assignments', 'hotel_admin')

    def hotel_summary(self, *path, **params):
        redirect_site_section('hotel_summary', 'hotel_reports')

    def summary(self, *path, **params):
        new_page = 'index' if c.PAGE in ['staffing_overview', 'guidebook_exports'] else ''
        new_sections = {'badge_exports': [
            'badge_hangars_supporters', 'personalized_badges_zip', 'printed_badges_attendee', 'printed_badges_guest',
            'printed_badges_minor', 'printed_badges_one_day', 'printed_badges_staff',
        ], 'dealer_reports': [
            'seller_comptroller_info', 'seller_table_info',
        ], 'merch_reports': [
            'extra_merch', 'shirt_counts', 'shirt_manufacturing_counts',
        ], 'other_reports': [
            'food_eligible', 'food_restrictions', 'requested_accessibility_services',
        ], 'reg_reports': [
            'affiliates', 'attendee_birthday_calendar', 'badges_sold', 'checkins_by_hour', 'event_birthday_calendar',
            'found_how', 'index'
        ], 'schedule_reports': [
            'export_guidebook_zip', 'guidebook_exports',
        ], 'staffing_reports': [
            'all_schedules', 'consecutive_threshold', 'departments', 'dept_head_contact_info', 'staffing_overview',
            'ratings', 'restricted_untaken', 'setup_teardown_neglect', 'volunteer_checklist_csv',
            'volunteer_checklists', 'volunteer_hours_overview', 'volunteers_owed_refunds',
            'volunteers_with_worked_hours',
        ]}
        for section in new_sections:
            if c.PAGE in new_sections[section]:
                redirect_site_section('summary', section, new_page)

    def budget(self, *path, **params):
        if 'promo_codes' in c.PATH:
            redirect_site_section('budget', 'promo_codes')

    def map(self, *path, **params):
        if c.PAGE == 'attendees_can_email_in_radius_csv':
            redirect_site_section('map', 'devtools', 'csv_export')
        new_page = 'map' if c.PAGE == 'index' else ''

        redirect_site_section('map', 'reg_reports', new_page)

    static_views = StaticViews()
    angular = AngularJavascript()


mount_site_sections(c.MODULE_ROOT)


def error_page_404(status, message, traceback, version):
    return "Sorry, page not found!<br/><br/>{}<br/>{}".format(status, message)


c.APPCONF['/']['error_page.404'] = error_page_404

cherrypy.tree.mount(Root(), c.CHERRYPY_MOUNT_PATH, c.APPCONF)
static_overrides(os.path.join(c.MODULE_ROOT, 'static'))


def _make_jsonrpc_handler(services, debug=c.DEV_BOX, precall=lambda body: None):

    @cherrypy.expose
    @cherrypy.tools.force_json_in()
    @cherrypy.tools.json_out(handler=json_handler)
    def _jsonrpc_handler(self=None):
        id = None

        def error(status, code, message):
            response = {'jsonrpc': '2.0', 'id': id, 'error': {'code': code, 'message': message}}
            log.debug('Returning error message: {}', repr(response).encode('utf-8'))
            cherrypy.response.status = status
            return response

        def success(result):
            response = {'jsonrpc': '2.0', 'id': id, 'result': result}
            log.debug('Returning success message: {}', {
                'jsonrpc': '2.0', 'id': id, 'result': len(result) if is_listy(result) else str(result).encode('utf-8')})
            cherrypy.response.status = 200
            return response

        request_body = cherrypy.request.json
        if not isinstance(request_body, dict):
            return error(400, ERR_INVALID_JSON, 'Invalid json input: {!r}'.format(request_body))

        log.debug('jsonrpc request body: {}', repr(request_body).encode('utf-8'))

        id, params = request_body.get('id'), request_body.get('params', [])
        if 'method' not in request_body:
            return error(400, ERR_INVALID_RPC, '"method" field required for jsonrpc request')

        method = request_body['method']
        if method.count('.') != 1:
            return error(404, ERR_MISSING_FUNC, 'Invalid method ' + method)

        module, function = method.split('.')
        if module not in services:
            return error(404, ERR_MISSING_FUNC, 'No module ' + module)

        service = services[module]
        if not hasattr(service, function):
            return error(404, ERR_MISSING_FUNC, 'No function ' + method)

        if not isinstance(params, (list, dict)):
            return error(400, ERR_INVALID_PARAMS, 'Invalid parameter list: {!r}'.format(params))

        args, kwargs = (params, {}) if isinstance(params, list) else ([], params)

        precall(request_body)
        try:
            return success(getattr(service, function)(*args, **kwargs))
        except HTTPError as http_error:
            return error(http_error.code, ERR_FUNC_EXCEPTION, http_error._message)
        except Exception as e:
            log.error('Unexpected error', exc_info=True)
            message = 'Unexpected error: {}'.format(e)
            if debug:
                message += '\n' + traceback.format_exc()
            return error(500, ERR_FUNC_EXCEPTION, message)
        finally:
            trigger_delayed_notifications()

    return _jsonrpc_handler


jsonrpc_services = {}


def register_jsonrpc(service, name=None):
    name = name or service.__name__
    assert name not in jsonrpc_services, '{} has already been registered'.format(name)
    jsonrpc_services[name] = service


jsonrpc_app = _make_jsonrpc_handler(jsonrpc_services, precall=jsonrpc_reset)
cherrypy.tree.mount(jsonrpc_app, os.path.join(c.CHERRYPY_MOUNT_PATH, 'jsonrpc'), c.APPCONF)
