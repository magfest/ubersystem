from common import *

# TODO: make UBER_SHUT_DOWN testable, since right not it's only checked at import time

if state.UBER_SHUT_DOWN:
    import site_sections.schedule, site_sections.signups
    @all_renderable()
    class Root:
        def default(self, *args, **kwargs):
            return render("closed.html")
        
        signups = site_sections.signups.Root()
        schedule = site_sections.schedule.Root()
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
    sections = [path.split("/")[1][:-3] for path in glob("site_sections/*.py") if "__init__" not in path]
    for section in sections:
        module = __import__("site_sections." + section, fromlist=["Root"])
        setattr(root, section, module.Root())

cherrypy.tree.mount(root, state.PATH, appconf)

if __name__=="__main__":
    cherrypy.engine.start()
    cherrypy.engine.wait(cherrypy.engine.states.STARTED)
    if not state.AT_THE_CON:
        daemonize(Reminder.send_all,  name = "EmailReminderTask")
        daemonize(delete_unpaid,      name = "UnpaidDeletionTask")
        daemonize(detect_duplicates,  name = "DuplicateReminder")
        daemonize(check_placeholders, name = "PlaceholdersReminder")
    cherrypy.engine.block()
