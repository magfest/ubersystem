import shutil

import logging
import cherrypy
from cherrypy.lib.static import serve_file

from uber.config import c
from uber.custom_tags import format_image_size
from uber.decorators import all_renderable, ajax, csrf_protected
from uber.errors import HTTPRedirect
from uber.files import FileService
from uber.forms import load_forms
from uber.models import Attendee, File, GuestGroup, IndieDeveloper, IndieGame, IndieGameCode
from uber.utils import add_opt, check, check_csrf, GuidebookUtils, validate_model

log = logging.getLogger(__name__)


@all_renderable(public=True)
class Root:
    def game(self, session, id='', message='', **params):
        if id in [None, '', 'None']:
            studio_id = params.get('studio_id', '')
            game = IndieGame(studio_id=studio_id)
            session.add(game)
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
            studio_id = params.get('studio_id', '')
            game = IndieGame(studio_id=studio_id)
        else:
            game = session.indie_game(params.get('id'))

        if not form_list:
            form_list = ['MivsGameInfo', 'MivsDemoInfo', 'MivsConsents']
        elif isinstance(form_list, str):
            form_list = [form_list]

        forms = load_forms(params, game, form_list)
        all_errors = validate_model(session, forms, game)

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
        all_errors = validate_model(session, forms, code)

        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    def screenshot(self, session, game_id, use_in_promo='', **params):
        game = session.indie_game(game_id)
        if params.get('id') in [None, '', 'None']:
            image = File(fk_id=game_id, fk_model='IndieGame')
            session.add(image)
        else:
            image = FileService.from_db_id(session, params.get('id')).file_obj

        if cherrypy.request.method == 'POST':
            forms = load_forms(params, image, ['MivsScreenshot'], field_prefix=params.get('id', 'new'))
            for form in forms.values():
                form.populate_obj(image)

            if use_in_promo:
                best_images = FileService.get_existing_files(session, game, and_flags=['use_in_promo'], uselist=True)
                if len(best_images) < 2:
                    image.flags['use_in_promo'] = True
                raise HTTPRedirect('../showcase/show_info?id={}&message={}', game_id,
                                   'Screenshot uploaded.' if image.is_new else 'Screenshot updated.')
            else:
                raise HTTPRedirect('../showcase/index?id={}&message={}', game.studio.id,
                                   'Screenshot uploaded.' if image.is_new else 'Screenshot updated.')
    
    @ajax
    def validate_image(self, session, game_id, form_list=[], **params):
        if params.get('id') in [None, '', 'None']:
            image = File(fk_id=game_id, fk_model='IndieGame')
        else:
            image = FileService.from_db_id(session, params.get('id')).file_obj

        if not form_list:
            form_list = ['MivsScreenshot']
        elif isinstance(form_list, str):
            form_list = [form_list]

        forms = load_forms(params, image, form_list, field_prefix=params.get('id', 'new'))
        all_errors = validate_model(session, forms, image)

        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    @csrf_protected
    def delete_screenshot(self, session, studio_id, id, show_info=False):
        screenshot_handler = FileService.from_db_id(session, id)
        game_id = screenshot_handler.file_obj.fk_id
        if screenshot_handler:
            screenshot_handler.delete()

        if show_info:
            raise HTTPRedirect('../showcase/show_info?id={}&message={}', game_id, 'Image deleted.')
        else:
            raise HTTPRedirect('../showcase/index?id={}&message={}', studio_id, 'Screenshot deleted.')

    @csrf_protected
    def delete_code(self, session, id):
        code = session.indie_game_code(id)
        studio_id = code.game.studio.id
        session.delete(code)
        raise HTTPRedirect('../showcase/index?id={}&message={}', studio_id, 'Code deleted.')
