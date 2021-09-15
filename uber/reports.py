from uber.barcode import generate_barcode_from_badge_num
from uber.config import c
from uber.models.attendee import Attendee


__all__ = ['PersonalizedBadgeReport', 'PrintedBadgeReport', 'ReportBase']


class ReportBase:
    def write_row(self, row, out):
        if self._include_badge_nums:
            # add in the barcodes here
            badge_num = row[0]
            barcode = generate_barcode_from_badge_num(badge_num)
            row.append(barcode)

        out.writerow(row)


class PersonalizedBadgeReport(ReportBase):
    """
    Generate a CSV file which contains personalized badges with custom printed_names on them

    Deferred badges probably should be printed, since in theory a Deferred badge might be checked in.
    For example, a badge might be marked as Deferred if the attendee name matches a name on our watch list,
    but we might find at the event that they're just a different person with the same name.

    see discussion: https://github.com/magfest/ubersystem/issues/1648
    """
    def __init__(self, include_badge_nums=True):
        self._include_badge_nums = include_badge_nums

    def run(self, out, session, *filters, order_by=None, badge_type_override=None):
        badge_nums_seen = []

        for a in (session.query(Attendee)
                         .filter(Attendee.badge_status != c.INVALID_STATUS, *filters)
                         .order_by(order_by).all()):

            # sanity check no duplicate badges
            if a.badge_num:
                if a.badge_num in badge_nums_seen:
                    raise ValueError("duplicate badge number detected: %s" % a.badge_num)
                badge_nums_seen += [a.badge_num]

            # write the actual data
            row = [a.badge_num] if self._include_badge_nums else []
            if badge_type_override:
                if callable(badge_type_override):
                    badge_type_label = badge_type_override(a)
                else:
                    badge_type_label = badge_type_override
            else:
                badge_type_label = a.badge_type_label

            if a.unassigned_name:
                printed_name = a.group.name if a.group else ''
            else:
                printed_name = a.badge_printed_name or a.full_name

            row += [badge_type_label, printed_name]
            self.write_row(row, out)


class PrintedBadgeReport(ReportBase):
    """Generate a CSV file of badges which do not have customized information"""
    def __init__(self, badge_type, include_badge_nums=True, range=None, badge_type_name=''):
        self._badge_type = badge_type
        self._include_badge_nums = include_badge_nums
        self._range = range
        self._badge_type_name = badge_type_name

    def run(self, out, session):
        badge_range = c.BADGE_RANGES[self._badge_type]
        min_badge_num = max([badge_range[0]] + ([self._range[0]] if self._range else []))
        max_badge_num = min([badge_range[1]] + ([self._range[1]] if self._range else [])) + 1

        empty_customized_name = ''

        for badge_num in range(min_badge_num, max_badge_num):
            self.write_row([badge_num, self._badge_type_name, empty_customized_name], out)
