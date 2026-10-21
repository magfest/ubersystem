"""Pytest bootstrap for volunteer department and shift tasks.

Mirrors tests/hotel/conftest.py and avoids tests/uber/conftest.py, which fails
at collection on main as of October 2026. Run inside the dev Python container:

    docker exec -e DB_CONNECTION_STRING=postgresql://uber_db:uber_db@db:5432/uber_test_shifts \
        magprime-python python -m pytest /app/tests/shifts/ -q
"""

import logging
import os

import pytest

TEST_DB_NAME = 'uber_test_shifts'
EXPECTED_DSN = f'postgresql://uber_db:uber_db@db:5432/{TEST_DB_NAME}'

# uber.models binds its engine to this variable at import time, so it cannot be
# corrected once pytest has started.
if os.environ.get('DB_CONNECTION_STRING', '') != EXPECTED_DSN:
    raise pytest.UsageError(f'tests/shifts must run with DB_CONNECTION_STRING={EXPECTED_DSN}')


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

    # The cherrypy 'start' hook normally binds model getters such as session.job.
    initialize_db()

    cfg = create_alembic_config()
    cfg.attributes['connection'] = Session.engine
    command.upgrade(cfg, 'heads')
    # alembic/env.py calls fileConfig(), which disables every logger that already
    # exists. Re-enable ours so caplog can see task warnings.
    for name, logger in logging.root.manager.loggerDict.items():
        if name.startswith('uber') and isinstance(logger, logging.Logger):
            logger.disabled = False
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


@pytest.fixture
def committed(request, database):
    """Commit a department, a job, and two staffers so separate connections can see them.

    Parametrize indirectly to set the job's slot count; the default is 1.
    """
    import uuid
    from datetime import timedelta

    from uber.config import c
    from uber.models import Attendee, Department, Job, Session, Shift, Tracking

    def staffer(session, first_name):
        attendee = Attendee(first_name=first_name, last_name='Assign', email=f'{uuid.uuid4().hex}@example.com',
                            badge_type=c.STAFF_BADGE, badge_status=c.COMPLETED_STATUS, paid=c.NEED_NOT_PAY,
                            staffing=True)
        session.add(attendee)
        return attendee

    slots = getattr(request, 'param', 1)
    with Session() as session:
        dept = Department(name=f'Assign {uuid.uuid4().hex[:8]}', description='Assign')
        session.add(dept)
        session.flush()
        job = Job(department_id=dept.id, name='Gate', start_time=c.EPOCH + timedelta(hours=2), duration=60, slots=slots)
        session.add(job)
        first, second = staffer(session, 'First'), staffer(session, 'Second')
        session.commit()
        ids = {'dept': dept.id, 'job': job.id, 'first': first.id, 'second': second.id}

    yield ids

    with Session() as session:
        session.query(Shift).filter(Shift.job_id == ids['job']).delete()
        session.query(Job).filter(Job.id == ids['job']).delete()
        session.query(Attendee).filter(Attendee.id.in_([ids['first'], ids['second']])).delete()
        session.query(Department).filter(Department.id == ids['dept']).delete()
        session.query(Tracking).filter(Tracking.fk_id.in_(list(ids.values()))).delete()
        # Shift rows are gone by now; their Tracking entries carry the job id in the repr.
        session.query(Tracking).filter(Tracking.model == 'Shift', Tracking.data.contains(ids['job'])).delete(
            synchronize_session=False)
        session.commit()


@pytest.fixture
def shift_count():
    """Return a function that counts committed shifts for a job."""
    from uber.models import Session, Shift

    def count(job_id):
        with Session() as session:
            return session.query(Shift).filter(Shift.job_id == job_id).count()
    return count
