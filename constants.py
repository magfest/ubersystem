from __future__ import division
from common import *

from secret_settings import OBFUSCATION_KEY, AWS_ACCESS_KEY_ID, AWS_SECRET_KEY

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

EVENT_LOC_OPTS = (
    (0,  "Panels 1"),
    (1,  "Panels 2"),
    (2,  "Panels 3"),
    (8,  "Panels 4"),
    (9,  "Panels 5"),
    (13, "Panels 6"),
    (10, "Autographs"),
    (5,  "Games on Film"),
    (3,  "Console (NGA Tournaments)"),
    (14, "Console (Attendee Tournaments)"),
    (15, "Consoles (Stage Tournaments)"),
    (4,  "Arcade"),
    (18, "LAN"),
    (6,  "Tabletop (Tournaments)"),
    (11, "Tabletop (Free Play)"),
    (12, "Tabletop (CCG)"),
    (7,  "Concerts"),
    (17, "Chiptunes"),
)
EVENT_LOCS = [loc for loc,desc in EVENT_LOC_OPTS]
EVENT_BOOKED = {"colspan": 0}
EVENT_OPEN   = {"colspan": 1}

BADGE_LOCK = RLock()

ATTENDEE_BADGE  = 0
STAFF_BADGE     = 1
GUEST_BADGE     = 2
SUPPORTER_BADGE = 3
ONE_DAY_BADGE   = 4
DORSAI_BADGE    = 5
BADGE_OPTS = (
    (ATTENDEE_BADGE,  "Attendee"),
    (STAFF_BADGE,     "Staff"),
    (GUEST_BADGE,     "Guest"),
    (SUPPORTER_BADGE, "Supporter"),
    (ONE_DAY_BADGE,   "One Day"),
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
NO_RIBBON        = 0
VOLUNTEER_RIBBON = 1
DEPT_HEAD_RIBBON = 2
PRESS_RIBBON     = 3
PANELIST_RIBBON  = 4
DEALER_RIBBON    = 5
BAND_RIBBON      = 6
RIBBON_OPTS = (
    (NO_RIBBON,        "no ribbon"),
    (VOLUNTEER_RIBBON, "Volunteer"),
    (DEPT_HEAD_RIBBON, "Department Head"),
    (PRESS_RIBBON,     "Camera"),
    (PANELIST_RIBBON,  "Panelist"),
    (DEALER_RIBBON,    "Shopkeep"),
    (BAND_RIBBON,      "Rock Star"),
)
PREASSIGNED_BADGE_TYPES = [STAFF_BADGE, SUPPORTER_BADGE]
CAN_UNSET = [ATTENDEE_BADGE]

NOT_PAID      = 0
HAS_PAID      = 1
NEED_NOT_PAY  = 2
REFUNDED      = 3
PAID_BY_GROUP = 4
PAID_OPTS = (
    (NOT_PAID,      "no"),
    (HAS_PAID,      "yes"),
    (NEED_NOT_PAY,  "doesn't need to"),
    (REFUNDED,      "paid and refunded"),
    (PAID_BY_GROUP, "paid by group")
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

LAN_ROOM = 3
INTEREST_OPTS = (
    (1, "consoles"),
    (2, "arcade"),
    (LAN_ROOM, "LAN"),
    (4, "music"),
    (5, "guests/panels"),
    (6, "videos"),
    (7, "tabletop games"),
    (8, "dealers"),
    (9, "tournaments"),
)

DEBIT  = 1
CREDIT = 2
BUDGET_TYPE_OPTS = (
    (DEBIT,  "expense"),
    (CREDIT, "revenue")
)
MAGFEST_FUNDS = 1

BANK_PAYMENT   = 1
PAYPAL_PAYMENT = 2
CASH_PAYMENT   = 3
PAYMENT_TYPE_OPTS = (
    (BANK_PAYMENT,   "Bank"),
    (PAYPAL_PAYMENT, "Paypal"),
    (CASH_PAYMENT,   "Cash")
)

ACCOUNTS   = 1
PEOPLE     = 2
STUFF      = 3
MONEY      = 4
CHALLENGES = 5
CHECKINS   = 6
ACCESS_OPTS = (
    (ACCOUNTS,   "Account Management"),
    (PEOPLE,     "Registration and Staffing"),
    (STUFF,      "Inventory and Scheduling"),
    (MONEY,      "Budget"),
    (CHALLENGES, "Challenges"),
    (CHECKINS,   "Checkins")
)
SIGNUPS = 100 # not an admin access level, so handled separately

JOB_INTEREST_OPTS = (
    (0, "Anything"),
    (1, "Arcade"),
    (2, "Challenges Booth"),
    (3, "Consoles"),
    (10,"Events"),
    (4, "Food Prep"),
    (5, "Jam Space"),
    (6, "LAN"),
    (7, "Security"),
    (8, "Regdesk"),
    (9, "Tabletop"),
    (12, "Tech Ops"),
    (11, "Video Room"),
)
ARCADE = 1
CONCERT = 3
CON_OPS = 5
MARKETPLACE = 10
MERCH = 11
STOPS = 17
JOB_LOC_OPTS = (
    (ARCADE, "Arcade"),
    (2, "Challenges"),
    (CONCERT, "Concert"),
    (4, "Consoles"),
    (CON_OPS, "Fest Ops"),
    (6, "Events"),
    (7, "Food Prep"),
    (8, "Jam Space"),
    (9, "LAN"),
    (MARKETPLACE, "Marketplace"),
    (MERCH, "Merchandise"),
    (13, "Regdesk"),
    (14, "Security"),
    (12, "Staff Support"),
    (STOPS, "Staffing Ops"),
    (15, "Tabletop"),
    (16, "Tech Ops"),
    (18, "Video Room"),
)
DEPT_CHAIRS = {
    ARCADE: "Ethan O'Toole, Tony Majors, Scott Schreiber, and Buffett",
    2: "Ryon Sumner and Challenge Andy",
    CONCERT: "James Pettigrew, Karen Lambey, and Matthew Stanford",
    4: "Michael Ridgaway, Bunny Smith, and Orvie Thumel",
    CON_OPS: "Aaron Churchill",
    6: "Carla Vorhees and Tim MacNeil",
    7: "Ben Seburn and David Lansdell",
    8: "Dan Kim and Ryan Meier",
    9: "Cleon Chick, Alex Cutlip, and Greg Cotton",
    MARKETPLACE: "Danielle Pomfrey",
    MERCH: "Ryan Nichols and Jeff Rosen",
    13: "Victoria Earl, Bob Earl, William Burghart, and Antigonut Jarrett",
    14: "Rene Gobeyn and Steve Simmons",
    12: "Eli Courtwright and Jack Boyd",
    STOPS: "Eli Courtwright and Jack Boyd",
    15: "Richard Mackay, Will Mackay, and Devon Courtwright",
    16: "Matthew Reid and Will Henson",
    18: "Gabriel Ricard",
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

SHIFT_UNMARKED = 0
SHIFT_WORKED   = 1
SHIFT_UNWORKED = 2
WORKED_OPTS = (
    (SHIFT_UNMARKED, "SELECT A STATUS"),
    (SHIFT_WORKED,   "This shift was worked"),
    (SHIFT_UNWORKED, "Staffer didn't show up")
)

UNRATED     = 0
RATED_BAD   = 1
RATED_GOOD  = 2
RATED_GREAT = 3
RATING_OPTS = (
    (UNRATED,     "Shift Unrated"),
    (RATED_BAD,   "Staffer performed poorly"),
    (RATED_GOOD,  "Staffer performed well"),
    (RATED_GREAT, "Staffer went above and beyond")
)

CREATE_AND_ASSOC    = 1
ASSOC_WITH_EXISTING = 2

AGE_UNKNOWN       = 0
UNDER_18          = 1
BETWEEN_18_AND_21 = 2
OVER_21           = 3
AGE_GROUP_OPTS = (
    (AGE_UNKNOWN,       "unknown"),
    (UNDER_18,          "under 18"),
    (BETWEEN_18_AND_21, "18, 19, or 20"),
    (OVER_21,           "21 or over")
)
PREREG_AGE_GROUP_OPTS = (
    (AGE_UNKNOWN,       "How old are you?"),
    (UNDER_18,          "under 18"),
    (BETWEEN_18_AND_21, "18, 19, or 20"),
    (OVER_21,           "21 or over")
)
WRISTBAND_COLORS = {
    UNDER_18: "red",
    BETWEEN_18_AND_21: "blue",
    OVER_21: "green"
}

NORMAL = 0
HARD   = 1
EXPERT = 2
UNFAIR = 3
LEVEL_OPTS = (
    (NORMAL, "Normal"),
    (HARD,   "Hard"),
    (EXPERT, "Expert"),
    (UNFAIR, "Unfair"),
)
LEVEL_VALUES = {
    NORMAL: 1,
    HARD:   2,
    EXPERT: 3,
    UNFAIR: 5,
}

CREATED = 0
UPDATED = 1
DELETED = 2
AUTO_BADGE_SHIFT = 3
TRACKING_OPTS = (
    (CREATED, "created"),
    (UPDATED, "updated"),
    (DELETED, "deleted"),
    (AUTO_BADGE_SHIFT, "automatic badge-shift"),
)

UNAPPROVED = 0
WAITLISTED = 1
APPROVED   = 2
STATUS_OPTS = (
    (UNAPPROVED, "Pending Approval"),
    (WAITLISTED, "Waitlisted"),
    (APPROVED,   "Approved"),
)

MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY, SATURDAY, SUNDAY = range(7)
NIGHTS_OPTS = (
    (MONDAY,    "Mon"),
    (TUESDAY,   "Tue"),
    (WEDNESDAY, "Wed"),
    (THURSDAY,  "Thu"),
    (FRIDAY,    "Fri"),
    (SATURDAY,  "Sat"),
    (SUNDAY,    "Sun"),
)

EMAIL_RE = re.compile("^[_A-Za-z0-9-]+(\\.[_A-Za-z0-9-+]+)*@[A-Za-z0-9-]+(\\.[A-Za-z0-9-]+)*(\\.[_A-Za-z0-9-]+)$")

MAX_TABLES  = 4
MAX_DEALERS = 3 * MAX_TABLES
MAX_GROUP_SIZE = 100

DEFAULT_AFFILIATES    = ["OC ReMix", "The Shizz", "ScrewAttack", "Empire Arcadia", "Yu-Gi-Oh Abridged"]

PAYPAL_ITEM = "item_number"
PAYPAL_COST = "mc_gross"
PAYPAL_STATUS = "payment_status"
PAYPAL_REASON = "pending_reason"
