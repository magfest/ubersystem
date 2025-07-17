import psutil
process = psutil.Process()
ram_usage = 0

def print_ram(arg):
    global ram_usage
    total = process.memory_info().rss
    diff = total - ram_usage
    ram_usage = total
    print(f"{arg}: Total {total / 1000000:0.1f}, Added {diff / 1000000:0.1f}")

print_ram("start __init__")
import os
print_ram("import os")
from decimal import Decimal
print_ram("import decimal")
import cherrypy
print_ram("import cherrypy")

from pockets.autolog import log
print_ram("import autolog")

from uber._version import __version__  # noqa: F401
print_ram("import version")

from uber import config  # noqa: F401
print_ram("import config")
from uber import api  # noqa: F401
print_ram("import api")
from uber import automated_emails  # noqa: F401
print_ram("import automated_emails")
from uber import custom_tags  # noqa: F401
from uber import forms  # noqa: F401
from uber import jinja  # noqa: F401
print_ram("import jinja")
from uber import menu  # noqa: F401
print_ram("import menu")
from uber import models  # noqa: F401
print_ram("import models")
from uber import model_checks  # noqa: F401
print_ram("import model_checks")
from uber import receipt_items  # noqa: F401
print_ram("import receipt_items")
from uber import sep_commands  # noqa: F401
print_ram("import sep_commands")
from uber import server  # noqa: F401
print_ram("import server")
from uber import tasks  # noqa: F401
from uber import validations  # noqa: F401
from uber.serializer import serializer # noqa: F401
print_ram("import serializer")

# NOTE: this will decrease the precision of some serialized decimal.Decimals
serializer.register(Decimal, lambda n: float(n))
print_ram("serializer register")

def create_data_dirs():
    from uber.config import c

    for directory in c.DATA_DIRS.values():
        if not os.path.exists(directory):
            log.info('Creating directory {}'.format(directory))
            os.makedirs(directory, mode=0o744)

print_ram("def func")
cherrypy.engine.subscribe('start', create_data_dirs, priority=98)
print_ram("engine sub")