import cherrypy
import logging

from uber.config import c
from uber.decorators import ajax, all_renderable, csv_file, multifile_zipfile
from uber.errors import HTTPRedirect
from uber.models import Attendee, MITSTeam, MITSGame
from uber.utils import add_opt, check_csrf, slugify

log = logging.getLogger(__name__)


@all_renderable()
class Root:
    def index(self, session, message=''):
        return {
            'message': message,
            'teams': session.mits_teams()
        }

    def accepted(self, session, message=''):
        return {
            'message': message,
            'accepted_teams': session.query(MITSTeam).filter(MITSTeam.status == c.ACCEPTED),
        }

    def create_new_application(self):
        cherrypy.session.pop('mits_team_id', None)
        raise HTTPRedirect('../mits/team')

    def team(self, session, id, message=''):
        return {
            'message': message,
            'team': session.mits_team(id)
        }

    def set_status(self, session, id, status=None, confirmed=False, csrf_token=None, return_to='index', message=''):
        team = session.mits_team(id)
        matching = [t for t in session.mits_teams() if t.name == team.name and t.id != team.id]
        if confirmed or (status and not matching and team.status == c.PENDING and team.completion_percentage == 100):
            check_csrf(csrf_token)
            team.status = int(status)
            separator = '&' if '?' in return_to else '?'
            raise HTTPRedirect(return_to + separator + 'message={}{}{}', team.name, ' marked as ', team.status_label)

        return {
            'team': team,
            'message': message,
            'matching': matching,
            'return_to': return_to
        }

    def delete_team(self, session, id, duplicate_of=None, csrf_token=None, message=''):
        team = session.mits_team(id)
        if cherrypy.request.method == 'POST':
            check_csrf(csrf_token)
            team.deleted = True
            team.duplicate_of = duplicate_of or None
            raise HTTPRedirect(
                'index?message={}{}{}', team.name, ' marked as deleted', ' and as a duplicate' if duplicate_of else '')

        other = [t for t in session.mits_teams() if t.id != id]
        return {
            'team': team,
            'message': message,
            'match_count': len([t for t in other if t.name == team.name]),
            'other_teams': sorted(other, key=lambda t: (t.name != team.name, t.name))
        }

    def badges(self, session):
        possibles = session.possible_match_list()

        applicants = []
        for team in session.mits_teams():
            if team.status == c.ACCEPTED:
                for a in team.applicants:
                    if not a.attendee_id:
                        applicants.append([a, set(possibles[a.email.lower()] + possibles[a.first_name, a.last_name])])

        return {'applicants': applicants}

    def teams_and_badges(self, session):
        return {
            'accepted_teams': session.query(MITSTeam).filter(MITSTeam.status == c.ACCEPTED),
        }

    @ajax
    def link_badge(self, session, applicant_id, attendee_id):
        attendee = session.attendee(attendee_id)
        try:
            applicant = session.mits_applicant(applicant_id)
            applicant.attendee = attendee
            add_opt(attendee.ribbon_ints, c.MIVS)
            session.commit()
        except Exception:
            log.error('unexpected error linking applicant to a badge', exc_info=True)
            return {'error': 'Unexpected error: unable to link applicant to badge.'}
        else:
            return {
                'name': applicant.full_name,
                'comp_count': applicant.team.comped_badge_count
            }

    @ajax
    def create_badge(self, session, applicant_id):
        try:
            applicant = session.mits_applicant(applicant_id)
            applicant.attendee = Attendee(
                placeholder=True,
                paid=c.NEED_NOT_PAY,
                badge_type=c.ATTENDEE_BADGE,
                ribbon=c.MIVS,
                first_name=applicant.first_name,
                last_name=applicant.last_name,
                email=applicant.email,
                cellphone=applicant.cellphone
            )
            session.add(applicant.attendee)
            session.commit()
        except Exception:
            log.error('unexpected error adding new applicant', exc_info=True)
            return {'error': 'Unexpected error: unable to add attendee'}
        else:
            return {'comp_count': applicant.team.comped_badge_count}

    @csv_file
    def hotel_requests(self, out, session):
        for team in session.mits_teams().filter_by(status=c.ACCEPTED):
            for applicant in team.applicants:
                if applicant.requested_room_nights:
                    out.writerow([
                        team.name,
                        applicant.full_name,
                        applicant.email,
                        applicant.cellphone
                    ] + [
                        desc if val in applicant.requested_room_nights_ints else ''
                        for val, desc in c.MITS_ROOM_NIGHT_OPTS
                    ])

    @csv_file
    def showcase_requests(self, out, session):
        out.writerow(['Team Name'] + [desc for val, desc in c.MITS_SHOWCASE_SCHEDULE_OPTS])
        for team in session.mits_teams().filter_by(status=c.ACCEPTED):
            if team.schedule and team.schedule.showcase_availability:
                available = getattr(team.schedule, 'showcase_availability_ints', [])
                out.writerow([team.name] + [
                    'available' if val in available else ''
                    for val, desc in c.MITS_SHOWCASE_SCHEDULE_OPTS
                ])

    @csv_file
    def panel_requests(self, out, session):
        out.writerow(['URL', 'Team', 'Primary Contact Names', 'Primary Contact Emails']
                     + [desc for val, desc in c.MITS_SCHEDULE_OPTS])
        for team in session.mits_teams().filter_by(status=c.ACCEPTED, panel_interest=True):
            available = getattr(team.schedule, 'availability_ints', [])
            out.writerow([
                c.URL_BASE + '/mits_admin/team?id=' + team.id,
                team.name,
                '\n'.join(a.full_name for a in team.primary_contacts),
                '\n'.join(a.email for a in team.primary_contacts)
            ] + [
                'available' if val in available else ''
                for val, desc in c.MITS_SCHEDULE_OPTS
            ])
    
    @csv_file
    def tournament_interest(self, out, session):
        out.writerow(['URL', 'Team', 'Primary Contact Names', 'Primary Contact Emails', 'Games'])
        for team in session.mits_teams().filter_by(status=c.ACCEPTED):
            tournament_games = [game for game in team.games if game.tournament]
            if tournament_games:
                out.writerow([
                    c.URL_BASE + '/mits_admin/team?id=' + team.id,
                    team.name,
                    '\n'.join(a.full_name for a in team.primary_contacts),
                    '\n'.join(a.email for a in team.primary_contacts),
                    '\n'.join(g.name for g in tournament_games),
                ])

    @multifile_zipfile
    def accepted_games_images_zip(self, zip_file, session):
        query = session.query(MITSGame).filter_by(has_been_accepted=True).outerjoin(MITSGame.pictures)

        for game in query:
            for pic in game.pictures:
                zip_file.write(pic.filepath, slugify(pic.game.name) + "_" + pic.filename)
