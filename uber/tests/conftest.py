from uber.common import *

import shutil

import pytest

from sideboard.tests import patch_session


@pytest.fixture(scope='session', autouse=True)
def init_db(request):
    patch_session(Session, request)
    register_session_listeners()
    with Session() as session:
        session.add(Attendee(
            placeholder=True,
            first_name='Regular',
            last_name='Volunteer',
            ribbon=VOLUNTEER_RIBBON,
            staffing=True
        ))
        session.add(Attendee(
            placeholder=True,
            first_name='Regular',
            last_name='Attendee'
        ))
        for name in ['One', 'Two', 'Three', 'Four', 'Five']:
            session.add(Attendee(
                placeholder=True,
                first_name=name,
                last_name=name,
                paid=NEED_NOT_PAY,
                badge_type=STAFF_BADGE
            ))
            session.add(Attendee(
                placeholder=True,
                first_name=name,
                last_name=name,
                paid=NEED_NOT_PAY,
                badge_type=SUPPORTER_BADGE
            ))
            session.commit()

@pytest.fixture(autouse=True)
def db(request, init_db):
    shutil.copy('/tmp/test.db', '/tmp/test.db.backup')
    request.addfinalizer(lambda: shutil.copy('/tmp/test.db.backup', '/tmp/test.db'))


modules = [uber.common, uber.models, uber.badge_funcs, uber.utils, uber.model_checks, uber.server]
for modname in os.listdir(os.path.join(MODULE_ROOT, 'site_sections')):
    if modname.endswith('.py') and not modname.startswith('_'):
        modules.append(__import__('uber.site_sections.' + modname[:-3], fromlist='*'))

def _make_setting_fixture(name, setting, val):
    def func(monkeypatch):
        for module in modules:
            monkeypatch.setattr(module, setting, val)
    func.__name__ = name
    globals()[name] = pytest.fixture(func)

'''
_make_setting_fixture('custom_badges_ordered', 'CUSTOM_BADGES_REALLY_ORDERED', True)
_make_setting_fixture('custom_badges_not_ordered', 'CUSTOM_BADGES_REALLY_ORDERED', False)
'''

@pytest.fixture
def precon(monkeypatch):
    for module in modules:
        monkeypatch.setattr(module, 'PRE_CON', True)
        monkeypatch.setattr(module, 'AT_THE_CON', False)
        monkeypatch.setattr(module, 'AT_OR_POST_CON', False)

@pytest.fixture
def at_con(monkeypatch):
    for module in modules:
        monkeypatch.setattr(module, 'PRE_CON', False)
        monkeypatch.setattr(module, 'AT_THE_CON', True)
        monkeypatch.setattr(module, 'AT_OR_POST_CON', True)

@pytest.fixture
def custom_badges_ordered(monkeypatch):
    for module in modules:
        monkeypatch.setattr(module, 'CUSTOM_BADGES_REALLY_ORDERED', True)

@pytest.fixture
def custom_badges_not_ordered(monkeypatch):
    for module in modules:
        monkeypatch.setattr(module, 'CUSTOM_BADGES_REALLY_ORDERED', False)
