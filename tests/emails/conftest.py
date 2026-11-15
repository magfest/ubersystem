"""Pytest bootstrap for email queueing and the email admin pages.

Mirrors tests/shifts/conftest.py and avoids tests/uber/conftest.py, which fails
at collection on main as of November 2026. Run inside the dev web container:

    docker exec -e DB_CONNECTION_STRING=postgresql://uber_db:uber_db@db:5432/uber_test_emails \
        magprime-web-1 python -m pytest /app/tests/emails/ -q -p no:cacheprovider
"""

import logging
import os

import pytest

TEST_DB_NAME = 'uber_test_emails'
EXPECTED_DSN = f'postgresql://uber_db:uber_db@db:5432/{TEST_DB_NAME}'

# uber.models binds its engine to this variable at import time, so it cannot be
# corrected once pytest has started.
if os.environ.get('DB_CONNECTION_STRING', '') != EXPECTED_DSN:
    raise pytest.UsageError(f'tests/emails must run with DB_CONNECTION_STRING={EXPECTED_DSN}')


def _ensure_database_exists():
    import sqlalchemy as sa

    admin_engine = sa.create_engine(EXPECTED_DSN.rsplit('/', 1)[0] + '/postgres', isolation_level='AUTOCOMMIT')
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(sa.text('SELECT 1 FROM pg_database WHERE datname = :name'),
                                  {'name': TEST_DB_NAME}).scalar()
            if not exists:
                conn.execute(sa.text(f'CREATE DATABASE {TEST_DB_NAME}'))
    finally:
        admin_engine.dispose()


@pytest.fixture(scope='session', autouse=True)
def database():
    """Create the test database if missing, migrate it to head, and load email fixtures."""
    _ensure_database_exists()

    from alembic import command

    from uber.migration import create_alembic_config
    from uber.models import AutomatedEmail, Session, initialize_db

    initialize_db()

    cfg = create_alembic_config()
    cfg.attributes['connection'] = Session.engine
    command.upgrade(cfg, 'heads')
    # alembic/env.py calls fileConfig(), which disables every logger that already
    # exists. Re-enable ours so caplog can see email errors.
    for name, logger in logging.root.manager.loggerDict.items():
        if name.startswith('uber') and isinstance(logger, logging.Logger):
            logger.disabled = False

    # queue_email looks fixtures up by their AutomatedEmail row, not the registry.
    AutomatedEmail.reconcile_fixtures()
    AutomatedEmail.initialized = True
    yield


@pytest.fixture
def session(database):
    """Yield a session that is rolled back at teardown, so tests only flush."""
    from uber.models import Session

    s = Session.session_factory()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def unwrap(func):
    """Strip page decorators so a handler can be called with a plain session."""
    while hasattr(func, '__wrapped__'):
        func = func.__wrapped__
    return func
