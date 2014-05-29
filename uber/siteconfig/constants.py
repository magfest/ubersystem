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
    TABLETOP    = 'Tabletop games',
    MARKETPLACE = 'Dealers',
    TOURNAMENTS = 'Tournaments',
    FILM_FEST   = 'Film Festival',
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


del enum