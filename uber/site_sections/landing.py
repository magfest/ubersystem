import cherrypy

from uber.decorators import all_renderable
from uber.errors import HTTPRedirect


@all_renderable(public=True)
class Root:
    def index(self, session, **params):
        if 'exit_kiosk' in params:
            cherrypy.session['kiosk_mode'] = False
        return {
            'message': params.get('message', ''),
            'email':   params.get('email', ''),
            'original_location': params.get('original_location'),
            'logged_in_account': session.current_attendee_account(),
            'kiosk_mode': cherrypy.session.get('kiosk_mode'),
        }
    
    def login_select(self, session, **params):
        
        return {
            'message': params.get('message')
        }


    def invalid(self, **params):
        return {'message': params.get('message')}
