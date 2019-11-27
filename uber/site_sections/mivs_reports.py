import os

from sqlalchemy.orm import joinedload

from uber.config import c
from uber.custom_tags import humanize_timedelta
from uber.decorators import all_renderable, csv_file, multifile_zipfile, xlsx_file
from uber.models import Attendee, Group, IndieGame, IndieStudio
from uber.utils import check, localized_now


@all_renderable()
class Root:
    @csv_file
    def social_media(self, out, session):
        out.writerow(['Studio', 'Website', 'Twitter', 'Facebook'])
        for game in session.indie_games():
            if game.confirmed:
                out.writerow([
                    game.studio.name,
                    game.studio.website,
                    game.studio.twitter,
                    game.studio.facebook
                ])

    @csv_file
    def everything(self, out, session):
        out.writerow([
            'Game', 'Studio', 'Studio URL', 'Primary Contact Names', 'Primary Contact Emails',
            'Game Website', 'Twitter', 'Facebook', 'Other Social Media',
            'Genres', 'Brief Description', 'Long Description', 'How to Play',
            'Link to Video for Judging', 'Link to Promo Video', 'Link to Game', 'Game Link Password',
            'Game Requires Codes?', 'Code Instructions', 'Build Status', 'Build Notes',
            'Game Submitted', 'Current Status',
            'Registered', 'Accepted', 'Confirmation Deadline',
            'Screenshot Links', 'Average Score', 'Individual Scores'
        ])
        for game in session.indie_games():
            out.writerow([
                game.title,
                game.studio.name,
                '{}/mivs/continue_app?id={}'.format(c.PATH, game.studio.id),
                game.studio.primary_contact_first_names,
                game.studio.email,
                game.link_to_webpage,
                game.twitter,
                game.facebook,
                game.other_social_media,
                ' / '.join(game.genres_labels),
                game.brief_description,
                game.description,
                game.how_to_play,
                game.link_to_video,
                game.link_to_promo_video,
                game.link_to_game,
                game.password_to_game,
                game.code_type_label,
                game.code_instructions,
                game.build_status_label,
                game.build_notes,
                'submitted' if game.submitted else 'not submitted',
                'accepted and confirmed' if game.confirmed else game.status_label,
                game.registered.strftime('%Y-%m-%d'),
                'n/a' if not game.accepted else game.accepted.strftime('%Y-%m-%d'),
                'n/a' if not game.accepted else game.studio.confirm_deadline.strftime('%Y-%m-%d'),
                '\n'.join(c.URL_BASE + screenshot.url.lstrip('.') for screenshot in game.screenshots),
                str(game.average_score)
            ] + [str(score) for score in game.scores])

    @csv_file
    def checklist_info_csv(self, out, session):
        header_row = ['Studio']
        for key, val in c.MIVS_CHECKLIST.items():
            header_row.append(val['name'])
            header_row.append('Past Due?')
        out.writerow(header_row)

        for studio in session.query(IndieStudio).join(IndieStudio.group).join(Group.guest):
            row = [studio.name]
            for key, val in c.MIVS_CHECKLIST.items():
                row.extend([
                    'Not Completed' if getattr(studio, key + "_status", None) is None
                    else getattr(studio, key + "_status"),
                    'No' if localized_now() <= studio.checklist_deadline(key)
                    else humanize_timedelta(studio.past_checklist_deadline(key), granularity='hours'),
                ])
            out.writerow(row)

    @csv_file
    def discussion_group_emails(self, out, session):
        out.writerow(['Studio', 'Emails', 'Last Updated'])
        for studio in session.query(IndieStudio).join(IndieStudio.group).join(Group.guest):
            emails = []
            row = [studio.name]
            emails.extend(studio.group.guest.email)
            if studio.discussion_emails:
                emails.extend(studio.discussion_emails_list)
            row.append(emails)
            row.append(studio.discussion_emails_last_updated.astimezone(c.EVENT_TIMEZONE))

            out.writerow(row)

    @xlsx_file
    def accepted_games_xlsx(self, out, session):
        rows = []
        for game in session.query(IndieGame).filter_by(status=c.ACCEPTED):
            screenshots = game.best_screenshot_download_filenames()
            rows.append([
                game.studio.name, game.studio.website,
                game.title, game.brief_description, game.link_to_webpage,
                game.twitter, game.facebook, game.other_social_media,
                game.link_to_promo_video, game.link_to_video, game.link_to_game,
                screenshots[0], screenshots[1]
            ])

        header_row = [
            'Studio', 'Studio Website',
            'Game Title', 'Description', 'Website',
            'Twitter', 'Facebook', 'Other Social Media',
            'Link to Promo Video', 'Link to Video for Judging', 'Link to Game',
            'Screenshot 1', 'Screenshot 2']
        out.writerows(header_row, rows)

    @multifile_zipfile
    def accepted_games_zip(self, zip_file, session):
        output = self.accepted_games_xlsx(set_headers=False)
        zip_file.writestr('mivs_accepted_games.xlsx', output)
        for game in session.query(IndieGame).filter_by(status=c.ACCEPTED):
            filenames = game.best_screenshot_download_filenames()
            screenshots = game.best_screenshot_downloads()
            for filename, screenshot in zip(filenames, screenshots):
                if filename:
                    filepath = os.path.join(c.MIVS_GAME_IMAGE_DIR, screenshot.id)
                    zip_file.write(filepath, os.path.join('mivs_accepted_game_images', filename))

    @csv_file
    def presenters(self, out, session):
        presenters = set()
        for game in (session.query(IndieGame)
                            .filter_by(status=c.ACCEPTED)
                            .options(joinedload(IndieGame.studio).joinedload(IndieStudio.group))):
            for attendee in getattr(game.studio.group, 'attendees', []):
                if not attendee.is_unassigned and attendee not in presenters:
                    presenters.add(attendee)
                    out.writerow([attendee.full_name, game.studio.name])
