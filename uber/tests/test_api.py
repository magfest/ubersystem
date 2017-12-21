import pytest

from uber.common import *
from uber.tests.conftest import csrf_token, cp_session
from uber.api import auth_by_token, auth_by_session, api_auth, all_api_auth


VALID_API_TOKEN = '39074db3-9295-447a-b831-8cbaa93a0522'


@pytest.fixture()
def session():
    with Session() as session:
        yield session


@pytest.fixture()
def admin_account(monkeypatch, session):
    admin_account = AdminAccount(attendee=Attendee())
    session.add(admin_account)
    session.commit()
    session.refresh(admin_account)
    monkeypatch.setitem(cherrypy.session, 'account_id', admin_account.id)
    yield admin_account
    cherrypy.session['account_id'] = None
    session.delete(admin_account)


@pytest.fixture()
def api_token(session, admin_account):
    api_token = ApiToken(
        admin_account=admin_account,
        token=VALID_API_TOKEN)
    session.add(api_token)
    session.commit()
    session.refresh(api_token)
    yield api_token
    session.delete(api_token)


class TestCheckAdminAccount(object):
    ACCESS_ERR = 'You do not have permission to change that access setting'

    TEST_ACCESS_CHANGES = [
        ([], [], None),
        ([], [c.ADMIN], ACCESS_ERR),
        ([], [c.ACCOUNTS], ACCESS_ERR),
        ([], [c.PEOPLE], ACCESS_ERR),
        ([], [c.ADMIN, c.PEOPLE], ACCESS_ERR),
        ([], [c.ADMIN, c.ACCOUNTS], ACCESS_ERR),
        ([], [c.ADMIN, c.ACCOUNTS, c.PEOPLE], ACCESS_ERR),
        ([], [c.ACCOUNTS, c.PEOPLE], ACCESS_ERR),

        ([c.ADMIN], [], None),
        ([c.ADMIN], [c.ADMIN], None),
        ([c.ADMIN], [c.ACCOUNTS], None),
        ([c.ADMIN], [c.PEOPLE], None),
        ([c.ADMIN], [c.ADMIN, c.PEOPLE], None),
        ([c.ADMIN], [c.ADMIN, c.ACCOUNTS], None),
        ([c.ADMIN], [c.ADMIN, c.ACCOUNTS, c.PEOPLE], None),
        ([c.ADMIN], [c.ACCOUNTS, c.PEOPLE], None),

        ([c.ACCOUNTS], [], None),
        ([c.ACCOUNTS], [c.ADMIN], ACCESS_ERR),
        ([c.ACCOUNTS], [c.ACCOUNTS], None),
        ([c.ACCOUNTS], [c.PEOPLE], None),
        ([c.ACCOUNTS], [c.ADMIN, c.PEOPLE], ACCESS_ERR),
        ([c.ACCOUNTS], [c.ADMIN, c.ACCOUNTS], ACCESS_ERR),
        ([c.ACCOUNTS], [c.ADMIN, c.ACCOUNTS, c.PEOPLE], ACCESS_ERR),
        ([c.ACCOUNTS], [c.ACCOUNTS, c.PEOPLE], None),

        ([c.PEOPLE], [], None),
        ([c.PEOPLE], [c.ADMIN], ACCESS_ERR),
        ([c.PEOPLE], [c.ACCOUNTS], ACCESS_ERR),
        ([c.PEOPLE], [c.PEOPLE], None),
        ([c.PEOPLE], [c.ADMIN, c.PEOPLE], ACCESS_ERR),
        ([c.PEOPLE], [c.ADMIN, c.ACCOUNTS], ACCESS_ERR),
        ([c.PEOPLE], [c.ADMIN, c.ACCOUNTS, c.PEOPLE], ACCESS_ERR),
        ([c.PEOPLE], [c.ACCOUNTS, c.PEOPLE], ACCESS_ERR),

        ([c.ADMIN, c.PEOPLE], [], None),
        ([c.ADMIN, c.PEOPLE], [c.ADMIN], None),
        ([c.ADMIN, c.PEOPLE], [c.ACCOUNTS], None),
        ([c.ADMIN, c.PEOPLE], [c.PEOPLE], None),
        ([c.ADMIN, c.PEOPLE], [c.ADMIN, c.PEOPLE], None),
        ([c.ADMIN, c.PEOPLE], [c.ADMIN, c.ACCOUNTS], None),
        ([c.ADMIN, c.PEOPLE], [c.ADMIN, c.ACCOUNTS, c.PEOPLE], None),
        ([c.ADMIN, c.PEOPLE], [c.ACCOUNTS, c.PEOPLE], None),

        ([c.ACCOUNTS, c.PEOPLE], [], None),
        ([c.ACCOUNTS, c.PEOPLE], [c.ADMIN], ACCESS_ERR),
        ([c.ACCOUNTS, c.PEOPLE], [c.ACCOUNTS], None),
        ([c.ACCOUNTS, c.PEOPLE], [c.PEOPLE], None),
        ([c.ACCOUNTS, c.PEOPLE], [c.ADMIN, c.PEOPLE], ACCESS_ERR),
        ([c.ACCOUNTS, c.PEOPLE], [c.ADMIN, c.ACCOUNTS], ACCESS_ERR),
        ([c.ACCOUNTS, c.PEOPLE], [c.ADMIN, c.ACCOUNTS, c.PEOPLE], ACCESS_ERR),
        ([c.ACCOUNTS, c.PEOPLE], [c.ACCOUNTS, c.PEOPLE], None),
    ]

    @pytest.mark.parametrize('admin_access,access_changes,expected', TEST_ACCESS_CHANGES)
    def test_check_admin_account_access_new(self, session, admin_account, admin_access, access_changes, expected):
        admin_access = ','.join(map(str, admin_access))
        access_changes = ','.join(map(str, access_changes))

        admin_account.access = admin_access
        session.commit()
        session.refresh(admin_account)

        test_attendee = Attendee(email='test@example.com')
        session.add(test_attendee)
        session.commit()
        test_admin_account = AdminAccount(
            access=access_changes,
            attendee_id=test_attendee.id,
            hashed='<bcrypted>')
        message = check(test_admin_account)
        assert message == expected

    @pytest.mark.parametrize('admin_access,access_changes,expected', TEST_ACCESS_CHANGES)
    def test_check_admin_account_access_remove(self, session, admin_account, admin_access, access_changes, expected):
        admin_access = ','.join(map(str, admin_access))
        access_changes = ','.join(map(str, access_changes))

        admin_account.access = admin_access
        session.commit()
        session.refresh(admin_account)

        test_attendee = Attendee(email='test@example.com')
        session.add(test_attendee)

        test_admin_account = AdminAccount(
            access=access_changes,
            attendee_id=test_attendee.id,
            hashed='<bcrypted>')
        session.add(test_admin_account)
        session.commit()
        session.refresh(test_admin_account)

        test_admin_account.access = ''
        message = check(test_admin_account)
        assert message == expected

    @pytest.mark.parametrize('admin_access,access_changes,expected', TEST_ACCESS_CHANGES)
    def test_check_admin_account_access_add(self, session, admin_account, admin_access, access_changes, expected):
        admin_access = ','.join(map(str, admin_access))
        access_changes = ','.join(map(str, access_changes))

        admin_account.access = admin_access
        session.commit()
        session.refresh(admin_account)

        test_attendee = Attendee(email='test@example.com')
        session.add(test_attendee)

        test_admin_account = AdminAccount(
            access='',
            attendee_id=test_attendee.id,
            hashed='<bcrypted>')
        session.add(test_admin_account)
        session.commit()
        session.refresh(test_admin_account)

        test_admin_account.access = access_changes
        message = check(test_admin_account)
        assert expected == message


