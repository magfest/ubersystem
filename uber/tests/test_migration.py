import pytest
import sqlite3
from uber.tests import dump_alembic_schema, dump_reset_uber_db_schema


@pytest.mark.skipif(
    sqlite3.sqlite_version_info < (3, 8),
    reason='requires recent version of sqlite')
def test_alembic_migrations():
    assert dump_alembic_schema() == dump_reset_uber_db_schema(), (
        'Missing or invalid migrations, see alembic/README.md')
