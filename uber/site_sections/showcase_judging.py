import cherrypy

from uber.config import c
from uber.decorators import all_renderable, ajax, render, site_mappable
from uber.errors import HTTPRedirect
from uber.forms import load_forms
from uber.models import IndieGameReview
from uber.tasks.email import send_email
from uber.utils import check, validate_model


@all_renderable()
class Root:
    @site_mappable
    def index(self, session, message='', **params):
        judge = session.indie_judge(params.get('id')) if 'id' in params else session.logged_in_judge()

        forms = load_forms(params, judge, ['MivsJudgeInfo'])

        if cherrypy.request.method == 'POST':
            if 'status' in params:
                if params['status'] not in map(str, [c.CONFIRMED, c.NEXT_YEAR, c.CANCELLED]):
                    message = "Not a valid option."
                else:
                    for form in forms.values():
                        form.populate_obj(judge)
                    judge.status = int(params['status'])
                    if judge.status == c.CONFIRMED:
                        message = 'Thanks for choosing to be a judge this year!'
                        if c.MIVS in judge.showcases_ints:
                            message += ' Please take a moment to update your hardware and preferences.'
                raise HTTPRedirect('index?id={}&message={}', judge.id, message)
            else:
                if judge.status != c.CONFIRMED:
                    raise HTTPRedirect('index?id={}&message={}', judge.id, 'Please select an option.')
                for form in forms.values():
                    form.populate_obj(judge)
                raise HTTPRedirect('index?id={}&message={}', judge.id, 'Preferences updated.')

        return {
            'message': message,
            'judge': judge,
            'forms': forms,
        }
    
    @ajax
    def validate_judge(self, session, form_list=[], **params):
        judge = session.indie_judge(params.get('id')) if 'id' in params else session.logged_in_judge()

        if not form_list:
            form_list = ['MivsJudgeInfo']
        elif isinstance(form_list, str):
            form_list = [form_list]

        forms = load_forms(params, judge, form_list)
        all_errors = validate_model(forms, judge)

        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    def game_review(self, session, message='', **params):
        review = session.indie_game_review(params.get('id'))

        form_list = ['GameReview']
        if review.game.showcase_type == c.MIVS:
            game_form_list = ['MivsGameInfo', 'MivsDemoInfo', 'MivsConsents']
        elif review.game.showcase_type == c.INDIE_ARCADE:
            game_form_list = ['ArcadeGameInfo', 'ArcadeConsents', 'ArcadeLogistics']
        elif review.game.showcase_type == c.INDIE_RETRO:
            game_form_list = ['RetroGameInfo', 'RetroGameDetails', 'RetroLogistics']
        else:
            game_form_list = []

        forms = load_forms(params, review, form_list)
        game_forms = load_forms({}, review.game, game_form_list, read_only=True)

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                form.populate_obj(review)

            if review.video_status in c.MIVS_PROBLEM_STATUSES\
                    and review.video_status != review.orig_value_of('video_status'):
                body = render('emails/mivs/admin_video_broken.txt', {'review': review}, encoding=None)
                send_email.delay(review.game.admin_email, review.game.admin_email, 'Indies Video Submission Marked as Broken', body)

            if review.game_status in c.MIVS_PROBLEM_STATUSES\
                    and review.game_status != review.orig_value_of('game_status'):
                body = render('emails/mivs/admin_game_broken.txt', {'review': review}, encoding=None)
                send_email.delay(review.game.admin_email, review.game.admin_email, 'Indies Game Submission Marked as Broken', body)

            raise HTTPRedirect('index?id={}&message={}{}', review.judge.id,
                               review.game.title, ' game review has been uploaded')

        return {
            'review': review,
            'game': review.game,
            'message': message,
            'game_code': session.code_for(review.game),
            'forms': forms,
            'game_forms': game_forms,
        }
    
    @ajax
    def validate_review(self, session, form_list=[], **params):
        if params.get('id') in [None, '', 'None']:
            review = IndieGameReview()
        else:
            review = session.indie_game_review(params.get('id'))

        if not form_list:
            form_list = ['GameReview']
        elif isinstance(form_list, str):
            form_list = [form_list]

        forms = load_forms(params, review, form_list)
        all_errors = validate_model(forms, review)

        if all_errors:
            return {"error": all_errors}

        return {"success": True}
