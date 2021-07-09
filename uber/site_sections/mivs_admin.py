import os

import bcrypt
import cherrypy
from pockets import listify
from sqlalchemy import and_, or_
from sqlalchemy.orm import joinedload

from uber.config import c
from uber.decorators import all_renderable, csrf_protected, render
from uber.errors import HTTPRedirect
from uber.models import AdminAccount, Attendee, Group, IndieGame, IndieGameReview, IndieStudio
from uber.tasks.email import send_email
from uber.utils import check, genpasswd


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

                if not attendee:
                    attendee = Attendee(first_name=first_name, last_name=last_name, email=email,
                                        placeholder=True, badge_type=c.ATTENDEE_BADGE, paid=c.NEED_NOT_PAY)
                    session.add(attendee)

                password = genpasswd()
                attendee.admin_account = AdminAccount(
                    judge=judge,
                    hashed=bcrypt.hashpw(password, bcrypt.gensalt())
                )
                email_body = render('emails/accounts/new_account.txt', {
                    'password': password,
                    'account': attendee.admin_account
                }, encoding=None)
                send_email.delay(
                    c.MIVS_EMAIL,
                    attendee.email,
                    'New {} Ubersystem Account'.format(c.EVENT_NAME),
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

    def judges_owed_refunds(self, session):
        return {
            'judges': [
                a for a in session.query(Attendee).join(Attendee.admin_account)
                    .filter(AdminAccount.judge != None)
                    .options(joinedload(Attendee.group))
                    .order_by(Attendee.full_name) if a.paid_for_badge and not a.has_been_refunded
            ]}  # noqa: E711

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
                    review.judge.email,
                    'MIVS: Video Problems Resolved for {}'.format(review.game.title),
                    body,
                    model=review.judge.to_dict('id'))
                review.video_status = c.PENDING
            if review.has_game_issues:
                body = render('emails/mivs/game_fixed.txt', {'review': review}, encoding=None)
                send_email.delay(
                    c.MIVS_EMAIL,
                    review.judge.email,
                    'MIVS: Game Problems Resolved for {}'.format(review.game.title),
                    body,
                    model=review.judge.to_dict('id'))
                review.game_status = c.PENDING
        raise HTTPRedirect(
            'index?message={}{}', review.game.title, ' has been marked as having its judging issues fixed')
