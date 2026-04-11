"""
Fixtures for visual regression tests.

Lifecycle:
  1. postgres_container  (session)  - testcontainer Postgres
  2. visual_db_engine    (session)  - tables created, Session patched
  3. visual_admin_setup  (session)  - admin account committed to DB
  4. live_server         (session)  - CherryPy HTTP server started
  5. browser             (session)  - Playwright Chromium instance
  6. authed_context      (session)  - browser context with admin cookie
  7. page                (function) - fresh page per test

Visual tests use their own Postgres container (separate from the unit test
container) so they can commit data without interfering with SAVEPOINT isolation.
"""
# Suppress SyntaxWarning from rpctools (invalid regex escape in third-party code).
# Must be done before any import that transitively loads rpctools, because the
# warning fires at bytecode-compile time before pytest's ini filterwarnings apply.
import warnings
warnings.filterwarnings('ignore', message=r'invalid escape sequence', category=SyntaxWarning)

import socket
import threading
import time
from pathlib import Path

import cherrypy
import pytest
import sqlalchemy
from playwright.sync_api import sync_playwright
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from tests.visual.visual_config import VIEWPORT_WIDTH, VIEWPORT_HEIGHT, NETWORK_IDLE_TIMEOUT


# ---------------------------------------------------------------------------
# pytest CLI option
# ---------------------------------------------------------------------------

def pytest_addoption(parser):
    parser.addoption(
        '--update-baselines',
        action='store_true',
        default=False,
        help='Save current screenshots as new baselines instead of comparing.',
    )
    parser.addoption(
        '--visual-chunk',
        default=None,
        metavar='CHUNK',
        help='Run only the named route chunk (see route_manifest.ROUTE_CHUNKS).',
    )


@pytest.fixture(scope='session')
def update_baselines(request):
    return request.config.getoption('--update-baselines')


def pytest_collection_modifyitems(config, items):
    """Deselect tests that don't belong to the requested --visual-chunk."""
    chunk = config.getoption('--visual-chunk', default=None)
    if not chunk:
        return

    from tests.visual.route_manifest import ROUTE_CHUNKS
    if chunk not in ROUTE_CHUNKS:
        raise ValueError(
            f'Unknown --visual-chunk {chunk!r}. '
            f'Valid chunks: {sorted(ROUTE_CHUNKS)}'
        )

    sections = ROUTE_CHUNKS[chunk]
    selected, deselected = [], []
    for item in items:
        # Test node IDs look like:
        #   test_visual_routes.py::test_admin_route_visual[section__handler]
        if '[' in item.nodeid:
            label = item.nodeid.split('[', 1)[1].rstrip(']')
            section = label.split('__')[0]
            (selected if section in sections else deselected).append(item)
        else:
            selected.append(item)

    config.hook.pytest_deselected(items=deselected)
    items[:] = selected


# ---------------------------------------------------------------------------
# Database — own container (visual tests need committed data)
# ---------------------------------------------------------------------------

@pytest.fixture(scope='session')
def visual_postgres_container():
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer(
        'postgres:16-alpine',
        username='test_uber',
        password='test_uber',
        dbname='test_uber',
    ) as pg:
        yield pg


@pytest.fixture(scope='session')
def visual_db_engine(visual_postgres_container):
    """
    Create all tables in the visual-test Postgres container and patch the
    uber Session infrastructure to point at it.
    """
    import uber.models as models
    from sqlmodel import SQLModel

    url = visual_postgres_container.get_connection_url()
    engine = sqlalchemy.create_engine(url, poolclass=NullPool)

    orig_engine = models.engine
    orig_factory = models.SessionFactory
    orig_scoped_engine = models._ScopedSession.engine
    orig_scoped_factory = models._ScopedSession.session_factory

    models.engine = engine
    models.SessionFactory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        class_=models.UberSession,
        query_cls=models.UberSession.QuerySubclass,
    )
    models._ScopedSession.session_factory.configure(bind=engine)
    models._ScopedSession.engine = engine
    models._ScopedSession.session_factory = models.SessionFactory

    SQLModel.metadata.create_all(engine)
    models.initialize_db()
    models.register_session_listeners()

    yield engine

    SQLModel.metadata.drop_all(engine)
    engine.dispose()

    models.engine = orig_engine
    models.SessionFactory = orig_factory
    models._ScopedSession.engine = orig_scoped_engine
    models._ScopedSession.session_factory = orig_scoped_factory


# ---------------------------------------------------------------------------
# Admin account (committed — not in a rolled-back transaction)
# ---------------------------------------------------------------------------

@pytest.fixture(scope='session')
def visual_admin_setup(visual_db_engine):
    """Insert the test admin account into the visual-test database."""
    from uber.models import Session

    with Session() as session:
        session.insert_test_admin_account()

    yield


# ---------------------------------------------------------------------------
# Live CherryPy server
# ---------------------------------------------------------------------------

def _find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