class TestAuthByToken(object):
    ACCESS_ERR = 'Insufficient access for auth token'

    def test_success(self, monkeypatch, api_token):
        monkeypatch.setitem(cherrypy.request.headers, 'X-Auth-Token', api_token.token)
        assert None == auth_by_token(set())

    @pytest.mark.parametrize('token,expected', [
        (None, 'Missing X-Auth-Token header'),
        ('XXXX', 'Invalid auth token,'),
        ('b6531a2b-eddf-4d08-9afe-0ced6376078c', 'Auth token not found:'),
    ])
    def test_failure(self, monkeypatch, token, expected):
        monkeypatch.setitem(cherrypy.request.headers, 'X-Auth-Token', token)
        result = auth_by_token(set())
        assert result['error'].startswith(expected)

    def test_revoked(self, monkeypatch, session, api_token):
        api_token.revoked_time = datetime.now(pytz.UTC)
        session.commit()
        session.refresh(api_token)
        monkeypatch.setitem(cherrypy.request.headers, 'X-Auth-Token', api_token.token)
        result = auth_by_token(set())
        assert result['error'].startswith('Revoked auth token:')

    @pytest.mark.parametrize('token_access,required_access,expected', [
        ([], [], None),
        ([], [c.API_READ], ACCESS_ERR),
        ([], [c.API_READ, c.API_UPDATE], ACCESS_ERR),
        ([c.API_READ], [], None),
        ([c.API_READ], [c.API_READ], None),
        ([c.API_READ], [c.API_READ, c.API_UPDATE], ACCESS_ERR),
        ([c.API_READ, c.API_UPDATE], [c.API_READ, c.API_UPDATE], None),
    ])
    def test_insufficient_access(self, monkeypatch, session, api_token, token_access, required_access, expected):
        api_token.access = ','.join(map(str, token_access))
        session.commit()
        session.refresh(api_token)
        monkeypatch.setitem(cherrypy.request.headers, 'X-Auth-Token', api_token.token)
        result = auth_by_token(set(required_access))
        if expected:
            assert result['error'].startswith(expected)
        else:
            assert result is None


