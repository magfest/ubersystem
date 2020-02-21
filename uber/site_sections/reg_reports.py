from collections import Counter, defaultdict, OrderedDict

from datetime import datetime
from dateutil.relativedelta import relativedelta
from geopy.distance import VincentyDistance
from pockets.autolog import log
from pytz import UTC
import six
from sqlalchemy import and_, or_, func
from sqlalchemy.orm import joinedload
from sqlalchemy.sql.expression import extract, literal
from uszipcode import ZipcodeSearchEngine

from uber.config import c
from uber.decorators import ajax, all_renderable, csv_file, site_mappable
from uber.jinja import JinjaEnv
from uber.models import Attendee, Event, Group, PromoCode


@JinjaEnv.jinja_filter
def get_count(counter, key):
    return counter.get(key)


class RegistrationDataOneYear:
    def __init__(self):
        self.event_name = ""

        # what is the final day of this event (i.e. Sunday of a Fri->Sun festival)
        self.end_date = ""

        # this holds how many registrations were taken each day starting at 365 days from the end date of the event.
        # this array is in chronological order and does not skip days.
        #
        # examples:
        # registrations_per_day[0]   is the #regs that were taken on end_date-365 (1 year before the event)
        # .....
        # registrations_per_day[362] is the #regs that were taken on end_date-2 (2 days before the end date)
        # registrations_per_day[363] is the #regs that were taken on end_date-1 (the day before the end date)
        # registrations_per_day[364] is the #regs that were taken on end_date
        self.registrations_per_day = []

        # same as above, but, contains a cumulative sum of the same data
        self.registrations_per_day_cumulative_sum = []

        self.num_days_to_report = 365

    def query_current_year(self, session):
        self.event_name = c.EVENT_NAME_AND_YEAR

        # TODO: we're hacking the timezone info out of ESCHATON (final day of event). probably not the right thing to do
        self.end_date = c.DATES['ESCHATON'].replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)

        def date_trunc_day(*args, **kwargs):
            # sqlite doesn't support date_trunc
            if c.SQLALCHEMY_URL.startswith('sqlite'):
                return func.date(*args, **kwargs)
            else:
                return func.date_trunc(literal('day'), *args, **kwargs)

        # return registrations where people actually paid money
        # exclude: dealers
        reg_per_day = session.query(
                date_trunc_day(Attendee.registered),
                func.count(date_trunc_day(Attendee.registered))
            ) \
            .outerjoin(Attendee.group).outerjoin(Attendee.promo_code) \
            .filter(
                (
                    (Attendee.group_id != None) &
                    (Attendee.paid == c.PAID_BY_GROUP) &  # if they're paid by group
                    (Group.tables == 0) &                 # make sure they aren't dealers
                    (Group.amount_paid > 0)               # make sure they've paid something
                ) | (                                     # OR
                    (Attendee.paid == c.HAS_PAID)         # if they're an attendee, make sure they're fully paid
                ) | (
                    (Attendee.promo_code != None) &
                    (PromoCode.group_id != None) &
                    (PromoCode.cost > 0)
                )
            ) \
            .group_by(date_trunc_day(Attendee.registered)) \
            .order_by(date_trunc_day(Attendee.registered)) \
            .all()  # noqa: E711

        # now, convert the query's data into the format we need.
        # SQL will skip days without registrations
        # we need all self.num_days_to_report days to have data, even if it's zero

        # create 365 elements in the final array
        self.registrations_per_day = self.num_days_to_report * [0]

        for reg_data in reg_per_day:
            day = reg_data[0]
            reg_count = reg_data[1]

            day_offset = self.num_days_to_report - (self.end_date - day).days
            day_index = day_offset - 1

            if day_index < 0 or day_index >= self.num_days_to_report:
                log.info(
                    "Ignoring some analytics data because it's not in range of the year before c.ESCHATON. "
                    "Either c.ESCHATON is set incorrectly or you have registrations starting 1 year before ESCHATON, "
                    "or occuring after ESCHATON. day_index=" + str(day_index))
                continue

            self.registrations_per_day[day_index] = reg_count

        self.compute_cumulative_sum_from_registrations_per_day()

    # compute cumulative sum up until the last non-zero data point
    def compute_cumulative_sum_from_registrations_per_day(self):

        if len(self.registrations_per_day) != self.num_days_to_report:
            raise 'array validation error: array size should be the same as the report size'

        # figure out where the last non-zero data point is in the array
        last_useful_data_index = self.num_days_to_report - 1
        for regs in reversed(self.registrations_per_day):
            if regs != 0:
                break  # found it, so we're done.
            last_useful_data_index -= 1

        # compute the cumulative sum, leaving all numbers past the last data point at zero
        self.registrations_per_day_cumulative_sum = self.num_days_to_report * [0]
        total_so_far = 0
        current_index = 0
        for regs_this_day in self.registrations_per_day:
            total_so_far += regs_this_day
            self.registrations_per_day_cumulative_sum[current_index] = total_so_far
            if current_index == last_useful_data_index:
                break
            current_index += 1

    def dump_data(self):
        return {
            "registrations_per_day": self.registrations_per_day,
            "registrations_per_day_cumulative_sum": self.registrations_per_day_cumulative_sum,
            "event_name": self.event_name,
            "event_end_date": self.end_date.strftime("%d-%m-%Y"),
        }


