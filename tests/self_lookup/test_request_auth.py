import inspect

import cherrypy
import pytest

from uber.api import SelfLookup
from uber.config import c
from uber.models import AdminAccount, ApiToken
from uber.self_lookup import authenticated_sub

from tests.self_lookup.factories import attendee

CLIENT = 'kc-OIDC-Debug-App'


@pytest.fixture(autouse=True)
def audience(monkeypatch):
    monkeypatch.setattr(c, 'OIDC_API_AUDIENCE', 'ubersystem-api')


@pytest.fixture
def self_token(session):
    admin = AdminAccount(attendee=attendee(session), hashed='')
    session.add(admin)
    token = ApiToken(admin_account=admin, access=str(c.API_SELF), oidc_client_id=CLIENT)
    session.add(token)
    session.flush()
    return token


@pytest.fixture
def claims(monkeypatch):
    data = {'sub': 'sub-1', 'azp': CLIENT}
    monkeypatch.setattr(cherrypy.tools.oidc, '_verify_token', lambda *a, **k: data)
    return data


def _headers(token, authorization='Bearer abc'):
    return {'X-Auth-Token': token.token, 'Authorization': authorization}


def _code(session, headers):
    with pytest.raises(cherrypy.HTTPError) as exc:
        authenticated_sub(session, headers)
    return exc.value.code


def test_valid_request_returns_sub(session, self_token, claims):
    assert authenticated_sub(session, _headers(self_token)) == 'sub-1'


def test_bearer_scheme_is_case_insensitive(session, self_token, claims):
    assert authenticated_sub(session, _headers(self_token, 'bEaReR abc')) == 'sub-1'


def test_verifier_receives_audience_and_token(session, self_token, monkeypatch):
    seen = {}

    def fake(token, audience=None):
        seen.update(token=token, audience=audience)
        return {'sub': 'sub-1', 'azp': CLIENT}
    monkeypatch.setattr(cherrypy.tools.oidc, '_verify_token', fake)
    authenticated_sub(session, _headers(self_token))
    assert seen == {'token': 'abc', 'audience': 'ubersystem-api'}


@pytest.mark.parametrize('sub', ['', '   ', None, 42])
def test_blank_or_bad_sub_is_401(session, self_token, claims, sub):
    claims['sub'] = sub
    assert _code(session, _headers(self_token)) == 401


def test_wrong_client_is_403(session, self_token, claims):
    claims['azp'] = 'some-other-app'
    assert _code(session, _headers(self_token)) == 403


def test_client_id_whitespace_is_ignored(session, self_token, claims):
    self_token.oidc_client_id = f'  {CLIENT} '
    assert authenticated_sub(session, _headers(self_token)) == 'sub-1'


@pytest.mark.parametrize('stored', ['', '   '])
@pytest.mark.parametrize('azp', [None, '', ' '])
def test_blank_stored_client_never_matches(session, self_token, claims, stored, azp):
    self_token.oidc_client_id = stored
    if azp is None:
        del claims['azp']
    else:
        claims['azp'] = azp
    assert _code(session, _headers(self_token)) == 403


def test_missing_azp_is_403(session, self_token, claims):
    del claims['azp']
    assert _code(session, _headers(self_token)) == 403


def test_rfc9068_client_id_is_accepted_without_azp(session, self_token, claims):
    del claims['azp']
    claims['client_id'] = CLIENT
    assert authenticated_sub(session, _headers(self_token)) == 'sub-1'


def test_azp_wins_over_client_id(session, self_token, claims):
    claims['azp'] = 'some-other-app'
    claims['client_id'] = CLIENT
    assert _code(session, _headers(self_token)) == 403


def test_okta_cid_is_not_read(session, self_token, claims):
    del claims['azp']
    claims['cid'] = CLIENT
    assert _code(session, _headers(self_token)) == 403


@pytest.mark.parametrize('authorization', [None, '', 'Bearer', 'Bearer   ', 'Basic abc', 'abc'])
def test_missing_or_malformed_bearer_is_401(session, self_token, claims, authorization):
    headers = {'X-Auth-Token': self_token.token}
    if authorization is not None:
        headers['Authorization'] = authorization
    assert _code(session, headers) == 401


def test_unverifiable_token_is_401(session, self_token, monkeypatch):
    monkeypatch.setattr(cherrypy.tools.oidc, '_verify_token', lambda *a, **k: None)
    assert _code(session, _headers(self_token)) == 401


def test_unconfigured_audience_is_503(session, self_token, claims, monkeypatch):
    monkeypatch.setattr(c, 'OIDC_API_AUDIENCE', '')
    assert _code(session, _headers(self_token)) == 503


def test_session_without_api_token_is_403(session, claims):
    assert _code(session, {'Authorization': 'Bearer x'}) == 403


@pytest.mark.parametrize('value', ['not-a-uuid', '', '00000000-0000-0000-0000-000000000000'])
def test_bad_or_unknown_api_token_is_403(session, claims, value):
    assert _code(session, {'X-Auth-Token': value, 'Authorization': 'Bearer x'}) == 403


def test_revoked_api_token_is_403(session, self_token, claims):
    from datetime import datetime, UTC
    self_token.revoked_time = datetime.now(UTC)
    session.flush()
    assert _code(session, _headers(self_token)) == 403


def test_read_token_with_client_id_is_403(session, claims):
    admin = AdminAccount(attendee=attendee(session), hashed='')
    session.add(admin)
    token = ApiToken(admin_account=admin, access=str(c.API_READ), oidc_client_id=CLIENT)
    session.add(token)
    session.flush()
    assert _code(session, _headers(token)) == 403


def test_read_token_lacks_self_level():
    assert ApiToken(access=str(c.API_READ)).api_self is False


@pytest.mark.parametrize('method', ['badges', 'badge'])
def test_service_methods_require_api_self(method):
    assert inspect.unwrap(getattr(SelfLookup, method)).required_access == {'api_self'}
