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

for _opt, _val in conf.items():
    if not isinstance(_val, dict):
        globals()[_opt.upper()] = _val

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

PRICE_BUMPS = {}
for _opt, _val in conf['badge_prices']['attendee'].items():
    PRICE_BUMPS[EVENT_TIMEZONE.localize(datetime.strptime(_opt, '%Y-%m-%d'))] = _val

AT_OR_POST_CON = AT_THE_CON or POST_CON
PRE_CON = not AT_OR_POST_CON
