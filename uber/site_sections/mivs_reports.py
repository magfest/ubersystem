import os

from sqlalchemy.orm import joinedload

from uber.config import c
from uber.custom_tags import humanize_timedelta
from uber.decorators import all_renderable, csv_file, multifile_zipfile, xlsx_file
from uber.models import Group, IndieGame, IndieJudge, IndieStudio, GuestGroup
from uber.utils import localized_now, normalize_newlines


@all_renderable()
class Root:
    @csv_file
    def social_media(self, out, session):
        out.writerow(['Studio', 'Website', 'Other Links'])
        for game in session.indie_games().filter(IndieGame.showcase_type == c.MIVS):
            if game.confirmed:
                out.writerow([
                    game.studio.name,
                    game.studio.website,
                    game.studio.other_links,
                ])

    @csv_file
    def everything(self, out, session):
        out.writerow([
            'Game', 'Studio', 'Studio URL', 'Studio Website', 'Other Links',
            'Primary Contact Names', 'Primary Contact Emails',
            'Genres', 'Platforms', 'Brief Description', 'Long Description', 'How to Play', 'Player Count',
            'Link to Video for Judging', 'Link to Promo Video', 'Link to Game', 'Game Link Password',
            'Game Requires Codes?', 'Code Instructions', 'Build Status', 'Build Notes',
            'Game Submitted', 'Current Status',
            'Registered', 'Accepted', 'Confirmation Deadline',
            'Screenshot Links', 'Average Score', 'Individual Scores'
        ])
        for game in session.indie_games().filter(IndieGame.showcase_type == c.MIVS):
            out.writerow([
                game.title,
                game.studio.name,
                '{}/showcase/index?id={}'.format(c.PATH, game.studio.id),
                game.studio.website, game.studio.other_links,
                game.studio.primary_contact_first_names,
                ' / '.join(game.studio.email),
                ' / '.join(game.genres_labels) + (f'{' / ' if game.genres else ''}Other: {game.genres_text}' if game.genres_text else ''),
                ' / '.join(game.platforms_labels) + (f'{' / ' if game.platforms else ''}Other: {game.platforms_text}' if game.platforms_text else ''),
                game.brief_description,
                game.description,
                game.how_to_play,
                game.player_count,
                game.link_to_video,
                game.link_to_promo_video,
                game.link_to_game,
                game.password_to_game,
                game.code_type_label,
                game.code_instructions,
                game.build_status_label,
                game.build_notes,
                'Submitted' if game.submitted else 'Not Submitted',
                'Accepted and Confirmed' if game.confirmed else game.status_label,
                game.registered.strftime('%Y-%m-%d'),
                'N/A' if not game.accepted else game.accepted.strftime('%Y-%m-%d'),
                'N/A' if not game.accepted else game.studio.confirm_deadline.strftime('%Y-%m-%d'),
                '\n'.join(c.URL_BASE + screenshot.url.lstrip('.') for screenshot in game.screenshots),
                str(game.average_score)
            ] + [str(score) for score in game.scores])

    @csv_file
    def checklist_info_csv(self, out, session):
        header_row = ['Studio', 'Showcase(s)']
        for key, val in c.MIVS_CHECKLIST.items():
            header_row.append(val['name'])
            header_row.append('Past Due?')
        out.writerow(header_row)

        for studio in session.query(IndieStudio).join(IndieStudio.group
                                                      ).join(Group.guest).filter(GuestGroup.group_type == c.MIVS):
            showcases = set([game.showcase_type_label for game in studio.games])
            row = [studio.name, ' / '.join(showcases)]
            for key, val in c.MIVS_CHECKLIST.items():
                not_complete = getattr(studio, key + "_status", None) is None
                row.extend([
                    'Not Completed' if not_complete
                    else getattr(studio, key + "_status"),
                    'No' if localized_now() <= studio.checklist_deadline(key) or not not_complete
                    else humanize_timedelta(studio.past_checklist_deadline(key), granularity='hours'),
                ])
            out.writerow(row)

    @csv_file
    def show_info_csv(self, out, session):
        out.writerow(['Studio', 'Game', 'Showcase', 'Promo Image 1', 'Promo Image 2', 'Guidebook Header', 'Guidebook Thumbnail',
                      'Brief Description', 'Full Description', 'Gameplay Video', 'Website', 'Steam Page',
                      'Other Social Media', 'Studio Contact Phone #'])
        for studio in session.query(IndieStudio).join(IndieStudio.group
                                                      ).join(Group.guest).filter(GuestGroup.group_type == c.MIVS):
            for game in studio.confirmed_games:
                promo_1_url, promo_2_url, header_url, thumbnail_url = '', '', '', '',
                image_url = c.URL_BASE + "/showcase/view_image?id={}"
                promo_images = game.best_images
                if promo_images:
                    promo_1_url = image_url.format(promo_images[0].id)
                    if len(promo_images) > 1:
                        promo_2_url = image_url.format(promo_images[1].id)
                if game.guidebook_header:
                    header_url = image_url.format(game.guidebook_header.id)
                if game.guidebook_thumbnail:
                    thumbnail_url = image_url.format(game.guidebook_thumbnail.id)

                out.writerow([
                    studio.name, game.title, game.showcase_type_label, promo_1_url, promo_2_url, header_url, thumbnail_url,
                    game.brief_description, normalize_newlines(game.description), game.link_to_promo_video, game.link_to_webpage,
                    game.link_to_store, game.other_social_media, studio.contact_phone
                ])

    @csv_file
    def discussion_group_emails(self, out, session):
        out.writerow(['Studio', 'Emails', 'Last Updated'])
        for studio in session.query(IndieStudio).join(IndieStudio.group
                                                      ).join(Group.guest).filter(GuestGroup.group_type == c.MIVS):
            emails = []
            row = [studio.name]
            emails.extend(studio.group.guest.email)
            if studio.discussion_emails:
                emails.extend(studio.discussion_emails_list)
            row.append(emails)
            row.append(studio.discussion_emails_last_updated.astimezone(c.EVENT_TIMEZONE)
                       if studio.discussion_emails_last_updated else 'N/A')

            out.writerow(row)

    @xlsx_file
    def accepted_games_xlsx(self, out, session):
        rows = []
        for game in session.query(IndieGame).filter(IndieGame.showcase_type == c.MIVS,
                                                    IndieGame.status == c.ACCEPTED):
            screenshots = game.accepted_image_download_filenames()
            rows.append([
                game.studio.name, game.studio.website, ' / '.join(game.studio.other_links.split(',')),
                game.title, game.brief_description,
                game.link_to_video, game.link_to_game,
                screenshots[0], screenshots[1]
            ])

        header_row = [
            'Studio', 'Studio Website', 'Other Links',
            'Game Title', 'Description',
            'Link to Promo Video', 'Link to Game',
            'Screenshot 1', 'Screenshot 2']
        out.writerows(header_row, rows)

    @multifile_zipfile
    def accepted_games_zip(self, zip_file, session):
        output = self.accepted_games_xlsx(set_headers=False)
        zip_file.writestr('mivs_accepted_games.xlsx', output)
        for game in session.query(IndieGame).filter(IndieGame.showcase_type == c.MIVS,
                                                    IndieGame.status == c.ACCEPTED):
            filenames = game.accepted_image_download_filenames()
            images = game.accepted_image_downloads()
            for filename, screenshot in zip(filenames, images):
                if filename:
                    filepath = os.path.join(c.MIVS_GAME_IMAGE_DIR, screenshot.id)
                    zip_file.write(filepath, os.path.join('mivs_accepted_game_images', filename))

    @csv_file
    def presenters(self, out, session):
        presenters = set()
        for game in (session.query(IndieGame).filter(IndieGame.showcase_type == c.MIVS,
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
            'Email', 'Status', 'Has Game Submission?',
            'Genres', 'Platforms', 'Other Platforms',
            'Staff Notes']

        for judge in session.query(IndieJudge).filter(IndieJudge.showcases.contains(c.MIVS)
                                                      ).options(joinedload(IndieJudge.admin_account)):
            attendee = judge.admin_account.attendee
            rows.append([
                attendee.first_name, attendee.last_name,
                attendee.email, judge.status_label, "No" if judge.no_game_submission else "Yes",
                " / ".join(judge.genres_labels), " / ".join(judge.platforms_labels), judge.platforms_text,
                judge.staff_notes
            ])

        out.writerows(header_row, rows)