class TestAuthBySession(object):
    ACCESS_ERR = 'Insufficient access for admin account'

    def test_success(self, admin_account, csrf_token):
        assert None == auth_by_session(set())

    def test_check_csrf_missing_from_headers(self):
        result = auth_by_session(set())
        assert result['error'].startswith('CSRF token missing')

    def test_check_csrf_missing_from_session(self, monkeypatch):
        monkeypatch.setitem(cherrypy.request.headers, 'CSRF-Token', 'XXXX')
        assert auth_by_session(set()) == (403, 'Your CSRF token is invalid. Please go back and try again.')

    def test_check_csrf_invalid(self, monkeypatch):
        monkeypatch.setitem(cherrypy.session, 'csrf_token', '74c18d5c-1a92-40f0-b5f3-924d46efafe4')
        monkeypatch.setitem(cherrypy.request.headers, 'CSRF-Token', 'XXXX')
        result = auth_by_session(set())
        assert result['error'].startswith("CSRF check failed: csrf tokens don't match")

    def test_missing_admin_account(self, monkeypatch):
        monkeypatch.setitem(cherrypy.session, 'csrf_token', '74c18d5c-1a92-40f0-b5f3-924d46efafe4')
        monkeypatch.setitem(cherrypy.request.headers, 'CSRF-Token', '74c18d5c-1a92-40f0-b5f3-924d46efafe4')
        result = auth_by_session(set())
        assert result['error'].startswith('Missing admin account in session')

    def test_invalid_admin_account(self, monkeypatch):
        monkeypatch.setitem(cherrypy.session, 'account_id', '4abd6dd4-8da3-44dc-8074-b2fc1b73185f')
        monkeypatch.setitem(cherrypy.session, 'csrf_token', '74c18d5c-1a92-40f0-b5f3-924d46efafe4')
        monkeypatch.setitem(cherrypy.request.headers, 'CSRF-Token', '74c18d5c-1a92-40f0-b5f3-924d46efafe4')
        result = auth_by_session(set())
        assert result['error'].startswith('Invalid admin account in session')

    @pytest.mark.parametrize('admin_access,required_access,expected', [
        ([], [], None),
        ([], [c.API_READ], ACCESS_ERR),
        ([], [c.API_READ, c.API_UPDATE], ACCESS_ERR),
        ([c.API_READ], [], None),
        ([c.API_READ], [c.API_READ], None),
        ([c.API_READ], [c.API_READ, c.API_UPDATE], ACCESS_ERR),
        ([c.API_READ, c.API_UPDATE], [c.API_READ, c.API_UPDATE], None),
    ])
    def test_insufficient_access(self, monkeypatch, session, admin_account, admin_access, required_access, expected):
        admin_account.access = ','.join(map(str, admin_access))
        session.commit()
        session.refresh(admin_account)
        monkeypatch.setitem(cherrypy.session, 'account_id', admin_account.id)
        monkeypatch.setitem(cherrypy.session, 'csrf_token', '74c18d5c-1a92-40f0-b5f3-924d46efafe4')
        monkeypatch.setitem(cherrypy.request.headers, 'CSRF-Token', '74c18d5c-1a92-40f0-b5f3-924d46efafe4')
        result = auth_by_session(set(required_access))
        if expected:
            assert result['error'].startswith(expected)
        else:
            assert result is None


