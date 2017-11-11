from uber.common import *


@all_renderable(c.API)
class Root:

    def index(self, session, message='', **params):
        return {'message': message}
