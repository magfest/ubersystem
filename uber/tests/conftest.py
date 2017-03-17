from uber.common import *
import shutil
import pytest
from sideboard.tests import patch_session


try:
    TEST_DB_FILE = c.TEST_DB_FILE
except AttributeError:
    TEST_DB_FILE = '/tmp/uber.db'


deadline_not_reached = localized_now() + timedelta(days=1)
deadline_has_passed  = localized_now() - timedelta(days=1)


def monkeypatch_db_column(column, patched_config_value):
    column.property.columns[0].type.choices = dict(patched_config_value)


@pytest.fixture(scope='session')
def sensible_defaults():
    """
    Our unit tests parse our config files, so we want to define
    the default settings which can be overridden in fixtures.
    """
    c.POST_CON = False
    c.AT_THE_CON = False
    c.SHIFT_CUSTOM_BADGES = True
    c.PRINTED_BADGE_DEADLINE = deadline_not_reached
    c.DEV_BOX = False
    c.SEND_EMAILS = False
    c.EVENT_NAME = 'CoolCon9000'
    c.HARDCORE_OPTIMIZATIONS_ENABLED = False
    c.NUMBERED_BADGES = True

    # our tests should work no matter what departments exist, so we'll add these departments to use in our tests
    patched_depts = {'console': 'Console', 'arcade': 'Arcade', 'con_ops': 'Fest Ops'}

    c.make_enum('test_departments', patched_depts)
    c.SHIFTLESS_DEPTS = [c.CON_OPS]

    # we want 2 preassigned types to test some of our logic, so we've
    # set these even though Supporter isn't really a badge type anymore
    c.PREASSIGNED_BADGE_TYPES = [c.STAFF_BADGE, c.SUPPORTER_BADGE]
    c.BADGE_RANGES[c.STAFF_BADGE] = [1, 399]
    c.BADGE_RANGES[c.SUPPORTER_BADGE] = [500, 999]
    c.BADGE_RANGES[c.ATTENDEE_BADGE] = [3000, 5999]

    # we need to set some default table prices so we can write tests against them without worrying about what's been configured
    c.TABLE_PRICES = defaultdict(lambda: 400, {1: 100, 2: 200, 3: 300})

    # override whatever is in c.JOB_LOCATION with our own test data
    # ensure that c.ARCADE and c.CONSOLES exist in any model columns using c.JOB_LOCATION
    c.make_enum('job_location', patched_depts)
    monkeypatch_db_column(Job.location, c.JOB_LOCATION_OPTS)
    monkeypatch_db_column(Attendee.assigned_depts, c.JOB_LOCATION_OPTS)
    monkeypatch_db_column(Attendee.trusted_depts, c.JOB_LOCATION_OPTS)

    # ensure that we have uniform c.INTERESTS despite whatever is in the INI
    c.make_enum('interest', {'console': 'Consoles', 'arcade': 'Arcade'})
    monkeypatch_db_column(Attendee.interests, c.INTEREST_OPTS)

    # default attendee prices
    c.INITIAL_ATTENDEE = 40
    c.GROUP_DISCOUNT = 10
    c.DEALER_BADGE_PRICE = 20
    c.PRICE_BUMPS = {}

    # tests should turn this on to test the effects
    c.HARDCORE_OPTIMIZATIONS_ENABLED = False

    # set some other config values off just to be safe
    c.AWS_ACCESS_KEY = ''
    c.AWS_SECRET_KEY = ''
    c.STRIPE_PUBLIC_KEY = ''
    c.STRIPE_PRIVATE_KEY = ''


@pytest.fixture(scope='session', autouse=True)
def init_db(request, sensible_defaults):
    if os.path.exists(TEST_DB_FILE):
        os.remove(TEST_DB_FILE)
    patch_session(Session, request)
    initialize_db()
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

        d_arcade = str(c.ARCADE)
        d_console = str(c.CONSOLE)
        d_arcade_and_console = '{},{}'.format(c.ARCADE, c.CONSOLE)
        assigned_depts = {
            'One': d_arcade,
            'Two': d_console,
            'Three': d_arcade_and_console,
            'Four': d_arcade_and_console,
            'Five': ''
        }
        trusted_depts = {
            'One': '',
            'Two': '',
            'Three': '',
            'Four': d_arcade_and_console,
            'Five': ''
        }

        for name in ['One', 'Two', 'Three', 'Four', 'Five']:
            session.add(Attendee(
                placeholder=True,
                first_name=name,
                last_name=name,
                paid=c.NEED_NOT_PAY,
                badge_type=c.STAFF_BADGE,
                assigned_depts=assigned_depts[name],
                trusted_depts=trusted_depts[name]
            ))
            session.add(Attendee(
                placeholder=True,
                first_name=name,
                last_name=name,
                paid=c.NEED_NOT_PAY,
                badge_type=c.SUPPORTER_BADGE
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
            location=c.ARCADE,
            extra15=True
        ))
        session.add(Job(
            name='Job Two',
            start_time=c.EPOCH + timedelta(hours=1),
            slots=1,
            weight=1,
            duration=2,
            location=c.ARCADE
        ))
        session.add(Job(
            name='Job Three',
            start_time=c.EPOCH + timedelta(hours=2),
            slots=1,
            weight=1,
            duration=2,
            location=c.ARCADE
        ))
        session.add(Job(
            name='Job Four',
            start_time=c.EPOCH,
            slots=2,
            weight=1,
            duration=2,
            location=c.CONSOLE,
            extra15=True
        ))
        session.add(Job(
            name='Job Five',
            start_time=c.EPOCH + timedelta(hours=2),
            slots=1,
            weight=1,
            duration=2,
            location=c.CONSOLE
        ))
        session.add(Job(
            name='Job Six',
            start_time=c.EPOCH,
            slots=1,
            weight=1,
            duration=2,
            location=c.CONSOLE,
            restricted=True
        ))
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
