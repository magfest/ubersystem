from uber.common import *

class State:
    @property
    def DEALER_REG_OPEN(self):
        return self.AFTER_DEALER_REG_START and self.BEFORE_DEALER_REG_SHUTDOWN

    @property
    def BADGES_SOLD(self):
        with Session() as session:
            attendees = session.query(Attendee)
            individuals = attendees.filter(or_(Attendee.paid == HAS_PAID, Attendee.paid == REFUNDED)).count()
            group_badges = attendees.join(Attendee.group).filter(Attendee.paid == PAID_BY_GROUP,
                                                                 Group.amount_paid > 0).count()
            return individuals + group_badges

    def get_oneday_price(self, dt):
        default = DEFAULT_SINGLE_DAY
        return conf['badge_prices']['single_day'].get(dt.strftime('%A'), default)

    def get_attendee_price(self, dt):
        price = INITIAL_ATTENDEE
        if PRICE_BUMPS_ENABLED:
            for day, bumped_price in sorted(PRICE_BUMPS.items()):
                if (dt or datetime.now(UTC)) >= day:
                    price = bumped_price
        return price

    def get_group_price(self, dt):
        return self.get_attendee_price(dt) - GROUP_DISCOUNT

    @property
    def ONEDAY_BADGE_PRICE(self):
        return self.get_oneday_price(localized_now())

    @property
    def BADGE_PRICE(self):
        return self.get_attendee_price(localized_now())

    @property
    def SUPPORTER_BADGE_PRICE(self):
        return self.BADGE_PRICE + SUPPORTER_LEVEL

    @property
    def GROUP_PRICE(self):
        return self.get_group_price(localized_now())

    @property
    def PREREG_BADGE_TYPES(self):
        types = [ATTENDEE_BADGE]
        for reg_open, badge_type in [(self.DEALER_REG_OPEN, PSEUDO_DEALER_BADGE),
                                     (self.BEFORE_GROUP_PREREG_TAKEDOWN, PSEUDO_GROUP_BADGE)]:
            if reg_open:
                types.append(badge_type)
        return types

    @property
    def PREREG_DONATION_OPTS(self):
        if localized_now() < SUPPORTER_DEADLINE:
            return DONATION_TIER_OPTS
        else:
            return [(amt, desc) for amt,desc in DONATION_TIER_OPTS if amt < SUPPORTER_LEVEL]

    @property
    def SUPPORTERS_ENABLED(self):
        return SUPPORTER_LEVEL in dict(self.PREREG_DONATION_OPTS)

    @property
    def SEASON_SUPPORTERS_ENABLED(self):
        return SEASON_LEVEL in dict(self.PREREG_DONATION_OPTS)

    @property
    def AT_THE_DOOR_BADGE_OPTS(self):
        opts = [(ATTENDEE_BADGE, 'Full Weekend Pass (${})'.format(self.BADGE_PRICE))]
        if ONE_DAYS_ENABLED:
            opts.append((ONE_DAY_BADGE,  'Single Day Pass (${})'.format(self.ONEDAY_BADGE_PRICE)))
        return opts

    def __getattr__(self, name):
        if name.split('_')[0] in ['BEFORE', 'AFTER']:
            date_setting = globals()[name.split('_', 1)[1]]
            if not date_setting:
                return False
            elif name.startswith('BEFORE_'):
                return localized_now() < date_setting
            else:
                return localized_now() > date_setting
        else:
            raise AttributeError('no such attribute {}'.format(name))

state = State()    

BADGE_LOCK = RLock()

CON_LENGTH = int((ESCHATON - EPOCH).total_seconds() // 3600)
START_TIME_OPTS = [(dt, dt.strftime('%I %p %a')) for dt in (EPOCH + timedelta(hours = i) for i in range(CON_LENGTH))]
DURATION_OPTS   = [(i, '%i hour%s'%(i,('s' if i > 1 else ''))) for i in range(1,8)]
EVENT_START_TIME_OPTS = [(dt, dt.strftime('%I %p %a') if not dt.minute else dt.strftime('%I:%M %a'))
                         for dt in [EPOCH + timedelta(minutes = i * 30) for i in range(2 * CON_LENGTH)]]
EVENT_DURATION_OPTS = [(i, '%.1f hour%s' % (i/2, 's' if i != 2 else '')) for i in range(1, 19)]


EVENT_NAME_AND_YEAR = EVENT_NAME + (' {}'.format(YEAR) if YEAR else '')
EVENT_MONTH = EPOCH.strftime('%B')
EVENT_START_DAY = int(EPOCH.strftime('%d')) % 100
EVENT_END_DAY = int(ESCHATON.strftime('%d')) % 100

DAYS = sorted({(dt.strftime('%Y-%m-%d'), dt.strftime('%a')) for dt,desc in START_TIME_OPTS})
HOURS = ['{:02}'.format(i) for i in range(24)]
MINUTES = ['{:02}'.format(i) for i in range(60)]

ORDERED_EVENT_LOCS = [loc for loc, desc in EVENT_LOCATION_OPTS]
EVENT_BOOKED = {'colspan': 0}
EVENT_OPEN   = {'colspan': 1}

MAX_BADGE = max(xs[1] for xs in BADGE_RANGES.values())

JOB_PAGE_OPTS = (
    ('index',    'Calendar View'),
    ('signups',  'Signups View'),
    ('staffers', 'Staffer Summary')
)
WEIGHT_OPTS = (
    ('1.0', 'x1.0'),
    ('1.5', 'x1.5'),
    ('2.0', 'x2.0'),
    ('2.5', 'x2.5'),
)
JOB_DEFAULTS = ['name', 'description', 'duration', 'slots', 'weight', 'restricted', 'extra15']

TABLE_OPTS = [
    (0,   'no table'),
    (0.5, 'half-table')
] + [(float(i), i) for i in range(1, 11)]

NIGHT_DISPLAY_ORDER = [globals()[night.upper()] for night in NIGHT_DISPLAY_ORDER]
NIGHT_NAMES = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']

PREREG_SHIRT_OPTS = SHIRT_OPTS[1:]
MERCH_SHIRT_OPTS = [(SIZE_UNKNOWN, 'select a size')] + list(PREREG_SHIRT_OPTS)
DONATION_TIER_OPTS = [(amt, '+ ${}: {}'.format(amt,desc) if amt else desc) for amt,desc in DONATION_TIER_OPTS]

STORE_ITEM_NAMES = [name for price,name in STORE_PRICE_OPTS]
FEE_ITEM_NAMES = [name for price,name in FEE_PRICE_OPTS]

AT_OR_POST_CON = AT_THE_CON or POST_CON
PRE_CON = not AT_OR_POST_CON
