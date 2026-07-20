"""Self-contained pytest bootstrap for the hotel domain-layer suite.

This conftest is deliberately independent of tests/uber/conftest.py (which
is broken on main): running `pytest tests/hotel/` never imports it, because
pytest only collects conftests on the path from the rootdir down to this
directory, and neither /app nor /app/tests has one.

Run inside the `uber-python` container:

    docker exec -e DB_CONNECTION_STRING=postgresql://uber_db:uber_db@db:5432/uber_test_hotel \
        uber-python python -m pytest /app/tests/hotel/ -q

The DB_CONNECTION_STRING env var MUST point at the dedicated test database
before the process starts: uber.config reads it at import time and
uber.models binds its engine to it at import time, so it cannot be fixed
up after the fact. We fail fast with a clear message otherwise.
"""

import os

import pytest

TEST_DB_NAME = 'uber_test_hotel'
EXPECTED_DSN = f'postgresql://uber_db:uber_db@db:5432/{TEST_DB_NAME}'

_actual_dsn = os.environ.get('DB_CONNECTION_STRING', '')
if _actual_dsn != EXPECTED_DSN:
    raise pytest.UsageError(
        'tests/hotel must run against a dedicated scratch database.\n'
        f'Expected DB_CONNECTION_STRING={EXPECTED_DSN}\n'
        f'Got      DB_CONNECTION_STRING={_actual_dsn or "(unset)"}\n'
        'uber.config reads this env var at import time, so it must be set '
        'on the pytest process itself, e.g.:\n'
        f'  docker exec -e DB_CONNECTION_STRING={EXPECTED_DSN} '
        'uber-python python -m pytest /app/tests/hotel/ -q')


def _ensure_database_exists():
    """Create the dedicated test DB (via the maintenance `postgres` DB with
    autocommit) if it is missing. Never touches uber_db / scratch_lottery."""
    import sqlalchemy as sa

    admin_url = EXPECTED_DSN.rsplit('/', 1)[0] + '/postgres'
    admin_engine = sa.create_engine(admin_url, isolation_level='AUTOCOMMIT')
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                sa.text('SELECT 1 FROM pg_database WHERE datname = :name'),
                {'name': TEST_DB_NAME}).scalar()
            if not exists:
                conn.execute(sa.text(f'CREATE DATABASE {TEST_DB_NAME}'))
    finally:
        admin_engine.dispose()


@pytest.fixture(scope='session', autouse=True)
def database():
    """Create the test database if needed and bring its schema to the full
    alembic head chain. Idempotent: an already-migrated DB upgrades in
    milliseconds."""
    _ensure_database_exists()

    from alembic import command

    from uber.migration import create_alembic_config
    from uber.models import Session

    cfg = create_alembic_config()
    # env.py calls .connect() on whatever sits in attributes['connection'],
    # so hand it the ENGINE (already bound to DB_CONNECTION_STRING).
    cfg.attributes['connection'] = Session.engine
    command.upgrade(cfg, 'heads')
    yield


@pytest.fixture
def session(database):
    """A per-test UberSession that is rolled back (never committed) at
    teardown. Fixtures/tests flush freely - the model presave hooks run on
    flush, which is exactly what we want - and everything is undone by the
    rollback, so tests are isolated without truncating tables.

    Uses Session.session_factory() directly rather than Session() so we
    never take the cherrypy-request-bound code path.
    """
    from uber.models import Session

    s = Session.session_factory()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.fixture
def no_cherrypy_session(monkeypatch):
    """uber.hotel.perms resolves the acting admin via `cherrypy.session`,
    which raises AttributeError outside a web request. Give it a falsy
    dict stand-in so audit-writing code paths resolve to 'no admin'
    instead of crashing (a dict, not None, because other code paths call
    .get() on whatever `getattr(cherrypy, 'session', {})` returns)."""
    import cherrypy

    monkeypatch.setattr(cherrypy, 'session', {}, raising=False)
