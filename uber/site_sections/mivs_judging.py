from uber.common import *


@all_renderable(c.INDIE_JUDGE)
class Root:
    def index(self, session, message='', **params):
        judge = session.indie_judge(params, checkgroups=['genres', 'platforms']) if 'id' in params else session.logged_in_judge()
        if cherrypy.request.method == 'POST':
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

    def video_review(self, session, message='', **params):
        review = session.indie_game_review(params)
        if cherrypy.request.method == 'POST':
            if review.video_status == c.PENDING:
                message = 'You must select a Video Status to tell us whether or not you were able to view the video'
            elif review.video_status == c.MIVS_VIDEO_REVIEWED and review.video_score == c.PENDING:
                message = 'You must indicate whether or not you believe the game should pass to round 2'
            else:
                if review.video_status in c.MIVS_PROBLEM_STATUSES\
                        and review.video_status != review.orig_value_of('video_status'):
                    body = render('emails/admin_video_broken.txt', {'review': review})
                    send_email(c.MIVS_EMAIL, c.MIVS_EMAIL, 'MIVS Video Submission Marked as Broken', body)
                raise HTTPRedirect('index?message={}{}', review.game.title, ' video review has been uploaded')

        return {
            'message': message,
            'review': review
        }

    def game_review(self, session, message='', **params):
        review = session.indie_game_review(params, bools=['game_content_bad'])
        if cherrypy.request.method == 'POST':
            if review.game_status == c.PENDING:
                message = 'You must select a Game Status to tell us whether or not you were able to download and run the game'
            elif review.game_status == c.PLAYABLE and not review.game_score:
                message = 'You must indicate whether or not you believe the game should be accepted'
            elif review.game_status != c.PLAYABLE and review.game_score:
                message = 'If the game is not playable, please leave the score field blank'
            else:
                if review.game_status in c.MIVS_PROBLEM_STATUSES\
                        and review.game_status != review.orig_value_of('game_status'):
                    body = render('emails/admin_game_broken.txt', {'review': review})
                    send_email(c.MIVS_EMAIL, c.MIVS_EMAIL, 'MIVS Game Submission Marked as Broken', body)
                raise HTTPRedirect('index?message={}{}', review.game.title, ' game review has been uploaded')

        return {
            'review': review,
            'message': message,
            'game_code': session.code_for(review.game)
        }