class TestApiAuth(object):
    AUTH_BY_SESSION_ERR = 'Missing X-Auth-Token header'
    AUTH_BY_TOKEN_ERR = 'Insufficient access for auth token'

    TEST_REQUIRED_ACCESS = [
        ([], [], False),
        ([], [c.API_READ], True),
        ([], [c.API_READ, c.API_UPDATE], True),
        ([c.API_READ], [], False),
        ([c.API_READ], [c.API_READ], False),
        ([c.API_READ], [c.API_READ, c.API_UPDATE], True),
        ([c.API_READ, c.API_UPDATE], [c.API_READ, c.API_UPDATE], False),
    ]

    @pytest.mark.parametrize('admin_access,required_access,expected', TEST_REQUIRED_ACCESS)
    def test_api_auth_by_session(self, monkeypatch, session, admin_account, admin_access, required_access, expected):

        @api_auth(*required_access)
        def _func():
            return 'SUCCESS'

        admin_account.access = ','.join(map(str, admin_access))
        session.commit()
        session.refresh(admin_account)
        monkeypatch.setitem(cherrypy.session, 'account_id', admin_account.id)
        monkeypatch.setitem(cherrypy.session, 'csrf_token', '74c18d5c-1a92-40f0-b5f3-924d46efafe4')
        monkeypatch.setitem(cherrypy.request.headers, 'CSRF-Token', '74c18d5c-1a92-40f0-b5f3-924d46efafe4')
        result = _func()
        if expected:
            assert result['error'].startswith(self.AUTH_BY_SESSION_ERR)
        else:
            assert 'SUCCESS' == result

    @pytest.mark.parametrize('token_access,required_access,expected', TEST_REQUIRED_ACCESS)
    def test_api_auth_by_token(self, monkeypatch, session, api_token, token_access, required_access, expected):

        @api_auth(*required_access)
        def _func():
            return 'SUCCESS'

        api_token.access = ','.join(map(str, token_access))
        session.commit()
        session.refresh(api_token)
        monkeypatch.setitem(cherrypy.request.headers, 'X-Auth-Token', api_token.token)
        result = _func()
        if expected:
            assert result['error'].startswith(self.AUTH_BY_TOKEN_ERR)
        else:
            assert 'SUCCESS' == result


class TestAllApiAuth(object):
    AUTH_BY_SESSION_ERR = 'Missing X-Auth-Token header'
    AUTH_BY_TOKEN_ERR = 'Insufficient access for auth token'

    TEST_REQUIRED_ACCESS = [
        ([], [], False),
        ([], [c.API_READ], True),
        ([], [c.API_READ, c.API_UPDATE], True),
        ([c.API_READ], [], False),
        ([c.API_READ], [c.API_READ], False),
        ([c.API_READ], [c.API_READ, c.API_UPDATE], True),
        ([c.API_READ, c.API_UPDATE], [c.API_READ, c.API_UPDATE], False),
    ]

    @pytest.mark.parametrize('admin_access,required_access,expected', TEST_REQUIRED_ACCESS)
    def test_all_api_auth_by_session(self, monkeypatch, session, admin_account, admin_access, required_access, expected):

        @all_api_auth(*required_access)
        class Service(object):
            def func_1(self):
                return 'SUCCESS1'

            def func_2(self):
                return 'SUCCESS2'

        service = Service()

        admin_account.access = ','.join(map(str, admin_access))
        session.commit()
        session.refresh(admin_account)
        monkeypatch.setitem(cherrypy.session, 'account_id', admin_account.id)
        monkeypatch.setitem(cherrypy.session, 'csrf_token', '74c18d5c-1a92-40f0-b5f3-924d46efafe4')
        monkeypatch.setitem(cherrypy.request.headers, 'CSRF-Token', '74c18d5c-1a92-40f0-b5f3-924d46efafe4')

        result = service.func_1()
        if expected:
            assert result['error'].startswith(self.AUTH_BY_SESSION_ERR)
        else:
            assert 'SUCCESS1' == result

        result = service.func_2()
        if expected:
            assert result['error'].startswith(self.AUTH_BY_SESSION_ERR)
        else:
            assert 'SUCCESS2' == result

    @pytest.mark.parametrize('token_access,required_access,expected', TEST_REQUIRED_ACCESS)
    def test_all_api_auth_by_token(self, monkeypatch, session, api_token, token_access, required_access, expected):

        @all_api_auth(*required_access)
        class Service(object):
            def func_1(self):
                return 'SUCCESS1'

            def func_2(self):
                return 'SUCCESS2'

        service = Service()

        api_token.access = ','.join(map(str, token_access))
        session.commit()
        session.refresh(api_token)
        monkeypatch.setitem(cherrypy.request.headers, 'X-Auth-Token', api_token.token)

        result = service.func_1()
        if expected:
            assert result['error'].startswith(self.AUTH_BY_TOKEN_ERR)
        else:
            assert 'SUCCESS1' == result

        result = service.func_2()
        if expected:
            assert result['error'].startswith(self.AUTH_BY_TOKEN_ERR)
        else:
            assert 'SUCCESS2' == result
