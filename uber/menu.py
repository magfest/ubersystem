from uber.common import *


class MenuItem:
    access = None   # list of permission levels allowed to display this menu
    href = None     # link to render
    submenu = None  # submenu to show
    name = None     # name of Menu item to show

    def __init__(self, href=None, access=None, submenu=None, name=None):
        if submenu:
            self.submenu = listify(submenu)
        else:
            self.href = href

        self.name = name
        self.access = access

    def __getitem__(self, key):
        for sm in self.submenu:
            if sm.name == key:
                return sm

    def append_menu_item(self, m):
        # if we aren't a submenu, convert us to one now
        if not self.submenu and self.href:
            self.submenu = [MenuItem(name=self.name, href=self.href)]
            self.href = None

        self.submenu.append(m)


c.MENU = MenuItem(name='Root', submenu=[
    MenuItem(name='Accounts', href='../accounts/', access=c.ACCOUNTS),

    MenuItem(name='People', access=[c.PEOPLE, c.REG_AT_CON], submenu=[
        MenuItem(name='Attendees', href='../registration/{}'.format('?invalid=True' if c.AT_THE_CON else '')),
        MenuItem(name='Groups', href='../groups/'),
        MenuItem(name='All Untaken Shifts', access=c.PEOPLE, href='../jobs/everywhere'),
        MenuItem(name='Jobs', access=c.PEOPLE, href='../jobs/'),
        MenuItem(name='Watchlist', access=c.WATCHLIST, href='../registration/watchlist_entries'),
        MenuItem(name='Feed of Database Changes', href='../registration/feed'),
    ]),

    MenuItem(name='Schedule', access=c.STUFF, submenu=[
        MenuItem(name='View Schedule', href='../schedule/'),
        MenuItem(name='View Schedule (Internal Only)', href='../schedule/internal'),
        MenuItem(name='Edit Schedule', href='../schedule/edit'),
    ]),

    MenuItem(name='Statistics', href='../summary/'),
])
