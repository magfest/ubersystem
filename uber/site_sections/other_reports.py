import cherrypy

from uber.config import c
from uber.decorators import all_renderable, csv_file, render, site_mappable
from uber.models import Attendee, FoodRestrictions, GuestCharity


@all_renderable()
class Root:
    def food_restrictions(self, session):
        all_fr = session.query(FoodRestrictions).all()
        guests = session.query(Attendee).filter_by(badge_type=c.GUEST_BADGE).count()
        volunteers = len([
            a for a in session.query(Attendee).filter_by(staffing=True).all()
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

    def food_eligible(self, session):
        cherrypy.response.headers['Content-Type'] = 'application/xml'
        eligible = {
            a: {attr.lower(): getattr(a.food_restrictions, attr, False) for attr in c.FOOD_RESTRICTION_VARS}
            for a in session.staffers().all() + session.query(Attendee).filter_by(badge_type=c.GUEST_BADGE).all()
            if not a.is_unassigned and (
                a.badge_type in (c.STAFF_BADGE, c.GUEST_BADGE)
                or c.VOLUNTEER_RIBBON in a.ribbon_ints
                and a.weighted_hours >= 12)
        }
        return render('other_reports/food_eligible.xml', {'attendees': eligible})
    
    def guest_donations(self, session):
        return {
            'donation_offers': session.query(GuestCharity).filter(GuestCharity.desc != '')
        }

    @csv_file
    @site_mappable
    def requested_accessibility_services(self, out, session):
        out.writerow(['Badge #', 'Full Name', 'Badge Type', 'Email', 'Comments'])
        query = session.query(Attendee).filter_by(requested_accessibility_services=True)
        for person in query.all():
            out.writerow([
                person.badge_num, person.full_name, person.badge_type_label,
                person.email, person.comments
            ])
