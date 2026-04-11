import os
import re
import warnings
from datetime import timedelta

# Suppress SyntaxWarning from rpctools before the import chain loads it.
warnings.filterwarnings('ignore', message=r'invalid escape sequence', category=SyntaxWarning)

import cherrypy
import pytest
import sqlalchemy
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from uber.config import c
from uber.models import Session
from uber.utils import localized_now


deadline_not_reached = localized_now() + timedelta(days=1)
deadline_has_passed = localized_now() - timedelta(days=1)


def assert_unique(x):
    assert len(x) == len(set(x))


def monkeypatch_db_column(column, patched_config_value):
    column.property.columns[0].type.choices = dict(patched_config_value)


def extract_message_from_html(html):
    match = re.search(r"var message = '(.*)';", html)
    return match.group(1) if match else None


# ---------------------------------------------------------------------------
# Testcontainer fixtures (session-scoped — started once, shared across tests)
# ---------------------------------------------------------------------------

@pytest.fixture(scope='session')
def postgres_container():
    """
    Starts a testcontainers Postgres instance, or yields None when
    DATABASE_URL is already set in the environment (e.g. GitHub Actions
    services).  Nothing in this fixture is started when DATABASE_URL is set.
    """
    if os.environ.get('DATABASE_URL'):
        yield None
        return

    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine",
                           username="test_uber",
                           password="test_uber",
                           dbname="test_uber") as pg:
        yield pg


@pytest.fixture(scope='session')
def redis_container():
    from testcontainers.redis import RedisContainer

    with RedisContainer("redis:7-alpine") as redis:
        yield redis


# ---------------------------------------------------------------------------
# Database engine + schema (session-scoped)
# ---------------------------------------------------------------------------

@pytest.fixture(scope='session')
def db_engine(postgres_container):
    """
    Create a SQLAlchemy engine pointing at the testcontainer Postgres (or a
    pre-existing Postgres when DATABASE_URL is set), patch the uber Session
    infrastructure to use it, create all tables, and register session
    listeners.
    """
    import uber.models as models
    from sqlmodel import SQLModel

    url = os.environ.get('DATABASE_URL') or postgres_container.get_connection_url()
    # NullPool: each connect() opens a real connection and close() truly closes
    # it, preventing stale sessions from previous tests from interfering.
    test_engine = sqlalchemy.create_engine(url, poolclass=NullPool)

    # --- Patch the module-level engine and session factory -----------------
    orig_engine = models.engine
    orig_factory = models.SessionFactory
    orig_scoped_engine = models._ScopedSession.engine
    orig_scoped_factory = models._ScopedSession.session_factory

    models.engine = test_engine

    models.SessionFactory = sessionmaker(
        bind=test_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        class_=models.UberSession,
        query_cls=models.UberSession.QuerySubclass,
    )

    # Update the scoped session registry so Session.query() etc. work
    models._ScopedSession.session_factory.configure(bind=test_engine)
    models._ScopedSession.engine = test_engine
    models._ScopedSession.session_factory = models.SessionFactory

    # --- Create all tables -------------------------------------------------
    SQLModel.metadata.create_all(test_engine)

    # --- Register model getters on SessionMixin ----------------------------
    models.initialize_db()

    # --- Register presave / tracking listeners -----------------------------
    models.register_session_listeners()

    yield test_engine

    # --- Teardown: restore originals ---------------------------------------
    SQLModel.metadata.drop_all(test_engine)
    test_engine.dispose()

    models.engine = orig_engine
    models.SessionFactory = orig_factory
    models._ScopedSession.engine = orig_scoped_engine
    models._ScopedSession.session_factory = orig_scoped_factory


