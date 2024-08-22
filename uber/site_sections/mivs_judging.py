import cherrypy

from uber.config import c
from uber.decorators import all_renderable, render, site_mappable
from uber.errors import HTTPRedirect
from uber.tasks.email import send_email
from uber.utils import check


@all_renderable()
class Root:
    @site_mappable
    def index(self, session, message='', **params):
        if 'status' in params:
            judge = session.indie_judge(params, bools=['no_game_submission'])
        else:
            judge = session.indie_judge(params, checkgroups=['genres', 'platforms']) if 'id' in params \
                else session.logged_in_judge()

        if cherrypy.request.method == 'POST':
            if 'status' in params:
                if judge.status == c.CONFIRMED:
                    message = 'Thanks for choosing to be a judge this year. ' \
                              'Please take a moment to update your hardware and preferences.'

                raise HTTPRedirect('index?message={}', message)

            message = check(judge)
            if not message:
                raise HTTPRedirect('index?message={}', 'Preferences updated')

        return {
            'message': message,
            'judge': judge
        }

    def studio(self, session, message='', **params):
        studio = session.indie_studio(params)
        if cherrypy.request.method == 'POST':
            # We currently only update notes, though we may add other things to this form later
            raise HTTPRedirect('index?message={}', 'Notes updated')

        return {'studio': studio}

    def game_review(self, session, message='', **params):
        review = session.indie_game_review(params, bools=['game_content_bad', 'read_how_to_play'])
        if cherrypy.request.method == 'POST':
            if review.video_status == c.PENDING and review.game_status == c.PENDING:
                message = 'You must select a Video or Game Status to tell us whether or not ' \
                          'you were able to view the video or download and run the game'
            elif review.game_status == c.PLAYABLE and not review.game_score:
                message = "You must indicate the game's readiness, design, and enjoyment"
            elif review.game_status == c.PLAYABLE and review.game.how_to_play and not review.read_how_to_play:
                message = "Please confirm that you've read the 'How to Play' instructions before reviewing this game."
            elif review.game_status != c.PLAYABLE and review.game_score:
                message = 'If the game is not playable, please leave the score fields blank'
            else:
                if review.video_status in c.MIVS_PROBLEM_STATUSES\
                        and review.video_status != review.orig_value_of('video_status'):
                    body = render('emails/mivs/admin_video_broken.txt', {'review': review}, encoding=None)
                    send_email.delay(c.MIVS_EMAIL, c.MIVS_EMAIL, 'MIVS Video Submission Marked as Broken', body)

                if review.game_status in c.MIVS_PROBLEM_STATUSES\
                        and review.game_status != review.orig_value_of('game_status'):
                    body = render('emails/mivs/admin_game_broken.txt', {'review': review}, encoding=None)
                    send_email.delay(c.MIVS_EMAIL, c.MIVS_EMAIL, 'MIVS Game Submission Marked as Broken', body)

                raise HTTPRedirect('index?message={}{}', review.game.title, ' game review has been uploaded')

        return {
            'review': review,
            'message': message,
            'game_code': session.code_for(review.game)
        }
