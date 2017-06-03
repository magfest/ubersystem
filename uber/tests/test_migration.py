from uber.tests import dump_alembic_schema, dump_reset_uber_db_schema


def test_alembic_migrations():
    assert dump_alembic_schema() == dump_reset_uber_db_schema(), (
        'Missing or invalid migrations, see alembic/README.md')
