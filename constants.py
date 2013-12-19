from common import *
from secret_settings import *

# TODO: property maker for datetimes that become booleans based on datetime.now()

DEV_BOX = True

YEAR = 12

EARLY_BADGE_PRICE = 40
LATE_BADGE_PRICE  = 45
LATER_BADGE_PRICE = 50
DOOR_BADGE_PRICE  = 60

EARLY_GROUP_PRICE = 30
LATE_GROUP_PRICE  = 35
LATER_GROUP_PRICE = 40

class State:
    SEND_EMAILS = True
    
    AT_THE_CON = False
    POST_CON = False
    UBER_SHUT_DOWN = False
    HIDE_SCHEDULE = False
    
    PREREG_CLOSED = False
    PREREG_NOT_OPEN_YET = False
    SUP_REG_OPEN = True
    GROUP_REG_OPEN = True
    DEALER_WAITLIST_CLOSED = False
    CUSTOM_BADGES_REALLY_ORDERED = False
    
    STAFFERS_IMPORTED    = datetime(2013,  7, 23)
    SHIFTS_CREATED       = datetime(2013, 10, 12, 23)
    PRICE_BUMP           = datetime(2013, 10, 31, 23, 59)
    SECOND_PRICE_BUMP    = datetime(2013, 11,  9, 23, 59)
    SECOND_GROUP_BUMP    = datetime(2013, 11, 30, 23, 59)
    DEALER_REG_START     = datetime(2013,  8,  8, 23, 59)
    DEALER_REG_DEADLINE  = datetime(2013,  8, 16, 23, 59)
    DEALER_REG_SHUTDOWN  = datetime(2013, 10, 30, 23, 59)
    DEALER_PAYMENT_DUE   = datetime(2013, 10, 31, 23, 59)
    MAGCON               = datetime(2013, 11,  9, 12)
    ROOM_DEADLINE        = datetime(2013, 12,  1, 23, 59)
    ROOMS_LOCKED_IN      = True
    SUPPORTER_DEADLINE   = datetime(2013, 12,  1, 23, 59)
    STAFF_BADGE_DEADLINE = datetime(2013, 12,  1, 23, 59)
    PREREG_TAKEDOWN      = datetime(2013, 12, 22, 23, 59)
    PLACEHOLDER_DEADLINE = datetime(2013, 12, 29, 23, 59)
    UBER_TAKEDOWN        = datetime(2013, 12, 29, 23, 59)
    EPOCH                = datetime(2014,  1,  2,  8)
    ESCHATON             = datetime(2014,  1,  5, 22)
    
    PATH     = "/magfest"
    HOSTNAME = "magfestubersystem.com"
    
    @property
    def URL_BASE(self):
        return "http://" + self.HOSTNAME + self.PATH
    
    @property
    def DEALER_REG_OPEN(self):
        return self.DEALER_REG_START < datetime.now() < self.DEALER_REG_SHUTDOWN
    
    @property
    def BADGE_PRICE(self):
        if datetime.now() < self.PRICE_BUMP:
            return EARLY_BADGE_PRICE
        elif datetime.now() < self.SECOND_PRICE_BUMP:
            return LATE_BADGE_PRICE
        elif state.AT_THE_CON:
            return DOOR_BADGE_PRICE
        else:
            return LATER_BADGE_PRICE
    
    @property
    def GROUP_PRICE(self):
        if datetime.now() < self.PRICE_BUMP:
            return EARLY_GROUP_PRICE
        elif datetime.now() < self.SECOND_GROUP_BUMP:
            return LATE_GROUP_PRICE
        else:
            return LATER_GROUP_PRICE
    
    @property
    def PREREG_BADGE_TYPES(self):
        types = [ATTENDEE_BADGE]
        for reg_open,badge_type in [(self.DEALER_REG_OPEN, PSEUDO_DEALER_BADGE),
                                    (self.GROUP_REG_OPEN,  PSEUDO_GROUP_BADGE)]:
            if reg_open:
                types.append(badge_type)
        return types
    
    @property
    def PREREG_DONATION_OPTS(self):
        if datetime.now() < self.SUPPORTER_DEADLINE:
            return DONATION_OPTS
        else:
            return [(amt, desc) for amt,desc in DONATION_OPTS if amt < SUPPORTER_LEVEL]
    
    @property
    def SHIFTS_AVAILABLE(self):
        return datetime.now() > self.SHIFTS_CREATED
    
    @property
    def ROOMS_AVAILABLE(self):
        return datetime.now() < self.ROOM_DEADLINE
    
    @property
    def DEALER_REG_FULL(self):
        return datetime.now() > self.DEALER_REG_DEADLINE
    
    @property
    def CUSTOM_BADGES_ORDERED(self):
        return datetime.now() > self.STAFF_BADGE_DEADLINE

