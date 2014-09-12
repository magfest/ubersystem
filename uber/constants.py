from uber.common import *

class State:
    @property
    def DEALER_REG_OPEN(self):
        return self.AFTER_DEALER_REG_START and self.BEFORE_DEALER_REG_SHUTDOWN
	
    @property
    def PREREG_OPEN(self):
        if PREREG_NOT_OPEN_YET or self.BEFORE_PREREG_OPENING:
            return "notopenyet"
        elif PREREG_CLOSED or self.AFTER_PREREG_TAKEDOWN:
            return "closed"
        else:
            return True
	
    @property
    def BADGES_SOLD(self):
        from uber.common import Attendee
        attendees = Attendee.objects.all()
        paid_group_sales = attendees.filter(paid=PAID_BY_GROUP, group__amount_paid__gt=0).count()
        paid_ind_sales = attendees.filter(paid=HAS_PAID, badge_type__in=[ATTENDEE_BADGE, SUPPORTER_BADGE]).count()
        badges_sold_count = paid_group_sales + paid_ind_sales
        return badges_sold_count
		
    def get_oneday_price(self, dt):
        default = conf['badge_prices']['default_single_day']
        return conf['badge_prices']['single_day'].get(dt.strftime('%A'), default)

    def get_attendee_price(self, dt):
        price = conf['badge_prices']['initial_attendee']
        for day, bumped_price in sorted(PRICE_BUMPS.items()):
            if dt >= day:
                price = bumped_price
        return price
    
    def get_specific_oneday_badge(self, day):
        for n in DAYS:
                current_day = datetime.strptime(n[0], "%Y-%m-%d")
                if day == current_day.strftime("%A"):
                    return state.get_oneday_price(current_day)
        return None

    def get_group_price(self, dt):
        return self.get_attendee_price(dt) - conf['badge_prices']['group_discount']

    @property
    def ONEDAY_BADGE_PRICE(self):
        return self.get_oneday_price(datetime.now())

    @property
    def BADGE_PRICE(self):
        return self.get_attendee_price(datetime.now())

    @property
    def SUPPORTER_BADGE_PRICE(self):
        supporter_price = self.BADGE_PRICE + SUPPORTER_LEVEL
        return supporter_price
    
    @property
    def GROUP_PRICE(self):
        return self.get_group_price(datetime.now())

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
        if datetime.now() < SUPPORTER_DEADLINE:
            return DONATION_OPTS
        else:
            return [(amt, desc) for amt,desc in DONATION_OPTS if amt < SUPPORTER_LEVEL]

    @property
    def THEME_DIR(self):
        return self.build_absolute_path(BASE_THEME_DIR + "/" + CURRENT_THEME)

    # example: turns string 'accounts/homepage' into
    # 'http://localhost:4321/magfest/accounts/homepage'
    def build_absolute_path(self, abs_path):
        return URL_BASE + "/" + abs_path

    def __getattr__(self, name):
        if name.startswith('BEFORE_'):
            return datetime.now() < globals()[name.split('_', 1)[1]]
        elif name.startswith('AFTER_'):
            return datetime.now() > globals()[name.split('_', 1)[1]]
        else:
            raise AttributeError('no such attribute {}'.format(name))


state = State()

EARLY_BADGE_PRICE = 50
LATE_BADGE_PRICE  = 60
DOOR_BADGE_PRICE  = 60

EARLY_GROUP_PRICE = 30
LATE_GROUP_PRICE  = 40

def enum(*, sort_by_declaration=False, **kwargs):
    if sort_by_declaration:
        with open(__file__) as f:
            lines = f.readlines()
        def _line(tup):
            for i,line in enumerate(lines):
                if re.match('^ {4}' + tup[0] + ' +=', line):
                    return i
    xs = []
    for name,desc in kwargs.items():
        val = int(sha512(name.encode()).hexdigest()[:7], 16)
        globals()[name] = val
        xs.append((name, val, desc))
    return [x[1:] for x in sorted(xs, key = _line if sort_by_declaration else lambda tup: tup[2])]

DEALER_BADGE_PRICE = 30
TABLE_PRICES = '$125 for the first table, $175 for the second table, $225 for the third table, $300 for the fourth table'

