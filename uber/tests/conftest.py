from uber.common import *

import shutil

import pytest

from sideboard.tests import patch_session


@pytest.fixture(scope='session', autouse=True)
def init_db(request):
    patch_session(Session, request)
    with Session() as session:
        session.add(Attendee(
            placeholder=True,
            first_name='Test',
            last_name='Test',
            paid=NEED_NOT_PAY
        ))

@pytest.fixture(autouse=True)
def db(request, init_db):
    shutil.copy('/tmp/test.db', '/tmp/test.db.backup')
    request.addfinalizer(lambda: shutil.copy('/tmp/test.db.backup', '/tmp/test.db'))


modules = [uber.common, uber.models, uber.badge_funcs, uber.utils, uber.model_checks, uber.server]
for modname in os.listdir(os.path.join(MODULE_ROOT, 'site_sections')):
    if modname.endswith('.py') and not modname.startswith('_'):
        modules.append(__import__('uber.site_sections.' + modname[:-3], fromlist='*'))

@pytest.fixture
def precon(monkeypatch):
    for module in modules:
        monkeypatch.setattr(module, 'AT_THE_CON', False)

@pytest.fixture
def at_the_con(monkeypatch):
    for module in modules:
        monkeypatch.setattr(module, 'AT_THE_CON', True)