# ---------------------------------------------------------------------------
# Per-test database isolation via transaction rollback
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def db(db_engine):
    """
    Wrap every test in a transaction that is rolled back after the test.

    Uses the SQLAlchemy 2.0 "join session into external transaction" pattern.
    The key is ``join_transaction_mode="create_savepoint"`` which makes
    session.commit() commit a SAVEPOINT instead of the real transaction.

    See: https://docs.sqlalchemy.org/en/20/orm/session_transaction.html
         #joining-a-session-into-an-external-transaction-such-as-for-test-suites
    """
    import uber.models as models

    connection = db_engine.connect()
    transaction = connection.begin()

    # Patch SessionFactory to bind to our transactional connection.
    # join_transaction_mode="create_savepoint" ensures that when test code
    # calls session.commit(), it only commits a savepoint, not the real txn.
    test_session_factory = sessionmaker(
        bind=connection,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        class_=models.UberSession,
        query_cls=models.UberSession.QuerySubclass,
        join_transaction_mode="create_savepoint",
    )

    orig_factory = models.SessionFactory
    models.SessionFactory = test_session_factory
    models._ScopedSession.session_factory = test_session_factory

    # HybridSessionProxy.__call__ (used by Session()) checks cherrypy.request.db_connection.
    # Outside a real CherryPy request the attribute persists across tests on the thread-local.
    # Pre-set it to the test connection so that Session() calls use the test transaction
    # instead of opening a new real connection that bypasses rollback isolation.
    had_db_connection = hasattr(cherrypy.request, 'db_connection')
    old_db_connection = getattr(cherrypy.request, 'db_connection', None)
    cherrypy.request.db_connection = connection

    yield connection

    # Rollback the outer transaction — all test changes are discarded
    transaction.rollback()
    connection.close()

    # Clear the request-level cache (threadlocal) so properties like BADGES_SOLD
    # don't bleed cached values from one test into the next.
    from uber.utils import request_cached_context
    request_cached_context._clear_cache()

    # Restore original factory
    models.SessionFactory = orig_factory
    models._ScopedSession.session_factory = orig_factory

    # Restore CherryPy request db_connection
    if not had_db_connection:
        try:
            del cherrypy.request.db_connection
        except AttributeError:
            pass
    else:
        cherrypy.request.db_connection = old_db_connection


# ---------------------------------------------------------------------------
# CherryPy / HTTP fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def cp_session():
    cherrypy.session = {}


@pytest.fixture()
def GET(monkeypatch):
    monkeypatch.setattr(cherrypy.request, 'method', 'GET')


@pytest.fixture()
def POST(monkeypatch):
    monkeypatch.setattr(cherrypy.request, 'method', 'POST')


@pytest.fixture()
def csrf_token(monkeypatch):
    token = '4a2cc6f4-bf9f-49d2-a925-00ff4e22ae4a'
    monkeypatch.setitem(cherrypy.session, 'csrf_token', token)
    monkeypatch.setitem(cherrypy.request.headers, 'CSRF-Token', token)
    yield token


@pytest.fixture()
def admin_attendee():
    from uber.models import Attendee

    with Session() as session:
        session.insert_test_admin_account()

    with Session() as session:
        attendee = session.query(Attendee).filter(
            Attendee.email == c.TEST_ADMIN_EMAIL).one()
        cherrypy.session['account_id'] = attendee.admin_account.id
        yield attendee
        cherrypy.session['account_id'] = None


# ---------------------------------------------------------------------------
# Config / mode fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def clear_price_bumps(monkeypatch):
    monkeypatch.setattr(c, 'PRICE_BUMPS', {})


@pytest.fixture(autouse=True)
def patch_send_email_delay(monkeypatch):
    from uber.tasks import email as email_tasks
    monkeypatch.setattr(email_tasks.send_email, 'delay', email_tasks.send_email)


@pytest.fixture
def at_con(monkeypatch):
    monkeypatch.setattr(c, 'AT_THE_CON', True)


@pytest.fixture
def post_con(monkeypatch):
    monkeypatch.setattr(c, 'POST_CON', True)


@pytest.fixture
def shifts_created(monkeypatch):
    monkeypatch.setattr(c, 'SHIFTS_CREATED', localized_now())


@pytest.fixture
def shifts_not_created(monkeypatch):
    monkeypatch.setattr(c, 'SHIFTS_CREATED', '')


@pytest.fixture
def before_printed_badge_deadline(monkeypatch):
    monkeypatch.setattr(c, 'PRINTED_BADGE_DEADLINE', deadline_not_reached)


@pytest.fixture
def after_printed_badge_deadline(monkeypatch):
    monkeypatch.setattr(c, 'PRINTED_BADGE_DEADLINE', deadline_has_passed)