@pytest.fixture(scope='session')
def live_server(visual_db_engine, visual_admin_setup):
    """
    Start a CherryPy HTTP server backed by the visual-test Postgres.

    Returns the base URL string, e.g. 'http://127.0.0.1:54321'.
    """
    # Import server.py so CherryPy's tree gets fully populated.
    # (mount_site_sections + cherrypy.tree.mount both happen at module level.)
    import uber.server  # noqa: F401 — side-effects are the point

    port = _find_free_port()

    # Override port and session storage (no Redis needed for visual tests)
    cherrypy.config.update({
        'server.socket_host': '127.0.0.1',
        'server.socket_port': port,
        'log.screen': False,
        'tools.sessions.storage_class': cherrypy.lib.sessions.RamSession,
    })

    cherrypy.engine.start()
    cherrypy.engine.wait(cherrypy.engine.states.STARTED)

    base_url = f'http://127.0.0.1:{port}'

    # Quick smoke-test: login page should respond
    _wait_for_server(base_url, timeout=15)

    yield base_url

    # exit() transitions to the EXIT state cleanly, preventing the
    # "Bus is in STOPPED state" RuntimeWarning on process exit.
    cherrypy.engine.exit()
    cherrypy.engine.wait(cherrypy.engine.states.EXITING)


def _wait_for_server(base_url: str, timeout: int = 15):
    """Poll until the server responds or timeout is reached."""
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f'{base_url}/accounts/login', timeout=2)
            return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError(f'CherryPy server at {base_url} did not start within {timeout}s')


# ---------------------------------------------------------------------------
# Playwright browser + authenticated context
# ---------------------------------------------------------------------------

@pytest.fixture(scope='session')
def playwright_instance():
    with sync_playwright() as pw:
        yield pw


@pytest.fixture(scope='session')
def browser(playwright_instance):
    b = playwright_instance.chromium.launch(headless=True)
    yield b
    b.close()


@pytest.fixture(scope='session')
def authed_context(browser, live_server):
    """
    A Playwright browser context pre-authenticated as the test admin.
    Shared across all visual tests in the session.
    """
    context = browser.new_context(
        viewport={'width': VIEWPORT_WIDTH, 'height': VIEWPORT_HEIGHT},
        ignore_https_errors=True,
    )
    page = context.new_page()

    # Log in as test admin
    page.goto(f'{live_server}/accounts/login', wait_until='networkidle',
              timeout=NETWORK_IDLE_TIMEOUT)
    page.fill('input[name="email"]', 'magfest@example.com')
    page.fill('input[name="password"]', 'magfest')
    page.click('input[type="submit"], button[type="submit"]')
    page.wait_for_load_state('networkidle', timeout=NETWORK_IDLE_TIMEOUT)

    page.close()
    yield context
    context.close()


@pytest.fixture(scope='session')
def public_context(browser, live_server):
    """An unauthenticated browser context for public-page screenshots."""
    context = browser.new_context(
        viewport={'width': VIEWPORT_WIDTH, 'height': VIEWPORT_HEIGHT},
        ignore_https_errors=True,
    )
    yield context
    context.close()


@pytest.fixture
def admin_page(authed_context):
    """Fresh Playwright page using the shared authenticated context."""
    page = authed_context.new_page()
    yield page
    page.close()


@pytest.fixture
def public_page(public_context):
    """Fresh Playwright page with no authentication."""
    page = public_context.new_page()
    yield page
    page.close()


# ---------------------------------------------------------------------------
# Test data — standard objects for routes that require an existing record
# ---------------------------------------------------------------------------

@pytest.fixture(scope='session')
def test_data(visual_db_engine):
    """
    Create one of each standard model so that 'requires id' routes can be
    tested.  Returns a dict of str UUIDs keyed by a logical name used in
    DATA_ROUTES query templates, e.g. ``'id={attendee_id}'``.
    """
    from uber.models import (
        Session, Attendee, Group, Department, DeptRole, WatchList,
        ArtShowApplication, MITSTeam,
    )
    from uber.config import c

    data = {}

    with Session() as session:
        # ---- Attendee ------------------------------------------------
        attendee = Attendee(
            first_name='Visual',
            last_name='Testuser',
            email='visual_testuser@example.com',
            badge_type=c.ATTENDEE_BADGE,
            paid=c.NOT_PAID,
            placeholder=False,
        )
        session.add(attendee)
        session.flush()
        data['attendee_id'] = str(attendee.id)

        # ---- Group ---------------------------------------------------
        group = Group(name='Visual Test Group')
        session.add(group)
        session.flush()
        data['group_id'] = str(group.id)

        # ---- Department + DeptRole -----------------------------------
        dept = Department(name='Visual Test Dept', description='Test dept')
        session.add(dept)
        session.flush()
        data['department_id'] = str(dept.id)

        role = DeptRole(name='Visual Test Role', department_id=dept.id)
        session.add(role)
        session.flush()
        data['dept_role_id'] = str(role.id)

        # ---- WatchList -----------------------------------------------
        watchlist = WatchList(
            first_names='Visual',
            last_name='Blocked',
            email='vblocked@example.com',
            reason='Visual test',
            action='Visual test action',
        )
        session.add(watchlist)
        session.flush()
        data['watchlist_id'] = str(watchlist.id)

        # ---- ArtShowApplication (linked to attendee) -----------------
        art_app = ArtShowApplication(
            attendee_id=attendee.id,
            artist_name='Visual Artist',
        )
        session.add(art_app)
        session.flush()
        data['art_show_app_id'] = str(art_app.id)

        # ---- MITSTeam ------------------------------------------------
        mits_team = MITSTeam(name='Visual Test MITS Team')
        session.add(mits_team)
        session.flush()
        data['mits_team_id'] = str(mits_team.id)

        session.commit()

    return data
