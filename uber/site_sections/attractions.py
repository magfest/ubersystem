from uber.common import *
from uber.site_sections.preregistration import check_post_con


@all_renderable()
@check_post_con
class Root:

    def index(self):
        pass

    def kiosk(self):
        pass
