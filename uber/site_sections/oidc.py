import cherrypy
import logging

from uber.decorators import all_renderable
from uber.errors import HTTPRedirect

log = logging.getLogger(__name__)

@all_renderable(public=True)
class Root:    
    def callback(self, code=None, error=None, **kwargs):
        if error:
            raise HTTPRedirect("landing/index?message={}", f"Error: {error}")
        
        cherrypy.tools.oidc.handle_login(code)
        
        if cherrypy.request.admin_account:
            raise HTTPRedirect(cherrypy.request.cookie['post_login_url'].value if 'post_login_url' in cherrypy.request.cookie else 'preregistration/homepage')
        if cherrypy.request.attendee_account:
            raise HTTPRedirect(cherrypy.request.cookie['post_login_url'].value if 'post_login_url' in cherrypy.request.cookie else 'accounts/homepage')
        raise HTTPRedirect('landing/index?message={}', 'Login Failed')
        
