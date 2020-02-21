import shutil
from datetime import datetime, timedelta

import cherrypy
from cherrypy.lib.static import serve_file
from pockets import listify
from pytz import UTC

from uber.config import c
from uber.decorators import all_renderable, csrf_protected, render
from uber.errors import HTTPRedirect
from uber.models import Email, MITSTeam
from uber.tasks.email import send_email
from uber.utils import check, localized_now


@all_renderable(public=True)
class Root:
    def index(self, session, message=''):
        return {
            'message': message,
            'team': session.logged_in_mits_team()
        }

    def logout(self):
        cherrypy.session.pop('mits_team_id', None)
        raise HTTPRedirect('team')

    def continue_app(self, session, id):
        session.log_in_as_mits_team(id, redirect_to='index')

    def login_explanation(self, message=''):
        return {'message': message}

    def cancel(self, session, id):
        team = session.mits_team(id)

        if team.status != c.ACCEPTED:
            team.status = c.CANCELLED
            raise HTTPRedirect('index?message={}', 'You have successfully cancelled your application.')
        else:
            raise HTTPRedirect(
                'Your application has already been accepted. Please contact us at {}.".format(c.MITS_EMAIL)')

    @csrf_protected
    def uncancel(self, session, id):
        team = session.mits_team(id)
        team.status = c.PENDING

        raise HTTPRedirect('index?message={}', 'Application re-enabled.')

    def view_picture(self, session, id):
        picture = session.mits_picture(id)
        return serve_file(picture.filepath, name=picture.filename, content_type=picture.content_type)

    def download_doc(self, session, id):
        doc = session.mits_document(id)
        cherrypy.response.headers['Content-Disposition'] = 'attachment; filename="{}"'.format(doc.filename)
        return serve_file(doc.filepath, name=doc.filename)

    def check_if_applied(self, session, message='', **params):
        if cherrypy.request.method == 'POST':
            subject = c.EVENT_NAME_AND_YEAR + ' MITS Team Confirmation'

            if 'email' not in params:
                message = "Please enter an email address."

            if not message:
                last_email = (session.query(Email)
                              .filter(Email.to.ilike(params['email']))
                              .filter_by(subject=subject)
                              .order_by(Email.when.desc()).first())
                if not last_email or last_email.when < (
                            localized_now() - timedelta(days=7)):
                    can_send_email = True
                else:
                    can_send_email = False

                mits_teams = session.query(MITSTeam).all()

                match_counter = 0
                for team in mits_teams:
                    if params['email'] in team.email:
                        match_counter += 1

                        if can_send_email:
                            send_email.delay(
                                c.MITS_EMAIL,
                                params['email'],
                                subject,
                                render('emails/mits/mits_check.txt',
                                       {'team': team}, encoding=None),
                                cc=team.email,
                                model=team.to_dict('id'))

                if match_counter:
                    message = 'We found {} team{}.{}'\
                        .format(match_counter, 's' if match_counter > 1 else '',
                                ' Please check your email for a link to your application.'
                                if can_send_email else ' Please check your spam or junk folder.')

        return {'message': message}

    def team(self, session, message='', **params):
        params.pop('id', None)
        team = session.mits_team(dict(params, id=cherrypy.session.get('mits_team_id', 'None')), restricted=True)
        applicant = session.mits_applicant(params, restricted=True)

        if cherrypy.request.method == 'POST':
            if 'no_showcase' in params:
                team.showcase_interest = False
            if 'no_panel' in params:
                team.panel_interest = False
            if 'no_hotel_space' in params:
                for applicant in team.applicants:
                    applicant.declined_hotel_space = True
            message = check(team)
            if not message and team.is_new:
                applicant.team = team
                message = check(applicant)
            if not message:
                session.add(team)
                if team.is_new:
                    applicant.primary_contact = True
                    session.add(applicant)
                raise HTTPRedirect('continue_app?id={}', team.id)

        return {
            'message': message,
            'team': team,
            'applicant': applicant
        }

    def applicant(self, session, message='', **params):
        applicant = session.mits_applicant(params, applicant=True)
        if applicant.attendee_id:
            raise HTTPRedirect(
                '../preregistration/confirm?id={}&return_to={}', applicant.attendee_id, '../mits/')

        if cherrypy.request.method == 'POST':
            message = check(applicant)
            if not message:
                session.add(applicant)
                raise HTTPRedirect('index?message={}', 'Team member uploaded')

        return {
            'message': message,
            'applicant': applicant
        }

    @csrf_protected
    def set_primary_contact(self, session, id, enable=False):
        applicant = session.mits_applicant(id, applicant=True)
        if not enable and len(applicant.team.primary_contacts) == 1:
            raise HTTPRedirect('index?message={}', 'At least one team member must be designated to receive emails')
        else:
            applicant.primary_contact = bool(enable)
            raise HTTPRedirect('index?message={}', 'Email designation updated')

    @csrf_protected
    def delete_applicant(self, session, id):
        applicant = session.mits_applicant(id, applicant=True)
        if applicant.primary_contact and len(applicant.team.primary_contacts) == 1:
            raise HTTPRedirect(
                'index?message={}', 'You cannot delete the only team member designated to receive emails')
        elif applicant.attendee_id:
            raise HTTPRedirect(
                '../preregistration/confirm?id={}',
                'Team members cannot be deleted after being granted a badge, '
                'but you may transfer this badge if you need to.')
        else:
            session.delete(applicant)
            raise HTTPRedirect('index?message={}', 'Team member deleted')

    def picture(self, session, message='', image=None, **params):
        picture = session.mits_picture(params, applicant=True)
        if cherrypy.request.method == 'POST':
            message = check(picture)
            if not message and (not image or not image.filename):
                message = 'You must select a picture to upload'
            if not message:
                picture.filename = image.filename
                picture.content_type = image.content_type.value
                picture.extension = image.filename.split('.')[-1].lower()
                with open(picture.filepath, 'wb') as f:
                    shutil.copyfileobj(image.file, f)
                raise HTTPRedirect('index?message={}', 'Picture Uploaded')

        return {
            'message': message,
            'picture': picture
        }

    @csrf_protected
    def delete_picture(self, session, id):
        picture = session.mits_picture(id, applicant=True)
        session.delete_mits_file(picture)
        raise HTTPRedirect('index?message={}', 'Picture deleted')

    def document(self, session, message='', upload=None, **params):
        doc = session.mits_document(params, applicant=True)
        if cherrypy.request.method == 'POST':
            message = check(doc)
            if not message and not upload:
                message = 'You must select a document to upload'
            if not message:
                doc.filename = upload.filename
                with open(doc.filepath, 'wb') as f:
                    shutil.copyfileobj(upload.file, f)
                raise HTTPRedirect('index?message={}', 'Document Uploaded')

        return {
            'doc': doc,
            'message': message
        }

    @csrf_protected
    def delete_document(self, session, id):
        doc = session.mits_document(id, applicant=True)
        session.delete_mits_file(doc)
        raise HTTPRedirect('index?message={}', 'Document deleted')

    def game(self, session, message='', **params):
        game = session.mits_game(params, bools=['personally_own', 'unlicensed', 'professional'], applicant=True)
        if cherrypy.request.method == 'POST':
            message = check(game)
            if not message:
                session.add(game)
                raise HTTPRedirect('index?message={}', 'Game saved')

        return {
            'game': game,
            'message': message
        }

    @csrf_protected
    def delete_game(self, session, id):
        game = session.mits_game(id, applicant=True)
        session.delete(game)
        raise HTTPRedirect('index?message={}', 'Game deleted')

    def panel(self, session, message='', **params):
        times_params = {'id': params.pop('schedule_id', None)}
        if cherrypy.request.method == 'POST':
            times_params['availability'] = params.pop('availability', '')

        panel_app = session.mits_panel_application(params, applicant=True, bools=['participation_interest'])
        times = session.mits_times(times_params, applicant=True, checkgroups=['availability'])
        team = session.logged_in_mits_team()

        if cherrypy.request.method == 'POST':
            if 'availability' in times_params:
                team.panel_interest = True
                if not panel_app.participation_interest and (not panel_app.name or not panel_app.description):
                    message = "Please fill in both a panel name and description and/or " \
                              "mark that you're interested in participating in a panel run by someone else."
            else:
                team.panel_interest = False
                if panel_app.participation_interest or panel_app.name or panel_app.description:
                    message = "Please tell us your availability for a panel."

            if not message:
                message = check(panel_app)
                message = message or check(times)

            if not message:
                session.add(panel_app)
                session.add(times)
                raise HTTPRedirect('index?message={}', 'Panel application saved')

        return {
            'times': times,
            'panel_app': panel_app,
            'message': message,
            'list': [
                (val, desc, val in times.availability_ints)
                for val, desc in c.MITS_SCHEDULE_OPTS
            ]
        }

    def schedule(self, session, message='', **params):
        times = session.mits_times(params, applicant=True, checkgroups=['showcase_availability'])
        team = session.logged_in_mits_team()
        if cherrypy.request.method == 'POST':
            if 'showcase_availability' in params:
                if params.get('showcase_consent'):
                    team.showcase_interest = True
                else:
                    message = "You must consent to using your information for the showcase."
            else:
                team.showcase_interest = False

            message = message or check(times)
            if not message:
                session.add(times)
                raise HTTPRedirect('index?message={}', 'Times saved')

        return {
            'team': team,
            'times': times,
            'message': message,
            'list': [
                (val, desc, val in times.showcase_availability_ints)
                for val, desc in c.MITS_SHOWCASE_SCHEDULE_OPTS
            ]
        }

    def hotel_requests(self, session, message='', **params):
        team = session.logged_in_mits_team()
        if cherrypy.request.method == 'POST':
            for applicant in team.applicants:
                applicant.declined_hotel_space = '{}-declined'.format(applicant.id) in params
                applicant.requested_room_nights = ','.join(listify(params.get('{}-night'.format(applicant.id), [])))
                if not applicant.declined_hotel_space and not applicant.requested_room_nights:
                    message = '{} must either declined hotel space or ' \
                        'indicate which room nights they need'.format(applicant.full_name)
                    break
                elif applicant.declined_hotel_space and applicant.requested_room_nights:
                    message = '{} cannot both decline hotel space and ' \
                        'request specific room nights'.format(applicant.full_name)
                    break

            if not message:
                raise HTTPRedirect('index?message={}', 'Room nights uploaded')

        return {
            'team': team,
            'message': message
        }

    def waiver(self, session, message='', **params):
        if params.get('id'):
            session.log_in_as_mits_team(params['id'], redirect_to='waiver')
        else:
            team = session.logged_in_mits_team()

        if cherrypy.request.method == 'POST':
            if not params['waiver_signature']:
                message = "Please enter your full name to sign the waiver."

            else:
                for applicant in team.applicants:
                    if getattr(applicant.attendee, 'full_name', applicant.full_name) == params['waiver_signature']:
                        team.waiver_signature = params['waiver_signature']
                        team.waiver_signed = localized_now()
                        break
                else:
                    message = "The name you entered did not match any of this team's members."

            if not message:
                raise HTTPRedirect('index?message={}', 'Thank you for signing the waiver!')
        return {
            'team': team,
            'message': message,
        }

    def submit_for_judging(self, session):
        """
        Sometimes we mark partially completed applications as accepted, either
        because there's enough information to complete judging OR because an
        admin created the application manually after the deadline for a team
        they wanted to make an exception for.  Applicants are therefore allowed
        to submit their applications either before the deadline or at any time
        if they've been pre-accepted.
        """
        team = session.logged_in_mits_team()
        if team.steps_completed < c.MITS_APPLICATION_STEPS - 1:
            raise HTTPRedirect('index?message={}', 'You have not completed all of the required steps')
        elif c.AFTER_MITS_SUBMISSION_DEADLINE and not team.accepted:
            raise HTTPRedirect('index?message={}', 'You cannot submit an application past the deadline')
        else:
            team.submitted = datetime.now(UTC)
            raise HTTPRedirect('index?message={}', 'Your application has been submitted')

    def accepted_teams(self, session):
        return {
            'teams': session.mits_teams()
        }
