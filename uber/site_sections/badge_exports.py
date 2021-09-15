from sqlalchemy import func

from uber.config import c
from uber.decorators import all_renderable, multifile_zipfile, xlsx_file
from uber.models import Attendee
from uber.reports import PersonalizedBadgeReport, PrintedBadgeReport


def generate_staff_badges(start_badge, end_badge, out, session):
    badge_range = (start_badge, end_badge)

    PrintedBadgeReport(
        badge_type=c.STAFF_BADGE,
        range=badge_range,
        badge_type_name='Staff').run(out, session)


@all_renderable()
class Root:
    @xlsx_file
    def printed_badges_attendee(self, out, session):
        PrintedBadgeReport(badge_type=c.ATTENDEE_BADGE, badge_type_name='Attendee').run(out, session)

    @xlsx_file
    def printed_badges_guest(self, out, session):
        PrintedBadgeReport(badge_type=c.GUEST_BADGE, badge_type_name='Guest').run(out, session)

    @xlsx_file
    def printed_badges_one_day(self, out, session):
        PrintedBadgeReport(badge_type=c.ONE_DAY_BADGE, badge_type_name='OneDay').run(out, session)

    @xlsx_file
    def printed_badges_minor(self, out, session):
        try:
            PrintedBadgeReport(badge_type=c.CHILD_BADGE, badge_type_name='Minor').run(out, session)
        except AttributeError:
            pass

    @xlsx_file
    def printed_badges_staff(self, out, session):

        # part 1, include staff and contractor badges
        PersonalizedBadgeReport().run(
            out,
            session,
            Attendee.badge_type.in_([c.STAFF_BADGE, c.CONTRACTOR_BADGE]),
            Attendee.badge_num != None,
            badge_type_override='Staff',
            order_by='badge_num')  # noqa: E711

        # part 2, include some extra for safety margin
        minimum_extra_amount = c.BLANK_STAFF_BADGES

        max_badges = max(c.BADGE_RANGES[c.STAFF_BADGE][1], c.BADGE_RANGES[c.CONTRACTOR_BADGE][1])
        start_badge = max_badges - minimum_extra_amount + 1
        end_badge = max_badges

        generate_staff_badges(start_badge, end_badge, out, session)

    @xlsx_file
    def printed_badges_staff__expert_mode_only(self, out, session, start_badge, end_badge):
        """
        Generate a CSV of staff badges. Note: This is not normally what you would call to do the badge export.
        For use by experts only.
        """

        generate_staff_badges(int(start_badge), int(end_badge), out, session)

    @xlsx_file
    def badge_hangars_supporters(self, out, session):
        PersonalizedBadgeReport(include_badge_nums=False).run(
            out,
            session,
            Attendee.amount_extra >= c.SUPPORTER_LEVEL,
            order_by=Attendee.full_name,
            badge_type_override=lambda a: 'Super Supporter' if a.amount_extra >= c.SEASON_LEVEL else 'Supporter')

    """
    Enumerate individual CSVs here that will be integrated into the .zip which will contain all the
    badge types.  Downstream plugins can override which items are in this list.
    """
    badge_zipfile_contents = [
        printed_badges_attendee,
        printed_badges_guest,
        printed_badges_one_day,
        printed_badges_minor,
        printed_badges_staff,
        badge_hangars_supporters,
    ]

    @multifile_zipfile
    def personalized_badges_zip(self, zip_file, session):
        """
        Put all printed badge report files in one convenient zipfile.  The idea
        is that this ZIP file, unmodified, should be completely ready to send to
        the badge printers.

        Plugins can override badge_zipfile_contents to do something different/event-specific.
        """
        for badge_report_fn in self.badge_zipfile_contents:
            # run the report function, but don't output headers because
            # 1) we'll do it with the zipfile
            # 2) we don't set headers until the very end when everything is 100% good
            #    so that exceptions are displayed to the end user properly
            output = badge_report_fn(self, session, set_headers=False)

            filename = '{}.{}'.format(badge_report_fn.__name__, badge_report_fn.output_file_extension or '')
            zip_file.writestr(filename, output)
