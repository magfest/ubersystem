import pytest

from uber.common import *


class TestCheckAdminAccount(object):
    @pytest.mark.parametrize('admin_access,access_changes,expected', [
        ([c.ADMIN], [c.ADMIN], None),
        ([], [c.ADMIN], 'You do not have permission to change that access setting'),
    ])
    def test_check_admin_account_access(self, admin_access, access_changes, expected):
        pass


class TestAuthByToken(object):
    def test_success(self):
        pass

    def test_missing_token(self):
        pass

    def test_bad_uuid(self):
        pass

    def test_invalid_auth_token(self):
        pass

    def test_revoked_auth_token(self):
        pass

    def test_insufficient_access(self):
        pass


class TestAuthBySession(object):
    def test_success(self):
        pass

    def test_check_csrf(self):
        pass

    def test_missing_admin_account(self):
        pass

    def test_invalid_admin_account(self):
        pass

    def test_insufficient_access(self):
        pass


class TestApiAuth(object):
    def test_api_auth(self):
        pass


class TestAllApiAuth(object):
    def test_all_api_auth(self):
        pass
