import cherrypy
from pockets import listify
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from uber.config import c
from uber.decorators import all_renderable, csrf_protected, render
from uber.errors import HTTPRedirect
from uber.models import AdminAccount, Attendee, IndieJudge, IndieGameReview, IndieStudio
from uber.tasks.email import send_email
from uber.utils import check, get_api_service_from_server, normalize_email_legacy


@all_renderable()
class Root:
    def index(self, session, message=''):
        return {
            'message': message,
            'judges': session.indie_judges().all(),
            'games': [g for g in session.indie_games() if g.submitted]
        }

    def studios(self, session, message=''):
        return {
            'message': message,
            'studios': session.query(IndieStudio).all()
        }
    
    def import_judges(self, session, target_server='', api_token='',
                      query='', message='', **params):
        service, service_message, target_url = get_api_service_from_server(target_server, api_token)
        message = message or service_message
        judges, existing_judges, existing_attendees, results = [], [], [], {}

        if service:
            try:
                results = service.mivs.judges_export()
                href_base = '{}/mivs_admin/edit_judge?id={}'
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
                results = service.mivs.judges_export()
            except Exception as ex:
                message = str(ex)

        if message:
            raise HTTPRedirect(redirect_url)

        # Rewrite this for Super 2026 to actually use the selection from the page (and rename export_judges)
        for old_judge, old_attendee in results:
            old_judge.pop('id', '')
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
                if False:
                    email_body = render('emails/accounts/new_account.txt', {
                            'password': password,
                            'account': attendee.admin_account,
                            'creator': AdminAccount.admin_name()
                        }, encoding=None)
                    send_email.delay(
                        c.MIVS_EMAIL,
                        c.ADMIN_EMAIL,
                        'New {} MIVS Judge Account'.format(c.EVENT_NAME),
                        email_body,
                        model=attendee.to_dict('id'))

            session.add(new_judge)
            session.add(attendee)

        raise HTTPRedirect(redirect_url + "&message=Judges imported!")

    def create_judge(self, session, message='', first_name='', last_name='', email='', **params):
        judge = session.indie_judge(params, checkgroups=['genres', 'platforms'])
        if cherrypy.request.method == 'POST':
            message = check(judge)
            if not message and not first_name or not last_name or not email:
                message = 'First name, last name, and email address are all required to add a judge'

            if not message:
                # only match on last name and email, to prevent nickname issues; this could cause
                # problems if we had two judges with the same last name AND the same email address
                attendee = session.query(Attendee).filter_by(last_name=last_name, email=email).first()
                if attendee and attendee.admin_account:
                    if attendee.admin_account.judge:
                        raise HTTPRedirect(
                            'index?message={}{}', attendee.full_name, ' is already registered as a judge')
                    else:
                        attendee.admin_account.judge = judge
                        raise HTTPRedirect('index?message={}{}', attendee.full_name, ' has been granted judge access')
                else:
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
                        'New {} MIVS Judge Account'.format(c.EVENT_NAME),
                        email_body,
                        model=attendee.to_dict('id'))
                raise HTTPRedirect(
                    'index?message={}{}', attendee.full_name, ' has been given an admin account as a MIVS Judge')

        return {
            'message': message,
            'judge': judge,
            'first_name': first_name,
            'last_name': last_name,
            'email': email
        }

    def edit_judge(self, session, message='', **params):
        judge = session.indie_judge(params, checkgroups=['genres', 'platforms'], bools=['no_game_submission'])
        if cherrypy.request.method == 'POST':
            message = check(judge)
            if not message:
                raise HTTPRedirect('index?message={}', 'Judge info updated')

        return {
            'judge': judge,
            'message': message
        }

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

    def assign_games(self, session, judge_id, message=''):
        judge = session.indie_judge(judge_id)
        unassigned_games = [
            g for g in session.indie_games() if g.submitted and judge.id not in (r.judge_id for r in g.reviews)]
        matching_genre = [
            g for g in unassigned_games if judge.mivs_all_genres or set(judge.genres_ints).intersection(g.genres_ints)]
        matching = [g for g in unassigned_games if set(judge.platforms_ints).intersection(g.platforms_ints)]
        nonmatching = [g for g in unassigned_games if g not in matching]

        return {
            'judge': judge,
            'message': message,
            'matching': matching,
            'matching_genre': matching_genre,
            'nonmatching': nonmatching
        }

    def assign_judges(self, session, game_id, message=''):
        game = session.indie_game(game_id)
        unassigned_judges = [j for j in session.indie_judges() if j.id not in (r.judge_id for r in game.reviews)]
        matching_genre = [
            j for j in unassigned_judges if j.mivs_all_genres or set(game.genres_ints).intersection(j.genres_ints)]
        matching = [j for j in unassigned_judges if set(game.platforms_ints).intersection(j.platforms_ints)]
        nonmatching = [j for j in unassigned_judges if j not in matching]

        return {
            'game': game,
            'message': message,
            'matching': matching,
            'matching_genre': matching_genre,
            'nonmatching': nonmatching
        }

    @csrf_protected
    def assign(self, session, game_id, judge_id, return_to):
        return_to = return_to + '&message={}'
        for gid in listify(game_id):
            for jid in listify(judge_id):
                if not session.query(IndieGameReview).filter_by(game_id=gid, judge_id=jid).first():
                    session.add(IndieGameReview(game_id=gid, judge_id=jid))
        raise HTTPRedirect(return_to, 'Assignment successful')

    @csrf_protected
    def remove(self, session, game_id, judge_id, return_to):
        return_to = return_to + '&message={}'
        for gid in listify(game_id):
            for jid in listify(judge_id):
                review = session.query(IndieGameReview).filter_by(game_id=gid, judge_id=jid).first()
                if review:
                    session.delete(review)
        raise HTTPRedirect(return_to, 'Removal successful')

    def game_results(self, session, id, message=''):
        return {
            'game': session.indie_game(id),
            'message': message
        }

    @csrf_protected
    def mark_verdict(self, session, id, status):
        if not status:
            raise HTTPRedirect('index?message={}', 'You did not mark a status')
        else:
            game = session.indie_game(id)
            game.status = int(status)
            raise HTTPRedirect('index?message={}{}{}', game.title, ' has been marked as ', game.status_label)

    @csrf_protected
    def send_reviews(self, session, game_id, review_id=None):
        game = session.indie_game(id=game_id)
        for review in game.reviews:
            if review.id in listify(review_id):
                review.send_to_studio = True
            elif review.send_to_studio:
                review.send_to_studio = False
            session.add(review)
        raise HTTPRedirect('game_results?id={}&message={}', game_id, 'Reviews marked for sending!')

    def problems(self, session, game_id):
        game = session.indie_game(game_id)
        if not game.has_issues:
            raise HTTPRedirect('index?message={}{}', game.title, ' has no outstanding issues')
        else:
            return {'game': game}

    @csrf_protected
    def reset_problems(self, session, game_id):
        game = session.indie_game(game_id)
        for review in game.reviews:
            if review.has_video_issues:
                body = render('emails/mivs/video_fixed.txt', {'review': review}, encoding=None)
                send_email.delay(
                    c.MIVS_EMAIL,
                    review.judge.email_to_address,
                    'MIVS: Video Problems Resolved for {}'.format(review.game.title),
                    body,
                    model=review.judge.to_dict('id'))
                review.video_status = c.PENDING
            if review.has_game_issues:
                body = render('emails/mivs/game_fixed.txt', {'review': review}, encoding=None)
                send_email.delay(
                    c.MIVS_EMAIL,
                    review.judge.email_to_address,
                    'MIVS: Game Problems Resolved for {}'.format(review.game.title),
                    body,
                    model=review.judge.to_dict('id'))
                review.game_status = c.PENDING
        raise HTTPRedirect(
            'index?message={}{}', review.game.title, ' has been marked as having its judging issues fixed')
