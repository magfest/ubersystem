import uuid

import cherrypy
import pytest
import sqlalchemy as sa

from uber.api import auth_by_token
from uber.config import c
from uber.model_checks import admin_has_required_api_access
from uber.models import AccessGroup, AdminAccount, ApiToken, Attendee, Session


@pytest.fixture
def committed_admin():
    """Commit an admin that holds only the Self-level API page, and delete it and its tokens at teardown.

    auth_by_token and admin_has_required_api_access open their own Session, so they cannot see rows
    that the rollback-only session fixture has flushed.
    """
    with Session() as s:
        group = AccessGroup(name='Self only {}'.format(uuid.uuid4().hex), access={'api_create_api_token': '1'})
        admin = AdminAccount(attendee=Attendee(first_name='Pat', last_name='Minter',
                                               email='{}@example.com'.format(uuid.uuid4().hex)),
                             access_groups=[group], hashed='')
        s.add(admin)
        s.commit()
        admin_id, attendee_id, group_id = admin.id, admin.attendee_id, group.id
    try:
        yield admin_id
    finally:
        with Session() as s:
            s.query(ApiToken).filter_by(admin_account_id=admin_id).delete()
            s.execute(sa.text('DELETE FROM admin_access_group WHERE admin_account_id = :id'), {'id': admin_id})
            s.query(AdminAccount).filter_by(id=admin_id).delete()
            s.query(AccessGroup).filter_by(id=group_id).delete()
            s.query(Attendee).filter_by(id=attendee_id).delete()
            s.commit()


def _call_with_token(monkeypatch, admin_id, access):
    with Session() as s:
        token = ApiToken(admin_account_id=admin_id, access=','.join(str(a) for a in access), oidc_client_id='kc-app')
        s.add(token)
        s.commit()
        token_value = token.token
    monkeypatch.setattr(cherrypy, 'session', {}, raising=False)
    monkeypatch.setattr(cherrypy.request, 'admin_account', None, raising=False)
    monkeypatch.setitem(cherrypy.request.headers, 'X-Auth-Token', token_value)
    return auth_by_token({'api_self'})


def test_self_only_token_sets_no_session(monkeypatch, committed_admin):
    assert _call_with_token(monkeypatch, committed_admin, [c.API_SELF]) is None
    assert 'account_id' not in cherrypy.session
    assert cherrypy.request.admin_account == committed_admin


def test_read_plus_self_token_keeps_existing_behavior(monkeypatch, committed_admin):
    assert _call_with_token(monkeypatch, committed_admin, [c.API_READ, c.API_SELF]) is None
    assert cherrypy.session['account_id'] == committed_admin


def test_self_only_admin_can_only_mint_self_tokens(committed_admin):
    with Session() as s:
        admin = s.get(AdminAccount, committed_admin)
        assert admin.allowed_api_access_opts == [(c.API_SELF, 'Self')]


def test_self_only_admin_cannot_mint_read_token(monkeypatch, committed_admin):
    monkeypatch.setattr(cherrypy, 'session', {'account_id': committed_admin}, raising=False)
    token = ApiToken(admin_account_id=committed_admin, access=str(c.API_READ))
    assert 'do not have permission' in admin_has_required_api_access(token)
