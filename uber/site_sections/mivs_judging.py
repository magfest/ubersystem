from uber.decorators import all_renderable
from uber.server import redirect_site_section


@all_renderable()
class Root:
    def index(self, session, message='', **params):
        redirect_site_section('mivs_judging','showcase_judging')