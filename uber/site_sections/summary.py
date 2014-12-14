from uber.common import *

@all_renderable(PEOPLE, STATS)
class Root:
    def index(self, session):
        attendees, groups = session.everyone()
        count = lambda **kwargs: len([a for a in attendees if all(val == getattr(a, name) for name, val in kwargs.items())])
        return {
            'total_count':   len(attendees),
            'shirt_sizes':   [(desc, count(shirt=shirt)) for shirt, desc in SHIRT_OPTS],
            'paid_counts':   [(desc, count(paid=status)) for status, desc in PAYMENT_OPTS],
            'badge_counts':  [(desc, count(badge_type=bt), count(paid=NOT_PAID, badge_type=bt), count(paid=HAS_PAID, badge_type=bt)) for bt, desc in BADGE_OPTS],
            'aff_counts':    [(aff['text'], count(badge_type=SUPPORTER_BADGE, affiliate=aff['text'], paid=HAS_PAID), count(badge_type=SUPPORTER_BADGE, affiliate=aff['text'], paid=NOT_PAID)) for aff in session.affiliates()],
            'checkin_count': count(checked_in=None),
            'paid_noshows':  count(paid=HAS_PAID, checked_in=None) + len([a for a in attendees if a.paid == PAID_BY_GROUP and a.group.amount_paid and not a.checked_in]),
            'free_noshows':  count(paid=NEED_NOT_PAY, checked_in=None),
            'interests':     [(desc, len([a for a in attendees if a.paid==NOT_PAID and dept in a.interests_ints])) for dept, desc in INTEREST_OPTS],
            'age_counts':    [(desc, count(age_group=ag)) for ag, desc in AGE_GROUP_OPTS],
            'paid_group':    len([a for a in attendees if a.paid == PAID_BY_GROUP and a.group.amount_paid]),
            'free_group':    len([a for a in attendees if a.paid == PAID_BY_GROUP and not a.group.amount_paid]),
            'shirt_sales':   [(i, len([a for a in attendees if a.registered <= datetime.now(UTC) - timedelta(days = i * 7) and a.shirt != NO_SHIRT])) for i in range(50)],
            'ribbons':       [(desc, count(ribbon=val)) for val, desc in RIBBON_OPTS if val != NO_RIBBON],
        }

    def affiliates(self, session):
        class AffiliateCounts:
            def __init__(self):
                self.tally, self.total = 0, 0
                self.amounts = {}

            @property
            def sorted(self):
                return sorted(self.amounts.items())

            def count(self, amount):
                self.tally += 1
                self.total += amount
                self.amounts[amount] = 1 + self.amounts.get(amount, 0)

        counts = defaultdict(AffiliateCounts)
        for affiliate, amount in session.query(Attendee.affiliate, Attendee.amount_extra) \
                                        .filter(Attendee.amount_extra > 0).all():
            counts['everything combined'].count(amount)
            counts[affiliate or 'no affiliate selected'].count(amount)
        return {
            'counts': sorted(counts.items(), key=lambda tup: -tup[-1].total),
            'registrations': session.query(Attendee).filter_by(paid=NEED_NOT_PAY).count(),
            'quantities': [(desc, session.query(Attendee).filter(Attendee.amount_extra >= amount).count())
                           for amount,desc in sorted(DONATION_TIERS.items()) if amount]
        }

    def departments(self, session):
        attendees = session.query(Attendee).filter_by(staffing=True).order_by(Attendee.full_name).all()
        everything = []
        for department, name in JOB_LOCATION_OPTS:
            assigned = [a for a in attendees if department in a.assigned_depts_ints]
            unassigned = [a for a in attendees if department in a.requested_depts_ints and a not in assigned]
            everything.append([name, assigned, unassigned])
        return {'everything': everything}

    def found_how(self, session):
        return {'all': sorted([a.found_how for a in session.query(Attendee).filter(Attendee.found_how != '').all()], key=lambda s: s.lower())}

    def all_schedules(self, session):
        return {'staffers': [a for a in session.query(Attendee).filter_by(staffing=True).order_by(Attendee.full_name) if a.shifts]}

    def food_restrictions(self, session):
        all_fr = session.query(FoodRestrictions).all()
        guests = session.query(Attendee).filter_by(badge_type=GUEST_BADGE).count()
        volunteers = len([a for a in session.query(Attendee).filter_by(staffing=True).all()
                            if a.badge_type == STAFF_BADGE or a.weighted_hours or not a.takes_shifts])
        return {
            'guests': guests,
            'volunteers': volunteers,
            'notes': filter(bool, [getattr(fr, 'freeform', '') for fr in all_fr]),
            'standard': {
                FOOD_RESTRICTIONS[globals()[category]]: len([fr for fr in all_fr if getattr(fr, category)])
                for category in FOOD_RESTRICTION_VARS
            },
            'sandwich_prefs': {
                sandtype: len([fr for fr in all_fr if fr.sandwich_pref == globals()[sandtype]])
                for sandtype in SANDWICH_VARS
            },
            'no_cheese': len([fr for fr in all_fr if fr.no_cheese])
        }

    def ratings(self, session):
        return {'attendees': [a for a in session.query(Attendee).filter_by(staffing=True).order_by(Attendee.full_name).all()
                                if 'poorly' in a.past_years]}

    def staffing_overview(self, session):
        jobs, shifts, attendees = session.everything()
        return {
            'hour_total': sum(j.weighted_hours * j.slots for j in jobs),
            'shift_total': sum(s.job.weighted_hours for s in shifts),
            'volunteers': len(attendees),
            'departments': [{
                'department': desc,
                'assigned': len([a for a in attendees if dept in a.assigned_depts_ints]),
                'total_hours': sum(j.weighted_hours * j.slots for j in jobs if j.location == dept),
                'taken_hours': sum(s.job.weighted_hours for s in shifts if s.job.location == dept)
            } for dept, desc in JOB_LOCATION_OPTS]
        }

    @csv_file
    def personalized_badges(self, out, session):
        for a in session.query(Attendee).filter(Attendee.badge_num != 0).order_by('badge_num').all():
            out.writerow([a.badge_num, a.badge_type_label, a.badge_printed_name or a.full_name])

    def food_eligible(self, session):
        cherrypy.response.headers['Content-Type'] = 'application/xml'
        eligible = {
            a: {attr.lower(): getattr(a.food_restrictions, attr, False) for attr in FOOD_RESTRICTION_VARS}
            for a in session.query(Attendee).order_by(Attendee.full_name).all()
            if not a.is_unassigned
                and (a.badge_type in (STAFF_BADGE, GUEST_BADGE)
                  or a.ribbon == VOLUNTEER_RIBBON and a.weighted_hours >= 12)
        }
        return render('summary/food_eligible.xml', {'attendees': eligible})

    @csv_file
    def staff_badges(self, out, session):
        for a in session.query(Attendee).filter_by(badge_type=STAFF_BADGE).order_by('badge_num').all():
            out.writerow([a.badge_num, a.full_name])

    def shirt_counts(self, session):
        counts = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
        labels = ['size unknown'] + [label for val, label in SHIRT_OPTS][1:]
        sort = lambda d: sorted(d.items(), key=lambda tup: labels.index(tup[0]))
        label = lambda s: 'size unknown' if s == 'no shirt' else s
        status = lambda got_merch: 'picked_up' if got_merch else 'outstanding'
        for attendee in session.query(Attendee).all():
            if attendee.gets_free_shirt:
                counts['free'][label(attendee.shirt_label)][status(attendee.got_merch)] += 1
            if attendee.gets_paid_shirt:
                counts['paid'][label(attendee.shirt_label)][status(attendee.got_merch)] += 1
            if attendee.gets_free_shirt and attendee.gets_paid_shirt:
                counts['both'][label(attendee.shirt_label)][status(attendee.got_merch)] += 1
        return {
            'categories': [
                ('Free', sort(counts['free'])),
                ('Paid', sort(counts['paid'])),
                ('Number of people who were counted in both of the above categories of', sort(counts['both']))
            ]
        }
