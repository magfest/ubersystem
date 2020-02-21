from uber.errors import HTTPRedirect
from uber.decorators import all_renderable

# We need this site section so we can control access to different types of guest groups
@all_renderable()
class Root:
    def index(self, session, message=''):
        HTTPRedirect('../group_admin/index#guests?message={}', message)
