from uber.common import *

conf = parse_config(__file__)

def _unrepr(d):
    for opt in d:
        val = d[opt]
        if val in ['True', 'False']:
            d[opt] = ast.literal_eval(val)
        elif isinstance(val, str) and val.isdigit():
            d[opt] = int(val)
        elif isinstance(d[opt], dict):
            _unrepr(d[opt])

_unrepr(conf['appconf'])

if 'DATABASE_URL' in os.environ:
    _url = urlparse(os.environ['DATABASE_URL'])
    conf['django']['DATABASES']['default'].update({
        'HOST': _url.hostname,
        'PORT': _url.port,
        'USER': _url.username,
        'PASSWORD': _url.password,
        'NAME': _url.path.strip('/')
    })
django.conf.settings.configure(**conf['django'].dict())

for _opt, _val in chain(conf.items(), conf['badge_prices'].items()):
    if not isinstance(_val, dict):
        globals()[_opt.upper()] = _val

DATES = {}
TIMESTAMP_FORMAT = '%Y-%m-%d %H:%M:%S'
EVENT_TIMEZONE = pytz.timezone(EVENT_TIMEZONE)
for _opt, _val in conf['dates'].items():
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
for _opt, _val in conf['badge_prices']['attendee'].items():
    PRICE_BUMPS[EVENT_TIMEZONE.localize(datetime.strptime(_opt, '%Y-%m-%d'))] = _val

def _make_enum(enum_name, section):
    opts, lookup = [], {}
    for name, desc in section.items():
        if isinstance(name, int):
            val = name
        else:
            val = globals()[name.upper()] = int(sha512(name.upper().encode()).hexdigest()[:7], 16)
        opts.append((val, desc))
        lookup[val] = desc

    enum_name = enum_name.upper()
    globals()[enum_name + '_OPTS'] = opts
    globals()[enum_name + ('' if enum_name.endswith('S') else 'S')] = lookup

for _name, _section in conf['enums'].items():
    _make_enum(_name, _section)

for _name, _val in conf['integer_enums'].items():
    if isinstance(_val, int):
        globals()[_name.upper()] = _val
for _name, _section in conf['integer_enums'].items():
    if isinstance(_section, dict):
        _interpolated = OrderedDict()
        for _desc, _val in _section.items():
            _interpolated[int(_val) if _val.isdigit() else globals()[_val.upper()]] = _desc
        _make_enum(_name, _interpolated)

BADGE_RANGES = {}
for _badge_type, _range in conf['badge_ranges'].items():
    BADGE_RANGES[globals()[_badge_type.upper()]] = _range
