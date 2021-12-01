import cherrypy

from uber.decorators import all_renderable


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

    def invalid(self, **params):
        return {'message': params.get('message')}
