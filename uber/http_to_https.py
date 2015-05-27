from uber.common import *


class Redirector:
    @cherrypy.expose
    def default(self, *args, **kwargs):
        raise HTTPRedirect('{}{req.path_info}?{req.query_string}'.format(URL_BASE, req=cherrypy.request))

if __name__ == '__main__':
    cherrypy.config.update({'server.socket_port': 80})
    cherrypy.tree.mount(Redirector(), '/')
    cherrypy.engine.start()
    cherrypy.engine.block()
