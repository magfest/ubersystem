from uber.common import *

MODULE_ROOT = abspath(dirname(__file__))
ROOT = MODULE_ROOT[:MODULE_ROOT.rfind(os.path.sep)]

_roots = ['root = string(default="{}")\n'.format(ROOT), 'module_root = string(default="{}")\n'.format(MODULE_ROOT)]
with open(join(MODULE_ROOT, 'configspec.ini')) as _f:
    _spec = ConfigObj(_roots + _f.readlines(), list_values=False, interpolation=False, _inspec=True)

conf = ConfigObj(open('uber/defaults.conf').readlines(), configspec=_spec, interpolation='ConfigParser')

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
    if _val:
        _val = datetime.strptime(_val + ' 23:59', '%Y-%m-%d %H:%M')
    globals()[_opt.upper()] = _val or None
