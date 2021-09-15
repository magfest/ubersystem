from collections import defaultdict, OrderedDict
from datetime import datetime

from pytz import UTC
from sqlalchemy import or_

from uber.config import c
from uber.decorators import all_renderable
from uber.models import Attendee


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
        labels = ['size unknown'] + [label for val, label in c.SHIRT_OPTS][1:]

        def sort(d):
            return sorted(d.items(), key=lambda tup: labels.index(tup[0]))

        def label(s):
            return 'size unknown' if s == c.SHIRTS[c.NO_SHIRT] else s

        for attendee in session.all_attendees():
            shirt_label = attendee.shirt_label or 'size unknown'
            counts['staff'][label(shirt_label)] += attendee.num_staff_shirts_owed
            counts['event'][label(shirt_label)] += attendee.num_event_shirts_owed

        categories = []
        if c.SHIRTS_PER_STAFFER > 0:
            categories.append(('Staff Uniform Shirts', sort(counts['staff'])))

        categories.append(('Event Shirts', sort(counts['event'])))

        return {
            'categories': categories,
        }

    def shirt_counts(self, session):
        counts = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
        labels = ['size unknown'] + [label for val, label in c.SHIRT_OPTS][1:]

        def sort(d):
            return sorted(d.items(), key=lambda tup: labels.index(tup[0]))

        def label(s):
            return 'size unknown' if s == c.SHIRTS[c.NO_SHIRT] else s

        def status(got_merch):
            return 'picked_up' if got_merch else 'outstanding'

        sales_by_week = OrderedDict([(i, 0) for i in range(50)])

        for attendee in session.all_attendees():
            shirt_label = attendee.shirt_label or 'size unknown'
            counts['all_staff_shirts'][label(shirt_label)][status(attendee.got_merch)] += attendee.num_staff_shirts_owed
            counts['all_event_shirts'][label(shirt_label)][status(attendee.got_merch)] += attendee.num_event_shirts_owed
            counts['free_event_shirts'][label(shirt_label)][status(attendee.got_merch)] += attendee.num_free_event_shirts
            if attendee.paid_for_a_shirt:
                counts['paid_event_shirts'][label(shirt_label)][status(attendee.got_merch)] += 1
                sales_by_week[(min(datetime.now(UTC), c.ESCHATON) - attendee.registered).days // 7] += 1

        for week in range(48, -1, -1):
            sales_by_week[week] += sales_by_week[week + 1]

        categories = [
            ('Free Event Shirts', sort(counts['free_event_shirts'])),
            ('Paid Event Shirts', sort(counts['paid_event_shirts'])),
            ('All Event Shirts', sort(counts['all_event_shirts'])),
        ]
        if c.SHIRTS_PER_STAFFER > 0:
            categories.append(('Staff Shirts', sort(counts['all_staff_shirts'])))

        return {
            'sales_by_week': sales_by_week,
            'categories': categories,
        }

    def extra_merch(self, session):
        return {
            'attendees': session.query(Attendee).filter(Attendee.extra_merch != '').order_by(Attendee.full_name).all()}
        
    def owed_merch(self, session):
        return {
            'attendees': session.query(Attendee).filter(Attendee.amount_extra > 0, Attendee.got_merch == False)
        }
