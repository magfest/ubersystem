from uber.common import *

@all_renderable(STATS)
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
        guests = session.query(Attendee).filter_by(badge_type=GUEST_BADGE).count()
        volunteers = [a for a in session.query(Attendee).filter_by(staffing=True).all() if a.badge_type == STAFF_BADGE or a.weighted_hours]
        return {
            'guests': guests,
            'volunteers': len(volunteers),
            'notes': filter(bool, [getattr(a.food_restrictions, 'freeform', '') for a in volunteers]),
            'standard': {
                category: len([a for a in volunteers if getattr(a.food_restrictions, category, False)])
                for category in ['vegetarian', 'vegan', 'gluten']
            }
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
        eligible = [a for a in session.query(Attendee).order_by(Attendee.full_name).all()
                      if not a.is_unassigned
                    and (a.badge_type in (STAFF_BADGE, GUEST_BADGE)
                      or a.ribbon == VOLUNTEER_RIBBON and a.weighted_hours >= 12)]
        return render('summary/food_eligible.xml', {'attendees': eligible})

    @csv_file
    def staff_badges(self, out, session):
        for a in session.query(Attendee).filter_by(badge_type=STAFF_BADGE).order_by('badge_num').all():
            out.writerow([a.badge_num, a.full_name])

    @csv_file
    def all_attendees(self, out, session):
        out.writerow(["status","placeholder","badge_num","badge_type","ribbon","first_name","last_name",
                     "email","birthdate","age_group_id","international","zip_code","address1","address2",
                     "city","region","country","no_cellphone","ec_name","ec_phone","cellphone","interests",
                     "found_how","comments","for_review","admin_notes","affiliate","shirt","can_spam",
                     "regdesk_info","extra_merch","got_merch","reg_station","registered","checked_in",
                     "paid","overridden_price","amount_paid","amount_extra","amount_refunded",
                     "payment_method","staffing","badge_printed_name","fire_safety_cert","requested_depts",
                     "assigned_depts","trusted","nonshift_hours","past_years","no_shirt","admin_account",
                     "hotel_requests","room_assignments","food_restrictions","group_id"])
        for a in session.query(Attendee).order_by('badge_num').all():
            try:
                birthdate = date.strftime(DATE_FORMAT, a.birthdate)
            except:
                raise
            out.writerow([a.status_label, a.placeholder, a.badge_num, a.badge_type_label, a.ribbon_label, a.first_name,
                          a.last_name, a.email, a.birthdate, a.age_group_id, a.international, a.zip_code,
                          a.address1, a.address2, a.city, a.region, a.country, a.no_cellphone, a.ec_name,
                          a.ec_phone, a.cellphone, a.interests, a.found_how, a.comments, a.for_review,
                          a.admin_notes, a.affiliate, a.shirt, a.can_spam, a.regdesk_info, a.extra_merch,
                          a.got_merch, a.reg_station, a.registered, a.checked_in, a.paid, a.overridden_price,
                          a.amount_paid, a.amount_extra, a.amount_refunded, a.payment_method, a.staffing,
                          a.badge_printed_name, a.fire_safety_cert, a.requested_depts, a.assigned_depts,
                          a.trusted, a.nonshift_hours, a.past_years, a.no_shirt, a.admin_account,
                          a.hotel_requests, a.room_assignments, a.food_restrictions, a.group_id])
