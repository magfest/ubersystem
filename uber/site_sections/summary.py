from uber.common import *


@all_renderable(c.STATS)
class Root:
    def index(self, session):
        counts = defaultdict(OrderedDict)
        counts.update({
            'groups': {'paid': 0, 'free': 0},
            'noshows': {'paid': 0, 'free': 0},
            'checked_in': {'yes': 0, 'no': 0}
        })
        count_labels = {
            'badges': c.BADGE_OPTS,
            'paid': c.PAYMENT_OPTS,
            'ages': c.AGE_GROUP_OPTS,
            'ribbons': c.RIBBON_OPTS,
            'interests': c.INTEREST_OPTS,
            'statuses': c.BADGE_STATUS_OPTS
        }
        for label, opts in count_labels.items():
            for val, desc in opts:
                counts[label][desc] = 0
        stocks = c.BADGE_PRICES['stocks']
        for var in c.BADGE_VARS:
            badge_type = getattr(c, var)
            counts['stocks'][c.BADGES[badge_type]] = stocks.get(var.lower(), 'no limit set')

        for a in session.query(Attendee).options(joinedload(Attendee.group)):
            counts['paid'][a.paid_label] += 1
            counts['ages'][a.age_group_label] += 1
            counts['ribbons'][a.ribbon_label] += 1
            counts['badges'][a.badge_type_label] += 1
            counts['statuses'][a.badge_status_label] += 1
            counts['checked_in']['yes' if a.checked_in else 'no'] += 1
            for val in a.interests_ints:
                counts['interests'][c.INTERESTS[val]] += 1
            if a.paid == c.PAID_BY_GROUP and a.group:
                counts['groups']['paid' if a.group.amount_paid else 'free'] += 1
            if not a.checked_in:
                key = 'paid' if a.paid == c.HAS_PAID or a.paid == c.PAID_BY_GROUP and a.group and a.group.amount_paid else 'free'
                counts['noshows'][key] += 1

        return {
            'counts': counts,
            'total_registrations': session.query(Attendee).count()
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
        for affiliate, amount in (session.query(Attendee.affiliate, Attendee.amount_extra)
                                         .filter(Attendee.amount_extra > 0)):
            counts['everything combined'].count(amount)
            counts[affiliate or 'no affiliate selected'].count(amount)

        return {
            'counts': sorted(counts.items(), key=lambda tup: -tup[-1].total),
            'registrations': session.query(Attendee).filter_by(paid=c.NEED_NOT_PAY).count(),
            'quantities': [(desc, session.query(Attendee).filter(Attendee.amount_extra >= amount).count())
                           for amount, desc in sorted(c.DONATION_TIERS.items()) if amount]
        }

    def departments(self, session):
        attendees = session.staffers().all()
        everything = []
        for department, name in c.JOB_LOCATION_OPTS:
            assigned = [a for a in attendees if department in a.assigned_depts_ints]
            unassigned = [a for a in attendees if department in a.requested_depts_ints and a not in assigned]
            everything.append([name, assigned, unassigned])
        return {'everything': everything}

    def found_how(self, session):
        return {'all': sorted([a.found_how for a in session.query(Attendee).filter(Attendee.found_how != '').all()], key=lambda s: s.lower())}

    def all_schedules(self, session):
        return {'staffers': [a for a in session.staffers() if a.shifts]}

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
            'prev_years': [a for a in session.staffers() if 'poorly' in a.past_years],
            'current': [a for a in session.staffers() if any(shift.rating == c.RATED_BAD for shift in a.shifts)]
        }

    def staffing_overview(self, session):
        attendees = session.staffers().all()
        jobs = session.jobs().all()
        return {
            'hour_total': sum(j.weighted_hours * j.slots for j in jobs),
            'shift_total': sum(j.weighted_hours * len(j.shifts) for j in jobs),
            'volunteers': len(attendees),
            'departments': [{
                'department': desc,
                'assigned': len([a for a in attendees if dept in a.assigned_depts_ints]),
                'total_hours': sum(j.weighted_hours * j.slots for j in jobs if j.location == dept),
                'taken_hours': sum(j.weighted_hours * len(j.shifts) for j in jobs if j.location == dept)
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

        # part 1, include only staff badges that have an assigned name
        uber.reports.PersonalizedBadgeReport().run(out, session,
            sa.Attendee.badge_type == c.STAFF_BADGE,
            sa.Attendee.badge_num != None,
            order_by='badge_num')

        # part 2, include a bunch of extra badges so we have some printed
        max_badges = c.BADGE_RANGES[c.STAFF_BADGE][1]
        extra_count = 20
        badge_range = (max_badges - extra_count, max_badges)
        uber.reports.PrintedBadgeReport(badge_type=c.STAFF_BADGE, range=badge_range).run(out, session)

    @csv_file
    def badge_hangars_supporters(self, out, session):
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
        zip_file.writestr('badge_hangars_supporters.csv', self.badge_hangars_supporters())

    def food_eligible(self, session):
        cherrypy.response.headers['Content-Type'] = 'application/xml'
        eligible = {
            a: {attr.lower(): getattr(a.food_restrictions, attr, False) for attr in c.FOOD_RESTRICTION_VARS}
            for a in session.staffers().all() + session.query(Attendee).filter_by(badge_type=c.GUEST_BADGE).all()
            if not a.is_unassigned
                and (a.badge_type in (c.STAFF_BADGE, c.GUEST_BADGE)
                  or a.ribbon == c.VOLUNTEER_RIBBON and a.weighted_hours >= 12)
        }
        return render('summary/food_eligible.xml', {'attendees': eligible})

    @csv_file
    def volunteers_with_worked_hours(self, out, session):
        out.writerow(['Badge #', 'Full Name', 'E-mail Address', 'Weighted Hours Scheduled', 'Weighted Hours Worked'])
        for a in session.query(Attendee).all():
            if a.worked_hours > 0:
                out.writerow([a.badge_num, a.full_name, a.email, a.weighted_hours, a.worked_hours])

    def shirt_counts(self, session):
        counts = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
        labels = ['size unknown'] + [label for val, label in c.SHIRT_OPTS][1:]
        sort = lambda d: sorted(d.items(), key=lambda tup: labels.index(tup[0]))
        label = lambda s: 'size unknown' if s == c.SHIRTS[c.NO_SHIRT] else s
        status = lambda got_merch: 'picked_up' if got_merch else 'outstanding'
        sales_by_week = OrderedDict([(i, 0) for i in range(50)])
        for attendee in session.staffers(only_staffing=False):
            shirt_label = attendee.shirt_label or 'size unknown'
            if attendee.gets_free_shirt:
                counts['free'][label(shirt_label)][status(attendee.got_merch)] += 1
                counts['all'][label(shirt_label)][status(attendee.got_merch)] += 1
            if attendee.gets_paid_shirt:
                counts['paid'][label(shirt_label)][status(attendee.got_merch)] += 1
                counts['all'][label(shirt_label)][status(attendee.got_merch)] += 1
                sales_by_week[(datetime.now(UTC) - attendee.registered).days // 7] += 1
            if attendee.gets_free_shirt and attendee.gets_paid_shirt:
                counts['both'][label(shirt_label)][status(attendee.got_merch)] += 1
        for week in range(48, -1, -1):
            sales_by_week[week] += sales_by_week[week + 1]
        return {
            'sales_by_week': sales_by_week,
            'categories': [
                ('Eligible free', sort(counts['free'])),
                ('Paid', sort(counts['paid'])),
                ('All pre-ordered', sort(counts['all'])),
                ('People with both free and paid shirts', sort(counts['both']))
            ]
        }

    def extra_merch(self, session):
        return {'attendees': session.query(Attendee).filter(Attendee.extra_merch != '').order_by(Attendee.full_name).all()}

    def restricted_untaken(self, session):
        untaken = defaultdict(lambda: defaultdict(list))
        for job in session.jobs():
            if job.restricted and job.slots_taken < job.slots:
                for hour in job.hours:
                    untaken[job.location][hour].append(job)
        flagged = []
        for attendee in session.staffers():
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
        flagged = []
        for attendee in session.staffers():
            if attendee.staffing and attendee.weighted_hours > 12:
                for start_time, desc in c.START_TIME_OPTS[::6]:
                    if exceeds_threshold(start_time, attendee):
                        flagged.append(attendee)
                        break
        return {'flagged': flagged}

    def setup_teardown_neglect(self, session):
        jobs = session.jobs().all()
        return {
            'unfilled': [
                ('Setup', [job for job in jobs if job.is_setup and job.slots_untaken]),
                ('Teardown', [job for job in jobs if job.is_teardown and job.slots_untaken])
            ]
        }

    def volunteers_owed_refunds(self, session):
        attendees = session.staffers(only_staffing=False).filter(Attendee.paid.in_([c.HAS_PAID, c.PAID_BY_GROUP, c.REFUNDED])).all()
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
