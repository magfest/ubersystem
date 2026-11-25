"""Pytest bootstrap for the panels admin pages.

Mirrors tests/shifts/conftest.py and avoids tests/uber/conftest.py, which fails
at collection on main as of November 2026. Run inside the dev Python container:

    docker exec -e DB_CONNECTION_STRING=postgresql://uber_db:uber_db@db:5432/uber_test_panels \
        magprime-python python -m pytest /app/tests/panels/ -q
"""

import logging
import os

import pytest

TEST_DB_NAME = 'uber_test_panels'
EXPECTED_DSN = f'postgresql://uber_db:uber_db@db:5432/{TEST_DB_NAME}'

# uber.models binds its engine to this variable at import time, so it cannot be
# corrected once pytest has started.
if os.environ.get('DB_CONNECTION_STRING', '') != EXPECTED_DSN:
    raise pytest.UsageError(f'tests/panels must run with DB_CONNECTION_STRING={EXPECTED_DSN}')


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

    # The cherrypy 'start' hook normally binds model getters such as session.panel_applicant.
    initialize_db()

    cfg = create_alembic_config()
    cfg.attributes['connection'] = Session.engine
    command.upgrade(cfg, 'heads')
    # alembic/env.py calls fileConfig(), which disables every logger that already
    # exists. Re-enable ours so caplog can see handler errors.
    for name, logger in logging.root.manager.loggerDict.items():
        if name.startswith('uber') and isinstance(logger, logging.Logger):
            logger.disabled = False
    yield


class Family:
    """Two accepted panels and four badges whose owners registered under one shared email."""

    def __init__(self, tag):
        self.tag = tag
        self.last = f'Okafor{tag}'
        self.email = f'family-{tag}@mailinator.com'
        self.work_email = f'work-{tag}@mailinator.com'
        self.ids = {}

    def add_row(self, first_name, app_key, badge_key=None):
        """Commit an applicant row on one panel, linked to one of the family's badges, and return its id."""
        from uber.models import PanelApplicant, PanelApplication, Session

        with Session() as session:
            row = PanelApplicant(first_name=first_name, last_name=self.last, email=self.email,
                                 attendee_id=self.ids[badge_key] if badge_key else None,
                                 applications=[session.get(PanelApplication, self.ids[app_key])])
            session.add(row)
            session.commit()
            return row.id


@pytest.fixture
def family():
    import uuid

    from sqlalchemy import func

    from uber.config import c
    from uber.models import Attendee, AttendeeAccount, PanelApplicant, PanelApplication, PasswordReset, Session

    fam = Family(uuid.uuid4().hex[:8])
    with Session() as session:
        for key in ['app', 'other_app']:
            app = PanelApplication(name=f'{key} {fam.tag}', status=c.ACCEPTED,
                                   presentation=c.PRESENTATION_OPTS[0][0], noise_level=c.NOISE_LEVEL_OPTS[0][0])
            session.add(app)
            session.flush()
            fam.ids[key] = app.id
        badges = {
            'jimmy': ('Jimmy', fam.email, c.NEW_STATUS),
            'sarah': ('Sarah', fam.email, c.NEW_STATUS),
            'jim_work': ('Jim', fam.work_email, c.NEW_STATUS),
            'invalid': ('Jim', fam.email, c.INVALID_STATUS),
        }
        for key, (first_name, email, status) in badges.items():
            badge = Attendee(first_name=first_name, last_name=fam.last, email=email, paid=c.NEED_NOT_PAY,
                             placeholder=True, badge_status=status)
            session.add(badge)
            session.flush()
            fam.ids[key] = badge.id
        session.commit()
    fam.ids['jim_row'] = fam.add_row('Jim', 'app')

    yield fam

    with Session() as session:
        for row in session.query(PanelApplicant).filter(PanelApplicant.last_name == fam.last):
            session.delete(row)
        for key in ['app', 'other_app']:
            session.delete(session.get(PanelApplication, fam.ids[key]))
        emails = [fam.email, fam.work_email]
        accounts = session.query(AttendeeAccount).filter(AttendeeAccount.email.in_(emails)).all()
        for account in accounts:
            session.query(PasswordReset).filter(PasswordReset.attendee_id == account.id).delete()
            account.attendees.clear()
            session.delete(account)
        for badge in session.query(Attendee).filter(func.lower(Attendee.last_name) == fam.last.lower()):
            session.delete(badge)
        session.commit()
