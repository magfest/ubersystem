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
            forms = load_forms(params, code, ['MivsCode'])
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

        forms = load_forms(params, code, form_list)
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
            forms = load_forms(params, screenshot, ['MivsScreenshot'])
            for form in forms.values():
                form.populate_obj(screenshot)

            session.add(screenshot)
            if use_in_promo:
                screenshot.use_in_promo = True

            if use_in_promo:
                raise HTTPRedirect('show_info?id={}&message={}', game_id,
                                   'Screenshot uploaded.' if screenshot.is_new else 'Screenshot updated.')
            else:
                raise HTTPRedirect('../showcase/index?id={}&message={}', screenshot.game.studio.id,
                                   'Screenshot uploaded.' if screenshot.is_new else 'Screenshot updated.')
    
    @ajax
    def validate_image(self, session, form_list=[], **params):
        if params.get('id') in [None, '', 'None']:
            code = IndieGameImage()
        else:
            code = session.indie_game_image(params.get('id'))

        if not form_list:
            form_list = ['MivsScreenshot']
        elif isinstance(form_list, str):
            form_list = [form_list]

        forms = load_forms(params, code, form_list)
        all_errors = validate_model(forms, code)

        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    @csrf_protected
    def delete_screenshot(self, session, id):
        screenshot = session.indie_game_image(id)
        studio_id = screenshot.game.studio.id
        session.delete_screenshot(screenshot)
        raise HTTPRedirect('../showcase/index?id={}&message={}', studio_id, 'Screenshot deleted.')

    @csrf_protected
    def mark_screenshot(self, session, id):
        screenshot = session.indie_game_image(id)
        if len(screenshot.game.best_screenshots) >= 2:
            raise HTTPRedirect('show_info?id={}&message={}', screenshot.game.id,
                               'You may only have up to two "best" screenshots')
        screenshot.use_in_promo = True
        session.add(screenshot)
        raise HTTPRedirect('show_info?id={}&message={}', screenshot.game.id,
                           'Screenshot marked as one of your "best" screenshots')

    @csrf_protected
    def unmark_screenshot(self, session, id):
        screenshot = session.indie_game_image(id, applicant=True)
        screenshot.use_in_promo = False
        session.add(screenshot)
        raise HTTPRedirect('show_info?id={}&message={}', screenshot.game.id,
                           'Screenshot unmarked as one of your "best" screenshots')

    @csrf_protected
    def delete_code(self, session, id):
        code = session.indie_game_code(id)
        studio_id = code.game.studio.id
        session.delete(code)
        raise HTTPRedirect('../showcase/index?id={}&message={}', studio_id, 'Code deleted.')

    def confirm(self, session, csrf_token=None, decision=None):
        studio = session.logged_in_studio()
        if not studio.comped_badges:
            raise HTTPRedirect('index?message={}', 'You did not have any games accepted')
        elif studio.group:
            raise HTTPRedirect('index?message={}', 'Your group has already been created')
        elif studio.after_confirm_deadline and not c.HAS_MIVS_ADMIN_ACCESS:
            raise HTTPRedirect('index?message={}', 'The deadline for confirming your acceptance has passed.')

        has_leader = False
        badges_remaining = studio.comped_badges
        developers = sorted(studio.developers, key=lambda d: (not d.primary_contact, d.full_name))
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
            check_csrf(csrf_token)
            assert decision in ['Accept', 'Decline']
            if decision == 'Decline':
                for game in studio.games:
                    if game.status == c.ACCEPTED:
                        game.status = c.CANCELLED
                raise HTTPRedirect('index?message={}', 'You have been marked as declining space in the showcase')
            else:
                group = studio.group = Group(name='MIVS Studio: ' + studio.name, can_add=True)
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
                raise HTTPRedirect('index?message={}', 'Your studio has been registered')

        return {
            'studio': studio,
            'developers': developers
        }

    def show_info(self, session, id, message='', **params):
        game = session.indie_game(id=id)
        header_pic, thumbnail_pic = None, None
        cherrypy.session['studio_id'] = game.studio.id
        if cherrypy.request.method == 'POST':
            header_image = params.get('header_image')
            thumbnail_image = params.get('thumbnail_image')
            game.apply(params, bools=['tournament_at_event', 'has_multiplayer', 'leaderboard_challenge'],
                       restricted=False)  # Setting restricted to false lets us define custom bools and checkgroups
            game.studio.name = params.get('studio_name', '')

            if not params.get('contact_phone', ''):
                message = "Please enter a phone number for MIVS staff to contact your studio."
            else:
                game.studio.contact_phone = params.get('contact_phone', '')

            if header_image and header_image.filename:
                message = GuidebookUtils.check_guidebook_image_filetype(header_image)
                if not message:
                    header_pic = IndieGameImage.upload_image(header_image, game_id=game.id,
                                                             is_screenshot=False, is_header=True)
                    if not header_pic.check_image_size():
                        message = f"Your header image must be {format_image_size(c.GUIDEBOOK_HEADER_SIZE)}."
            elif not game.guidebook_header:
                message = f"You must upload a {format_image_size(c.GUIDEBOOK_HEADER_SIZE)} header image."
            
            if not message:
                if thumbnail_image and thumbnail_image.filename:
                    message = GuidebookUtils.check_guidebook_image_filetype(thumbnail_image)
                    if not message:
                        thumbnail_pic = IndieGameImage.upload_image(thumbnail_image, game_id=game.id,
                                                                    is_screenshot=False, is_thumbnail=True)
                        if not thumbnail_pic.check_image_size():
                            message = f"Your thumbnail image must be {format_image_size(c.GUIDEBOOK_THUMBNAIL_SIZE)}."
                elif not game.guidebook_thumbnail:
                    message = f"You must upload a {format_image_size(c.GUIDEBOOK_THUMBNAIL_SIZE)} thumbnail image."

            if not message:
                message = check(game) or check(game.studio)
            if not message:
                session.add(game)
                if header_pic:
                    if game.guidebook_header:
                        session.delete(game.guidebook_header)
                    session.add(header_pic)
                if thumbnail_pic:
                    if game.guidebook_thumbnail:
                        session.delete(game.guidebook_thumbnail)
                    session.add(thumbnail_pic)

                if game.studio.group.guest:
                    raise HTTPRedirect('../guests/mivs_show_info?guest_id={}&message={}',
                                       game.studio.group.guest.id, 'Game information uploaded')
                raise HTTPRedirect('index?message={}', 'Game information uploaded')

        return {
            'message': message,
            'game': game,
        }
