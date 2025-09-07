import shutil

import bcrypt
import cherrypy
from cherrypy.lib.static import serve_file

from uber.config import c
from uber.custom_tags import format_image_size
from uber.decorators import all_renderable, ajax, csrf_protected
from uber.errors import HTTPRedirect
from uber.forms import load_forms
from uber.models import Attendee, Group, IndieGameCode, IndieStudio, IndieDeveloper, IndieGameImage
from uber.utils import add_opt, check, check_csrf, GuidebookUtils, validate_model


@all_renderable(public=True)
class Root:
    def apply(self, session, message='', **params):
        studio = IndieStudio()
        developer = IndieDeveloper(gets_emails=True)

        forms = load_forms(params, studio, ['StudioInfo'])
        dev_form = load_forms(params, developer, ['DeveloperInfo'])
        forms.update(dev_form)

        if cherrypy.request.method == 'POST':
            forms['studio_info'].populate_obj(studio)
            forms['developer_info'].populate_obj(developer)
            developer.studio = studio
            session.add(studio)
            session.add(developer)
            raise HTTPRedirect('index?id={}&message={}', studio.id,
                               "Studio created successfully! Submit one or more games to our showcases below.")

        return {
            'message': message,
            'forms': forms,
        }

    @ajax
    def validate_new_studio(self, session, form_list=[], **params):
        all_errors = {}

        forms = load_forms(params, IndieStudio(), ['StudioInfo'])
        studio_errors = validate_model(forms, IndieStudio())
        if studio_errors:
            all_errors.update(studio_errors)

        dev_forms = load_forms(params, IndieDeveloper(), ['DeveloperInfo'])
        dev_errors = validate_model(dev_forms, IndieDeveloper())
        if dev_errors:
            all_errors.update(dev_errors)

        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    def index(self, session, id, message='', **params):
        studio = session.indie_studio(id)
        demo_forms = {}
        code_forms = {}
        image_forms = {}

        for game in studio.mivs_games:
            demo_forms[game.id] = load_forms({}, game, ['MivsDemoInfo'],
                                             read_only=not c.MIVS_SUBMISSIONS_OPEN and not c.HAS_SHOWCASE_ADMIN_ACCESS)
            image_forms['mivs_new'] = load_forms({}, IndieGameImage(), ['MivsScreenshot'], field_prefix='new')
            for image in game.screenshots:
                image_forms[image.id] = load_forms({}, image, ['MivsScreenshot'], field_prefix=image.id,
                                                   read_only=not c.MIVS_SUBMISSIONS_OPEN and not c.HAS_SHOWCASE_ADMIN_ACCESS)
            if game.code_type != c.NO_CODE:
                code_forms['new'] = load_forms({}, IndieGameCode(), ['MivsCode'], field_prefix='new')
                for code in game.codes:
                    code_forms[code.id] = load_forms({}, code, ['MivsCode'], field_prefix=code.id,
                                                     read_only=not c.MIVS_SUBMISSIONS_OPEN and not c.HAS_SHOWCASE_ADMIN_ACCESS)
        for game in studio.arcade_games:
            image_forms['arcade_new'] = load_forms({}, IndieGameImage(), ['ArcadePhoto'], field_prefix='new')
            for image in game.submission_images:
                image_forms[image.id] = load_forms({}, image, ['ArcadePhoto'], field_prefix=image.id,
                                                   read_only=not c.INDIE_ARCADE_SUBMISSIONS_OPEN and not c.HAS_SHOWCASE_ADMIN_ACCESS)
        for game in studio.retro_games:
            image_forms['retro_new'] = load_forms({}, IndieGameImage(), ['RetroScreenshot'], field_prefix='new')
            for image in game.submission_images:
                image_forms[image.id] = load_forms({}, image, ['RetroScreenshot'], field_prefix=image.id,
                                                   read_only=not c.INDIE_RETRO_SUBMISSIONS_OPEN and not c.HAS_SHOWCASE_ADMIN_ACCESS)

        return {
            'message': message,
            'studio': studio,
            'demo_forms': demo_forms,
            'code_forms': code_forms,
            'image_forms': image_forms,
        }

    def view_image(self, session, id):
        image = session.indie_game_image(id)
        return serve_file(image.filepath, name=image.filename, content_type=image.content_type)
    
    def studio(self, session, id, message='', **params):
        studio = session.indie_studio(id)
        forms = load_forms(params, studio, ['StudioInfo'])

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                form.populate_obj(studio)

            raise HTTPRedirect('index?id={}&message={}', studio.id,
                               "Studio information updated.")

        return {
            'message': message,
            'studio': studio,
            'forms': forms,
        }
    
    @ajax
    def validate_studio(self, session, form_list=[], **params):
        if params.get('id') in [None, '', 'None']:
            studio = IndieStudio()
        else:
            studio = session.indie_studio(params.get('id'))

        if not form_list:
            form_list = ['StudioInfo']
        elif isinstance(form_list, str):
            form_list = [form_list]

        forms = load_forms(params, studio, form_list)
        all_errors = validate_model(forms, studio)

        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    def developer(self, session, id='', message='', **params):
        if id in [None, '', 'None']:
            developer = IndieDeveloper()
            studio_id = params.get('studio_id', '')
        else:
            developer = session.indie_developer(id)
            studio_id = developer.studio.id
        
        studio = session.indie_studio(studio_id)

        forms = load_forms(params, developer, ['DeveloperInfo'])

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                form.populate_obj(developer)

            developer.studio_id = studio_id
            session.add(developer)

            if developer.is_new:
                message = f"{developer.full_name} has been added!"
            else:
                message = f"{developer.full_name}'s information has been updated."

            raise HTTPRedirect('index?id={}&message={}', studio_id, message)

        return {
            'message': message,
            'developer': developer,
            'studio': studio,
            'forms': forms,
        }
    
    @ajax
    def validate_developer(self, session, form_list=[], **params):
        if params.get('id') in [None, '', 'None']:
            developer = IndieDeveloper()
        else:
            developer = session.indie_developer(params.get('id'))

        if not form_list:
            form_list = ['DeveloperInfo']
        elif isinstance(form_list, str):
            form_list = [form_list]

        forms = load_forms(params, developer, form_list)
        all_errors = validate_model(forms, developer)

        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    def delete_developer(self, session, id, **params):
        developer = session.indie_developer(id)
        studio = developer.studio
        if developer.gets_emails and len(studio.primary_contacts) == 1:
            raise HTTPRedirect('index?id={}&message={}', studio.id,
                               'You cannot delete the only presenter who receives email updates.')

        session.delete(developer)
        raise HTTPRedirect('index?id={}&message={}', studio.id, 'Presenter deleted.')

    def submit_game(self, session, id, **params):
        game = session.indie_game(id)
        if game.missing_steps:
            raise HTTPRedirect('index?id={}&message={}', game.studio.id,
                               'You have not completed all the prerequisites for submitting your game.')
        else:
            game.submitted = True
            raise HTTPRedirect('index?id={}&message={}', game.studio.id,
                               'Your game has been submitted to our panel of judges.')