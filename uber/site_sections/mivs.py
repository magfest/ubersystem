import shutil

import bcrypt
import cherrypy
from cherrypy.lib.static import serve_file

from uber.config import c
from uber.decorators import all_renderable, csrf_protected
from uber.errors import HTTPRedirect
from uber.models import Attendee, Group, GuestGroup, IndieDeveloper, IndieStudio
from uber.utils import check, check_csrf


@all_renderable(public=True)
class Root:
    def index(self, session, message='', **params):
        if cherrypy.request.method == 'POST':
            game = session.indie_game(params, applicant=True)
            message = check(game)
            if not message:
                session.add(game)
                raise HTTPRedirect('index?message={}', 'Game information updated')

        return {
            'message': message,
            'studio': session.logged_in_studio()
        }

    def logout(self):
        cherrypy.session.pop('studio_id', None)
        raise HTTPRedirect('studio?message={}', 'You have been logged out')

    def continue_app(self, id):
        cherrypy.session['studio_id'] = id
        raise HTTPRedirect('index')

    def login(self, session, message='', studio_name=None, password=None):
        if cherrypy.request.method == 'POST':
            studio = session.query(IndieStudio).filter_by(name=studio_name).first()
            if not studio:
                message = 'No studio exists with that name'
            elif not studio.hashed == bcrypt.hashpw(password, studio.hashed):
                message = 'That is not the correct password'
            else:
                raise HTTPRedirect('continue_app?id={}', studio.id)

        return {'message': message}

    def studio(self, session, message='', **params):
        params.pop('id', None)
        studio = session.indie_studio(dict(params, id=cherrypy.session.get('studio_id', 'None')), restricted=True)
        developer = session.indie_developer(params, restricted=True)

        if cherrypy.request.method == 'POST':
            message = check(studio)
            if not message and studio.is_new:
                message = check(developer)
            if not message:
                session.add(studio)
                if studio.is_new:
                    developer.studio, developer.primary_contact = studio, True
                    session.add(developer)
                raise HTTPRedirect('continue_app?id={}', studio.id)

        return {
            'message': message,
            'studio': studio,
            'developer': developer
        }

    def game(self, session, message='', **params):
        game = session.indie_game(params, checkgroups=['genres', 'platforms'],
                                  bools=['agreed_liability', 'agreed_showtimes'], applicant=True)
        if cherrypy.request.method == 'POST':
            message = check(game)
            if not message:
                session.add(game)
                raise HTTPRedirect('index?message={}', 'Game information uploaded')

        return {
            'game': game,
            'message': message
        }

    def developer(self, session, message='', **params):
        developer = session.indie_developer(params, applicant=True, restricted=True)
        if cherrypy.request.method == 'POST':
            message = check(developer)
            if not message:
                primaries = session.query(IndieDeveloper).filter_by(
                    studio_id=developer.studio_id, primary_contact=True).all()

                if not developer.primary_contact and len(primaries) == 1 and developer.id == primaries[0].id:
                    message = "Studio requires at least one presenter to receive emails."
                else:
                    session.add(developer)
                    raise HTTPRedirect('index?message={}', 'Presenters updated')

        return {
            'message': message,
            'developer': developer
        }

    @csrf_protected
    def delete_developer(self, session, id):
        developer = session.indie_developer(id, applicant=True)
        assert not developer.primary_contact, 'You cannot delete the primary contact for a studio'
        session.delete(developer)
        raise HTTPRedirect('index?message={}', 'Presenter deleted')

    def code(self, session, game_id, message='', **params):
        code = session.indie_game_code(params, bools=['unlimited_use'], applicant=True)
        code.game = session.indie_game(game_id, applicant=True)
        if cherrypy.request.method == 'POST':
            message = check(code)
            if not message:
                session.add(code)
                raise HTTPRedirect('index?message={}', 'Code added')

        return {
            'message': message,
            'code': code
        }

    def screenshot(self, session, game_id, message='', use_in_promo='', image=None, **params):
        screenshot = session.indie_game_image(params, applicant=True)
        screenshot.game = session.indie_game(game_id, applicant=True)
        if cherrypy.request.method == 'POST':
            screenshot.filename = image.filename
            screenshot.content_type = image.content_type.value
            screenshot.extension = image.filename.split('.')[-1].lower()
            if use_in_promo:
                screenshot.use_in_promo = True
            message = check(screenshot)
            if not message:
                with open(screenshot.filepath, 'wb') as f:
                    shutil.copyfileobj(image.file, f)
                if use_in_promo:
                    raise HTTPRedirect('show_info?id={}&message={}', screenshot.game.id, 'Screenshot Uploaded')
                else:
                    raise HTTPRedirect('index?message={}', 'Screenshot Uploaded')

        return {
            'message': message,
            'use_in_promo': use_in_promo,
            'screenshot': screenshot
        }

    def view_image(self, session, id):
        screenshot = session.indie_game_image(id)
        return serve_file(screenshot.filepath, name=screenshot.filename, content_type=screenshot.content_type)

    @csrf_protected
    def delete_screenshot(self, session, id):
        screenshot = session.indie_game_image(id, applicant=True)
        session.delete_screenshot(screenshot)
        raise HTTPRedirect('index?message={}', 'Screenshot deleted')

    @csrf_protected
    def mark_screenshot(self, session, id):
        screenshot = session.indie_game_image(id, applicant=True)
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
        code = session.indie_game_code(id, applicant=True)
        session.delete(code)
        raise HTTPRedirect('index?message={}', 'Code deleted')

    @csrf_protected
    def submit_game(self, session, id):
        game = session.indie_game(id, applicant=True)
        if not game.submittable:
            raise HTTPRedirect('index?message={}', 'You have not completed all the prerequisites for your game')
        else:
            game.submitted = True
            raise HTTPRedirect('index?message={}', 'Your game has been submitted to our panel of judges')

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
                        if not dev.matching_attendee.group_id:
                            group.attendees.append(dev.matching_attendee)
                            if dev.leader:
                                group.leader_id = dev.matching_attendee.id
                    else:
                        attendee = Attendee(
                            placeholder=True,
                            badge_type=c.ATTENDEE_BADGE,
                            paid=c.NEED_NOT_PAY if dev.comped else c.PAID_BY_GROUP,
                            first_name=dev.first_name,
                            last_name=dev.last_name,
                            cellphone=dev.cellphone,
                            email=dev.email
                        )
                        group.attendees.append(attendee)
                        session.commit()
                        if dev.leader:
                            group.leader_id = attendee.id
                for i in range(badges_remaining):
                    group.attendees.append(Attendee(badge_type=c.ATTENDEE_BADGE, paid=c.NEED_NOT_PAY))
                group.cost = group.default_cost
                group.guest = GuestGroup()
                group.guest.group_type = c.MIVS
                raise HTTPRedirect('index?message={}', 'Your studio has been registered')

        return {
            'studio': studio,
            'developers': developers
        }

    def show_info(self, session, id, message='', promo_image=None, **params):
        game = session.indie_game(id=id)
        cherrypy.session['studio_id'] = game.studio.id
        if cherrypy.request.method == 'POST':
            game.apply(params, bools=['tournament_at_event', 'has_multiplayer', 'leaderboard_challenge'],
                       restricted=False)  # Setting restricted to false lets us define custom bools and checkgroups
            game.studio.name = params.get('studio_name', '')
            if not params.get('contact_phone', ''):
                message = "Please enter a phone number for MIVS staff to contact your studio."
            else: 
                game.studio.contact_phone = params.get('contact_phone', '')
            if promo_image:
                image = session.indie_game_image(params)
                image.game = game
                image.content_type = promo_image.content_type.value
                image.extension = promo_image.filename.split('.')[-1].lower()
                image.is_screenshot = False
                message = check(image)
                if not message:
                    with open(image.filepath, 'wb') as f:
                        shutil.copyfileobj(promo_image.file, f)
            message = check(game) or check(game.studio)
            if not message:
                session.add(game)
                if game.studio.group.guest:
                    raise HTTPRedirect('../guests/mivs_show_info?guest_id={}&message={}', 
                                       game.studio.group.guest.id, 'Game information uploaded')
                raise HTTPRedirect('index?message={}', 'Game information uploaded')

        return {
            'message': message,
            'game': game,
        }
