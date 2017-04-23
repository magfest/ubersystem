from collections import OrderedDict
from os.path import abspath, dirname, join

from alembic import command
from alembic.config import Config as AlembicConfig

from sideboard.internal.imports import plugin_dirs
from uber.models import Session


alembic_ini_path = abspath(join(dirname(__file__), '..', 'alembic.ini'))

version_locations = OrderedDict()
for name, path in plugin_dirs.items():
    version_locations[name] = join(path, 'alembic', 'versions')
version_locations_option = ','.join(version_locations.values())


def stamp(version):
    with Session.engine.begin() as connection:
        alembic_config = AlembicConfig(alembic_ini_path)
        alembic_config.set_main_option('version_locations', version_locations_option)
        alembic_config.attributes['connection'] = connection
        command.stamp(alembic_config, 'head')
