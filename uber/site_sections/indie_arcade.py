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
        forms = load_forms(params, game, ['ArcadeGameInfo', 'ArcadeConsents', 'ArcadeLogistics'])

        if cherrypy.request.method == 'POST':
            if not c.INDIE_ARCADE_SUBMISSIONS_OPEN and not c.HAS_SHOWCASE_ADMIN_ACCESS:
                raise HTTPRedirect('../showcase/index?id={}&message={}', studio_id,
                                   'Sorry, submissions for Indie Arcade are now closed.')
            for form in forms.values():
                form.populate_obj(game)

            session.add(game)
            game.studio = studio
            game.showcase_type = c.INDIE_ARCADE
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
            form_list = ['ArcadeGameInfo', 'ArcadeConsents', 'ArcadeLogistics']
        elif isinstance(form_list, str):
            form_list = [form_list]

        forms = load_forms(params, game, form_list)
        all_errors = validate_model(forms, game)

        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    def photo(self, session, game_id, use_in_promo='', **params):
        if params.get('id') in [None, '', 'None']:
            photo = IndieGameImage()
        else:
            photo = session.indie_game_image(params.get('id'))

        if cherrypy.request.method == 'POST':
            photo.game = session.indie_game(game_id)

            forms = load_forms(params, photo, ['ArcadePhoto'],
                               field_prefix='new' if photo.is_new else photo.id)
            for form in forms.values():
                form.populate_obj(photo)

            session.add(photo)
            if use_in_promo:
                photo.use_in_promo = True

            if use_in_promo:
                raise HTTPRedirect('show_info?id={}&message={}', game_id,
                                   'Photo uploaded.' if photo.is_new else 'Photo updated.')
            else:
                raise HTTPRedirect('../showcase/index?id={}&message={}', photo.game.studio.id,
                                   'Photo uploaded.' if photo.is_new else 'Photo updated.')
    
    @ajax
    def validate_image(self, session, form_list=[], **params):
        if params.get('id') in [None, '', 'None']:
            image = IndieGameImage()
        else:
            image = session.indie_game_image(params.get('id'))

        if not form_list:
            form_list = ['ArcadePhoto']
        elif isinstance(form_list, str):
            form_list = [form_list]

        forms = load_forms(params, image, form_list,
                           field_prefix='new' if image.is_new else image.id)
        all_errors = validate_model(forms, image)

        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    @csrf_protected
    def delete_photo(self, session, id):
        photo = session.indie_game_image(id)
        studio_id = photo.game.studio.id
        session.delete_screenshot(photo)
        raise HTTPRedirect('../showcase/index?id={}&message={}', studio_id, 'Photo deleted.')

    def confirm(self, session, csrf_token=None, decision=None):
        studio = session.logged_in_studio()
        if not studio.comped_badges:
            raise HTTPRedirect('index?message={}', 'You did not have any games accepted')
        elif studio.group:
            raise HTTPRedirect('index?message={}', 'Your group has already been created')
        elif studio.after_confirm_deadline and not c.HAS_SHOWCASE_ADMIN_ACCESS:
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
                                                             is_photo=False, is_header=True)
                    if not header_pic.check_image_size():
                        message = f"Your header image must be {format_image_size(c.GUIDEBOOK_HEADER_SIZE)}."
            elif not game.guidebook_header:
                message = f"You must upload a {format_image_size(c.GUIDEBOOK_HEADER_SIZE)} header image."
            
            if not message:
                if thumbnail_image and thumbnail_image.filename:
                    message = GuidebookUtils.check_guidebook_image_filetype(thumbnail_image)
                    if not message:
                        thumbnail_pic = IndieGameImage.upload_image(thumbnail_image, game_id=game.id,
                                                                    is_photo=False, is_thumbnail=True)
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
