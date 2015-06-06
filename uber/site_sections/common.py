from uber.common import *


@all_renderable()
class Root:
    def index(self):
        return render('index.html')