state = State()

SHIRT_LEVEL = 20
SUPPORTER_LEVEL = 60
SEASON_LEVEL = 160
DONATION_TIERS = {
    0: "No thanks",
    5: "'Friend of MAGFest' ribbon",
    10: "button",
    SHIRT_LEVEL: "tshirt",
    40: "$10 in Mpoints",
    SUPPORTER_LEVEL: "Supporter Package",
    80: "pin",
    100: "'Don't ask what I had to do to get this ribbon'",
    120: "$0.000000001 Mpoint coin",
    SEASON_LEVEL: "Season Supporter Pass for 2014",
    200: "Tiara",
    300: "Pendant",
    400: "Scepter",
    500: "Robe and Wizard Hat"
}
DONATION_OPTS = sorted((amt, "+ ${}: {}".format(amt,desc) if amt else desc) for amt,desc in DONATION_TIERS.items())

def enum(**kwargs):
    decl_sort = kwargs.pop("_sort_by_declaration", False)
    if decl_sort:
        with open(__file__) as f:
            lines = f.readlines()
        def _line(tup):
            for i,line in enumerate(lines):
                if tup[0] in line:
                    return i
    xs = []
    for name,desc in kwargs.items():
        val = int(sha512(name.encode()).hexdigest()[:7], 16)
        globals()[name] = val
        xs.append((name, val, desc))
    return [x[1:] for x in sorted(xs, key = _line if decl_sort else lambda tup: tup[2])]

ONEDAY_BADGE_PRICE = 35
DEALER_BADGE_PRICE = 30
TABLE_PRICES       = "$125 for the first table, $175 for the second table, $225 for the third table, $300 for the fourth table"

ADMIN_EMAIL = "Eli Courtwright <eli@courtwright.org>"
REGDESK_EMAIL = "MAGFest Registration <regdesk@magfest.org>"
STAFF_EMAIL = "MAGFest Staffing <stops@magfest.org>"
MARKETPLACE_EMAIL = "MAGFest Marketplace <marketplace@magfest.org>"
PANELS_EMAIL = "MAGFest Panels <panels@magfest.org>"
REG_EMAILS = [ADMIN_EMAIL]
PAYMENT_BCC = [ADMIN_EMAIL]

CONSENT_FORM_URL  = state.URL_BASE + "/static/MinorConsentForm.pdf"

PAYPAL_RETURN_URL = "http://magfest.org/prereg-complete"
if DEV_BOX:
    PAYPAL_ACTION = "https://www.sandbox.paypal.com/cgi-bin/webscr"
else:
    REG_EMAILS += ["magfest.prereg@gmail.com"]
    PAYPAL_ACTION = "https://www.paypal.com/cgi-bin/webscr"

REGDESK_EMAIL_SIGNATURE = """\
 - Victoria Earl,
MAGFest Registration Chair"""

STOPS_EMAIL_SIGNATURE = """\
 - Jack Boyd,
MAGFest Staffing Coordinator"""

MARKETPLACE_EMAIL_SIGNATURE = """\
 - Danielle Pomfrey,
MAGFest Marketplace Coordinator"""

CON_LENGTH      = (state.ESCHATON - state.EPOCH).days * 24 + (state.ESCHATON - state.EPOCH).seconds // 3600
START_TIME_OPTS = [(dt, dt.strftime("%I %p %a")) for dt in (state.EPOCH + timedelta(hours = i) for i in range(CON_LENGTH))]
DURATION_OPTS   = [(i, "%i hour%s"%(i,("s" if i > 1 else ""))) for i in range(1,8)]
EVENT_START_TIME_OPTS = [(dt, dt.strftime("%I %p %a") if not dt.minute else dt.strftime("%I:%M %a"))
                         for dt in [state.EPOCH + timedelta(minutes = i * 30) for i in range(2 * CON_LENGTH)]]
EVENT_DURATION_OPTS = [(i, "%.1f hour%s" % (i/2, "s" if i != 2 else "")) for i in range(1, 19)]

