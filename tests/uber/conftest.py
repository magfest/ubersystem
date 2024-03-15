import os
import re
import shutil
from datetime import date, timedelta

import cherrypy
import pytest
from sideboard.lib import threadlocal
from sideboard.tests import patch_session

from uber.config import c
from uber.models import Attendee, Department, DeptMembership, DeptRole, Job, PromoCode, Session, WatchList, \
    initialize_db, register_session_listeners
from uber.utils import localized_now


try:
    TEST_DB_FILE = c.TEST_DB_FILE
except AttributeError:
    TEST_DB_FILE = '/tmp/uber.db'


deadline_not_reached = localized_now() + timedelta(days=1)
deadline_has_passed = localized_now() - timedelta(days=1)


def assert_unique(x):
    assert len(x) == len(set(x))


def monkeypatch_db_column(column, patched_config_value):
    column.property.columns[0].type.choices = dict(patched_config_value)


def extract_message_from_html(html):
    match = re.search(r"var message = '(.*)';", html)
    return match.group(1) if match else None


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
    with Session() as session:
        session.insert_test_admin_account()

    with Session() as session:
        attendee = session.query(Attendee).filter(
            Attendee.email == 'magfest@example.com').one()
        cherrypy.session['account_id'] = attendee.admin_account.id
        yield attendee
        cherrypy.session['account_id'] = None
        session.delete(attendee)


@pytest.fixture
def clear_price_bumps(request, monkeypatch):
    monkeypatch.setattr(c, 'PRICE_BUMPS', {})


@pytest.fixture(autouse=True)
def patch_send_email_delay(request, monkeypatch):
    from uber.tasks import email as email_tasks
    monkeypatch.setattr(email_tasks.send_email, 'delay', email_tasks.send_email)


@pytest.fixture(scope='session', autouse=True)
def init_db(request):
    if os.path.exists(TEST_DB_FILE):
        os.remove(TEST_DB_FILE)
    patch_session(Session, request)
    initialize_db(modify_tables=True)
    register_session_listeners()
    with Session() as session:
        session.add(Attendee(
            placeholder=True,
            first_name='Regular',
            last_name='Volunteer',
            ribbon=c.VOLUNTEER_RIBBON,
            staffing=True
        ))
        session.add(Attendee(
            placeholder=True,
            first_name='Regular',
            last_name='Attendee'
        ))

        d_arcade_trusted_dept_role = DeptRole(name='Trusted', description='Trusted in Arcade')
        d_arcade = Department(name='Arcade', description='Arcade', dept_roles=[d_arcade_trusted_dept_role])

        d_console_trusted_dept_role = DeptRole(name='Trusted', description='Trusted in Console')
        d_console = Department(name='Console', description='Console', dept_roles=[d_console_trusted_dept_role])
        session.add_all([d_arcade, d_arcade_trusted_dept_role, d_console, d_console_trusted_dept_role])

        assigned_depts = {
            'One': [d_arcade],
            'Two': [d_console],
            'Three': [d_arcade, d_console],
            'Four': [d_arcade, d_console],
            'Five': []
        }
        trusted_depts = {
            'One': [],
            'Two': [],
            'Three': [],
            'Four': [d_arcade, d_console],
            'Five': []
        }

        for name in ['One', 'Two', 'Three', 'Four', 'Five']:
            dept_memberships = []
            for dept in assigned_depts[name]:
                is_trusted = dept in trusted_depts[name]
                dept_memberships.append(DeptMembership(
                    department_id=dept.id,
                    dept_roles=(dept.dept_roles if is_trusted else [])
                ))
            session.add_all(dept_memberships)

            session.add(Attendee(
                placeholder=True,
                first_name=name,
                last_name=name,
                paid=c.NEED_NOT_PAY,
                badge_type=c.STAFF_BADGE,
                dept_memberships=dept_memberships
            ))

            session.add(Attendee(
                placeholder=True,
                first_name=name,
                last_name=name,
                paid=c.NEED_NOT_PAY,
                badge_type=c.CONTRACTOR_BADGE
            ))
            session.commit()

        session.add(WatchList(
            first_names='Banned, Alias, Nickname',
            last_name='Attendee',
            email='banned@mailinator.com',
            birthdate=date(1980, 7, 10),
            action='Action', reason='Reason'
        ))

        session.add(Job(
            name='Job One',
            start_time=c.EPOCH,
            slots=1,
            weight=1,
            duration=2,
            department=d_arcade,
            extra15=True
        ))
        session.add(Job(
            name='Job Two',
            start_time=c.EPOCH + timedelta(hours=1),
            slots=1,
            weight=1,
            duration=2,
            department=d_arcade
        ))
        session.add(Job(
            name='Job Three',
            start_time=c.EPOCH + timedelta(hours=2),
            slots=1,
            weight=1,
            duration=2,
            department=d_arcade
        ))
        session.add(Job(
            name='Job Four',
            start_time=c.EPOCH,
            slots=2,
            weight=1,
            duration=2,
            department=d_console,
            extra15=True
        ))
        session.add(Job(
            name='Job Five',
            start_time=c.EPOCH + timedelta(hours=2),
            slots=1,
            weight=1,
            duration=2,
            department=d_console
        ))
        session.add(Job(
            name='Job Six',
            start_time=c.EPOCH,
            slots=1,
            weight=1,
            duration=2,
            department=d_console,
            required_roles=[d_console_trusted_dept_role]
        ))

        session.add(PromoCode(code='ten percent off', discount=10,
                              discount_type=PromoCode._PERCENT_DISCOUNT))
        session.add(PromoCode(code='ten dollars off', discount=10,
                              discount_type=PromoCode._FIXED_DISCOUNT))
        session.add(PromoCode(code='ten dollar badge', discount=10,
                              discount_type=PromoCode._FIXED_PRICE))
        session.add(PromoCode(code='free badge', discount=0, uses_allowed=100))

        session.commit()


@pytest.fixture(autouse=True)
def db(request, init_db):
    shutil.copy(TEST_DB_FILE, TEST_DB_FILE + '.backup')
    request.addfinalizer(lambda: shutil.move(TEST_DB_FILE + '.backup', TEST_DB_FILE))


@pytest.fixture(autouse=True)
def cp_session():
    cherrypy.session = {}


@pytest.fixture(autouse=True)
def reset_threadlocal_cache():
    threadlocal.clear()


@pytest.fixture
def at_con(monkeypatch): monkeypatch.setattr(c, 'AT_THE_CON', True)


@pytest.fixture
def shifts_created(monkeypatch): monkeypatch.setattr(c, 'SHIFTS_CREATED', localized_now())


@pytest.fixture
def shifts_not_created(monkeypatch): monkeypatch.setattr(c, 'SHIFTS_CREATED', '')


@pytest.fixture
def before_printed_badge_deadline(monkeypatch): monkeypatch.setattr(c, 'PRINTED_BADGE_DEADLINE', deadline_not_reached)


@pytest.fixture
def after_printed_badge_deadline(monkeypatch): monkeypatch.setattr(c, 'PRINTED_BADGE_DEADLINE', deadline_has_passed)


@pytest.fixture
def custom_badges_ordered(monkeypatch): monkeypatch.setattr(c, 'SHIFT_CUSTOM_BADGES', False)
