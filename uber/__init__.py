import os
from decimal import Decimal
import cherrypy

from pockets.autolog import log

from uber._version import __version__  # noqa: F401

from uber import config  # noqa: F401
from uber import api  # noqa: F401
from uber import automated_emails  # noqa: F401
from uber import custom_tags  # noqa: F401
from uber import jinja  # noqa: F401
from uber import menu  # noqa: F401
from uber import models  # noqa: F401
from uber import model_checks  # noqa: F401
from uber import receipt_items  # noqa: F401
from uber import sep_commands  # noqa: F401
from uber import server  # noqa: F401
from uber import tasks  # noqa: F401
from uber.serializer import serializer # noqa: F401

# NOTE: this will decrease the precision of some serialized decimal.Decimals
serializer.register(Decimal, lambda n: float(n))


def create_data_dirs():
    from uber.config import c

    for directory in c.DATA_DIRS.values():
        if not os.path.exists(directory):
            log.info('Creating directory {}'.format(directory))
            os.makedirs(directory, mode=0o744)

cherrypy.engine.subscribe('start', create_data_dirs, priority=98)