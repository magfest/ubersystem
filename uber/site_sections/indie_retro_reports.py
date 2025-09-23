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
            'Primary Contact Name', 'Primary Contact Email', 'Short Description', 'Publisher Name',
            'Genres', 'Platforms', 'Expected Release Date', 'Full Description', 'Game Logo URL',
            'Link to Additional Promotional Assets', 'Link to Video', 'Link to Rom File',
            'Instructions to Play', 'Link to Available Game Pages', 'Attending In Person?',
            'Delivery Method', 'Found How', 'Game Submitted', 'Current Status',
            'Registered', 'Accepted', 'Confirmation Deadline',
            'Screenshot Links', 'Average Score', 'Individual Scores'
        ])
        for game in session.indie_games().filter(IndieGame.showcase_type == c.INDIE_RETRO):
            out.writerow([
                game.title, game.studio.name, '{}/showcase/index?id={}'.format(c.PATH, game.studio.id),
                game.studio.website, game.studio.other_links,
                game.primary_contact.full_name, game.primary_contact.email,
                game.brief_description, game.publisher_name,
                ' / '.join(game.genres_labels) + (f'{' / ' if game.genres else ''}Other: {game.genres_text}' if game.genres_text else ''),
                ' / '.join(game.platforms_labels) + (f'{' / ' if game.platforms else ''}Other: {game.platforms_text}' if game.platforms_text else ''),
                game.release_date, game.description, c.URL_BASE + game.game_logo_image.url.lstrip('.'),
                game.other_assets, game.link_to_video, game.link_to_game,
                game.how_to_play, game.link_to_webpage, game.in_person, game.delivery_method_label, game.found_how,
                'Submitted' if game.submitted else 'Not Submitted',
                'Accepted and Confirmed' if game.confirmed else game.status_label,
                game.registered.strftime('%Y-%m-%d'),
                'N/A' if not game.accepted else game.accepted.strftime('%Y-%m-%d'),
                'N/A' if not game.accepted else game.studio.confirm_deadline.strftime('%Y-%m-%d'),
                '\n'.join(c.URL_BASE + screenshot.url.lstrip('.') for screenshot in game.screenshots),
                str(game.average_score)
            ] + [str(score) for score in game.scores])

    @csv_file
    def presenters(self, out, session):
        presenters = set()
        for game in (session.query(IndieGame).filter(IndieGame.showcase_type == c.INDIE_RETRO,
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

        for judge in session.query(IndieJudge).filter(IndieJudge.showcases.contains(c.INDIE_RETRO)
                                                      ).options(joinedload(IndieJudge.admin_account)):
            attendee = judge.admin_account.attendee
            rows.append([
                attendee.first_name, attendee.last_name,
                attendee.email, judge.status_label,
                judge.staff_notes
            ])

        out.writerows(header_row, rows)
