import cherrypy
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from uber.config import c
from uber.decorators import ajax, all_renderable, csrf_protected, render, site_mappable
from uber.errors import HTTPRedirect
from uber.forms import load_forms
from uber.models import AdminAccount, Attendee, IndieJudge, IndieGameReview, IndieStudio, IndieGame
from uber.tasks.email import send_email
from uber.utils import check, get_api_service_from_server, normalize_email_legacy, validate_model, listify


def _process_showcase_type(showcase_type, message=''):
    if showcase_type != 'all':
        try:
            showcase_type = int(showcase_type)
        except ValueError:
            message = message or f"Invalid showcase type: {showcase_type}."
            showcase_type = 'all'
    return message, showcase_type


@all_renderable()
class Root:
    def index(self, session, message='', showcase_type='all', show_all=False):
        games = session.indie_games()
        judges = session.indie_judges()
        studios = session.query(IndieStudio).outerjoin(IndieStudio.games)
        message, showcase_type = _process_showcase_type(showcase_type, message)

        if showcase_type != 'all':
            games = games.filter(IndieGame.showcase_type == showcase_type)
            judges = judges.filter(IndieJudge.showcases.contains(showcase_type))

        if not show_all:
            games = games.filter(IndieGame.submitted == True)

        studio_forms = {}
        for studio in studios:
            studio_forms[studio.id] = load_forms({}, studio, ['AdminStudioInfo'])

        return {
            'message': message,
            'judges': judges,
            'games': games,
            'studios': studios,
            'studio_forms': studio_forms,
            'show_all': show_all,
            'showcase_type': showcase_type,
            'showcase_label': 'All' if showcase_type == 'all' else c.SHOWCASE_GAME_TYPES[showcase_type],
        }
    
    def update_studio(self, session, message='', **params):
        studio = session.indie_studio(params.get('id'))

        forms = load_forms(params, studio, ['AdminStudioInfo'])

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                form.populate_obj(studio)
            message = f"{studio.name} updated."
            if params.get('showcase_type'):
                raise HTTPRedirect('index?showcase_type={}&message={}',
                                params.get('showcase_type', 'all'), message)
            raise HTTPRedirect('studios?message={}', message)

    @ajax
    def validate_studio(self, session, form_list=[], **params):
        studio = session.indie_studio(params.get('id'))

        if not form_list:
            form_list = ['AdminStudioInfo']
        elif isinstance(form_list, str):
            form_list = [form_list]

        forms = load_forms(params, studio, form_list)
        all_errors = validate_model(forms, studio, is_admin=True)

        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    def studios(self, session, message=''):
        studios = session.query(IndieStudio).outerjoin(IndieStudio.games)
        studio_forms = {}
        for studio in studios:
            studio_forms[studio.id] = load_forms({}, studio, ['AdminStudioInfo'])

        return {
            'message': message,
            'studios': studios,
            'studio_forms': studio_forms,
        }

    def create_judge(self, session, message='', first_name='', last_name='', email='', showcase_type='all', **params):
        from uber.forms import NewJudgeInfo
        judge = IndieJudge()
        message, showcase_type = _process_showcase_type(showcase_type, message)

        if showcase_type != 'all' and cherrypy.request.method != 'POST':
            if showcase_type in [c.INDIE_RETRO, c.INDIE_ARCADE]:
                params['all_games_showcases'] = [showcase_type]
            else:
                params['assignable_showcases'] = [showcase_type]

        forms = load_forms(params, judge, ['NewJudgeInfo', 'JudgeShowcaseInfo', 'MivsJudgeInfo'])

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                if not isinstance(form, NewJudgeInfo):
                    form.populate_obj(judge)

            # only match on last name and email, to prevent nickname issues; this could cause
            # problems if we had two judges with the same last name AND the same email address
            attendee = session.query(Attendee).filter_by(last_name=last_name, email=email).first()
            index_link = f'index?showcase_type={showcase_type}&message=' + '{}#judges'
            if attendee and attendee.admin_account:
                if attendee.admin_account.judge:
                    raise HTTPRedirect(
                        index_link, f'{attendee.full_name} is already registered as a judge.')
                else:
                    attendee.admin_account.judge = judge
                    session.add(judge)
                    raise HTTPRedirect(index_link, f'{attendee.full_name} has been granted judge access.')
            else:
                session.add(judge)

                if not attendee:
                    attendee = Attendee(first_name=first_name, last_name=last_name, email=email,
                                        placeholder=True, badge_type=c.ATTENDEE_BADGE, paid=c.NEED_NOT_PAY)
                    session.add(attendee)

                attendee.admin_account, password = session.create_admin_account(attendee, judge=judge)
                email_body = render('emails/accounts/new_account.txt', {
                    'password': password,
                    'account': attendee.admin_account,
                    'creator': AdminAccount.admin_name()
                }, encoding=None)
                send_email.delay(
                    c.MIVS_EMAIL,
                    attendee.email_to_address,
                    f'New {c.EVENT_NAME} Indies Judge Account',
                    email_body,
                    model=attendee.to_dict('id'))
            raise HTTPRedirect(
                index_link, f'{attendee.full_name} has been given an admin account as an Indies Judge.')

        return {
            'message': message,
            'judge': judge,
            'forms': forms,
        }

    def edit_judge(self, session, message='', showcase_type='all', **params):
        judge = session.indie_judge(params.get('id'))
        message, showcase_type = _process_showcase_type(showcase_type, message)

        forms = load_forms(params, judge, ['JudgeShowcaseInfo', 'MivsJudgeInfo'])

        available_games = session.indie_games().filter(IndieGame.showcase_type.in_(judge.showcases_ints),
                                                       IndieGame.submitted == True)

        unassigned_games = [
            g for g in available_games if judge.id not in (r.judge_id for r in g.reviews)]
        matching_genre = [
            g for g in unassigned_games if judge.mivs_all_genres or set(judge.genres_ints).intersection(g.genres_ints)]
        matching = [g for g in unassigned_games if g.showcase_type != c.MIVS or 
                    set(judge.platforms_ints).intersection(g.platforms_ints)]
        nonmatching = [g for g in unassigned_games if g not in matching]

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                form.populate_obj(judge)
            if params.get('save_return_to_search', False):
                raise HTTPRedirect('index?message={}&showcase_type={}#{}',
                                f"Successfully updated info for {judge.full_name}.", showcase_type, 'judges')
            raise HTTPRedirect('edit_judge?id={}&message={}&showcase_type={}',
                               judge.id, "Judge info updated.", showcase_type)

        return {
            'judge': judge,
            'forms': forms,
            'message': message,
            'showcase_type': showcase_type,
            'matching': matching,
            'nonmatching': nonmatching,
            'matching_genre': matching_genre,
        }
    
    @ajax
    def validate_judge(self, session, form_list=[], **params):
        if params.get('id') in [None, '', 'None']:
            judge = IndieJudge()
        else:
            judge = session.indie_judge(params.get('id'))

        if not form_list:
            form_list = ['JudgeShowcaseInfo', 'MivsJudgeInfo']
        elif isinstance(form_list, str):
            form_list = [form_list]

        forms = load_forms(params, judge, form_list)
        all_errors = validate_model(forms, judge, is_admin=True)

        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    def disqualify_judge(self, session, message='', id='', **params):
        judge = session.indie_judge(id)
        attendee = judge.attendee

        judge.status = c.DISQUALIFIED
        prior_payment_status = attendee.paid

        if prior_payment_status == c.NEED_NOT_PAY:
            attendee.paid = c.NOT_PAID
            session.add(attendee)

        session.commit()

        email_body = render('emails/mivs/judge_disqualified.txt', {
                    'judge': judge,
                    'prior_payment_status': prior_payment_status,
                }, encoding=None)
        send_email.delay(
            c.MIVS_EMAIL,
            judge.attendee.email_to_address,
            'MIVS Judging Disqualification',
            email_body,
            model=attendee.to_dict('id'))

        raise HTTPRedirect('index?message={}{}', attendee.full_name,
                           ' has been disqualified from judging for this year')

    def judges_owed_refunds(self, session):
        return {
            'judges': [
                a for a in session.query(Attendee).join(Attendee.admin_account)
                .filter(AdminAccount.judge != None)  # noqa: E711
                .options(joinedload(Attendee.group))
                .order_by(Attendee.full_name) if a.paid_for_badge and not a.has_been_refunded
            ]}

    def edit_game(self, session, id, message='', **params):
        game = session.indie_game(id)
        matching_genre, matching, nonmatching = [], [], []

        if game.showcase_type == c.MIVS:
            form_list = ['MivsGameInfo', 'MivsDemoInfo', 'MivsConsents']
        elif game.showcase_type == c.INDIE_ARCADE:
            form_list = ['ArcadeGameInfo', 'ArcadeConsents', 'ArcadeLogistics']
        elif game.showcase_type == c.INDIE_RETRO:
            form_list = ['RetroGameInfo', 'RetroGameDetails', 'RetroLogistics']
        else:
            form_list = []
        
        forms = load_forms(params, game, form_list)

        available_judges = session.indie_judges().filter(IndieJudge.showcases.contains(game.showcase_type),
                                                         IndieJudge.status == c.CONFIRMED)
        unassigned = [j for j in available_judges if j.id not in (r.judge_id for r in game.reviews)]

        if game.showcase_type == c.MIVS:
            matching = [j for j in unassigned if set(game.platforms_ints).intersection(j.platforms_ints)]
        else:
            matching = unassigned
        
        nonmatching = [j for j in unassigned if j not in matching]        
        matching_genre = [
            j for j in unassigned if j.mivs_all_genres or set(game.genres_ints).intersection(j.genres_ints)] if game.genres else []
        
        if cherrypy.request.method == 'POST':
            for form in forms.values():
                form.populate_obj(game)
            if params.get('save_return_to_search', False):
                raise HTTPRedirect('index?message={}&showcase_type={}#{}',
                                f"Successfully updated info for {game.title}.", game.showcase_type, 'games')
            raise HTTPRedirect('edit_game?id={}&message={}', game.id, "Game information updated.")

        return {
            'game': game,
            'studio': game.studio,
            'message': message,
            'forms': forms,
            'matching': matching,
            'matching_genre': matching_genre,
            'nonmatching': nonmatching,
        }
    
    @ajax
    def validate_game(self, session, form_list=[], **params):
        if params.get('id') in [None, '', 'None']:
            game = IndieGame()
        else:
            game = session.indie_game(params.get('id'))

        if not form_list:
            if not game.showcase_type:
                return {"error": "You can't save a game that has no showcase type."}
            if game.showcase_type == c.MIVS:
                form_list = ['MivsGameInfo', 'MivsDemoInfo', 'MivsConsents']
            elif game.showcase_type == c.INDIE_ARCADE:
                form_list = ['ArcadeGameInfo', 'ArcadeConsents', 'ArcadeLogistics']
            elif game.showcase_type == c.INDIE_RETRO:
                form_list = ['RetroGameInfo', 'RetroGameDetails', 'RetroLogistics']
        elif isinstance(form_list, str):
            form_list = [form_list]

        forms = load_forms(params, game, form_list)
        all_errors = validate_model(forms, game, is_admin=True)

        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    @csrf_protected
    def assign(self, session, return_to, game_id=None, judge_id=None):
        if 'edit_game' in return_to:
            what_assigned = "Judge" + ('s' if len(listify(game_id)) > 1 else '')
            return_to = return_to + '&message={}#judges'
        elif 'edit_judge' in return_to:
            what_assigned = "Game" + ('s' if len(listify(judge_id)) > 1 else '')
            return_to = return_to + '&message={}#games'

        if game_id is None:
            raise HTTPRedirect(return_to, 'Please select at least one game to assign.')
        if judge_id is None:
            raise HTTPRedirect(return_to, 'Please select at least one judge to assign.')

        for gid in listify(game_id):
            for jid in listify(judge_id):
                if not session.query(IndieGameReview).filter_by(game_id=gid, judge_id=jid).first():
                    session.add(IndieGameReview(game_id=gid, judge_id=jid))
        raise HTTPRedirect(return_to, f'{what_assigned} successfully assigned!')

    @csrf_protected
    def remove(self, session, return_to, game_id=None, judge_id=None):
        if 'edit_game' in return_to:
            what_removed = "Judge" + ('s' if len(listify(game_id)) > 1 else '')
            return_to = return_to + '&message={}#judges'
        elif 'edit_judge' in return_to:
            what_removed = "Game" + ('s' if len(listify(judge_id)) > 1 else '')
            return_to = return_to + '&message={}#games'

        if game_id is None:
            raise HTTPRedirect(return_to, 'Please select at least one game to remove.')
        if judge_id is None:
            raise HTTPRedirect(return_to, 'Please select at least one judge to remove.')

        for gid in listify(game_id):
            for jid in listify(judge_id):
                review = session.query(IndieGameReview).filter_by(game_id=gid, judge_id=jid).first()
                if review:
                    session.delete(review)
        raise HTTPRedirect(return_to, f'{what_removed} successfully removed.')

    @csrf_protected
    def mark_verdict(self, session, id, status):
        if not status:
            raise HTTPRedirect('edit_game?id={}&message={}#results', id, 'You did not mark a status.')
        else:
            game = session.indie_game(id)
            game.status = int(status)
            raise HTTPRedirect('edit_game?id={}&message={}#results', game.id, f"{game.title} has been marked as {game.status_label}.")

    @csrf_protected
    def send_reviews(self, session, game_id, review_id=None):
        game = session.indie_game(id=game_id)
        for review in game.reviews:
            if review.id in listify(review_id):
                review.send_to_studio = True
            elif review.send_to_studio:
                review.send_to_studio = False
            session.add(review)
        raise HTTPRedirect('edit_game?id={}&message={}#results', game_id, 'Reviews marked for sending!')

    @csrf_protected
    def reset_problems(self, session, game_id, no_emails=False):
        game = session.indie_game(game_id)

        for review in game.reviews:
            if review.has_video_issues:
                review.video_status = c.PENDING
                if not no_emails:
                    body = render('emails/mivs/video_fixed.txt', {'review': review}, encoding=None)
                    send_email.delay(
                        game.admin_email,
                        review.judge.email_to_address,
                        f'{game.showcase_type_label}: Video Problems Resolved for {game.title}',
                        body,
                        model=review.judge.to_dict('id'))
            if review.has_game_issues:
                review.game_status = c.PENDING
                if not no_emails:
                    body = render('emails/mivs/game_fixed.txt', {'review': review}, encoding=None)
                    send_email.delay(
                        game.admin_email,
                        review.judge.email_to_address,
                        f'{game.showcase_type_label}: Game Problems Resolved for {game.title}',
                        body,
                        model=review.judge.to_dict('id'))
        raise HTTPRedirect(
            'edit_game?id={}&message={}{}{}', game.id, game.title,
            ' has been marked as having its judging issues fixed',
            '.' if no_emails else ' and all affected judges have been notified.')
    
    @site_mappable
    def import_judges(self, session, target_server='', api_token='',
                      query='', message='', **params):
        service, service_message, target_url = get_api_service_from_server(target_server, api_token)
        message = message or service_message
        judges, existing_judges, existing_attendees, results = [], [], [], {}

        if service:
            try:
                results = service.mivs.export_judges()
                href_base = '{}/showcase_admin/edit_judge?id={}'
            except Exception as ex:
                message = str(ex)

        if cherrypy.request.method == 'POST' and not message:
            for judge, attendee in results:
                d = {'first_name': attendee['first_name'],
                     'attendee': attendee,
                     'judge': judge,
                     'href': href_base.format(target_url, judge['id'])
                     }

                existing_attendee = session.query(Attendee).filter(
                    func.lower(Attendee.first_name) == attendee['first_name'].lower(),
                    func.lower(Attendee.last_name) == attendee['last_name'].lower(),
                    Attendee.normalized_email == normalize_email_legacy(attendee['email'])).first()
                if existing_attendee and existing_attendee.admin_account and existing_attendee.admin_account.judge:
                    d['existing_judge'] = existing_attendee.admin_account.judge
                    existing_judges.append(d)
                elif existing_attendee:
                    d['existing_attendee'] = existing_attendee
                    existing_attendees.append(d)
                else:
                    judges.append(d)

        return {
            'target_server': target_server,
            'api_token': api_token,
            'message': message,
            'existing_judges': sorted(existing_judges, key=lambda a: a['first_name']),
            'existing_attendees': sorted(existing_attendees, key=lambda a: a['first_name']),
            'judges': sorted(judges, key=lambda a: a['first_name']),
        }

    def confirm_import_judges(self, session, target_server, api_token, judge_ids, **params):
        redirect_url = f'import_judges?target_server={target_server}&api_token={api_token}'
        if cherrypy.request.method != 'POST':
            raise HTTPRedirect(redirect_url)

        judge_ids = judge_ids if isinstance(judge_ids, list) else [judge_ids]

        service, message, target_url = get_api_service_from_server(target_server, api_token)

        if not message:
            try:
                results = service.mivs.export_judges()
            except Exception as ex:
                message = str(ex)

        if message:
            raise HTTPRedirect(redirect_url)

        for old_judge, old_attendee in results:
            judge_id = old_judge.pop('id', '')
            if judge_id not in judge_ids:
                continue
            old_judge.pop('admin_id', '')
            password = ''
            new_judge = IndieJudge().apply(old_judge, restricted=False)
            new_judge.status = c.UNCONFIRMED
            new_judge.no_game_submission = None

            existing_attendee = session.query(Attendee).filter(
                func.lower(Attendee.first_name) == old_attendee['first_name'].lower(),
                func.lower(Attendee.last_name) == old_attendee['last_name'].lower(),
                Attendee.normalized_email == normalize_email_legacy(old_attendee['email'])).first()
            if existing_attendee and existing_attendee.admin_account and existing_attendee.admin_account.judge:
                continue
            elif existing_attendee:
                attendee = existing_attendee
            else:
                old_attendee.pop('id', '')
                old_attendee.pop('badge_num', '')
                attendee = Attendee().apply(old_attendee, restricted=False)
                attendee.badge_status = c.NEW_STATUS
                attendee.placeholder = True
                attendee.badge_type = c.ATTENDEE_BADGE
                attendee.paid = c.NEED_NOT_PAY

            if attendee.admin_account:
                new_judge.admin_id = attendee.admin_account.id
            else:
                attendee.admin_account, password = session.create_admin_account(attendee, judge=new_judge)
                new_judge.admin_id = attendee.admin_account.id
                email_body = render('emails/accounts/new_account.txt', {
                        'password': password,
                        'account': attendee.admin_account,
                        'creator': AdminAccount.admin_name()
                    }, encoding=None)
                send_email.delay(
                    c.MIVS_EMAIL,
                    attendee.email,
                    'New {} MIVS Judge Account'.format(c.EVENT_NAME),
                    email_body,
                    model=attendee.to_dict('id'))

            session.add(new_judge)
            session.add(attendee)

        raise HTTPRedirect(redirect_url + "&message=Judges imported!")