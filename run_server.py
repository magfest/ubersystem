from __future__ import unicode_literals

import os
import cherrypy

is_wsgi = __name__ != '__main__' or os.environ.get("GRANIAN") == "true"

if is_wsgi:
    cherrypy.config.update({'environment': 'embedded', 'engine.signals.on': False})
    cherrypy.server.unsubscribe()

import uber.server

if is_wsgi:
    cherrypy.server.unsubscribe()
    cherrypy.engine.start()

application = cherrypy.tree

if __name__ == '__main__':
    cherrypy.engine.start()
    cherrypy.engine.block()
