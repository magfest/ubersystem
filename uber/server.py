import mimetypes

from uber.common import *
from uber.site_sections.emails import Reminder
from uber.site_sections import schedule, signups, preregistration


def _rollback():
    connection._rollback()
cherrypy.tools.rollback_on_error = cherrypy.Tool('after_error_response', _rollback)

def _add_email():
    [body] = cherrypy.response.body
    body = body.replace(b'<body>', b'''<body>Please email <a href='mailto:contact@magfest.org'>contact@magfest.org</a> if you're not sure why you're seeing this page.''')
    cherrypy.response.headers['Content-Length'] = len(body)
    cherrypy.response.body = [body]
cherrypy.tools.add_email_to_error_page = cherrypy.Tool('after_error_response', _add_email)


@all_renderable()
class UberShutDown:
    def default(self, *args, **kwargs):
        return render('closed.html')
    
    signups = signups.Root()
    schedule = schedule.Root()
    preregistration = preregistration.Root()

mimetypes.init()

class StaticViews:
    def path_args_to_string(self, path_args):
        return '/'.join(path_args)

    def get_full_path_from_path_args(self, path_args):
        return 'static_views/' + self.path_args_to_string(path_args)

    def get_filename_from_path_args(self, path_args):
        return path_args[-1]

    @cherrypy.expose
    def default(self, *path_args, **kwargs):
        content_filename = self.get_filename_from_path_args(path_args)

        template_name = self.get_full_path_from_path_args(path_args)
        content = render(template_name)

        guessed_content_type = mimetypes.guess_type(content_filename)[0]
        return cherrypy.lib.static.serve_fileobj(content, name=content_filename, content_type=guessed_content_type)

@all_renderable()
class Uber:
    def index(self):
        return render('index.html')

    def common_js(self):
        cherrypy.response.headers['Content-Type'] = 'text/javascript'
        return render('common.js')

    static_views = StaticViews()

_sections = [path.split('/')[-1][:-3] for path in glob(os.path.join(MODULE_ROOT, 'site_sections', '*.py'))
                                      if not path.endswith('__init__.py')]
for _section in _sections:
    _module = __import__('uber.site_sections.' + _section, fromlist=['Root'])
    setattr(Uber, _section, _module.Root())

Root = UberShutDown if UBER_SHUT_DOWN else Uber

class Redirector:
    @cherrypy.expose
    def index(self):
        if AT_THE_CON:
            raise HTTPRedirect(PATH + '/accounts/homepage')
        else:
            raise HTTPRedirect(PATH)

cherrypy.tree.mount(Redirector(), '/', {})
cherrypy.tree.mount(Root(), PATH, conf['appconf'].dict())

if SEND_EMAILS:
    DaemonTask(Reminder.send_all, name='EmailReminderTask')
if PRE_CON:
    DaemonTask(detect_duplicates, name='DuplicateReminder')
    DaemonTask(check_unassigned, name='UnassignedReminder')
    if CHECK_PLACEHOLDERS:
        DaemonTask(check_placeholders, name='PlaceholdersReminder')
