import uuid

import pytest

from uber.auth import OIDC
from uber.config import c
from uber.errors import HTTPRedirect
from uber.models import Attendee, AttendeeAccount, Email, PasswordReset
from uber.site_sections.preregistration import Root

from tests.emails.conftest import unwrap

reset_password = unwrap(Root.reset_password)


@pytest.fixture
def session(session, monkeypatch):
    """The handlers commit; flush instead so the suite's rollback undoes it."""
    monkeypatch.setattr(session, 'commit', session.flush)
    monkeypatch.setattr(c, 'SSO_EMAIL_DOMAINS', [])
    return session


def _account(session, email=None):
    account = AttendeeAccount(email=email or f'{uuid.uuid4().hex}@example.com')
    attendee = Attendee(first_name='Rosa', last_name='Delgado', email=account.email,
                        badge_status=c.COMPLETED_STATUS, paid=c.NEED_NOT_PAY)
    session.add_all([account, attendee])
    session.flush()
    session.add_attendee_to_account(attendee, account)
    session.flush()
    return account


def _reset(session, account, **params):
    with pytest.raises(HTTPRedirect) as redirect:
        reset_password(Root(), session, account_email=account.email, **params)
    return str(redirect.value)


def _reset_rows(session, account):
    session.flush()  # The session does not autoflush, and the handler leaves its new row unflushed
    return session.query(PasswordReset).filter_by(attendee_id=account.id).all()


@pytest.mark.parametrize('params', [{'admin_url': 'reg_admin/attendee_accounts?'}, {}],
                         ids=['admin page', 'public form'])
def test_reset_password_keeps_an_unused_claim_link_for_an_sso_account(session, monkeypatch, params):
    monkeypatch.setattr(c, 'OIDC_ENABLED', True)
    account = _account(session)
    OIDC.send_claim_token(session, account)
    claim_token = _reset_rows(session, account)[0].token

    _reset(session, account, **params)

    assert [row.token for row in _reset_rows(session, account)] == [claim_token]


def test_reset_password_tells_the_admin_sso_accounts_have_no_password(session, monkeypatch):
    monkeypatch.setattr(c, 'OIDC_ENABLED', True)
    account = _account(session)

    redirect = _reset(session, account, admin_url='reg_admin/attendee_accounts?')

    assert 'SSO accounts do not have passwords' in redirect


def test_reset_password_still_emails_a_local_account(session, monkeypatch):
    monkeypatch.setattr(c, 'OIDC_ENABLED', False)
    account = _account(session)

    _reset(session, account, admin_url='reg_admin/attendee_accounts?')

    assert len(_reset_rows(session, account)) == 1
    assert session.query(Email).filter_by(ident='attendee_password_reset', fk_id=account.id).count() == 1


def _admin_pages(session, monkeypatch, account):
    import cherrypy

    from uber.decorators import render
    from uber.site_sections import reg_admin

    monkeypatch.setattr(cherrypy, 'session', {}, raising=False)  # The pages' CSRF fields read the web session

    account_page = unwrap(reg_admin.Root.attendee_account_form)(reg_admin.Root(), session, id=account.id)
    # A search with one result redirects to that account, so give it a second match
    tag = account.email.split('@')[0]
    _account(session, email=f'{tag}.second@example.com')
    search_page = unwrap(reg_admin.Root.attendee_accounts)(reg_admin.Root(), session, search_text=tag)
    return [render('reg_admin/attendee_account_form.html', account_page, encoding=None),
            render('reg_admin/attendee_accounts.html', search_page, encoding=None)]


@pytest.mark.parametrize('oidc, shown', [(True, False), (False, True)], ids=['sso account', 'local account'])
def test_admin_pages_offer_reset_password_only_to_local_accounts(session, monkeypatch, oidc, shown):
    monkeypatch.setattr(c, 'OIDC_ENABLED', oidc)
    account = _account(session)

    assert [('Reset Password' in html) for html in _admin_pages(session, monkeypatch, account)] == [shown, shown]


def test_new_account_setup_keeps_an_existing_sso_accounts_claim_link(session, monkeypatch):
    from uber.site_sections.preregistration import set_up_new_account

    monkeypatch.setattr(c, 'OIDC_ENABLED', True)
    account = _account(session)
    OIDC.send_claim_token(session, account)
    claim_token = _reset_rows(session, account)[0].token
    badge = Attendee(first_name='Sam', last_name='Okafor', email=account.email,
                     badge_status=c.COMPLETED_STATUS, paid=c.NEED_NOT_PAY)
    session.add(badge)
    session.flush()

    set_up_new_account(session, badge, account.email)

    assert [row.token for row in _reset_rows(session, account)] == [claim_token]
