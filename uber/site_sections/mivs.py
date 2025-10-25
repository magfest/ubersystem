import shutil

import bcrypt
import cherrypy
from cherrypy.lib.static import serve_file

from uber.config import c
from uber.custom_tags import format_image_size
from uber.decorators import all_renderable, ajax, csrf_protected
from uber.errors import HTTPRedirect
from uber.forms import load_forms
from uber.models import Attendee, Group, GuestGroup, IndieDeveloper, IndieGame, IndieGameImage, IndieGameCode
from uber.utils import add_opt, check, check_csrf, GuidebookUtils, validate_model


@all_renderable(public=True)
class Root:
    def game(self, session, id='', message='', **params):
        if id in [None, '', 'None']:
            game = IndieGame()
            studio_id = params.get('studio_id', '')
        else:
            game = session.indie_game(id)
            studio_id = game.studio.id
        
        studio = session.indie_studio(studio_id)
        forms = load_forms(params, game, ['MivsGameInfo', 'MivsDemoInfo', 'MivsConsents'])

        if cherrypy.request.method == 'POST':
            if not c.MIVS_SUBMISSIONS_OPEN and not c.HAS_SHOWCASE_ADMIN_ACCESS:
                raise HTTPRedirect('../showcase/index?id={}&message={}', studio_id,
                                   'Sorry, submissions for MIVS are now closed.')
            for form in forms.values():
                form.populate_obj(game)

            session.add(game)
            game.studio = studio
            raise HTTPRedirect('../showcase/index?id={}&message={}', studio_id,
                                'Game information uploaded.')

        return {
            'message': message,
            'game': game,
            'studio': studio,
            'forms': forms,
        }
    
    @ajax
    def validate_game(self, session, form_list=[], **params):
        if params.get('id') in [None, '', 'None']:
            game = IndieGame()
        else:
            game = session.indie_game(params.get('id'))

        if not form_list:
            form_list = ['MivsGameInfo', 'MivsDemoInfo', 'MivsConsents']
        elif isinstance(form_list, str):
            form_list = [form_list]

        forms = load_forms(params, game, form_list)
        all_errors = validate_model(forms, game)

        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    def update_demo_info(self, session, id, message='', **params):
        game = session.indie_game(id)

        if cherrypy.request.method == 'POST':
            forms = load_forms(params, game, ['MivsDemoInfo'])
            for form in forms.values():
                form.populate_obj(game)

            session.add(game)
            raise HTTPRedirect('../showcase/index?id={}&message={}', game.studio.id,
                                f'Demo information updated for {game.title}.')

    def code(self, session, game_id, message='', **params):
        if params.get('id') in [None, '', 'None']:
            code = IndieGameCode()
        else:
            code = session.indie_game_code(params.get('id'))
        
        if cherrypy.request.method == 'POST':
            code.game = session.indie_game(game_id)
            forms = load_forms(params, code, ['MivsCode'], field_prefix='new' if code.is_new else code.id)
            for form in forms.values():
                form.populate_obj(code)

            session.add(code)
            raise HTTPRedirect('../showcase/index?id={}&message={}', code.game.studio.id,
                               'Code added.' if code.is_new else 'Code updated.')

    @ajax
    def validate_code(self, session, form_list=[], **params):
        if params.get('id') in [None, '', 'None']:
            code = IndieGameCode()
        else:
            code = session.indie_game_code(params.get('id'))

        if not form_list:
            form_list = ['MivsCode']
        elif isinstance(form_list, str):
            form_list = [form_list]

        forms = load_forms(params, code, form_list, field_prefix='new' if code.is_new else code.id)
        all_errors = validate_model(forms, code)

        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    def screenshot(self, session, game_id, use_in_promo='', **params):
        if params.get('id') in [None, '', 'None']:
            screenshot = IndieGameImage()
        else:
            screenshot = session.indie_game_image(params.get('id'))

        if cherrypy.request.method == 'POST':
            screenshot.game = session.indie_game(game_id)

            forms = load_forms(params, screenshot, ['MivsScreenshot'], field_prefix='new' if screenshot.is_new else screenshot.id)
            for form in forms.values():
                form.populate_obj(screenshot)

            session.add(screenshot)
            if use_in_promo:
                screenshot.use_in_promo = True

            if use_in_promo:
                raise HTTPRedirect('../showcase/show_info?id={}&message={}', game_id,
                                   'Screenshot uploaded.' if screenshot.is_new else 'Screenshot updated.')
            else:
                raise HTTPRedirect('../showcase/index?id={}&message={}', screenshot.game.studio.id,
                                   'Screenshot uploaded.' if screenshot.is_new else 'Screenshot updated.')
    
    @ajax
    def validate_image(self, session, form_list=[], **params):
        if params.get('id') in [None, '', 'None']:
            image = IndieGameImage()
        else:
            image = session.indie_game_image(params.get('id'))

        if not form_list:
            form_list = ['MivsScreenshot']
        elif isinstance(form_list, str):
            form_list = [form_list]

        forms = load_forms(params, image, form_list, field_prefix='new' if image.is_new else image.id)
        all_errors = validate_model(forms, image)

        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    @csrf_protected
    def delete_screenshot(self, session, id, show_info=False):
        screenshot = session.indie_game_image(id)
        studio_id = screenshot.game.studio.id
        session.delete_screenshot(screenshot)
        if show_info:
            raise HTTPRedirect('../showcase/show_info?id={}&message={}', studio_id, 'Image deleted.')
        else:
            raise HTTPRedirect('../showcase/index?id={}&message={}', studio_id, 'Screenshot deleted.')

    @csrf_protected
    def delete_code(self, session, id):
        code = session.indie_game_code(id)
        studio_id = code.game.studio.id
        session.delete(code)
        raise HTTPRedirect('../showcase/index?id={}&message={}', studio_id, 'Code deleted.')
