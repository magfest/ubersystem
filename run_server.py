from __future__ import unicode_literals

import cherrypy

import uber.server
import logging
logging.basicConfig()
logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)

if __name__ == '__main__':
    cherrypy.engine.start()
    cherrypy.engine.block()
