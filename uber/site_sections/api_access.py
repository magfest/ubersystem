from uber.common import *


@all_renderable(c.API)
class Root:

    def index(self, session, message='', **params):
        admin_account = session.current_admin_account()
        if c.ADMIN not in admin_account.access_ints:
            raise HTTPRedirect('account?id={}', admin_account.id)

        return {
            'message': message
        }

    def account(self, session, id, message='', **params):
        admin_account = session.admin_account(id)
        return {
            'message': message,
            'admin_account': admin_account
        }
