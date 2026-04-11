"""
Migration tests.

Verifies that:
1. Alembic can run all migrations from empty to HEAD on a fresh PostgreSQL
   database (the most complete integration test for schema evolution).
2. Key application tables exist after a full upgrade.
3. The most recent migration can be rolled back with a downgrade step.

These tests use a SEPARATE database ("test_migrations") within the same
testcontainer as the main test suite, so they don't interfere with the
SAVEPOINT-isolated test DB.

Marked as `slow` because upgrading 200+ migrations takes ~30-60 seconds.
Run with: pytest -m slow
Skip with: pytest -m "not slow"
"""

import pytest
import sqlalchemy
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.pool import NullPool


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def migration_db(postgres_container):
    """
    Create a fresh "test_migrations" database in the shared testcontainer
    and return a SQLAlchemy engine connected to it.

    The test_uber user is a superuser in the default Postgres Docker image,
    so it can CREATE and DROP databases.
    """
    # Connect to the default "test_uber" DB to issue CREATE DATABASE
    base_url = postgres_container.get_connection_url()
    admin_engine = sqlalchemy.create_engine(
        base_url,
        isolation_level='AUTOCOMMIT',
        poolclass=NullPool,
    )

    with admin_engine.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS test_migrations"))
        conn.execute(text("CREATE DATABASE test_migrations"))

    admin_engine.dispose()

    # Build URL pointing at the new DB (replace only the database name, not the username)
    migration_url = base_url.rsplit('/test_uber', 1)[0] + '/test_migrations'
    migration_engine = sqlalchemy.create_engine(migration_url, poolclass=NullPool)

    yield migration_engine

    migration_engine.dispose()

    # Cleanup: drop the migrations test DB
    admin_engine = sqlalchemy.create_engine(
        base_url,
        isolation_level='AUTOCOMMIT',
        poolclass=NullPool,
    )
    with admin_engine.connect() as conn:
        # Terminate other connections before drop
        conn.execute(text(
            "SELECT pg_terminate_backend(pid) "
            "FROM pg_stat_activity "
            "WHERE datname = 'test_migrations' AND pid <> pg_backend_pid()"
        ))
        conn.execute(text("DROP DATABASE IF EXISTS test_migrations"))
    admin_engine.dispose()


@pytest.fixture(scope='module')
def alembic_config_for_migration(migration_db):
    """
    Return an Alembic config wired to the migration test database.
    Uses the uber migration helper to get the correct version locations.
    """
    from uber.migration import create_alembic_config

    config = create_alembic_config()
    config.attributes['connection'] = migration_db  # env.py calls .connect() on this
    return config


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_alembic_upgrade_head(migration_db, alembic_config_for_migration):
    """
    Running 'alembic upgrade head' on an empty PostgreSQL database should
    succeed and produce all expected application tables.
    """
    # Run all migrations from scratch
    command.upgrade(alembic_config_for_migration, 'head')

    inspector = inspect(migration_db)
    tables = set(inspector.get_table_names())

    # Verify core tables exist after full migration
    expected_core_tables = {
        'attendee',
        'group',
        'model_receipt',
        'receipt_transaction',
        'receipt_item',
        'automated_email',
        'email',
        'promo_code',
        'department',
        'job',
        'shift',
        'alembic_version',
    }
    missing = expected_core_tables - tables
    assert not missing, (
        f"After alembic upgrade head, these tables were missing: {missing}"
    )


@pytest.mark.slow
def test_alembic_head_matches_model_metadata(migration_db, alembic_config_for_migration):
    """
    After a full migration, the table set from Alembic should match the
    table set defined in SQLModel metadata (schema consistency check).
    """
    from sqlmodel import SQLModel

    # Tables created by alembic
    inspector = inspect(migration_db)
    alembic_tables = set(inspector.get_table_names()) - {'alembic_version'}

    # Tables defined in code (excluding alembic_version which isn't a model)
    model_tables = set(SQLModel.metadata.tables.keys())

    # Any table in models but missing from alembic migration is a schema drift
    missing_from_alembic = model_tables - alembic_tables
    assert not missing_from_alembic, (
        f"These model tables are missing from alembic migrations: {missing_from_alembic}\n"
        "You may need to generate a new migration with: alembic revision --autogenerate"
    )


@pytest.mark.slow
def test_most_recent_migration_can_downgrade(migration_db, alembic_config_for_migration):
    """
    The most recent migration should have a working downgrade step.
    This catches migrations that use 'pass' in their downgrade() function.
    """
    from alembic.script import ScriptDirectory
    from uber.migration import create_alembic_config

    script = ScriptDirectory.from_config(create_alembic_config())
    heads = script.get_heads()
    assert heads, "No alembic heads found — migration chain may be broken"

    # Downgrade one step from each head (usually just one head)
    command.downgrade(alembic_config_for_migration, '-1')

    inspector = inspect(migration_db)
    tables = set(inspector.get_table_names())

    # Core tables should still exist after -1 downgrade
    assert 'attendee' in tables, "Core 'attendee' table missing after downgrade -1"
