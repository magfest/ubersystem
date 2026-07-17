from __future__ import unicode_literals

import traceback
import sys
import os

import cherrypy

import uber.server

cherrypy.engine.start()
application = cherrypy.tree

if __name__ == '__main__':
    cherrypy.engine.block()