CON_LENGTH = int((ESCHATON - EPOCH).total_seconds() // 3600)
START_TIME_OPTS = [(dt, dt.strftime('%I %p %a')) for dt in (EPOCH + timedelta(hours = i) for i in range(CON_LENGTH))]
DURATION_OPTS   = [(i, '%i hour%s'%(i,('s' if i > 1 else ''))) for i in range(1,8)]
EVENT_START_TIME_OPTS = [(dt, dt.strftime('%I %p %a') if not dt.minute else dt.strftime('%I:%M %a'))
                         for dt in [EPOCH + timedelta(minutes = i * 30) for i in range(2 * CON_LENGTH)]]
EVENT_DURATION_OPTS = [(i, '%.1f hour%s' % (i/2, 's' if i != 2 else '')) for i in range(1, 19)]

if YEAR == '0':
    EVENT_NAME_AND_YEAR = EVENT_NAME 
else:
    EVENT_NAME_AND_YEAR = EVENT_NAME + " " + YEAR
PREREG_OPEN_DATE = PREREG_OPENING.strftime('%B') + " " + str(int(EPOCH.strftime('%d')) % 100)
EVENT_MONTH = EPOCH.strftime('%B')
EVENT_START_DAY = int(EPOCH.strftime('%d')) % 100
EVENT_END_DAY = int(ESCHATON.strftime('%d')) % 100

DAYS = sorted({(dt.strftime('%Y-%m-%d'), dt.strftime('%a')) for dt,desc in START_TIME_OPTS})
HOURS = ['{:02}'.format(i) for i in range(24)]
MINUTES = ['{:02}'.format(i) for i in range(60)]

EVENT_LOC_OPTS = enum(
    PANELS_1 = 'Panels 1',
    PANELS_2 = 'Panels 2',
    PANELS_3 = 'Panels 3',
    LAN = 'LAN',
    ARCADE = 'Arcade',
    CONCERTS = 'Concerts',
    TABLETOP = 'Tabletop',
    TABLETOP_CCG = 'Tabletop CCG',
    CONSOLE_ROOM = 'Console Room',
    OUTDOORS = 'Outdoor Events',
    JAMSPACE = 'Jamspace',
    CHIPTUNES = 'Chiptunes',
    REGISTRATION = 'Registration',
    HORIZONS = 'Horizons'
)
GROUPED_EVENTS = [PANELS_1, PANELS_2, PANELS_3,
                  CONCERTS, CHIPTUNES, JAMSPACE]
EVENT_LOCS = GROUPED_EVENTS + [loc for loc,desc in EVENT_LOC_OPTS if loc not in GROUPED_EVENTS]
EVENT_BOOKED = {'colspan': 0}
EVENT_OPEN   = {'colspan': 1}

BADGE_LOCK = RLock()

BADGE_OPTS = enum(
    ATTENDEE_BADGE  = 'Attendee',
    SUPPORTER_BADGE = 'Supporter',
    STAFF_BADGE     = 'Staff',
    GUEST_BADGE     = 'Guest',
    FRIDAY_BADGE    = 'Friday',
    SATURDAY_BADGE  = 'Saturday',
    SUNDAY_BADGE    = 'Sunday'
)
NORMAL_AT_THE_DOOR_BADGE_OPTS = enum(
    sort_by_declaration = True,
    ATTENDEE_BADGE = 'Full Weekend Pass (${})'.format(state.BADGE_PRICE),
    FRIDAY_BADGE   = 'Friday Pass (${})'.format(state.get_specific_oneday_badge(day="Friday")),
    SATURDAY_BADGE = 'Saturday Pass (${})'.format(state.get_specific_oneday_badge(day="Saturday")),
    SUNDAY_BADGE   = 'Sunday Pass (${})'.format(state.get_specific_oneday_badge(day="Sunday"))
)
AT_THE_DOOR_BADGE_OPTS = NORMAL_AT_THE_DOOR_BADGE_OPTS

PSEUDO_GROUP_BADGE  = 1  # people registering in groups will get attendee badges
PSEUDO_DEALER_BADGE = 2  # dealers get attendee badges with a ribbon
BADGE_RANGES = {         # these may overlap, but shouldn't
    STAFF_BADGE:     [1, 199],
    SUPPORTER_BADGE: [200, 799],
    GUEST_BADGE:     [800, 999],
    ATTENDEE_BADGE:  [1000, 2999],
    FRIDAY_BADGE:    [5000, 5499],
    SATURDAY_BADGE:  [5000, 5499],
    SUNDAY_BADGE:    [5000, 5499],
}
MAX_BADGE = max(xs[1] for xs in BADGE_RANGES.values())

RIBBON_OPTS = enum(
    NO_RIBBON        = 'no ribbon',
    VOLUNTEER_RIBBON = 'Volunteer',
    DEPT_HEAD_RIBBON = 'Department Head',
    PRESS_RIBBON     = 'Camera',
    PANELIST_RIBBON  = 'Panelist',
    DEALER_RIBBON    = 'Shopkeep',
    BAND_RIBBON      = 'Rock Star',
)
PREASSIGNED_BADGE_TYPES = [STAFF_BADGE, SUPPORTER_BADGE]
CAN_UNSET = [ATTENDEE_BADGE]

PAID_OPTS = enum(
    NOT_PAID      = 'no',
    HAS_PAID      = 'yes',
    NEED_NOT_PAY  = "doesn't need to",
    REFUNDED      = 'paid and refunded',
    PAID_BY_GROUP = 'paid by group'
)

FEE_PAYMENT_OPTS = enum(
    CASH = 'cash',
    CREDIT = 'credit'
)

PAYMENT_OPTIONS = enum(
    CASH = 'Cash',
    STRIPE = 'Stripe',
    SQUARE = 'Square',
    MANUAL = 'Stripe',
    GROUP = 'Group'
)

NEW_REG_PAYMENT_OPTS = enum(
    CASH = 'Cash',
    SQUARE = 'Square',
    MANUAL = 'Stripe'
)

DOOR_PAYMENT_OPTS = enum(
    sort_by_declaration = True,
    CASH   = 'Pay with cash',
    STRIPE = 'Pay with credit card now (faster)',
    MANUAL = 'Pay with credit card at the registration desk (slower)',
    GROUP  = 'Taking an unassigned Group badge (group leader must be present)'
)

KLUDGE_PAYMENT_OPTS = enum(
    CASH   = 'Pay with cash',
    MANUAL = 'Pay with credit card at the registration desk',
    GROUP  = 'Taking an unassigned Group badge (group leader must be present)'
)
KLUDGE_PAYMENT_OPTS = DOOR_PAYMENT_OPTS

STORE_PRICES = (                # start as a tuple to preserve order for STORE_ITEMS
    ('MAGFest 12 tshirt', 15),
    ('MAGFest 11 tshirt', 10),
    ('EB Papas tshirt', 5),
    ('MAGFest hoodie', 30),
    ('MAGFest 12 sticker', 1),
    ('Squarewave Bumper Sticker', 2),
    ('Squarewave Car Window Decal', 4),
    ('Squarewave Lanyard', 4),
)
STORE_ITEMS = [(item,item) for item,price in STORE_PRICES]
STORE_PRICES = dict(STORE_PRICES)
FEE_PRICES = (
    ('Badge Replacement',    60),
    ('Wristband Replacement', 5),
)
FEE_ITEMS = [(item,item) for item,price in FEE_PRICES]
FEE_PRICES = dict(FEE_PRICES)

SALE_OPTS = enum(
    MERCH = 'Merch',
    CASH = 'Cash',
    CREDIT = 'Credit Card'
)

ACCESS_OPTS = enum(
    ACCOUNTS   = 'Account Management',
    PEOPLE     = 'Registration and Staffing',
    STUFF      = 'Inventory and Scheduling',
    MONEY      = 'Budget',
    CHECKINS   = 'Checkins',
    STATS      = 'Analytics',
)
SIGNUPS = 100 # not an admin access level, so handled separately

JOB_LOC_OPTS = enum(
    ARCADE        = 'Arcade',
    ARTEMIS       = 'Artemis',
    CHALLENGES    = 'Challenges',
    CHARITY       = 'Charity',
    CHIPSPACE     = 'Chipspace',
    CONCERT       = 'Concert',
    CONSOLE       = 'Consoles',
    CONTRACTORS   = 'Contractors',
    CON_OPS       = 'Fest Ops',
    DISPATCH      = 'Dispatch',
    DORSAI        = 'Dorsai',
    PANELS        = 'Events',
    FOOD_PREP     = 'Food Prep',
    TEA_ROOM      = 'Tea Room',
    INDIE_GAMES   = 'Indie Games',
    JAMSPACE      = 'Jam Space',
    LAN           = 'LAN',
    LOADIN        = 'Load-In',
    MARKETPLACE   = 'Marketplace',
    MERCH         = 'Merchandise',
    MOPS          = 'MEDIATRON!',
    REGDESK       = 'Regdesk',
    REG_MANAGERS  = 'Reg Managers',
    RESCUERS      = 'Rescuers',
    SECURITY      = 'Security',
    SHEDSPACE     = 'Shedspace',
    STAFF_SUPPORT = 'Staff Support',
    STOPS         = 'Staffing Ops',
    TABLETOP      = 'Tabletop',
    TREASURY      = 'Treasury',
    CCG_TABLETOP  = 'Tabletop (CCG)',
    TECH_OPS      = 'Tech Ops',
)
DEPT_CHAIR_OVERRIDES = {
    STAFF_SUPPORT: 'Jack Boyd',
    SECURITY:      'The Dorsai Irregulars'
}
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
JOB_DEFAULTS = ['name','description','duration','slots','weight','restricted','extra15']

WORKED_OPTS = enum(
    SHIFT_UNMARKED = 'SELECT A STATUS',
    SHIFT_WORKED   = 'This shift was worked',
    SHIFT_UNWORKED = "Staffer didn't show up"
)

RATING_OPTS = enum(
    UNRATED     = 'Shift Unrated',
    RATED_BAD   = 'Staffer performed poorly',
    RATED_GOOD  = 'Staffer performed well',
    RATED_GREAT = 'Staffer went above and beyond'
)

AGE_GROUP_OPTS = enum(
    sort_by_declaration = True,
    AGE_UNKNOWN       = 'How old are you?',
    UNDER_18          = 'under 18',
    BETWEEN_18_AND_21 = '18, 19, or 20',
    OVER_21           = '21 or over'
)

WRISTBAND_COLORS = {
    UNDER_18: 'red',
    BETWEEN_18_AND_21: 'blue',
    OVER_21: 'green'
}

TRACKING_OPTS = enum(
    CREATED = 'created',
    UPDATED = 'updated',
    DELETED = 'deleted',
    UNPAID_PREREG = 'unpaid preregistration',
    EDITED_PREREG = 'edited_unpaid_prereg',
    AUTO_BADGE_SHIFT = 'automatic badge-shift'
)

TABLE_OPTS = [
    (0,   'no table'),
    (0.5, 'half-table')
] + [(float(i), i) for i in range(1, 11)]

STATUS_OPTS = enum(
    UNAPPROVED = 'Pending Approval',
    WAITLISTED = 'Waitlisted',
    APPROVED   = 'Approved'
)

NIGHTS_OPTS = enum(
    MONDAY    = 'Mon',
    TUESDAY   = 'Tue',
    WEDNESDAY = 'Wed',
    THURSDAY  = 'Thu',
    FRIDAY    = 'Fri',
    SATURDAY  = 'Sat',
    SUNDAY    = 'Sun'
)
ORDERED_NIGHTS = [MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY, SATURDAY, SUNDAY]
NIGHT_NAMES = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']

FOOD_RESTRICTION_OPTS = enum(
    VEGETARIAN = 'Vegetarian',
    VEGAN      = 'Vegan',
    GLUTEN     = 'Cannot eat gluten',
    NO_PORK    = 'No Pork',
    NO_DAIRY   = 'No Dairy'
)

BASE_THEME_DIR = "static/themes"


# gotta be a better way than exec into global scope. not sure how though.
try:
    exec("from siteconfig.constants import *")
except ImportError:
    pass
try:
    exec("from siteconfig." + CURRENT_THEME + ".constants import *")
except ImportError:
    pass

PREREG_SHIRT_OPTS = SHIRT_OPTS[1:]
MERCH_SHIRT_OPTS = [(SIZE_UNKNOWN, 'select a size')] + list(PREREG_SHIRT_OPTS)
DONATION_OPTS = sorted((amt, '+ ${}: {}'.format(amt,desc) if amt else desc) for amt,desc in DONATION_TIERS.items())
