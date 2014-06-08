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