EVENT_LOC_OPTS = enum(
    PANELS_1 = "Panels 1",
    PANELS_2 = "Panels 2",
    PANELS_3 = "Panels 3",
    PANELS_4 = "Panels 4",
    PANELS_5 = "MAGES",
    AUTOGRAPHS = "Autographs",
    GAMES_ON_FILM = "Games on Film",
    CONSOLE_NGA = "Console (NGA Tournaments)",
    CONSOLE_ATTENDEE = "Console (Attendee Tournaments)",
    CONSOLE_STAGE = "Console (Stage Tournaments)",
    ARCADE = "Arcade",
    LAN_1 = "LAN 1",
    LAN_2 = "LAN 2",
    TABLETOP_TOURNAMENTS = "Tabletop (Tournaments)",
    TABLETOP_FREEPLAY = "Tabletop (Free Play)",
    TABLETOP_CCG = "Tabletop (CCG)",
    CONCERTS = "Concerts",
    CHIPTUNES = "Chiptunes",
    SHEDSPACE = "Shedspace",
)
EVENT_LOCS = [loc for loc,desc in EVENT_LOC_OPTS]
EVENT_BOOKED = {"colspan": 0}
EVENT_OPEN   = {"colspan": 1}

BADGE_LOCK = RLock()

BADGE_OPTS = enum(
    ATTENDEE_BADGE  = "Attendee",
    SUPPORTER_BADGE = "Supporter",
    STAFF_BADGE     = "Staff",
    GUEST_BADGE     = "Guest",
    ONE_DAY_BADGE   = "One Day"
)
PSEUDO_GROUP_BADGE  = 101 # people registering in groups will get attendee badges
PSEUDO_DEALER_BADGE = 102 # dealers get attendee badges with a ribbon
BADGE_RANGES = {          # these may overlap, but shouldn't
    STAFF_BADGE:     [1, 499],
    SUPPORTER_BADGE: [500, 999],
    GUEST_BADGE:     [1000, 1250],
    ATTENDEE_BADGE:  [2000, 9500],
    ONE_DAY_BADGE:   [10000, 11000],
}
MAX_BADGE = max(xs[1] for xs in BADGE_RANGES.values())

RIBBON_OPTS = enum(
    NO_RIBBON        = "no ribbon",
    VOLUNTEER_RIBBON = "Volunteer",
    DEPT_HEAD_RIBBON = "Department Head",
    PRESS_RIBBON     = "Camera",
    PANELIST_RIBBON  = "Panelist",
    DEALER_RIBBON    = "Shopkeep",
    BAND_RIBBON      = "Rock Star"
)
PREASSIGNED_BADGE_TYPES = [STAFF_BADGE, SUPPORTER_BADGE]
CAN_UNSET = [ATTENDEE_BADGE]

PAID_OPTS = enum(
    NOT_PAID      = "no",
    HAS_PAID      = "yes",
    NEED_NOT_PAY  = "doesn't need to",
    REFUNDED      = "paid and refunded",
    PAID_BY_GROUP = "paid by group"
)

STORE_PRICES = (                # start as a tuple to preserve order for STORE_ITEMS
    ("MAGFest 11 tshirt", 15),
    ("EB Papas tshirt", 5),
    ("MAGFest 9 tshirt", 5),
    ("MAGFest X tshirt", 10),
    ("MAGFest hoodie", 30),
    ("MAGFest 11 sticker", 1),
    ("Squarewave Bumper Sticker", 2),
    ("Squarewave Car Window Decal", 4),
    ("Squarewave Lanyard", 4),
)
STORE_ITEMS = [(item,item) for item,price in STORE_PRICES]
STORE_PRICES = dict(STORE_PRICES)
FEE_PRICES = (
    ("Badge Replacement",    60),
    ("Wristband Replacement", 5),
)
FEE_ITEMS = [(item,item) for item,price in FEE_PRICES]
FEE_PRICES = dict(FEE_PRICES)

NO_SHIRT = 0
SHIRT_OPTS = (
    (NO_SHIRT, "no shirt"),
    (1, "small"),
    (2, "medium"),
    (3, "large"),
    (4, "x-large"),
    (5, "xx-large"),
    (6, "xxx-large"),
    (7, "small (female)"),
    (8, "medium (female)"),
    (9, "large (female)"),
    (10, "x-large (female)"),
)
PREREG_SHIRT_OPTS = SHIRT_OPTS[1:]

INTEREST_OPTS = enum(
    CONSOLE     = "Consoles",
    ARCADE      = "Arcade",
    LAN         = "LAN",
    MUSIC       = "Music",
    PANELS      = "Guests/Panels",
    VIDEO_ROOM  = "Videos",
    TABLETOP    = "Tabletop games",
    MARKETPLACE = "Dealers",
    TOURNAMENTS = "Tournaments"
)

