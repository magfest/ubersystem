import os

from sqlalchemy.orm import joinedload

from uber.config import c
from uber.custom_tags import humanize_timedelta
from uber.decorators import all_renderable, csv_file, multifile_zipfile, xlsx_file
from uber.models import Group, IndieGame, IndieJudge, IndieStudio, GuestGroup
from uber.utils import localized_now


@all_renderable()
class Root:
    @csv_file
    def everything(self, out, session):
        out.writerow([
            'Game', 'Studio', 'Studio URL', 'Studio Website', 'Other Links',
            'Primary Contact Name', 'Primary Contact Email', 'Description', 'Link to Video',
            'Can Run 72 Hours', 'Online Until 2pm Sunday', 'Player Count', 'Required Floorspace',
            'Cabinet/Installation Type', 'Sanitation Considerations', 'Transit Needs',
            'Found How', 'Read the FAQ', 'Mailing List', 'Game Submitted', 'Current Status',
            'Registered', 'Accepted', 'Confirmation Deadline',
            'Photo Links', 'Average Score', 'Individual Scores'
        ])
        for game in session.indie_games().filter(IndieGame.showcase_type == c.INDIE_ARCADE):
            full_name = game.primary_contact.full_name if game.primary_contact else 'No Primary Contact'
            email = game.primary_contact.email if game.primary_contact else 'N/A'
            out.writerow([
                game.title, game.studio.name, '{}/showcase/index?id={}'.format(c.PATH, game.studio.id),
                game.studio.website, game.studio.other_links, full_name, email,
                game.description, game.link_to_video,
                game.game_hours +(f': {game.game_hours_text}' if game.game_hours == 'Other' else ''),
                game.game_end_time, game.player_count,
                game.floorspace_label + (f': {game.floorspace_text}' if game.floorspace == c.OTHER else ''),
                game.cabinet_type_label + (f': {game.cabinet_type_text}' if game.cabinet_type == c.OTHER else ''),
                game.sanitation_requests, game.transit_needs, game.found_how, game.read_faq, game.mailing_list,
                'Submitted' if game.submitted else 'Not Submitted',
                'Accepted and Confirmed' if game.confirmed else game.status_label,
                game.registered.strftime('%Y-%m-%d'),
                'N/A' if not game.accepted else game.accepted.strftime('%Y-%m-%d'),
                'N/A' if not game.accepted else game.studio.confirm_deadline.strftime('%Y-%m-%d'),
                '\n'.join(c.URL_BASE + screenshot.url.lstrip('.') for screenshot in game.submission_images),
                str(game.average_score)
            ] + [str(score) for score in game.scores])

    @csv_file
    def presenters(self, out, session):
        presenters = set()
        for game in (session.query(IndieGame).filter(IndieGame.showcase_type == c.INDIE_ARCADE,
                                                     IndieGame.status == c.ACCEPTED).options(
                                                         joinedload(IndieGame.studio).joinedload(IndieStudio.group))):
            for attendee in getattr(game.studio.group, 'attendees', []):
                if not attendee.is_unassigned and attendee not in presenters:
                    presenters.add(attendee)
                    out.writerow([attendee.full_name, game.studio.name])

    @xlsx_file
    def judges(self, out, session):
        rows = []
        header_row = [
            'First Name', 'Last Name',
            'Email', 'Status', 'Staff Notes']

        for judge in session.query(IndieJudge).filter(IndieJudge.showcases.contains(c.INDIE_ARCADE)
                                                      ).options(joinedload(IndieJudge.admin_account)):
            attendee = judge.admin_account.attendee
            rows.append([
                attendee.first_name, attendee.last_name,
                attendee.email, judge.status_label,
                judge.staff_notes
            ])

        out.writerows(header_row, rows)
