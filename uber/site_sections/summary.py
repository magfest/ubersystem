from uber.common import *


@all_renderable(c.STATS)
class Root:
    def index(self, session):
        attendees, groups = session.everyone()
        count = lambda *args, **kwargs: len([a for a in attendees
                                               if all(matcher(a) for matcher in args) and
                                                  all(val == getattr(a, name) for name, val in kwargs.items())])
        return {
            'total_count':   len(attendees),
            'shirt_sizes':   [(desc, count(shirt=shirt)) for shirt, desc in c.SHIRT_OPTS],
            'paid_counts':   [(desc, count(paid=status)) for status, desc in c.PAYMENT_OPTS],
            'badge_counts':  [(desc, count(badge_type=bt), count(paid=c.NOT_PAID, badge_type=bt), count(paid=c.HAS_PAID, badge_type=bt)) for bt, desc in c.BADGE_OPTS],
            'aff_counts':    [(aff['text'], len([a for a in attendees if a.amount_extra >= c.SUPPORTER_LEVEL and a.affiliate == aff['text']])) for aff in session.affiliates()],
            'checkin_count': count(lambda a: a.checked_in),
            'paid_noshows':  count(paid=c.HAS_PAID, checked_in=None) + len([a for a in attendees if a.paid == c.PAID_BY_GROUP and a.group and a.group.amount_paid and not a.checked_in]),
            'free_noshows':  count(paid=c.NEED_NOT_PAY, checked_in=None),
            'interests':     [(desc, len([a for a in attendees if a.paid != c.NOT_PAID and dept in a.interests_ints])) for dept, desc in c.INTEREST_OPTS],
            'age_counts':    [(desc, count(age_group=ag)) for ag, desc in c.AGE_GROUP_OPTS],
            'paid_group':    len([a for a in attendees if a.paid == c.PAID_BY_GROUP and a.group and a.group.amount_paid]),
            'free_group':    len([a for a in attendees if a.paid == c.PAID_BY_GROUP and a.group and not a.group.amount_paid]),
            'shirt_sales':   [(i, len([a for a in attendees if a.registered <= datetime.now(UTC) - timedelta(days=i * 7) and a.shirt != c.NO_SHIRT and (a.amount_paid or a.group and a.group.amount_paid)])) for i in range(50)],
            'ribbons':       [(desc, count(ribbon=val)) for val, desc in c.RIBBON_OPTS if val != c.NO_RIBBON],
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
            'registrations': session.query(Attendee).filter_by(paid=c.NEED_NOT_PAY).count(),
            'quantities': [(desc, session.query(Attendee).filter(Attendee.amount_extra >= amount).count())
                           for amount, desc in sorted(c.DONATION_TIERS.items()) if amount]
        }

    def departments(self, session):
        attendees = session.query(Attendee).filter_by(staffing=True).order_by(Attendee.full_name).all()
        everything = []
        for department, name in c.JOB_LOCATION_OPTS:
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
        guests = session.query(Attendee).filter_by(badge_type=c.GUEST_BADGE).count()
        volunteers = len([a for a in session.query(Attendee).filter_by(staffing=True).all()
                            if a.badge_type == c.STAFF_BADGE or a.weighted_hours or not a.takes_shifts])
        return {
            'guests': guests,
            'volunteers': volunteers,
            'notes': filter(bool, [getattr(fr, 'freeform', '') for fr in all_fr]),
            'standard': {
                c.FOOD_RESTRICTIONS[getattr(c, category)]: len([fr for fr in all_fr if getattr(fr, category)])
                for category in c.FOOD_RESTRICTION_VARS
            },
            'sandwich_prefs': {
                desc: len([fr for fr in all_fr if val in fr.sandwich_pref_ints])
                for val, desc in c.SANDWICH_OPTS
            }
        }

    def ratings(self, session):
        return {
            'prev_years': [a for a in session.query(Attendee)
                                             .filter_by(staffing=True)
                                             .order_by(Attendee.full_name).all()
                             if 'poorly' in a.past_years],
            'current': [a for a in session.query(Attendee)
                                          .options(joinedload(Attendee.shifts)).all()
                          if any(shift.rating == c.RATED_BAD for shift in a.shifts)]
        }

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
            } for dept, desc in c.JOB_LOCATION_OPTS]
        }

    @csv_file
    def printed_badges_attendee(self, out, session):
        uber.reports.PrintedBadgeReport(badge_type=c.ATTENDEE_BADGE).run(out, session)

    @csv_file
    def printed_badges_guest(self, out, session):
        uber.reports.PrintedBadgeReport(badge_type=c.GUEST_BADGE).run(out, session)

    @csv_file
    def printed_badges_one_day(self, out, session):
        uber.reports.PrintedBadgeReport(badge_type=c.ONE_DAY_BADGE).run(out, session)

    @csv_file
    def printed_badges_staff(self, out, session):
        uber.reports.PersonalizedBadgeReport().run(out, session,
            sa.Attendee.badge_type == c.STAFF_BADGE,
            sa.Attendee.badge_num != 0,
            order_by='badge_num')

    @csv_file
    def printed_badges_supporters(self, out, session):
        uber.reports.PersonalizedBadgeReport(include_badge_nums=False).run(out, session,
            sa.Attendee.amount_extra >= c.SUPPORTER_LEVEL,
            order_by=sa.Attendee.full_name,
            badge_type_override='supporter')

    @multifile_zipfile
    def personalized_badges_zip(self, zip_file, session):
        """All printed badge CSV files in one zipfile."""
        zip_file.writestr('printed_badges_attendee.csv', self.printed_badges_attendee())
        zip_file.writestr('printed_badges_guest.csv', self.printed_badges_guest())
        zip_file.writestr('printed_badges_one_day.csv', self.printed_badges_one_day())
        zip_file.writestr('printed_badges_staff.csv', self.printed_badges_staff())
        zip_file.writestr('printed_badges_supporters.csv', self.printed_badges_supporters())

    def food_eligible(self, session):
        cherrypy.response.headers['Content-Type'] = 'application/xml'
        eligible = {
            a: {attr.lower(): getattr(a.food_restrictions, attr, False) for attr in c.FOOD_RESTRICTION_VARS}
            for a in session.query(Attendee).order_by(Attendee.full_name).all()
            if not a.is_unassigned
                and (a.badge_type in (c.STAFF_BADGE, c.GUEST_BADGE)
                  or a.ribbon == c.VOLUNTEER_RIBBON and a.weighted_hours >= 12)
        }
        return render('summary/food_eligible.xml', {'attendees': eligible})

    @csv_file
    def staff_badges(self, out, session):
        for a in session.query(Attendee).filter_by(badge_type=c.STAFF_BADGE).order_by('badge_num').all():
            out.writerow([a.badge_num, a.full_name])

    @csv_file
    def all_attendees(self, out, session):
        cols = [getattr(Attendee, col.name) for col in Attendee.__table__.columns]
        out.writerow([col.name for col in cols])

        for attendee in session.valid_attendees().filter(Attendee.first_name != '').order_by(Attendee.badge_num).all():
            row = []
            for col in cols:
                if isinstance(col.type, Choice):
                    # Choice columns are integers with a single value with an automatic
                    # _label property, e.g. the "shirt" column has a "shirt_label"
                    # property, so we'll use that.
                    row.append(getattr(attendee, col.name + '_label'))
                elif isinstance(col.type, MultiChoice):
                    # MultiChoice columns are comma-separated integer lists with an
                    # automatic _labels property which is a list of string labels.
                    # So we'll get that and then separate the labels with slashes.
                    row.append(' / '.join(getattr(attendee, col.name + '_labels')))
                elif isinstance(col.type, UTCDateTime):
                    # Use the empty string if this is null, otherwise use strftime.
                    # Also you should fill in whatever actual format you want.
                    val = getattr(attendee, col.name)
                    row.append(val.strftime('%Y-%m-%d %H:%M:%S') if val else '')
                else:
                    # For everything else we'll just dump the value, although we might
                    # consider adding more special cases for things like foreign keys.
                    row.append(getattr(attendee, col.name))
            out.writerow(row)

    def shirt_counts(self, session):
        counts = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
        labels = ['size unknown'] + [label for val, label in c.SHIRT_OPTS][1:]
        sort = lambda d: sorted(d.items(), key=lambda tup: labels.index(tup[0]))
        label = lambda s: 'size unknown' if s == c.SHIRTS[c.NO_SHIRT] else s
        status = lambda got_merch: 'picked_up' if got_merch else 'outstanding'
        for attendee in session.query(Attendee).all():
            if attendee.gets_free_shirt:
                counts['free'][label(attendee.shirt_label)][status(attendee.got_merch)] += 1
                counts['all'][label(attendee.shirt_label)][status(attendee.got_merch)] += 1
            if attendee.gets_paid_shirt:
                counts['paid'][label(attendee.shirt_label)][status(attendee.got_merch)] += 1
                counts['all'][label(attendee.shirt_label)][status(attendee.got_merch)] += 1
        return {
            'categories': [
                ('Eligible free', sort(counts['free'])),
                ('Paid', sort(counts['paid'])),
                ('All pre-ordered', sort(counts['all']))
            ]
        }

    def extra_merch(self, session):
        return {'attendees': session.query(Attendee).filter(Attendee.extra_merch != '').order_by(Attendee.full_name).all()}

    def restricted_untaken(self, session):
        jobs, shifts, attendees = session.everything()
        untaken = defaultdict(lambda: defaultdict(list))
        for job in jobs:
            if job.restricted and job.slots_taken < job.slots:
                for hour in job.hours:
                    untaken[job.location][hour].append(job)
        flagged = []
        for attendee in attendees:
            if not attendee.is_dept_head:
                overlapping = defaultdict(set)
                for shift in attendee.shifts:
                    if not shift.job.restricted:
                        for dept in attendee.assigned_depts_ints:
                            for hour in shift.job.hours:
                                if attendee.trusted_in(dept) and hour in untaken[dept]:
                                    overlapping[shift.job].update(untaken[dept][hour])
                if overlapping:
                    flagged.append([attendee, sorted(overlapping.items(), key=lambda tup: tup[0].start_time)])
        return {'flagged': flagged}

    def consecutive_threshold(self, session):
        def exceeds_threshold(start_time, attendee):
            time_slice = [start_time + timedelta(hours=i) for i in range(18)]
            return len([h for h in attendee.hours if h in time_slice]) > 12
        jobs, shifts, attendees = session.everything()
        flagged = []
        for attendee in attendees:
            if attendee.staffing and attendee.weighted_hours > 12:
                for start_time, desc in c.START_TIME_OPTS[::6]:
                    if exceeds_threshold(start_time, attendee):
                        flagged.append(attendee)
                        break
        return {'flagged': flagged}

    def setup_teardown_neglect(self, session):
        return {
            'unfilled': [
                ('Setup', [job for job in session.query(Job).all() if job.is_setup and job.slots_untaken]),
                ('Teardown', [job for job in session.query(Job).all() if job.is_teardown and job.slots_untaken])
            ]
        }

    def volunteers_owed_refunds(self, session):
        attendees = session.query(Attendee).filter(Attendee.paid.in_([c.HAS_PAID, c.PAID_BY_GROUP, c.REFUNDED])).all()
        is_unrefunded = lambda a: a.paid == c.HAS_PAID or a.paid == c.PAID_BY_GROUP and a.group and a.group.amount_paid
        return {
            'attendees': [(
                'Volunteers Owed Refunds',
                [a for a in attendees if is_unrefunded(a) and a.worked_hours >= c.HOURS_FOR_REFUND]
            ), (
                'Volunteers Already Refunded',
                [a for a in attendees if a.paid == c.REFUNDED and a.staffing]
            ), (
                'Volunteers Who Can Be Refunded Once Their Shifts Are Marked',
                [a for a in attendees if is_unrefunded(a) and a.worked_hours < c.HOURS_FOR_REFUND
                                                          and a.weighted_hours >= c.HOURS_FOR_REFUND]
            )]
        }
