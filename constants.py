from common import *

from secret_settings import AWS_ACCESS_KEY_ID, AWS_SECRET_KEY

DEV_BOX = True

EARLY_BADGE_PRICE = 40
LATE_BADGE_PRICE  = 45
DOOR_BADGE_PRICE  = 60

EARLY_GROUP_PRICE = 30
LATE_GROUP_PRICE  = 35

class State:
    SEND_EMAILS = True
    AUTO_EMAILS = True
    
    AT_THE_CON = False
    POST_CON = False
    UBER_SHUT_DOWN = False
    HIDE_SCHEDULE = False
    
    PREREG_CLOSED = True
    PREREG_NOT_OPEN_YET = True
    SUP_REG_OPEN = False
    GROUP_REG_OPEN = True
    DEALER_WAITLIST_CLOSED = True
    ETCHED_BADGES_ORDERED = False
    
    STAFFERS_IMPORTED    = datetime(2012,  5, 29)
    SHIFTS_CREATED       = datetime(2012, 11,  3)
    PRICE_BUMP           = datetime(2012, 11,  4, 23, 59)
    DEALER_REG_START     = datetime(2012,  7, 27, 11, 59)
    DEALER_REG_SHUTDOWN  = datetime(2012, 11, 19, 11, 59)
    DEALER_REG_DEADLINE  = datetime(2012,  9,  3, 11, 59)
    DEALER_PAYMENT_DUE   = datetime(2012, 11, 30, 23, 59)
    ROOM_DEADLINE        = datetime(2012, 12,  1, 23, 59)
    STAFF_BADGE_DEADLINE = datetime(2012, 12,  9, 23, 59)
    PREREG_TAKEDOWN      = datetime(2012, 12, 23, 23, 59)
    PLACEHOLDER_DEADLINE = datetime(2012, 12, 30, 23, 59)
    UBER_TAKEDOWN        = datetime(2012, 12, 30, 23, 59)
    EPOCH                = datetime(2013,  1,  3,  8)
    ESCHATON             = datetime(2013,  1,  6, 22)
    
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
        elif state.AT_THE_CON:
            return DOOR_BADGE_PRICE
        else:
            return LATE_BADGE_PRICE
    
    @property
    def GROUP_PRICE(self):
        if datetime.now() < state.PRICE_BUMP:
            return EARLY_GROUP_PRICE
        else:
            return LATE_GROUP_PRICE
    
    @property
    def PREREG_BADGE_TYPES(self):
        types = [ATTENDEE_BADGE]
        for reg_open,badge_type in [(self.SUP_REG_OPEN,    SUPPORTER_BADGE),
                                    (self.DEALER_REG_OPEN, PSEUDO_DEALER_BADGE),
                                    (self.GROUP_REG_OPEN,  PSEUDO_GROUP_BADGE)]:
            if reg_open:
                types.append(badge_type)
        return types
    
    @property
    def SHIFTS_AVAILABLE(self):
        return datetime.now() > self.SHIFTS_CREATED
    
    @property
    def ROOMS_AVAILABLE(self):
        return datetime.now() < state.ROOM_DEADLINE
    
    @property
    def DEALER_REG_FULL(self):
        return datetime.now() > self.DEALER_REG_DEADLINE
    
    @property
    def CUSTOM_BADGES_ORDERED(self):
        return datetime.now() > self.STAFF_BADGE_DEADLINE

state = State()

def enum(**kwargs):
    xs = []
    for name,desc in kwargs.items():
        val = int(sha512(name.encode()).hexdigest()[:7], 16)
        globals()[name] = val
        xs.append((val, desc))
    return sorted(xs, key = lambda tup: tup[1])

SUPPORTER_BADGE_PRICE = 100
ONEDAY_BADGE_PRICE    = 35
DEALER_BADGE_PRICE    = 30
TABLE_PRICES          = "$120 for the first table, $160 for the second table, $200 for each additional table"

