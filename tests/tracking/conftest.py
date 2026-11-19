"""Pytest bootstrap for the Tracking audit log.

Mirrors tests/shifts/conftest.py. Run inside the dev Python container:

    docker exec -e DB_CONNECTION_STRING=postgresql://uber_db:uber_db@db:5432/uber_test_tracking \
        magprime-python python -m pytest /app/tests/tracking/ -q -p no:cacheprovider
"""

import logging
import os
import uuid

import pytest

TEST_DB_NAME = 'uber_test_tracking'
EXPECTED_DSN = f'postgresql://uber_db:uber_db@db:5432/{TEST_DB_NAME}'

# uber.models binds its engine to this variable at import time, so it cannot be
# corrected once pytest has started.
if os.environ.get('DB_CONNECTION_STRING', '') != EXPECTED_DSN:
    raise pytest.UsageError(f'tests/tracking must run with DB_CONNECTION_STRING={EXPECTED_DSN}')


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
    """Create the test database if missing and migrate it to head."""
    _ensure_database_exists()

    from alembic import command

    from uber.migration import create_alembic_config
    from uber.models import Session, initialize_db

    initialize_db()

    cfg = create_alembic_config()
    cfg.attributes['connection'] = Session.engine
    command.upgrade(cfg, 'heads')
    # alembic/env.py calls fileConfig(), which disables every logger that already exists.
    for name, logger in logging.root.manager.loggerDict.items():
        if name.startswith('uber') and isinstance(logger, logging.Logger):
            logger.disabled = False
    yield


@pytest.fixture
def committed_move(database):
    """Commit a badge on one account and a second account to move it to.

    The target account has no password, so add_attendee_to_account treats it as
    claimed and removes the badge from its old account, as it does in production.
    """
    from uber.config import c
    from uber.models import Attendee, AttendeeAccount, Session

    with Session() as session:
        old = AttendeeAccount(email=f'{uuid.uuid4().hex}@example.com', hashed='x')
        new = AttendeeAccount(email=f'{uuid.uuid4().hex}@example.com', hashed='')
        attendee = Attendee(first_name='Moved', last_name='Badge', email=f'{uuid.uuid4().hex}@example.com',
                            badge_status=c.COMPLETED_STATUS, paid=c.NEED_NOT_PAY)
        session.add_all([old, new, attendee])
        old.attendees.append(attendee)
        session.commit()
        ids = {'attendee': attendee.id, 'old': old.id, 'new': new.id}

    yield ids

    _delete_with_tracking(ids, [(Attendee, 'attendee'), (AttendeeAccount, 'old'), (AttendeeAccount, 'new')])


@pytest.fixture
def committed_admin(database):
    """Commit an admin account and an access group it does not have yet."""
    from uber.config import c
    from uber.models import AccessGroup, AdminAccount, Attendee, Session

    with Session() as session:
        attendee = Attendee(first_name='Granted', last_name='Admin', email=f'{uuid.uuid4().hex}@example.com',
                            badge_status=c.COMPLETED_STATUS, paid=c.NEED_NOT_PAY)
        group = AccessGroup(name=f'Tracking test {uuid.uuid4().hex[:8]}')
        session.add_all([attendee, group])
        session.flush()
        admin = AdminAccount(attendee=attendee, hashed='')
        session.add(admin)
        session.commit()
        ids = {'admin': admin.id, 'group': group.id, 'attendee': attendee.id}

    yield ids

    _delete_with_tracking(ids, [(AdminAccount, 'admin'), (AccessGroup, 'group'), (Attendee, 'attendee')])


def _delete_with_tracking(ids, models_and_keys):
    from uber.models import Session, Tracking

    with Session() as session:
        for model, key in models_and_keys:
            instance = session.get(model, ids[key])
            if instance:
                session.delete(instance)
        session.commit()

    # The DELETED rows for the objects above are written during that commit, so they are removed afterward.
    with Session() as session:
        session.query(Tracking).filter(Tracking.fk_id.in_(list(ids.values()))).delete(synchronize_session=False)
        session.commit()