@all_renderable()
class Root:
    def index(self, session):
        counts = defaultdict(OrderedDict)
        counts['donation_tiers'] = OrderedDict([(k, 0) for k in sorted(c.DONATION_TIERS.keys()) if k > 0])

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
            'statuses': c.BADGE_STATUS_OPTS,
            'checked_in_by_type': c.BADGE_OPTS,
        }
        for label, opts in count_labels.items():
            for val, desc in opts:
                counts[label][desc] = 0
        stocks = c.BADGE_PRICES['stocks']
        for var in c.BADGE_VARS:
            badge_type = getattr(c, var)
            counts['stocks'][c.BADGES[badge_type]] = stocks.get(var.lower(), 'no limit set')
            counts['counts'][c.BADGES[badge_type]] = c.get_badge_count_by_type(badge_type)

        for a in session.query(Attendee).options(joinedload(Attendee.group)):
            counts['paid'][a.paid_label] += 1
            counts['ages'][a.age_group_label] += 1
            for val in a.ribbon_ints:
                counts['ribbons'][c.RIBBONS[val]] += 1
            counts['badges'][a.badge_type_label] += 1
            counts['statuses'][a.badge_status_label] += 1
            counts['checked_in']['yes' if a.checked_in else 'no'] += 1
            if a.checked_in:
                counts['checked_in_by_type'][a.badge_type_label] += 1
            for val in a.interests_ints:
                counts['interests'][c.INTERESTS[val]] += 1
            if a.paid == c.PAID_BY_GROUP and a.group:
                counts['groups']['paid' if a.group.amount_paid else 'free'] += 1

            donation_amounts = list(counts['donation_tiers'].keys())
            for index, amount in enumerate(donation_amounts):
                next_amount = donation_amounts[index + 1] if index + 1 < len(donation_amounts) else six.MAXSIZE
                if a.amount_extra >= amount and a.amount_extra < next_amount:
                    counts['donation_tiers'][amount] = counts['donation_tiers'][amount] + 1
            if not a.checked_in:
                is_paid = a.paid == c.HAS_PAID or a.paid == c.PAID_BY_GROUP and a.group and a.group.amount_paid
                key = 'paid' if is_paid else 'free'
                counts['noshows'][key] += 1

        return {
            'counts': counts,
            'total_registrations': session.query(Attendee).count()
        }
        
    def comped_badges(self, session, message='', show='all'):
        regular_comped = session.attendees_with_badges().filter(Attendee.paid == c.NEED_NOT_PAY, 
                                                                Attendee.promo_code == None)
        promo_comped = session.attendees_with_badges().join(PromoCode).filter(Attendee.paid == c.NEED_NOT_PAY,
                                                                              or_(PromoCode.cost == None, 
                                                                                  PromoCode.cost == 0))
        group_comped = session.attendees_with_badges().join(Group, Attendee.group_id == Group.id)\
                .filter(Attendee.paid == c.PAID_BY_GROUP, Group.cost == 0)
        all_comped = regular_comped.union(promo_comped, group_comped)
        claimed_comped = all_comped.filter(Attendee.placeholder == False)
        unclaimed_comped = all_comped.filter(Attendee.placeholder == True)
            
        return {
            'message': message,
            'comped_attendees': all_comped,
            'all_comped': all_comped.count(),
            'claimed_comped': claimed_comped.count(),
            'unclaimed_comped': unclaimed_comped.count(),
            'show': show,
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

    def found_how(self, session):
        return {'all': sorted(
            [a.found_how for a in session.query(Attendee).filter(Attendee.found_how != '').all()],
            key=lambda s: s.lower())}

    @csv_file
    @site_mappable
    def attendee_birthday_calendar(
            self,
            out,
            session,
            year=datetime.now(UTC).year):

        out.writerow([
            'Subject', 'Start Date', 'Start Time', 'End Date', 'End Time',
            'All Day Event', 'Description', 'Location', 'Private'])

        query = session.query(Attendee).filter(Attendee.birthdate != None)  # noqa: E711
        for person in query.all():
            subject = "%s's Birthday" % person.full_name
            delta_years = year - person.birthdate.year
            start_date = person.birthdate + relativedelta(years=delta_years)
            end_date = start_date
            all_day = True
            private = False
            out.writerow([
                subject, start_date, '', end_date, '', all_day, '', '', private
            ])

    @csv_file
    @site_mappable
    def event_birthday_calendar(self, out, session):
        out.writerow([
            'Subject', 'Start Date', 'Start Time', 'End Date', 'End Time',
            'All Day Event', 'Description', 'Location', 'Private'])

        is_multiyear = c.EPOCH.year != c.ESCHATON.year
        is_multimonth = c.EPOCH.month != c.ESCHATON.month
        query = session.query(Attendee).filter(Attendee.birthdate != None)  # noqa: E711
        birth_month = extract('month', Attendee.birthdate)
        birth_day = extract('day', Attendee.birthdate)
        if is_multiyear:
            # The event starts in one year and ends in another
            query = query.filter(or_(
                or_(
                    birth_month > c.EPOCH.month,
                    birth_month < c.ESCHATON.month),
                and_(
                    birth_month == c.EPOCH.month,
                    birth_day >= c.EPOCH.day),
                and_(
                    birth_month == c.ESCHATON.month,
                    birth_day <= c.ESCHATON.day)))
        elif is_multimonth:
            # The event starts in one month and ends in another
            query = query.filter(or_(
                and_(
                    birth_month > c.EPOCH.month,
                    birth_month < c.ESCHATON.month),
                and_(
                    birth_month == c.EPOCH.month,
                    birth_day >= c.EPOCH.day),
                and_(
                    birth_month == c.ESCHATON.month,
                    birth_day <= c.ESCHATON.day)))
        else:
            # The event happens entirely within a single month
            query = query.filter(and_(
                birth_month == c.EPOCH.month,
                birth_day >= c.EPOCH.day,
                birth_day <= c.ESCHATON.day))

        for person in query.all():
            subject = "%s's Birthday" % person.full_name

            year_of_birthday = c.ESCHATON.year
            if is_multiyear:
                birth_month = person.birthdate.month
                birth_day = person.birthdate.day
                if birth_month >= c.EPOCH.month and birth_day >= c.EPOCH.day:
                    year_of_birthday = c.EPOCH.year

            delta_years = year_of_birthday - person.birthdate.year
            start_date = person.birthdate + relativedelta(years=delta_years)
            end_date = start_date
            all_day = True
            private = False
            out.writerow([
                subject, start_date, '', end_date, '', all_day, '', '', private
            ])

    @csv_file
    def checkins_by_hour(self, out, session):
        def date_trunc_hour(*args, **kwargs):
            # sqlite doesn't support date_trunc
            if c.SQLALCHEMY_URL.startswith('sqlite'):
                return func.strftime(literal('%Y-%m-%d %H:00'), *args, **kwargs)
            else:
                return func.date_trunc(literal('hour'), *args, **kwargs)

        out.writerow(["time_utc", "count"])
        query_result = session.query(
            date_trunc_hour(Attendee.checked_in),
            func.count(date_trunc_hour(Attendee.checked_in))
        ) \
            .filter(Attendee.checked_in.isnot(None)) \
            .group_by(date_trunc_hour(Attendee.checked_in)) \
            .order_by(date_trunc_hour(Attendee.checked_in)) \
            .all()

        for result in query_result:
            hour = result[0]
            count = result[1]
            out.writerow([hour, count])

    def badges_sold(self, session):
        graph_data_current_year = RegistrationDataOneYear()
        graph_data_current_year.query_current_year(session)

        return {
            'current_registrations': graph_data_current_year.dump_data(),
        }

    zips_counter = Counter()
    zips = {}
    center = ZipcodeSearchEngine().by_zipcode("20745")

    def map(self):
        return {
            'zip_counts': self.zips_counter,
            'center': self.center,
            'zips': self.zips
        }

    @ajax
    def refresh(self, session, **params):
        zips = {}
        self.zips_counter = Counter()
        attendees = session.query(Attendee).all()
        for person in attendees:
            if person.zip_code:
                self.zips_counter[person.zip_code] += 1

        for z in self.zips_counter.keys():
            found = ZipcodeSearchEngine().by_zipcode(z)
            if found.Zipcode:
                zips[z] = found

        self.zips = zips
        return True

    @csv_file
    def radial_zip_data(self, out, session, **params):
        if params.get('radius'):
            res = ZipcodeSearchEngine().by_coordinate(
                self.center["Latitude"], self.center["Longitude"], radius=int(params['radius']), returns=0)

            out.writerow(['# of Attendees', 'City', 'State', 'Zipcode', 'Miles from Event', '% of Total Attendees'])
            if len(res) > 0:
                keys = self.zips.keys()
                center_coord = (self.center["Latitude"], self.center["Longitude"])
                filter = Attendee.badge_status.in_([c.NEW_STATUS, c.COMPLETED_STATUS])
                attendees = session.query(Attendee).filter(filter)
                total_count = attendees.count()
                for x in res:
                    if x['Zipcode'] in keys:
                        out.writerow([self.zips_counter[x['Zipcode']], x['City'], x['State'], x['Zipcode'],
                                      VincentyDistance((x["Latitude"], x["Longitude"]), center_coord).miles,
                                      "%.2f" % float(self.zips_counter[x['Zipcode']] / total_count * 100)])

    @ajax
    def set_center(self, session, **params):
        if params.get("zip"):
            self.center = ZipcodeSearchEngine().by_zipcode(params["zip"])
            return "Set to %s, %s - %s" % (self.center["City"], self.center["State"], self.center["Zipcode"])
        return False

