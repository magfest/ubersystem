from uber.common import *

# TODO: move daemonize into cherrypy.engine.subscribe

if __name__=="__main__":
    cherrypy.engine.start()
    cherrypy.engine.wait(cherrypy.engine.states.STARTED)
    daemonize(Reminder.send_all, name = "EmailReminderTask")
    if not AT_THE_CON and not POST_CON:
        daemonize(detect_duplicates,  name = "DuplicateReminder")
        daemonize(check_placeholders, name = "PlaceholdersReminder")
    cherrypy.engine.block()