ADMIN_EMAIL = "Eli Courtwright <eli@courtwright.org>"
REGDESK_EMAIL = "Victoria Earl <regdesk@magfest.org>"
STAFF_EMAIL = "Jack Boyd <stops@magfest.org>"
MARKETPLACE_EMAIL = "Danielle Pomfrey <marketplace@magfest.org>"
PANELS_EMAIL = "panels@magfest.org"
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
    PANELS_5 = "Panels 5",
    PANELS_6 = "Panels 6",
    AUTOGRAPHS = "Autographs",
    GAMES_ON_FILM = "Games on Film",
    CONSOLE_NGA = "Console (NGA Tournaments)",
    CONSOLE_ATTENDEE = "Console (Attendee Tournaments)",
    CONSOLE_STAGE = "Console (Stage Tournaments)",
    ARCADE = "Arcade",
    LAN = "LAN",
    TABLETOP_TOURNAMENTS = "Tabletop (Tournaments)",
    TABLETOP_FREEPLAY = "Tabletop (Free Play)",
    TABLETOP_CCG = "Tabletop (CCG)",
    CONCERTS = "Concerts",
    CHIPTUNES = "Chiptunes",
)
EVENT_LOCS = [loc for loc,desc in EVENT_LOC_OPTS]
EVENT_BOOKED = {"colspan": 0}
EVENT_OPEN   = {"colspan": 1}

BADGE_LOCK = RLock()

BADGE_OPTS = enum(
    ATTENDEE_BADGE  = "Attendee",
    STAFF_BADGE     = "Staff",
    GUEST_BADGE     = "Guest",
    SUPPORTER_BADGE = "Supporter",
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

SHIRT_OPTS = (
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
)

ACCESS_OPTS = enum(
    ACCOUNTS   = "Account Management",
    PEOPLE     = "Registration and Staffing",
    STUFF      = "Inventory and Scheduling",
    MONEY      = "Budget",
    CHALLENGES = "Challenges",
    CHECKINS   = "Checkins"
)
SIGNUPS = 100 # not an admin access level, so handled separately

JOB_INTEREST_OPTS = enum(
    ANYTHING   = "Anything",
    ARCADE     = "Arcade",
    CHALLENGES = "Challenges Booth",
    CONSOLES   = "Consoles",
    EVENTS     = "Events",
    FOOD_PREP  = "Food Prep",
    JAMSPACE   = "Jam Space",
    LAN        = "LAN",
    SECURITY   = "Security",
    REGDESK    = "Regdesk",
    TABLETOP   = "Tabletop",
    TECHOPS    = "Tech Ops",
    VIDEO_ROOM = "Video Room",
)
JOB_LOC_OPTS = enum(
    ARCADE        = "Arcade",
    CHALLENGES    = "Challenges",
    CONCERT       = "Concert",
    CONSOLE       = "Consoles",
    CON_OPS       = "Fest Ops",
    PANELS        = "Events",
    FOOD_PREP     = "Food Prep",
    JAMSPACE      = "Jam Space",
    LAN           = "LAN",
    MARKETPLACE   = "Marketplace",
    MERCH         = "Merchandise",
    REGDESK       = "Regdesk",
    SECURITY      = "Security",
    STAFF_SUPPORT = "Staff Support",
    STOPS         = "Staffing Ops",
    TABLETOP      = "Tabletop",
    TECHOPS       = "Tech Ops",
    VIDEO_ROOM    = "Video Room",
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
    TECHOPS:       "Matthew Reid and Will Henson",
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
    AGE_UNKNOWN       = "unknown",
    UNDER_18          = "under 18",
    BETWEEN_18_AND_21 = "18, 19, or 20",
    OVER_21           = "21 or over"
)
PREREG_AGE_GROUP_OPTS = enum(
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

EMAIL_RE = re.compile("^[_A-Za-z0-9-]+(\\.[_A-Za-z0-9-+]+)*@[A-Za-z0-9-]+(\\.[A-Za-z0-9-]+)*(\\.[_A-Za-z0-9-]+)$")

MAX_TABLES  = 4
MAX_DEALERS = 3 * MAX_TABLES
MAX_GROUP_SIZE = 100

DEFAULT_AFFILIATES = ["OC ReMix", "The Shizz", "ScrewAttack", "Empire Arcadia", "Yu-Gi-Oh Abridged"]

PAYPAL_ITEM = "item_number"
PAYPAL_COST = "mc_gross"
PAYPAL_STATUS = "payment_status"
PAYPAL_REASON = "pending_reason"
