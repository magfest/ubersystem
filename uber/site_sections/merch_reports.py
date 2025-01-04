from collections import defaultdict, OrderedDict
from datetime import datetime
from pytz import UTC
from sqlalchemy import or_

from uber.config import c
from uber.custom_tags import format_currency, datetime_local_filter
from uber.decorators import all_renderable, csv_file
from uber.models import Attendee


def sort(d, label_list):
    return sorted(d.items(), key=lambda tup: label_list.index(tup[0]))


def label(s):
    return 'size unknown' if s == c.SHIRTS[c.NO_SHIRT] else s


@all_renderable()
class Root:
    def shirt_manufacturing_counts(self, session):
        """
        This report should be the definitive report about the count and sizes of
        shirts needed to be ordered.

        There are two types of shirts:
        - "staff shirts" - staff uniforms, each staff gets c.SHIRTS_PER_STAFFER
        - "event shirts" - pre-ordered swag shirts, which are received by:
            - volunteers (non-staff who get one for free)
            - attendees (who can pre-order them)
        """
        counts = defaultdict(lambda: defaultdict(int))
        labels = ['size unknown', 'opted out'] + [label for val, label in c.SHIRT_OPTS][1:]
        staff_labels = ['size unknown', 'opted out'] + [label for val, label in c.STAFF_SHIRT_OPTS][1:]

        for attendee in session.all_attendees():
            if attendee.shirt_opt_out == c.ALL_OPT_OUT:
                counts['staff']['opted out'] += 1
                counts['event']['opted out'] += 1
            else:
                shirt_label = attendee.shirt_label or 'size unknown'
                if c.STAFF_SHIRT_OPTS != c.SHIRT_OPTS:
                    staff_shirt_label = attendee.staff_shirt_label or 'size unknown'
                else:
                    staff_shirt_label = attendee.shirt_label or 'size unknown'

                if attendee.shirt_opt_out == c.STAFF_OPT_OUT:
                    counts['staff']['opted out'] += 1
                else:
                    counts['staff'][label(staff_shirt_label)] += attendee.num_staff_shirts_owed

                if attendee.shirt_opt_out == c.EVENT_OPT_OUT:
                    counts['event']['opted out'] += 1
                else:
                    counts['event'][label(shirt_label)] += attendee.num_event_shirts_owed

        categories = []
        if c.SHIRTS_PER_STAFFER > 0:
            categories.append(('Staff Uniform Shirts', sort(counts['staff'], staff_labels)))

        categories.append(('Event Shirts', sort(counts['event'], labels)))

        return {
            'categories': categories,
        }

    def shirt_counts(self, session):
        counts = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
        labels = ['size unknown'] + [label for val, label in c.SHIRT_OPTS][1:]
        staff_labels = ['size unknown'] + [label for val, label in c.STAFF_SHIRT_OPTS][1:]

        def status(got_merch):
            return 'picked_up' if got_merch else 'outstanding'

        sales_by_week = OrderedDict([(i, 0) for i in range(53)])

        for attendee in session.all_attendees():
            shirt_label = attendee.shirt_label or 'size unknown'
            if c.STAFF_SHIRT_OPTS != c.SHIRT_OPTS:
                staff_shirt_label = attendee.staff_shirt_label or 'size unknown'
            else:
                staff_shirt_label = attendee.shirt_label or 'size unknown'
            counts['all_staff_shirts'][
                label(staff_shirt_label)][status(attendee.got_merch)] += attendee.num_staff_shirts_owed
            counts['all_event_shirts'][
                label(shirt_label)][status(attendee.got_merch)] += attendee.num_event_shirts_owed
            counts['free_event_shirts'][
                label(shirt_label)][status(attendee.got_merch)] += attendee.num_free_event_shirts
            if attendee.paid_for_a_shirt:
                counts['paid_event_shirts'][label(shirt_label)][status(attendee.got_merch)] += 1
                sale_week = (min(datetime.now(UTC), c.ESCHATON) - attendee.registered).days // 7
                sales_by_week[min(sale_week, 52)] += 1

        for week in range(48, -1, -1):
            sales_by_week[week] += sales_by_week[week + 1]

        categories = [
            ('Free Event Shirts', sort(counts['free_event_shirts'], labels)),
            ('Paid Event Shirts', sort(counts['paid_event_shirts'], labels)),
            ('All Event Shirts', sort(counts['all_event_shirts'], labels)),
        ]
        if c.SHIRTS_PER_STAFFER > 0:
            categories.append(('Staff Shirts', sort(counts['all_staff_shirts'], staff_labels)))

        return {
            'sales_by_week': sales_by_week,
            'categories': categories,
        }

    def extra_merch(self, session):
        return {
            'attendees': session.valid_attendees().filter(
                Attendee.extra_merch != '').order_by(Attendee.full_name).all()}

    def owed_merch(self, session):
        return {
            'attendees': session.valid_attendees().filter(or_(Attendee.amount_extra > 0,
                                                              Attendee.badge_type.in_(c.BADGE_TYPE_PRICES)),
                                                          Attendee.got_merch == False)  # noqa: E712
        }

    @csv_file
    def owed_merch_csv(self, out, session):
        out.writerow([
            'Name',
            'Name on ID',
            'Email Address',
            'Merch',
            'Extra Merch',
            'Shirt Size',
            'Badge #',
            'Money Owed',
            'Checked In',
            'Admin Notes',
        ])
        attendees = session.valid_attendees().filter(or_(Attendee.amount_extra > 0,
                                                         Attendee.badge_type.in_(c.BADGE_TYPE_PRICES)),
                                                     Attendee.got_merch == False)  # noqa: E712
        for attendee in attendees:
            out.writerow([
                attendee.full_name,
                attendee.legal_name,
                attendee.email,
                attendee.merch,
                attendee.extra_merch,
                attendee.shirt_label,
                attendee.badge_num,
                format_currency(attendee.amount_unpaid),
                datetime_local_filter(attendee.checked_in),
                attendee.admin_notes,
            ])
