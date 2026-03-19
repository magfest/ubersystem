import shutil

import bcrypt
import cherrypy
from cherrypy.lib.static import serve_file

from uber.config import c
from uber.custom_tags import format_image_size
from uber.decorators import all_renderable, ajax, csrf_protected
from uber.errors import HTTPRedirect
from uber.files import FileService
from uber.forms import load_forms
from uber.models import Attendee, File, Group, GuestGroup, IndieGameCode, IndieStudio, IndieDeveloper, IndieGame
from uber.utils import add_opt, check, check_csrf, GuidebookUtils, validate_model


@all_renderable(public=True)
class Root:
    def apply(self, session, message='', **params):
        studio = IndieStudio()
        developer = IndieDeveloper(receives_emails=True)

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
        studio_errors = validate_model(session, forms, IndieStudio())
        if studio_errors:
            all_errors.update(studio_errors)

        dev_forms = load_forms(params, IndieDeveloper(), ['DeveloperInfo'])
        dev_errors = validate_model(session, dev_forms, IndieDeveloper())
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

        mivs_game_screenshots = FileService.files_by_fk_id(session, [game.id for game in studio.mivs_games], and_flags=['mivs_screenshot'])
        arcade_game_photos = FileService.files_by_fk_id(session, [game.id for game in studio.arcade_games], and_flags=['arcade_photo'])
        retro_game_screenshots = FileService.files_by_fk_id(session, [game.id for game in studio.retro_games], and_flags=['retro_screenshot'])

        for game in studio.mivs_games:
            demo_forms[game.id] = load_forms({}, game, ['MivsDemoInfo'],
                                             read_only=not c.MIVS_SUBMISSIONS_OPEN and not c.HAS_SHOWCASE_ADMIN_ACCESS)
            image_forms['mivs_new'] = load_forms({}, File(), ['MivsScreenshot'], field_prefix='new')
            for image_list in mivs_game_screenshots.values():
                for image in image_list:
                    image_forms[image.id] = load_forms({}, image, ['MivsScreenshot'], field_prefix=image.id,
                                                       read_only=not c.MIVS_SUBMISSIONS_OPEN and not c.HAS_SHOWCASE_ADMIN_ACCESS)
            if game.code_type != c.NO_CODE:
                code_forms['new'] = load_forms({}, game, ['MivsCode'], field_prefix='new')
                for code in game.codes:
                    code_forms[code.id] = load_forms({}, code, ['MivsCode'], field_prefix=code.id,
                                                     read_only=not c.MIVS_SUBMISSIONS_OPEN and not c.HAS_SHOWCASE_ADMIN_ACCESS)
        for game in studio.arcade_games:
            image_forms['arcade_new'] = load_forms({}, File(), ['ArcadePhoto'], field_prefix='new')
            for image_list in arcade_game_photos.values():
                for image in image_list:
                    image_forms[image.id] = load_forms({}, image, ['ArcadePhoto'], field_prefix=image.id,
                                                       read_only=not c.INDIE_ARCADE_SUBMISSIONS_OPEN and not c.HAS_SHOWCASE_ADMIN_ACCESS)
        for game in studio.retro_games:
            image_forms['retro_new'] = load_forms({}, File(), ['RetroScreenshot'], field_prefix='new')
            for image_list in retro_game_screenshots.values():
                for image in image_list:
                    image_forms[image.id] = load_forms({}, image, ['RetroScreenshot'], field_prefix=image.id,
                                                       read_only=not c.INDIE_RETRO_SUBMISSIONS_OPEN and not c.HAS_SHOWCASE_ADMIN_ACCESS)

        return {
            'message': message,
            'studio': studio,
            'demo_forms': demo_forms,
            'code_forms': code_forms,
            'image_forms': image_forms,
            'mivs_game_screenshots': mivs_game_screenshots,
            'arcade_game_photos': arcade_game_photos,
            'retro_game_screenshots': retro_game_screenshots,
        }

    def view_image(self, session, id):
        image = session.indie_game_image(id)
        cherrypy.response.headers['Cache-Control'] = 'no-store'
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
        all_errors = validate_model(session, forms, studio)

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
        all_errors = validate_model(session, forms, developer)

        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    def delete_developer(self, session, id, **params):
        developer = session.indie_developer(id)
        studio = developer.studio
        if developer.receives_emails and len(studio.primary_contacts) == 1:
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
    
    def confirm(self, session, id, decision=None, **params):
        studio = session.indie_studio(id)

        if not studio.comped_badges:
            raise HTTPRedirect('index?id={}&message={}', studio.id,
                               'You did not have any games accepted.')
        elif studio.group:
            raise HTTPRedirect('index?id={}&message={}', studio.id,
                               'Your group has already been created.')
        elif studio.after_confirm_deadline and not c.HAS_SHOWCASE_ADMIN_ACCESS:
            raise HTTPRedirect('index?id={}&message={}', studio.id,
                               'The deadline for confirming your acceptance has passed.')

        has_leader = False
        badges_remaining = studio.comped_badges
        developers = sorted(studio.developers, key=lambda d: (not d.receives_emails, d.full_name))
        for dev in developers:
            if not dev.matching_attendee and badges_remaining:
                dev.comped = True
                badges_remaining -= 1
            else:
                dev.comped = False

            if not has_leader and not getattr(dev.matching_attendee, 'group_id', None):
                dev.leader = has_leader = True
            else:
                dev.leader = False

        if cherrypy.request.method == 'POST':
            assert decision in ['accept', 'decline']
            if decision == 'decline':
                for game in studio.games:
                    if game.status == c.ACCEPTED:
                        game.status = c.CANCELLED
                raise HTTPRedirect('index?id={}&message={}', studio.id,
                                   'You have been marked as declining space in the showcase.')
            else:
                group = studio.group = Group(name='Showcase Studio: ' + studio.name, can_add=True)
                session.add(group)
                session.commit()
                for dev in developers:
                    if dev.matching_attendee:
                        add_opt(dev.matching_attendee.ribbon_ints, c.MIVS)
                        if not dev.matching_attendee.group_id:
                            group.attendees.append(dev.matching_attendee)
                            if dev.leader:
                                group.leader_id = dev.matching_attendee.id
                        dev.matching_attendee.indie_developer = dev
                    else:
                        attendee = Attendee(
                            placeholder=True,
                            badge_type=c.ATTENDEE_BADGE,
                            ribbon=c.MIVS,
                            paid=c.NEED_NOT_PAY if dev.comped else c.PAID_BY_GROUP,
                            first_name=dev.first_name,
                            last_name=dev.last_name,
                            cellphone=dev.cellphone,
                            email=dev.email
                        )
                        attendee.indie_developer = dev
                        group.attendees.append(attendee)
                        session.commit()
                        if dev.leader:
                            group.leader_id = attendee.id
                for i in range(badges_remaining):
                    group.attendees.append(Attendee(badge_type=c.ATTENDEE_BADGE, paid=c.NEED_NOT_PAY))
                group.cost = group.calc_default_cost()
                group.guest = GuestGroup()
                group.guest.group_type = c.MIVS
                raise HTTPRedirect('index?id={}&message={}', studio.id, 'Your studio has been registered!')

        return {
            'studio': studio,
            'developers': developers
        }
    
    def show_info(self, session, message='', **params):
        game = session.indie_game(params)
        cherrypy.session['studio_id'] = game.studio.id
        image_form = load_forms({}, File(), ['MivsScreenshot'], field_prefix='new')

        if cherrypy.request.method == 'POST':
            header_image = params.get('header_image')
            thumbnail_image = params.get('thumbnail_image')
            file_handlers = []

            if not params.get('contact_phone', ''):
                message = "Please enter a phone number for MAGFest Indies staff to contact your studio."
            else:
                game.studio.contact_phone = params.get('contact_phone', '')
            
            if not params.get('studio_name', ''):
                message = "Please enter a studio name."
            else:
                game.studio.contact_phone = params.get('contact_phone', '')

            message = check(game)

            if not message:
                existing_header = FileService.get_existing_files(session, game, and_flags=['guidebook_header'])
                if header_image and header_image.filename:
                    file_handler = FileService.file_handler(session, game, flags={'guidebook_header': True})
                    message = file_handler.process_file_upload(header_image,
                                                               allowed_extensions=c.GUIDEBOOK_ALLOWED_IMAGE_TYPES,
                                                               delete_existing=False,
                                                               update_model=game)
                    file_handlers.append(file_handler)
                elif not existing_header:
                    message = f"You must upload a {format_image_size(c.GUIDEBOOK_HEADER_SIZE)} header image."
            
            if not message:
                existing_thumbnail = FileService.get_existing_files(session, game, and_flags=['guidebook_thumbnail'])
                if thumbnail_image and thumbnail_image.filename:
                    file_handler = FileService.file_handler(session, game, flags={'guidebook_thumbnail': True})
                    message = file_handler.process_file_upload(thumbnail_image,
                                                               allowed_extensions=c.GUIDEBOOK_ALLOWED_IMAGE_TYPES,
                                                               update_model=game)
                    file_handlers.append(file_handler)
                elif not existing_thumbnail:
                    message = f"You must upload a {format_image_size(c.GUIDEBOOK_THUMBNAIL_SIZE)} thumbnail image."

            if not message:
                message = check(game) or check(game.studio)

            if message:
                for handler in file_handlers:
                    handler.delete()
            else:
                for handler in file_handlers:
                    FileService.delete_existing_files(session, handler.file_obj, and_flags=handler.file_obj.true_flags)

                if game.studio.group.guest:
                    raise HTTPRedirect('../guests/mivs_show_info?guest_id={}&message={}',
                                       game.studio.group.guest.id, 'Show information updated.')
                raise HTTPRedirect('index?message={}', 'Show information updated.')

        return {
            'message': message,
            'game': game,
            'image_form': image_form,
            'game_submission_images': FileService.get_existing_files(
                session, game, or_flags=['mivs_screenshot', 'arcade_photo', 'retro_screenshot'], uselist=True),
            'game_best_images': FileService.get_existing_files(session, game, and_flags=['use_in_promo'], uselist=True),
            'game_guidebook_header': FileService.get_existing_files(session, game, and_flags=['guidebook_header']),
            'game_guidebook_thumbnail': FileService.get_existing_files(session, game, and_flags=['guidebook_thumbnail']),
        }

    @csrf_protected
    def mark_image(self, session, id):
        image = FileService.from_db_id(session, id).file_obj
        game = session.indie_game(image.fk_id)
        best_images = FileService.get_existing_files(session, game, and_flags=['use_in_promo'], uselist=True)
        if len(best_images) >= 2:
            raise HTTPRedirect('show_info?id={}&message={}', game.id,
                               'You may only have up to two "best" images.')
        image.flags['use_in_promo'] = True
        session.add(image)
        raise HTTPRedirect('show_info?id={}&message={}', game.id,
                           'Screenshot marked as one of your "best" images.')

    @csrf_protected
    def unmark_image(self, session, id):
        image = FileService.from_db_id(session, id).file_obj
        game = session.indie_game(image.fk_id)
        image.flags['use_in_promo'] = False
        session.add(image)
        raise HTTPRedirect('show_info?id={}&message={}', game.id,
                           'Screenshot unmarked as one of your "best" images.')

