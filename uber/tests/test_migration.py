import pytest
import sqlite3
from uber.models import Session
from uber.tests import dump_alembic_schema, dump_reset_uber_db_schema


def test_alembic_migrations():
    if Session.engine.dialect.name == 'sqlite' and \
            sqlite3.sqlite_version_info < (3, 8):
        pytest.skip('requires recent version of sqlite')
    assert dump_alembic_schema() == dump_reset_uber_db_schema(), (
        'Missing or invalid migrations, see alembic/README.md')
