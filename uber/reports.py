from uber.common import *


class ReportBase:
    def __init__(self, badge_type, include_badge_nums=True):
        self._badge_type = badge_type
        self._include_badge_nums = include_badge_nums

    def write_row(self, row, out):
        # plugins can override this hook
        out.writerow(row)


class PersonalizedBadgeReport(ReportBase):
    """
    Generate a CSV file which contains personalized badges with custom printed_names on them
    """

    def run(self, out, session):
        for a in session.query(sa.Attendee).order_by('badge_num')\
                .filter(sa.Attendee.badge_num != 0)\
                .filter(sa.Attendee.badge_type == self._badge_type)\
                .all():

            row = []
            if self._include_badge_nums:
                row.append(a.badge_num)
            row += [a.badge_type_label, a.badge_printed_name or a.full_name]

            self.write_row(row, out)


class SupporterBadgeReport(PersonalizedBadgeReport):
    def run(self, out, session):

        # override this no matter what user says, supporters don't have badge#s
        self._include_badge_nums = False

        # 1) generate the original report
        super().run(out, session)

        # 2) special case: also add in any staff who are also supporters
        for a in session.query(sa.Attendee)\
                .filter(sa.Attendee.badge_type == c.STAFF_BADGE)\
                .filter(sa.Attendee.amount_extra >= c.SUPPORTER_LEVEL)\
                .order_by(sa.Attendee.full_name)\
                .all():

            self.write_row(['Supporter', a.badge_printed_name or a.full_name], out)


class PrintedBadgeReport(ReportBase):
    """
    Generate a CSV file of badges which do not have customized information
    """

    def run(self, out, session):
        badge_range = c.BADGE_RANGES[self._badge_type]
        for badge_num in range(badge_range[0], badge_range[1]+1):
            self.write_row([badge_num], out)


printed_badge_report_type = PrintedBadgeReport
personalized_badge_report_type = PersonalizedBadgeReport
supporter_badge_report_type = SupporterBadgeReport
