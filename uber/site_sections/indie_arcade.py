import shutil

import bcrypt
import cherrypy
from cherrypy.lib.static import serve_file

from uber.config import c
from uber.custom_tags import format_image_size
from uber.decorators import all_renderable, ajax, csrf_protected, requires_account, get_studio_id
from uber.errors import HTTPRedirect
from uber.files import FileService
from uber.forms import load_forms
from uber.models import Attendee, File, Group, GuestGroup, IndieStudio, IndieGame, IndieGameCode
from uber.utils import add_opt, check, check_csrf, GuidebookUtils, validate_model


@all_renderable(public=True)
class Root:
    @get_studio_id(IndieGame)
    @requires_account(IndieStudio)
    def game(self, session, id='', message='', **params):
        if id in [None, '', 'None']:
            studio_id = params.get('studio_id', '')
            game = IndieGame(studio_id=studio_id, showcase_type=c.INDIE_ARCADE)
            session.add(game)
        else:
            game = session.indie_game(id)
            studio_id = game.studio.id

        studio = session.indie_studio(studio_id)
        forms = load_forms(params, game, ['ArcadeGameInfo', 'ArcadeConsents', 'ArcadeLogistics'])

        if cherrypy.request.method == 'POST':
            if not c.INDIE_ARCADE_SUBMISSIONS_OPEN and not c.HAS_SHOWCASE_ADMIN_ACCESS:
                raise HTTPRedirect('../showcase/index?id={}&message={}', studio_id,
                                   'Sorry, submissions for Indie Arcade are now closed.')
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
            game = IndieGame(studio_id=studio_id, showcase_type=c.INDIE_ARCADE)
        else:
            game = session.indie_game(params.get('id'))

        if not form_list:
            form_list = ['ArcadeGameInfo', 'ArcadeConsents', 'ArcadeLogistics']
        elif isinstance(form_list, str):
            form_list = [form_list]

        forms = load_forms(params, game, form_list)
        all_errors = validate_model(session, forms, game)

        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    @get_studio_id(IndieGame, 'game_id')
    @requires_account(IndieStudio)
    def photo(self, session, game_id, use_in_promo='', **params):
        game = session.indie_game(game_id)
        if params.get('id') in [None, '', 'None']:
            photo = File(fk_id=game_id, fk_model='IndieGame')
            session.add(photo)
        else:
            photo = FileService.from_db_id(session, params.get('id')).file_obj

        if cherrypy.request.method == 'POST':
            forms = load_forms(params, photo, ['ArcadePhoto'], field_prefix=params.get('id', 'new'))
            for form in forms.values():
                form.populate_obj(photo)

            if use_in_promo:
                best_images = FileService.get_existing_files(session, game, and_flags=['use_in_promo'], uselist=True)
                if len(best_images) < 2:
                    photo.flags['use_in_promo'] = True
                raise HTTPRedirect('show_info?id={}&message={}', game_id,
                                   'Photo uploaded.' if photo.is_new else 'Photo updated.')
            else:
                raise HTTPRedirect('../showcase/index?id={}&message={}', game.studio.id,
                                   'Photo uploaded.' if photo.is_new else 'Photo updated.')
    
    @ajax
    def validate_image(self, session, game_id, form_list=[], **params):
        if params.get('id') in [None, '', 'None']:
            image = File(fk_id=game_id, fk_model='IndieGame')
        else:
            image = FileService.from_db_id(session, params.get('id')).file_obj

        if not form_list:
            form_list = ['ArcadePhoto']
        elif isinstance(form_list, str):
            form_list = [form_list]

        forms = load_forms(params, image, form_list, field_prefix=params.get('id', 'new'))
        all_errors = validate_model(session, forms, image)

        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    @requires_account(IndieStudio)
    @csrf_protected
    def delete_photo(self, session, studio_id, id):
        photo_handler = FileService.from_db_id(session, id)
        if photo_handler:
            photo_handler.delete()
        raise HTTPRedirect('../showcase/index?id={}&message={}', studio_id, 'Photo deleted.')
