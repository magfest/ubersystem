import cherrypy

from uber.decorators import all_renderable, requires_account
from uber.errors import HTTPRedirect
from uber.forms import attendee as attendee_forms, load_forms
from uber.models import Attendee
from uber.payments import PreregCart


@all_renderable(public=True)
class Root:
    def index(self, session, **params):
        if 'exit_kiosk' in params:
            cherrypy.session['kiosk_mode'] = False

        if 'clear_cookies' in params:
            for key in PreregCart.session_keys:
                cherrypy.session.pop(key)

        forms = load_forms({}, Attendee(), ['BadgeExtras'])

        return {
            'message': params.get('message', ''),
            'email':   params.get('email', ''),
            'original_location': params.get('original_location'),
            'logged_in_account': session.current_attendee_account(),
            'kiosk_mode': cherrypy.session.get('kiosk_mode'),
            'badge_extras': forms['badge_extras'],
            'attendee': Attendee(),
        }

    def invalid(self, **params):
        return {'message': params.get('message')}
