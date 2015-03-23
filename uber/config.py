from uber.common import *

# Any configurable property defined in our configuration is automatically converted into a global constant,
# so outside of this file, we should never need to access this dictionary directly.  So we should prefer
# using the DONATIONS_ENABLED global constant instead of saying _config['donations_enabled'], etc.  See
# the comments in configspec.ini for explanations of the particilar options, which are documented there.
# All global constants defined and exported here are also passed to our templates.
_config = parse_config(__file__)

class State:
    """
    We use global constants for all of our configurable global state.  This works really well for things
    which do not change over time, such a the name of our event or what features are enabled.  However,
    some things depend on the date/time (such as the badge price, which can change over time), or whether
    we've hit our configured attendance cap (which changes based on the state of the database).  This
    class offers properties and methods for checking the state of these things.  Much like our global
    constants, the properties defined here are also passed directly to our templates.

    There's a single global instance of this class called "state" which you should use, e.g. if you need
    to check whether dealer registration is open in your code, you'd say state.DEALER_REG_OPEN (but in
    a template you'd just say DEALER_REG_CLOSED).

    For all of the datetime config options, we also define BEFORE_ and AFTER_ properties, e.g. you can
    check the booleans returned by state.BEFORE_PLACEHOLDER_DEADLINE or state.AFTER_PLACEHOLDER_DEADLINE
    """

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
        return BADGE_PRICES['single_day'].get(dt.strftime('%A'), default)

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
    def SEASON_BADGE_PRICE(self):
        return self.BADGE_PRICE + SEASON_LEVEL

    @property
    def GROUP_PRICE(self):
        return self.get_group_price(localized_now())

    @property
    def PREREG_BADGE_TYPES(self):
        types = [ATTENDEE_BADGE, PSEUDO_DEALER_BADGE, IND_DEALER_BADGE]
        for reg_open, badge_type in [(self.BEFORE_GROUP_PREREG_TAKEDOWN, PSEUDO_GROUP_BADGE)]:
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
        opts = [(ATTENDEE_BADGE, '12+ Full Weekend Pass (${})'.format(self.BADGE_PRICE))]
        if ONE_DAYS_ENABLED:
            opts.append((ONE_DAY_BADGE,  '12+ Single Day Pass (${})'.format(self.ONEDAY_BADGE_PRICE)))
        opts.append((YOUTH_BADGE,  '5-12 Full Weekend Pass($20)'))
        opts.append((KID_BADGE,  'Under 5 Full Weekend Pass($0)'))
        return opts

    @property
    def DISPLAY_ONEDAY_BADGES(self):
        return ONE_DAYS_ENABLED and days_before(30, EPOCH)

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

def _unrepr(d):
    for opt in d:
        val = d[opt]
        if val in ['True', 'False']:
            d[opt] = ast.literal_eval(val)
        elif isinstance(val, str) and val.isdigit():
            d[opt] = int(val)
        elif isinstance(d[opt], dict):
            _unrepr(d[opt])

_unrepr(_config['appconf'])
APPCONF = _config['appconf'].dict()

django.conf.settings.configure(**_config['django'].dict())

BADGE_PRICES = _config['badge_prices']
for _opt, _val in chain(_config.items(), BADGE_PRICES.items()):
    if not isinstance(_val, dict):
        globals()[_opt.upper()] = _val

DATES = {}
TIMESTAMP_FORMAT = '%Y-%m-%d %H:%M:%S'
DATE_FORMAT = '%Y-%m-%d'
EVENT_TIMEZONE = pytz.timezone(EVENT_TIMEZONE)
for _opt, _val in _config['dates'].items():
    if not _val:
        _dt = None
    elif ' ' in _val:
        _dt = EVENT_TIMEZONE.localize(datetime.strptime(_val, '%Y-%m-%d %H'))
    else:
        _dt = EVENT_TIMEZONE.localize(datetime.strptime(_val + ' 23:59', '%Y-%m-%d %H:%M'))
    globals()[_opt.upper()] = _dt
    if _dt:
        DATES[_opt.upper()] = _dt

PRICE_BUMPS = {}
for _opt, _val in BADGE_PRICES['attendee'].items():
    PRICE_BUMPS[EVENT_TIMEZONE.localize(datetime.strptime(_opt, '%Y-%m-%d'))] = _val

def _make_enum(enum_name, section, prices=False):
    opts, lookup, varnames = [], {}, []
    for name, desc in section.items():
        if isinstance(name, int):
            if prices:
                val, desc = desc, name
            else:
                val = name
        else:
            varnames.append(name.upper())
            val = globals()[name.upper()] = int(sha512(name.upper().encode()).hexdigest()[:7], 16)
        opts.append((val, desc))
        lookup[val] = desc

    enum_name = enum_name.upper()
    globals()[enum_name + '_OPTS'] = opts
    globals()[enum_name + '_VARS'] = varnames
    globals()[enum_name + ('' if enum_name.endswith('S') else 'S')] = lookup

def _is_intstr(s):
    if s and s[0] in ('-', '+'):
        return s[1:].isdigit()
    return s.isdigit()

for _name, _section in _config['enums'].items():
    _make_enum(_name, _section)

