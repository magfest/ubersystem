from collections import OrderedDict
from os.path import abspath, dirname, join

from alembic import command
from alembic.config import Config as AlembicConfig

from sideboard.internal.imports import plugin_dirs


# Path to "alembic.ini", cached here for convenience
alembic_ini_path = abspath(join(dirname(__file__), '..', 'alembic.ini'))


# Version locations are usually hard-coded in "alembic.ini". Since uber ships
# with a variety of plugins, each with its own set of version scripts, we must
# dynamically create the set of version locations.
#
# `sep alembic` uses the following convention for each version location:
#     PLUGIN_DIR/alembic/versions
version_locations = OrderedDict()
for name, path in plugin_dirs.items():
    version_locations[name] = join(path, 'alembic', 'versions')


# Version locations in the format expected in "alembic.ini", cached here for
# convenience
version_locations_option = ','.join(version_locations.values())


def create_alembic_config(*args, **kwargs):
    """Returns an `alembic.config.Config` object configured for uber.
    """
    alembic_config = AlembicConfig(*args, **kwargs)
    # Override version_locations from "alembic.ini"
    alembic_config.set_main_option(
        'version_locations', version_locations_option)
    return alembic_config


def stamp(version):
    """Stamp the "version_table" in the database with the given version.

    This is typically used after the database is created by some process other
    than alembic, and you'd like to stamp the database as being up-to-date by
    calling::

        from uber import migration
        migration.stamp('head')

    """
    from uber.models import Session
    with Session.engine.begin() as connection:
        if version:
            alembic_config = create_alembic_config(alembic_ini_path)
            alembic_config.attributes['connection'] = connection
            command.stamp(alembic_config, version)
        else:
            connection.execute('drop table if exists alembic_version;')
