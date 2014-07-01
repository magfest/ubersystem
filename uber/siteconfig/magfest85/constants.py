from uber.common import *

# used for constants that changed based on the event
# TODO: eventually this should go in the config file if possible.
# for now, it stays here.

# Common / base to all events

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

INTEREST_OPTS = enum(
    CONSOLE     = 'Consoles',
    ARCADE      = 'Arcade',
    LAN         = 'LAN',
    MUSIC       = 'Music',
    PANELS      = 'Guests/Panels',
    TABLETOP    = 'Tabletop Games',
    MARKETPLACE = 'Dealers',
    TOURNAMENTS = 'Tournaments',
    FILM_FEST   = 'Video Room',
    SPECIAL     = 'Special Events/Panels',
)

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


JOB_INTEREST_OPTS = enum(
    ANYTHING   = 'Anything',
    ARCADE     = 'Arcade',
    CONSOLE    = 'Consoles',
    PANELS     = 'Panels',
    FOOD_PREP  = 'Food Prep',
    JAMSPACE   = 'Jam Space',
    LAN        = 'LAN',
    SECURITY   = 'Security',
    REGDESK    = 'Regdesk',
    TABLETOP   = 'Tabletop',
    TECH_OPS   = 'Tech Ops',
    FILM_FEST  = 'Video Room',
)

SHIRT_LEVEL = 20
SUPPORTER_LEVEL = 50
SEASON_LEVEL = 160
DONATION_TIERS = {
    0: 'No thanks',
    5: 'Friend of MAGFest ribbon',
    SHIRT_LEVEL: 'T-shirt',
    SUPPORTER_LEVEL: 'Supporter Package',
}

DEALER_BADGE_PRICE = 30

BADGE_OPTS = enum(
    ATTENDEE_BADGE  = 'Attendee',
    SUPPORTER_BADGE = 'Supporter',
    STAFF_BADGE     = 'Staff',
    GUEST_BADGE     = 'Guest',
    ONE_DAY_BADGE   = 'One Day'
)

BADGE_RANGES = {         # these may overlap, but shouldn't
    STAFF_BADGE:     [1, 200],
    SUPPORTER_BADGE: [201, 700],
    GUEST_BADGE:     [701, 750],
    ATTENDEE_BADGE:  [751, 3000],
    ONE_DAY_BADGE:   [0, 0],
}

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
    ('Badge Replacement',    50),
    ('Wristband Replacement', 5),
)
FEE_ITEMS = [(item,item) for item,price in FEE_PRICES]
FEE_PRICES = dict(FEE_PRICES)

del enum