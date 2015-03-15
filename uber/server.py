from uber.common import *
from uber.site_sections import schedule, signups, preregistration


def _add_email():
    [body] = cherrypy.response.body
    body = body.replace(b'<body>', b'''<body>Please contact us via <a href="CONTACT_URL">CONTACT_URL</a> if you're not sure why you're seeing this page.'''.replace(b'CONTACT_URL', c.CONTACT_URL.encode('utf-8')))
    cherrypy.response.headers['Content-Length'] = len(body)
    cherrypy.response.body = [body]
cherrypy.tools.add_email_to_error_page = cherrypy.Tool('after_error_response', _add_email)

mimetypes.init()

class StaticViews:
    def path_args_to_string(self, path_args):
        return '/'.join(path_args)

    def get_full_path_from_path_args(self, path_args):
        return 'static_views/' + self.path_args_to_string(path_args)

    def get_filename_from_path_args(self, path_args):
        return path_args[-1]

    @cherrypy.expose
    def magfest_js(self):
        """
        We have several Angular apps which need to be able to access our constants like c.ATTENDEE_BADGE and such.
        We also need those apps to be able to make HTTP requests with CSRF tokens, so we set that default.
        """
        cherrypy.response.headers['Content-Type'] = 'text/javascript'
        renderable = {k: v for k, v in renderable_data().items() if isinstance(v, (bool, int, str))}
        consts = json.dumps(renderable, indent=4)
        return '\n'.join([
            'angular.module("magfest", [])',
            '.constant("magconsts", {})'.format(consts),
            '.run(function ($http) {',
            '   $http.defaults.headers.common["CSRF-Token"] = "{}";'.format(renderable.get('CSRF_TOKEN')),
            '});'
        ])

    @cherrypy.expose
    def default(self, *path_args, **kwargs):
        content_filename = self.get_filename_from_path_args(path_args)

        template_name = self.get_full_path_from_path_args(path_args)
        content = render(template_name)

        guessed_content_type = mimetypes.guess_type(content_filename)[0]
        return cherrypy.lib.static.serve_fileobj(content, name=content_filename, content_type=guessed_content_type)

@all_renderable()
class Root:
    def index(self):
        return render('index.html')

    def common_js(self):
        cherrypy.response.headers['Content-Type'] = 'text/javascript'
        return render('common.js')

    static_views = StaticViews()

_sections = [path.split('/')[-1][:-3] for path in glob(os.path.join(c.MODULE_ROOT, 'site_sections', '*.py'))
                                      if not path.endswith('__init__.py')]
for _section in _sections:
    _module = __import__('uber.site_sections.' + _section, fromlist=['Root'])
    setattr(Root, _section, _module.Root())


class Redirector:
    @cherrypy.expose
    def index(self):
        if c.AT_THE_CON:
            raise HTTPRedirect(c.PATH + '/accounts/homepage')
        else:
            raise HTTPRedirect(c.PATH)

cherrypy.tree.mount(Root(), c.PATH, c.APPCONF)

DaemonTask(check_unassigned, interval=300)
DaemonTask(detect_duplicates, interval=300)
DaemonTask(check_placeholders, interval=300)
DaemonTask(AutomatedEmail.send_all, interval=300)

# this should be replaced by something a little cleaner, but it's a useful debugging tool, so we'll go with it for now
#DaemonTask(lambda: log.error(Session.engine.pool.status()), interval=5)
