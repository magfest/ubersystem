from uber.common import *

# TODO: open source DaemonTask and use it properly with cherrypy engine hooks
# TODO: make UBER_SHUT_DOWN testable, since right not it's only checked at import time
# TODO: more elegant importing for uber shutdown

if state.UBER_SHUT_DOWN:
    import uber.site_sections.schedule, uber.site_sections.signups, uber.site_sections.preregistration
    @all_renderable()
    class Root:
        def default(self, *args, **kwargs):
            return render("closed.html")
        
        signups = uber.site_sections.signups.Root()
        schedule = uber.site_sections.schedule.Root()
        preregistration = uber.site_sections.preregistration.Root()
    root = Root()
else:
    @all_renderable()
    class Root:
        def index(self):
            return render("index.html")
        
        def common_js(self):
            cherrypy.response.headers["Content-Type"] = "text/javascript"
            return render("common.js")
    
    root = Root()
    sections = [path.split("/")[-1][:-3] for path in glob(os.path.join(HERE, "site_sections", "*.py"))
                                         if "__init__" not in path]
    for section in sections:
        module = __import__("uber.site_sections." + section, fromlist=["Root"])
        setattr(root, section, module.Root())

class Redirector:
    @cherrypy.expose
    def index(self):
        if state.AT_THE_CON:
            raise HTTPRedirect(state.PATH + '/accounts/homepage')
        else:
            raise HTTPRedirect(state.PATH)

cherrypy.tree.mount(Redirector(), "/", {})
cherrypy.tree.mount(root, state.PATH, appconf)