for _name, _val in _config['integer_enums'].items():
    if isinstance(_val, int):
        globals()[_name.upper()] = _val

for _name, _section in _config['integer_enums'].items():
    if isinstance(_section, dict):
        _interpolated = OrderedDict()
        for _desc, _val in _section.items():
            if _is_intstr(_val):
                key = int(_val)
            else:
                key = globals()[_val.upper()]

            _interpolated[key] = _desc

        _make_enum(_name, _interpolated, prices=_name.endswith('_price'))

BADGE_RANGES = {}
for _badge_type, _range in _config['badge_ranges'].items():
    BADGE_RANGES[globals()[_badge_type.upper()]] = _range

SHIFTLESS_DEPTS = {globals()[dept.upper()] for dept in SHIFTLESS_DEPTS}
PREASSIGNED_BADGE_TYPES = [globals()[badge_type.upper()] for badge_type in PREASSIGNED_BADGE_TYPES]
TRANSFERABLE_BADGE_TYPES = [globals()[badge_type.upper()] for badge_type in TRANSFERABLE_BADGE_TYPES]

SEASON_EVENTS = _config['season_events']
DEPT_HEAD_CHECKLIST = _config['dept_head_checklist']

BADGE_LOCK = RLock()

CON_LENGTH = int((ESCHATON - EPOCH).total_seconds() // 3600)
START_TIME_OPTS = [(dt, dt.strftime('%I %p %a')) for dt in (EPOCH + timedelta(hours=i) for i in range(CON_LENGTH))]
DURATION_OPTS   = [(i, '%i hour%s' % (i, ('s' if i > 1 else ''))) for i in range(1, 9)]
EVENT_START_TIME_OPTS = [(dt, dt.strftime('%I %p %a') if not dt.minute else dt.strftime('%I:%M %a'))
                         for dt in [EPOCH + timedelta(minutes = i * 30) for i in range(2 * CON_LENGTH)]]
EVENT_DURATION_OPTS = [(i, '%.1f hour%s' % (i/2, 's' if i != 2 else '')) for i in range(1, 19)]
SETUP_TIME_OPTS = [(dt, dt.strftime('%I %p %a')) for dt in (EPOCH - timedelta(days=2) + timedelta(hours=i) for i in range(16))] \
                + [(dt, dt.strftime('%I %p %a')) for dt in (EPOCH - timedelta(days=1) + timedelta(hours=i) for i in range(24))]
TEARDOWN_TIME_OPTS = [(dt, dt.strftime('%I %p %a')) for dt in (ESCHATON + timedelta(hours=i) for i in range(6))] \
                   + [(dt, dt.strftime('%I %p %a')) for dt in
                        ((ESCHATON + timedelta(days=1)).replace(hour=10) + timedelta(hours=i) for i in range(12))]


EVENT_NAME_AND_YEAR = EVENT_NAME + (' {}'.format(YEAR) if YEAR else '')
EVENT_YEAR = EPOCH.strftime('%Y')
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
    (0.5, 'Half Table'),
    (1.0, 'Full Table'),
    (2.0, 'Double Table'),
    (3.0, 'Triple Table'),
    (4.0, 'Island/Quad Table')
]

ADMIN_TABLE_OPTS = [(0.0, 'No Table')] + TABLE_OPTS + [(float(i), str(i)) for i in range(5, 11)]

TABLE_PRICES = {0: 0, 0.5: 40, 1: 100, 2: 350, 3: 600, 4: 999}

TABLE_OPTS = [(count, '{}: ${}'.format(desc, TABLE_PRICES[count])) for count, desc in TABLE_OPTS]

TABLE_EXTRA_PRICES = {POWER_TABLE: 60, WALL_TABLE: 10}

MAX_DEALER_BADGES = {0: 1, 0.5: 2, 1: 2, 2: 3, 3: 4, 4: 5}

NIGHT_DISPLAY_ORDER = [globals()[night.upper()] for night in NIGHT_DISPLAY_ORDER]
NIGHT_NAMES = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
CORE_NIGHTS = []
_day = EPOCH
while _day.date() != ESCHATON.date():
    CORE_NIGHTS.append(globals()[_day.strftime('%A').upper()])
    _day += timedelta(days=1)
SETUP_NIGHTS = NIGHT_DISPLAY_ORDER[:NIGHT_DISPLAY_ORDER.index(CORE_NIGHTS[0])]
TEARDOWN_NIGHTS = NIGHT_DISPLAY_ORDER[1 + NIGHT_DISPLAY_ORDER.index(CORE_NIGHTS[-1]):]

PREREG_SHIRT_OPTS = SHIRT_OPTS[1:]
MERCH_SHIRT_OPTS = [(SIZE_UNKNOWN, 'select a size')] + list(PREREG_SHIRT_OPTS)
DONATION_TIER_OPTS = [(amt, '+ ${}: {}'.format(amt,desc) if amt else desc) for amt,desc in DONATION_TIER_OPTS]

STORE_ITEM_NAMES = list(STORE_PRICES.keys())
FEE_ITEM_NAMES = list(FEE_PRICES.keys())

AT_OR_POST_CON = AT_THE_CON or POST_CON
PRE_CON = not AT_OR_POST_CON

SAME_NUMBER_REPEATED = r'^(\d)\1+$'
