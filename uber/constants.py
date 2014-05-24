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
        paid_ind_sales = attendees.filter(paid=HAS_PAID).count()
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

    def __getattr__(self, name):
        if name.startswith('BEFORE_'):
            return datetime.now() < globals()[name.split('_', 1)[1]]
        elif name.startswith('AFTER_'):
            return datetime.now() > globals()[name.split('_', 1)[1]]
        else:
            raise AttributeError('no such attribute {}'.format(name))


state = State()

EARLY_BADGE_PRICE = 50
LATE_BADGE_PRICE  = 50
DOOR_BADGE_PRICE  = 50

EARLY_GROUP_PRICE = 30
LATE_GROUP_PRICE  = 40

SHIRT_LEVEL = 20
SUPPORTER_LEVEL = 50
SEASON_LEVEL = 160
DONATION_TIERS = {
    0: 'No thanks',
    5: 'Friend of MAGFest ribbon',
    SHIRT_LEVEL: 'T-shirt',
    SUPPORTER_LEVEL: 'Supporter Package',
}
DONATION_OPTS = sorted((amt, '+ ${}: {}'.format(amt,desc) if amt else desc) for amt,desc in DONATION_TIERS.items())

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

DAYS = sorted({(dt.strftime('%Y-%m-%d'), dt.strftime('%a')) for dt,desc in START_TIME_OPTS})
HOURS = ['{:02}'.format(i) for i in range(24)]
MINUTES = ['{:02}'.format(i) for i in range(60)]

EVENT_LOC_OPTS = enum(
    PANELS_1 = 'Panels 1',
    PANELS_2 = 'Panels 2',
    PANELS_3 = 'Panels 3',
    PANELS_4 = 'Panels 4',
    PANELS_5 = 'MAGES',
    BRAINSPACE = 'BrainSpace',
    AUTOGRAPHS = 'Autographs',
    FILM_FEST = 'Games on Film',
    CONSOLE_NGA = 'Console (NGA Tournaments)',
    CONSOLE_ATTENDEE = 'Console (Attendee Tournaments)',
    CONSOLE_STAGE = 'J.S. Joust + Sportsfriends',
    ARCADE = 'Arcade',
    LAN_1 = 'LAN 1',
    LAN_2 = 'LAN 2',
    TABLETOP_POKER = 'Tabletop (Poker)',
    TABLETOP_TOURNAMENTS = 'Tabletop (Tournaments)',
    TABLETOP_FREEPLAY = 'Tabletop (Free Play)',
    TABLETOP_CCG = 'Tabletop (CCG)',
    CONCERTS = 'Concerts',
    CHIPTUNES = 'Chiptunes',
    SHEDSPACE = 'Shedspace',
)
GROUPED_EVENTS = [PANELS_1, PANELS_2, PANELS_3, PANELS_4, PANELS_5, BRAINSPACE, AUTOGRAPHS,
                  CONCERTS, CHIPTUNES, SHEDSPACE,
                  CONSOLE_NGA, CONSOLE_ATTENDEE, CONSOLE_STAGE]
EVENT_LOCS = GROUPED_EVENTS + [loc for loc,desc in EVENT_LOC_OPTS if loc not in GROUPED_EVENTS]
EVENT_BOOKED = {'colspan': 0}
EVENT_OPEN   = {'colspan': 1}

BADGE_LOCK = RLock()

BADGE_OPTS = enum(
    ATTENDEE_BADGE  = 'Attendee',
    SUPPORTER_BADGE = 'Supporter',
    STAFF_BADGE     = 'Staff',
    GUEST_BADGE     = 'Guest',
    ONE_DAY_BADGE   = 'One Day'
)
AT_THE_DOOR_BADGE_OPTS = enum(
    ATTENDEE_BADGE = 'Full Weekend Pass (${})'.format(state.BADGE_PRICE),
    ONE_DAY_BADGE = 'Single Day Pass (${})'.format(state.ONEDAY_BADGE_PRICE)
)
PSEUDO_GROUP_BADGE  = 1  # people registering in groups will get attendee badges
PSEUDO_DEALER_BADGE = 2  # dealers get attendee badges with a ribbon
BADGE_RANGES = {         # these may overlap, but shouldn't
    STAFF_BADGE:     [1, 200],
    SUPPORTER_BADGE: [201, 700],
    GUEST_BADGE:     [701, 750],
    ATTENDEE_BADGE:  [751, 3000],
    ONE_DAY_BADGE:   [0, 0],
}
MAX_BADGE = max(xs[1] for xs in BADGE_RANGES.values())

RIBBON_OPTS = enum(
    NO_RIBBON        = 'no ribbon',
    VOLUNTEER_RIBBON = 'Volunteer',
    DEPT_HEAD_RIBBON = 'Department Head',
    PRESS_RIBBON     = 'Camera',
    PANELIST_RIBBON  = 'Panelist',
    DEALER_RIBBON    = 'Shopkeep',
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

SIZE_UNKNOWN = -1
NO_SHIRT = 0
SHIRT_OPTS = (
    (NO_SHIRT, 'no shirt'),
    (1, 'small'),
    (2, 'medium'),
    (3, 'large'),
    (4, 'x-large'),
    (5, 'xx-large'),
    (6, 'xxx-large'),
    (7, 'small (female)'),
    (8, 'medium (female)'),
    (9, 'large (female)'),
    (10, 'x-large (female)'),
)
PREREG_SHIRT_OPTS = SHIRT_OPTS[1:]
MERCH_SHIRT_OPTS = [(SIZE_UNKNOWN, 'select a size')] + list(PREREG_SHIRT_OPTS)

INTEREST_OPTS = enum(
    CONSOLE     = 'Consoles',
    ARCADE      = 'Arcade',
    LAN         = 'LAN',
    MUSIC       = 'Music',
    PANELS      = 'Guests/Panels',
    TABLETOP    = 'Tabletop games',
    MARKETPLACE = 'Dealers',
    TOURNAMENTS = 'Tournaments',
    FILM_FEST   = 'Film Festival',
)

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

JOB_INTEREST_OPTS = enum(
    ANYTHING   = 'Anything',
    ARCADE     = 'Arcade',
    CHALLENGES = 'Challenges Booth',
    CONSOLE    = 'Consoles',
    PANELS     = 'Panels',
    FOOD_PREP  = 'Food Prep',
    JAMSPACE   = 'Jam Space',
    LAN        = 'LAN',
    SECURITY   = 'Security',
    REGDESK    = 'Regdesk',
    TABLETOP   = 'Tabletop',
    TECH_OPS   = 'Tech Ops',
    FILM_FEST  = 'Film Festival',
)
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
    FILM_FEST     = 'Games on Film',
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
    GLUTEN     = 'Cannot eat gluten'
)