BUDGET_TYPE_OPTS = enum(
    DEBIT  = "expense",
    CREDIT = "revenue"
)
MAGFEST_FUNDS = 1

PAYMENT_TYPE_OPTS = enum(
    BANK_PAYMENT   = "Bank",
    PAYPAL_PAYMENT = "Paypal",
    CASH_PAYMENT   = "Cash"
)

ACCESS_OPTS = enum(
    ACCOUNTS   = "Account Management",
    PEOPLE     = "Registration and Staffing",
    STUFF      = "Inventory and Scheduling",
    MONEY      = "Budget",
    CHALLENGES = "Challenges",
    CHECKINS   = "Checkins",
    STATS      = "Analytics",
)
SIGNUPS = 100 # not an admin access level, so handled separately

JOB_INTEREST_OPTS = enum(
    ANYTHING   = "Anything",
    ARCADE     = "Arcade",
    CHALLENGES = "Challenges Booth",
    CONSOLE    = "Consoles",
    PANELS     = "Panels",
    FOOD_PREP  = "Food Prep",
    JAMSPACE   = "Jam Space",
    LAN        = "LAN",
    SECURITY   = "Security",
    REGDESK    = "Regdesk",
    TABLETOP   = "Tabletop",
    TECH_OPS   = "Tech Ops",
    VIDEO_ROOM = "Film Festival",
)
JOB_LOC_OPTS = enum(
    ARCADE        = "Arcade",
    ARTEMIS       = "Artemis",
    CHALLENGES    = "Challenges",
    CHARITY       = "Charity",
    CHIPSPACE     = "Chipspace",
    CONCERT       = "Concert",
    CONSOLE       = "Consoles",
    CON_OPS       = "Fest Ops",
    DISPATCH      = "Dispatch",
    PANELS        = "Events",
    FOOD_PREP     = "Food Prep",
    INDIE_GAMES   = "Indie Games",
    JAMSPACE      = "Jam Space",
    LAN           = "LAN",
    LOADIN        = "Load-In",
    MARKETPLACE   = "Marketplace",
    MERCH         = "Merchandise",
    MOPS          = "MEDIATRON!",
    REGDESK       = "Regdesk",
    REG_MANAGERS  = "Reg Managers",
    RESCUERS      = "Rescuers",
    SECURITY      = "Security",
    SHEDSPACE     = "Shedspace",
    STAFF_SUPPORT = "Staff Support",
    STOPS         = "Staffing Ops",
    TABLETOP      = "Tabletop",
    TREASURY      = "Treasury",
    CCG_TABLETOP  = "Tabletop (CCG)",
    TECH_OPS      = "Tech Ops",
    VIDEO_ROOM    = "Games on Film",
)
DEPT_CHAIRS = {
    ARCADE:        "Ethan O'Toole, Tony Majors, Scott Schreiber, and Buffett",
    CHALLENGES:    "Ryon Sumner and Challenge Andy",
    CONCERT:       "James Pettigrew, Karen Lambey, and Matthew Stanford",
    CONSOLE:       "Michael Ridgaway, Bunny Smith, and Orvie Thumel",
    CON_OPS:       "Aaron Churchill",
    PANELS:        "Carla Vorhees and Tim MacNeil",
    FOOD_PREP:     "Ben Seburn and David Lansdell",
    JAMSPACE:      "Dan Kim and Ryan Meier",
    LAN:           "Cleon Chick, Alex Cutlip, and Greg Cotton",
    MARKETPLACE:   "Danielle Pomfrey",
    MERCH:         "Ryan Nichols and Jeff Rosen",
    REGDESK:       "Victoria Earl, Bob Earl, William Burghart, and Antigonut Jarrett",
    SECURITY:      "Rene Gobeyn and Steve Simmons",
    STAFF_SUPPORT: "Eli Courtwright and Jack Boyd",
    STOPS:         "Eli Courtwright and Jack Boyd",
    TABLETOP:      "Richard Mackay, Will Mackay, and Devon Courtwright",
    TECH_OPS:      "Matthew Reid and Will Henson",
    VIDEO_ROOM:    "Gabriel Ricard",
}
JOB_PAGE_OPTS = (
    ("index",    "Calendar View"),
    ("signups",  "Signups View"),
    ("staffers", "Staffer Summary")
)
WEIGHT_OPTS = (
    ("1.0", "x1.0"),
    ("1.5", "x1.5"),
    ("2.0", "x2.0"),
    ("2.5", "x2.5"),
)
JOB_DEFAULTS = ["name","description","duration","slots","weight","restricted","extra15"]

