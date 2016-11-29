from uber.common import *


@all_renderable()
class Root:
    def index(self):
        return {}

    def error(self, message=''):
        return{
            "message": message
        }