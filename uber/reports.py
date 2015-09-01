from uber.common import *


class ReportBase:
    def write_row(self, row, out):
        # plugins can override this hook
        out.writerow(row)


class PersonalizedBadgeReport(ReportBase):
    """
    Generate a CSV file which contains personalized badges with custom printed_names on them
    """

    def __init__(self, include_badge_nums=True):
        self._include_badge_nums = include_badge_nums

    def run(self, out, session, *filters, order_by=None, badge_type_override=None):
        for a in session.query(sa.Attendee)\
                .filter(*filters)\
                .order_by(order_by)\
                .all():

            row = [a.badge_num] if self._include_badge_nums else []
            badge_type_label = badge_type_override if badge_type_override else a.badge_type_label

            row += [badge_type_label, a.badge_printed_name or a.full_name]

            self.write_row(row, out)


class PrintedBadgeReport(ReportBase):
    """
    Generate a CSV file of badges which do not have customized information
    """

    def __init__(self, badge_type, include_badge_nums=True):
        self._badge_type = badge_type
        self._include_badge_nums = include_badge_nums

    def run(self, out, session):
        badge_range = c.BADGE_RANGES[self._badge_type]
        for badge_num in range(badge_range[0], badge_range[1]+1):
            self.write_row([badge_num], out)


printed_badge_report_type = PrintedBadgeReport
personalized_badge_report_type = PersonalizedBadgeReport