WORKED_OPTS = enum(
    SHIFT_UNMARKED = "SELECT A STATUS",
    SHIFT_WORKED   = "This shift was worked",
    SHIFT_UNWORKED = "Staffer didn't show up"
)

RATING_OPTS = enum(
    UNRATED     = "Shift Unrated",
    RATED_BAD   = "Staffer performed poorly",
    RATED_GOOD  = "Staffer performed well",
    RATED_GREAT = "Staffer went above and beyond"
)

AGE_GROUP_OPTS = enum(
    _sort_by_declaration = True,
    AGE_UNKNOWN       = "How old are you?",
    UNDER_18          = "under 18",
    BETWEEN_18_AND_21 = "18, 19, or 20",
    OVER_21           = "21 or over"
)

WRISTBAND_COLORS = {
    UNDER_18: "red",
    BETWEEN_18_AND_21: "blue",
    OVER_21: "green"
}

LEVEL_OPTS = enum(
    NORMAL = "Normal",
    HARD   = "Hard",
    EXPERT = "Expert",
    UNFAIR = "Unfair"
)
LEVEL_VALUES = {
    NORMAL: 1,
    HARD:   2,
    EXPERT: 3,
    UNFAIR: 5,
}

TRACKING_OPTS = enum(
    CREATED = "created",
    UPDATED = "updated",
    DELETED = "deleted",
    UNPAID_PREREG = "unpaid preregistration",
    EDITED_PREREG = "edited_unpaid_prereg",
    AUTO_BADGE_SHIFT = "automatic badge-shift"
)

STATUS_OPTS = enum(
    UNAPPROVED = "Pending Approval",
    WAITLISTED = "Waitlisted",
    APPROVED   = "Approved"
)

NIGHTS_OPTS = enum(
    MONDAY    = "Mon",
    TUESDAY   = "Tue",
    WEDNESDAY = "Wed",
    THURSDAY  = "Thu",
    FRIDAY    = "Fri",
    SATURDAY  = "Sat",
    SUNDAY    = "Sun"
)
ORDERED_NIGHTS = [MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY, SATURDAY, SUNDAY]
NIGHT_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

FOOD_RESTRICTION_OPTS = enum(
    VEGETARIAN = "Vegetarian",
    VEGAN      = "Vegan",
    GLUTEN     = "Cannot eat gluten"
)

EMAIL_RE = re.compile("^[_A-Za-z0-9-]+(\\.[_A-Za-z0-9-+]+)*@[A-Za-z0-9-]+(\\.[A-Za-z0-9-]+)*(\\.[_A-Za-z0-9-]+)$")

MAX_TABLES  = 4
MAX_DEALERS = 20
MIN_GROUP_SIZE, MAX_GROUP_SIZE = 8, 100

DEFAULT_AFFILIATES = ["OC ReMix", "ScrewAttack",                                # got 26 and 12 supporters last year
                      "Destructoid", "Metroid Metal", "Lordkat",                # got 8 supporters last year
                      "8BitX Radio Network", "Channel Awesome", "The Megas",    # got 7 supporters last year
                      "TheShizz"]

SEASON_EVENTS = {
    "game_over_baltimore": {
        "day": datetime(2013, 7, 7),
        "deadline": datetime(2013, 7, 5, 23, 59),
        "location": "The Metro Gallery in Baltimore, Maryland",
        "url": "http://www.missiontix.com/events/product/17615/magfest-presents-game-over-baltimore-ii",
    },
    "game_over_durham": {
        "day": datetime(2013, 10, 4, 19, 30),
        "location": "The Pinhook in Durham, North Carolina",
        "url": "http://www.thepinhook.com/event/362215-mag-fest-game-over-durham/"
    },
    "magstock": {
        "day": datetime(2013, 7, 26),
        "location": "the Small Country Campground in Louisa, Virginia",
        "url": "http://magstock.net/"
    },
    "bitgen": {
        "day": datetime(2013, 8, 10),
        "url": "http://bitgen.magfest.org/",
        "location": "Rams Head Live in Baltimore",
        "deadline": datetime(2013, 8, 8, 23, 59)
    }
}
for _slug,_event in SEASON_EVENTS.items():
    _event['slug'] = _slug
    _event.setdefault('name', _slug.replace("_", " ").title())
    _event.setdefault('deadline', datetime.combine((_event['day'] - timedelta(days = 7)).date(), time(23, 59)))
