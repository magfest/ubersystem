from uber.common import *

@all_renderable(PEOPLE, STATS)
class Root:
    def index(self):
        attendees = Attendee.objects.all()
        return {
            'total_count':   attendees.count(),
            'shirt_sizes':   [(desc,attendees.filter(shirt=shirt).count()) for shirt,desc in SHIRT_OPTS],
            'paid_counts':   [(desc,attendees.filter(paid=status).count()) for status,desc in PAID_OPTS],
            'badge_counts':  [(desc,attendees.filter(badge_type=bt).count(),attendees.filter(badge_type=bt,paid=NOT_PAID).count(),attendees.filter(badge_type=bt,paid=HAS_PAID).count()) for bt,desc in BADGE_OPTS],
            'aff_counts':    [(name,attendees.filter(badge_type=SUPPORTER_BADGE,affiliate=aff,paid=HAS_PAID).count(),attendees.filter(badge_type=SUPPORTER_BADGE,affiliate=aff,paid=NOT_PAID).count()) for name,aff in affiliates(exclude={})+[('None','')]],
            'checkin_count': attendees.exclude(checked_in__isnull=True).count(),
            'paid_noshows':  attendees.filter(paid=HAS_PAID, checked_in__isnull=True).count() + attendees.filter(paid=PAID_BY_GROUP, group__amount_paid__gt=0, checked_in__isnull=True).count(),
            'free_noshows':  attendees.filter(paid=NEED_NOT_PAY, checked_in__isnull=True).count(),
            'interests':     [(desc,attendees.exclude(paid=NOT_PAID).filter(interests__contains=str(i)).count()) for i,desc in INTEREST_OPTS],
            'age_counts':    [(desc,attendees.filter(age_group=ag).count()) for ag,desc in AGE_GROUP_OPTS],
            'paid_group':    attendees.filter(paid=PAID_BY_GROUP, group__amount_paid__gt=0).count(),
            'free_group':    attendees.filter(paid=PAID_BY_GROUP, group__amount_paid=0).count(),
            'shirt_sales':   [(i, Attendee.objects.filter(registered__lte=datetime.now(UTC) - timedelta(days = i * 7)).exclude(shirt=NO_SHIRT).count()) for i in range(50)],
            'ribbons':       [(desc, Attendee.objects.filter(ribbon=val).count()) for val,desc in RIBBON_OPTS if val != NO_RIBBON],
        }
    
    def affiliates(self):
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
        for affiliate,amount in Attendee.objects.filter(amount_extra__gt=0).values_list('affiliate', 'amount_extra'):
            counts['everything combined'].count(amount)
            counts[affiliate or 'no affiliate selected'].count(amount)
        return {
            'counts': sorted(counts.items(), key=lambda tup: -tup[-1].total),
            'registrations': Attendee.objects.exclude(paid=NEED_NOT_PAY).count(),
            'quantities': [(desc, Attendee.objects.filter(amount_extra__gte=amount).count())
                           for amount,desc in sorted(DONATION_TIERS.items()) if amount]
        }
    
    def departments(self):
        attendees = list(Attendee.objects.filter(staffing=True).order_by('first_name', 'last_name'))
        everything = []
        for department, name in JOB_LOC_OPTS:
            assigned = [a for a in attendees if department in a.assigned]
            unassigned = [a for a in attendees if department in a.requested_depts_ints and a not in assigned]
            everything.append([name, assigned, unassigned])
        return {'everything': everything}
    
    def found_how(self):
        return {'all': sorted(Attendee.objects.exclude(found_how='').values_list('found_how', flat=True), key=lambda s: s.lower())}
    
    def email_links(self):
        join = lambda al: ','.join(a.email for a in al)
        all = Attendee.objects.exclude(email='')
        return {
            'all':      join(all),
            'unpaid':   join(all.filter(paid=NOT_PAID)),
            'paid':     join(all.filter(paid=HAS_PAID)),
            'neednot':  join(all.filter(paid=NEED_NOT_PAY)),
            'groupies': join(all.filter(paid=PAID_BY_GROUP))
        }
    
    def all_schedules(self):
        return {'staffers': [a for a in Attendee.objects.filter(staffing = True).order_by('last_name','first_name') if a.shifts]}
    
    def food_restrictions(self):
        guests = Attendee.objects.filter(badge_type = GUEST_BADGE).count()
        volunteers = [a for a in Attendee.objects.filter(staffing = True) if a.badge_type == STAFF_BADGE or a.weighted_hours]
        return {
            'guests': guests,
            'volunteers': len(volunteers),
            'notes': filter(bool, [getattr(a.food_restrictions, 'freeform', '') for a in volunteers]),
            'standard': {
                category: len([a for a in volunteers if getattr(a.food_restrictions, category, False)])
                for category in ['vegetarian', 'vegan', 'gluten']
            }
        }
    
    def ratings(self):
        return {'attendees': [a for a in Attendee.objects.filter(staffing=True).order_by('first_name', 'last_name')
                                if 'poorly' in a.past_years]}
    
    def staffing_overview(self):
        jobs, shifts, attendees = Job.everything()
        return {
            'hour_total': sum(j.weighted_hours * j.slots for j in jobs),
            'shift_total': sum(s.job.weighted_hours for s in shifts),
            'volunteers': len(attendees),
            'departments': [{
                'department': desc,
                'assigned': len([a for a in attendees if dept in a.assigned]),
                'total_hours': sum(j.weighted_hours * j.slots for j in jobs if j.location == dept),
                'taken_hours': sum(s.job.weighted_hours for s in shifts if s.job.location == dept)
            } for dept,desc in JOB_LOC_OPTS]
        }
    
    @csv_file
    def personalized_badges(self, out):
        for a in Attendee.objects.exclude(badge_num=0).order_by('badge_num'):
            out.writerow([a.badge_num, a.get_badge_type_display(), a.badge_printed_name or a.full_name])
    
    def food_eligible(self):
        cherrypy.response.headers['Content-Type'] = 'application/xml'
        eligible = [a for a in Attendee.objects.order_by('first_name', 'last_name')
                      if not a.is_unassigned
                    and (a.badge_type in (STAFF_BADGE, GUEST_BADGE)
                      or a.ribbon == VOLUNTEER_RIBBON and a.weighted_hours >= 12)]
        return render('summary/food_eligible.xml', {'attendees': eligible})
    
    @csv_file
    def staff_badges(self, out):
        for a in Attendee.objects.filter(badge_type=STAFF_BADGE).order_by('badge_num'):
            out.writerow([a.badge_num, a.full_name])
