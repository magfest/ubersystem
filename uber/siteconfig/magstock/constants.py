from uber.common import *

# used for constants that changed based on the event
# TODO: eventually this should go in the config file if possible.
# for now, it stays here.

# Magstock settings

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
    SLIP_N_SLIDE="Slip+N+Slide",
    MUSIC="Music",
    MOON_BOUNCE="Moon Bounce",
    COOKING="Cooking",
    NATURE_STUFF="Nature Stuff",
    SWIMMING="Swimming",
    PLAYING_VIDEOGAMES="Playing Videogames",
    FLOATING_THING_IN_LAKE="Floating Thing In Lake",
    NO_IDEA_FIRST_TIME="No idea (first time)",
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


SHIRT_COLOR_OPTS = (
    (NO_SHIRT, 'no shirt'),
    (1, 'Black'),
    (2, 'White (for tie-dyeing later)'),
)

PREREG_SHIRT_COLOR_OPTS = SHIRT_COLOR_OPTS[1:]

JOB_INTEREST_OPTS = enum(
    ANYTHING        = "Anything",
    FOOD_PREP       = "Food Prep",
    STAFF_SUPPORT   = "Staff support",
    MUSIC           = "Music",
    REGISTRATION    = "Registration",
    DRIVING         = "Driving campers On-site",
)


SHIRT_LEVEL = 20
SUPPORTER_LEVEL = 50
SEASON_LEVEL = 160
DONATION_TIERS = {
    SHIRT_LEVEL: 'T-shirt',
}

SHIRT_COST = SHIRT_LEVEL

del enum