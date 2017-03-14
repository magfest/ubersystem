from uber.common import *


def generate_staff_badges(start_badge, end_badge, out, session):
    assert start_badge >= c.BADGE_RANGES[c.STAFF_BADGE][0]
    assert end_badge <= c.BADGE_RANGES[c.STAFF_BADGE][1]

    badge_range = (start_badge, end_badge)

    uber.reports.PrintedBadgeReport(
        badge_type=c.STAFF_BADGE,
        range=badge_range,
        badge_type_name='Staff') \
        .run(out, session)


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
    def dept_head_contact_info(self, out, session):
        out.writerow(["Full Name", "Email", "Phone", "Department(s)"])
        for a in session.query(Attendee).filter_by(ribbon=c.DEPT_HEAD_RIBBON).order_by('last_name'):
            for label in a.assigned_depts_labels:
                out.writerow([a.full_name, a.email, a.cellphone, label])

    @csv_file
    def dealer_table_info(self, out, session):
        out.writerow([
            'Name',
            'Description',
            'URL',
            'Address',
            'Tables',
            'Amount Paid',
            'Cost',
            'Badges'
        ])
        dealer_groups = session.query(Group).filter(Group.tables > 0).all()
        for group in dealer_groups:
            if group.approved and group.is_dealer:
                out.writerow([
                    group.name,
                    group.description,
                    group.website,
                    group.address,
                    group.tables,
                    group.amount_paid,
                    group.cost,
                    group.badges
                ])

    @csv_file
    def printed_badges_attendee(self, out, session):
        uber.reports.PrintedBadgeReport(badge_type=c.ATTENDEE_BADGE, badge_type_name='Attendee').run(out, session)

    @csv_file
    def printed_badges_guest(self, out, session):
        uber.reports.PrintedBadgeReport(badge_type=c.GUEST_BADGE, badge_type_name='Guest').run(out, session)

    @csv_file
    def printed_badges_one_day(self, out, session):
        uber.reports.PrintedBadgeReport(badge_type=c.ONE_DAY_BADGE, badge_type_name='OneDay').run(out, session)

    @csv_file
    def printed_badges_minor(self, out, session):
        uber.reports.PrintedBadgeReport(badge_type=c.CHILD_BADGE, badge_type_name='Minor').run(out, session)

    @csv_file
    def printed_badges_staff(self, out, session):

        # part 1, include only staff badges that have an assigned name
        uber.reports.PersonalizedBadgeReport().run(out, session,
                                                   Attendee.badge_type == c.STAFF_BADGE,
                                                   Attendee.badge_num != None,
                                                   order_by='badge_num')

        # part 2, include some extra for safety marging
        minimum_extra_amount = 5

        max_badges = c.BADGE_RANGES[c.STAFF_BADGE][1]
        start_badge = max_badges - minimum_extra_amount + 1
        end_badge = max_badges

        generate_staff_badges(start_badge, end_badge, out, session)

    @csv_file
    def printed_badges_staff__expert_mode_only(self, out, session, start_badge, end_badge):
        """
        Generate a CSV of staff badges. Note: This is not normally what you would call to do the badge export.
        For use by experts only.
        """

        generate_staff_badges(int(start_badge), int(end_badge), out, session)

    @csv_file
    def badge_hangars_supporters(self, out, session):
        uber.reports.PersonalizedBadgeReport(include_badge_nums=False).run(out, session,
            sa.Attendee.amount_extra >= c.SUPPORTER_LEVEL,
            order_by=sa.Attendee.full_name,
            badge_type_override='supporter')

    """
    Enumerate individual CSVs here that will be intergrated into the .zip which will contain all the
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
        Put all printed badge CSV files in one convenient zipfile.  The idea
        is that this ZIP file, unmodified, should be completely ready to send to
        the badge printers.

        Plugins can override badge_zipfile_contents to do something different/event-specific.
        """
        for badge_csv_fn in self.badge_zipfile_contents:
            csv_filename = '{}.csv'.format(badge_csv_fn.__name__)
            output = badge_csv_fn(self, session, set_headers=False)
            zip_file.writestr(csv_filename, output)

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

    def shirt_manufacturing_counts(self, session):
        """
        This report should be the definitive report about the count and sizes of shirts needed to be ordered.

        There are 2 types of shirts:
        - "staff shirts" - staff uniforms, each staff gets TWO currently
        - "swag shirts" - pre-ordered shirts, which the following groups receive:
            - volunteers (non-staff who get one for free)
            - attendees (who can pre-order them)
        """
        counts = defaultdict(lambda: defaultdict(int))
        labels = ['size unknown'] + [label for val, label in c.SHIRT_OPTS][1:]
        sort = lambda d: sorted(d.items(), key=lambda tup: labels.index(tup[0]))
        label = lambda s: 'size unknown' if s == c.SHIRTS[c.NO_SHIRT] else s

        for attendee in session.all_attendees():
            shirt_label = attendee.shirt_label or 'size unknown'

            if attendee.gets_staff_shirt:
                counts['staff'][label(shirt_label)] += c.SHIRTS_PER_STAFFER

            counts['swag'][label(shirt_label)] += attendee.num_swag_shirts_owed

        return {
            'categories': [
                ('Staff Uniform Shirts', sort(counts['staff'])),
                ('Swag Shirts', sort(counts['swag'])),
            ]
        }

    def shirt_counts(self, session):
        counts = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
        labels = ['size unknown'] + [label for val, label in c.SHIRT_OPTS][1:]
        sort = lambda d: sorted(d.items(), key=lambda tup: labels.index(tup[0]))
        label = lambda s: 'size unknown' if s == c.SHIRTS[c.NO_SHIRT] else s
        status = lambda got_merch: 'picked_up' if got_merch else 'outstanding'
        sales_by_week = OrderedDict([(i, 0) for i in range(50)])
        for attendee in session.all_attendees():
            shirt_label = attendee.shirt_label or 'size unknown'
            if attendee.volunteer_swag_shirt_eligible:
                counts['free_swag_shirts'][label(shirt_label)][status(attendee.got_merch)] += 1
                counts['all_swag_shirts'][label(shirt_label)][status(attendee.got_merch)] += 1
            if attendee.paid_for_a_swag_shirt:
                counts['paid_swag_shirts'][label(shirt_label)][status(attendee.got_merch)] += 1
                counts['all_swag_shirts'][label(shirt_label)][status(attendee.got_merch)] += 1
                sales_by_week[(datetime.now(UTC) - attendee.registered).days // 7] += 1
            if attendee.gets_staff_shirt:
                counts['staff_shirts'][label(shirt_label)][status(attendee.got_merch)] += c.SHIRTS_PER_STAFFER
        for week in range(48, -1, -1):
            sales_by_week[week] += sales_by_week[week + 1]
        return {
            'sales_by_week': sales_by_week,
            'categories': [
                ('Free Swag Shirts', sort(counts['free_swag_shirts'])),
                ('Paid Swag Shirts', sort(counts['paid_swag_shirts'])),
                ('All Swag Shirts', sort(counts['all_swag_shirts'])),
                ('Staff Shirts', sort(counts['staff_shirts']))
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
        attendees = session.all_attendees().filter(Attendee.paid.in_([c.HAS_PAID, c.PAID_BY_GROUP, c.REFUNDED])).all()
        is_unrefunded = lambda a: a.paid == c.HAS_PAID or a.paid == c.PAID_BY_GROUP and a.group and a.group.amount_paid\
                                                          and not a.group.amount_refunded
        return {
            'attendees': [(
                'Volunteers Owed Refunds',
                [a for a in attendees if is_unrefunded(a) and a.worked_hours >= c.HOURS_FOR_REFUND]
            ), (
                'Volunteers Already Refunded',
                [a for a in attendees if not is_unrefunded(a) and a.staffing]
            ), (
                'Volunteers Who Can Be Refunded Once Their Shifts Are Marked',
                [a for a in attendees if is_unrefunded(a) and a.worked_hours < c.HOURS_FOR_REFUND
                                                          and a.weighted_hours >= c.HOURS_FOR_REFUND]
            )]
        }
