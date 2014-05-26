from uber.common import *

MODULE_ROOT = abspath(dirname(__file__))
ROOT = MODULE_ROOT[:MODULE_ROOT.rfind(os.path.sep)]

_roots = ['root = "{}"'.format(ROOT), 'module_root = "{}"'.format(MODULE_ROOT)]
_rootspec = ['root = string(default="{}")\n'.format(ROOT), 'module_root = string(default="{}")\n'.format(MODULE_ROOT)]
with open(join(MODULE_ROOT, 'configspec.ini')) as _f:
    _spec = ConfigObj(_rootspec + _f.readlines(), list_values=False, interpolation=False, _inspec=True)

with open(join(MODULE_ROOT, 'defaults.conf')) as _f:
    conf = ConfigObj(_f.readlines(), configspec=_spec, interpolation='ConfigParser')

if any(sys.argv[0].endswith(testrunner) for testrunner in ['py.test', 'nosetests']):
    _overrides = ['uber/tests/test.conf']
else:
    _overrides = ['development.conf', 'production.conf']

_overrides.append('event.conf')

for _fname in _overrides:
    _fpath = join(ROOT, _fname)
    if exists(_fpath):
        with open(_fpath) as _f:
            conf.merge(ConfigObj(_roots + _f.readlines(), configspec=_spec, interpolation='ConfigParser'))

_validator = Validator()
_errors = conf.validate(_validator, preserve_errors=True)
if _errors != True:
    _errors = flatten_errors(conf, _errors)
    print('failed to validate configspec')
    pprint(_errors)
    raise ConfigObjError(_errors)

def _unrepr(d):
    for opt in d:
        val = d[opt]
        if val in ['True', 'False']:
            d[opt] = ast.literal_eval(val)
        elif isinstance(val, str) and val.isdigit():
            d[opt] = int(val)
        elif isinstance(d[opt], dict):
            _unrepr(d[opt])

_unrepr(conf['cherrypy'])
_unrepr(conf['appconf'])
cherrypy.config.update(conf['cherrypy'].dict())
cherrypy.engine.autoreload.files.update([
    join(ROOT, 'event.conf'),
    join(ROOT, 'production.conf'),
    join(ROOT, 'development.conf'),
    join(MODULE_ROOT, 'defaults.conf'),
    join(MODULE_ROOT, 'configspec.ini')
])
try:
    os.makedirs(conf['cherrypy']['tools.sessions.storage_path'])
except:
    pass

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

for _logger, _level in conf['loggers'].items():
    logging.getLogger(_logger).setLevel(getattr(logging, _level))

log = logging.getLogger()
_handler = logging.FileHandler('uber.log')
_handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
log.addHandler(_handler)

for _opt, _val in conf.items():
    if not isinstance(_val, dict):
        globals()[_opt.upper()] = _val

for _opt, _val in conf['dates'].items():
    if not _val:
        _dt = None
    elif ' ' in _val:
        _dt = datetime.strptime(_val, '%Y-%m-%d %H')
    else:
        _dt = datetime.strptime(_val + ' 23:59', '%Y-%m-%d %H:%M')
    globals()[_opt.upper()] = _dt

PRICE_BUMPS = {}
for _opt, _val in conf['badge_prices']['attendee'].items():
    PRICE_BUMPS[datetime.strptime(_opt, '%Y-%m-%d')] = _val

AT_OR_POST_CON = AT_THE_CON or POST_CON
PRE_CON = not AT_OR_POST_CON
