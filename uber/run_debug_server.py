from uber.common import *
from debugger import debugger_helpers_all_init

if __name__ == '__main__':

    debugger_helpers_all_init()

    cherrypy.engine.start()
    cherrypy.engine.block()
