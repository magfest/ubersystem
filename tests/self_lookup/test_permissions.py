import inspect

import cherrypy
import pytest

from uber.config import c
from uber.errors import CSRFException, HTTPRedirect
from uber.model_checks import self_token_has_client
from uber.models import AccessGroup, AdminAccount, ApiToken
from uber.site_sections.api import Root

from tests.self_lookup.factories import attendee


def _admin(session, access):
    group = AccessGroup(name='Group {}'.format(len(access)), access=access)
    admin = AdminAccount(attendee=attendee(session), access_groups=[group], hashed='')
    session.add(admin)
    session.flush()
    return admin


def test_page_key_grants_self_but_not_read(session):
    admin = _admin(session, {'api_create_api_token': '1', 'api_index': '1', 'api_revoke_api_token': '1'})
    assert admin.api_self and not admin.api_read


def test_read_only_api_group_grants_self(session):
    group = AccessGroup(name='Read only api', read_only_access={'api': '1'})
    admin = AdminAccount(attendee=attendee(session), access_groups=[group], hashed='')
    session.add(admin)
    session.flush()
    assert admin.api_read and admin.api_self


def test_self_token_requires_client_id(session):
    assert 'OIDC client' in self_token_has_client(ApiToken(access=str(c.API_SELF), oidc_client_id=' '))


def test_self_token_with_client_id_passes(session):
    assert self_token_has_client(ApiToken(access=str(c.API_SELF), oidc_client_id='kc-OIDC-Debug-App')) is None


def _revoke(session, monkeypatch, caller, token, csrf_token='csrf-1'):
    monkeypatch.setattr(cherrypy.request, 'method', 'POST', raising=False)
    monkeypatch.setattr(cherrypy, 'session', {'account_id': caller.id, 'csrf_token': 'csrf-1'}, raising=False)
    monkeypatch.setattr(cherrypy.request, 'headers', {}, raising=False)
    revoke = inspect.unwrap(Root.revoke_api_token)
    with pytest.raises(HTTPRedirect) as exc:
        revoke(Root(), session, id=token.id, csrf_token=csrf_token)
    return exc.value


def test_revoke_rejects_another_admins_token(session, monkeypatch):
    owner = _admin(session, {'api_index': '1'})
    caller = _admin(session, {'api_revoke_api_token': '1', 'api_index': '1', 'x': '1'})
    token = ApiToken(admin_account_id=owner.id, access=str(c.API_READ))
    session.add(token)
    session.flush()
    redirect = _revoke(session, monkeypatch, caller, token)
    assert 'only%20revoke%20your%20own' in str(redirect)
    assert token.revoked_time is None


def test_revoke_allows_owner(session, monkeypatch):
    owner = _admin(session, {'api_index': '1', 'y': '1'})
    token = ApiToken(admin_account_id=owner.id, access=str(c.API_READ))
    session.add(token)
    session.flush()
    _revoke(session, monkeypatch, owner, token)
    assert token.revoked_time is not None


def test_revoke_allows_super_admin(session, monkeypatch):
    owner = _admin(session, {'api_index': '1', 'z': '1'})
    boss = _admin(session, {'devtools': '5'})
    token = ApiToken(admin_account_id=owner.id, access=str(c.API_READ))
    session.add(token)
    session.flush()
    _revoke(session, monkeypatch, boss, token)
    assert token.revoked_time is not None


@pytest.mark.parametrize('csrf_token', [None, 'wrong'])
def test_revoke_requires_csrf_token(session, monkeypatch, csrf_token):
    owner = _admin(session, {'api_index': '1', 'w': '1'})
    token = ApiToken(admin_account_id=owner.id, access=str(c.API_READ))
    session.add(token)
    session.flush()
    with pytest.raises(CSRFException):
        _revoke(session, monkeypatch, owner, token, csrf_token=csrf_token)
    assert token.revoked_time is None
