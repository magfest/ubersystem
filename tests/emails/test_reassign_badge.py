import uuid

import cherrypy
import pytest

from uber.auth import OIDC
from uber.config import c
from uber.errors import HTTPRedirect
from uber.models import AdminAccount, Attendee, AttendeeAccount, Email
from uber.site_sections import reg_admin
from uber.site_sections.reg_admin import Root

from tests.emails.conftest import unwrap

lookup = unwrap(Root.reassign_account_lookup)
reassign = unwrap(Root.orphaned_attendees)


@pytest.fixture
def session(session, monkeypatch):
    """The reassign handler commits; flush instead so the suite's rollback undoes it."""
    monkeypatch.setattr(session, 'commit', session.flush)
    monkeypatch.setattr(reg_admin, 'valid_email', lambda email: None if '@' in email else 'Enter a valid email.')
    monkeypatch.setattr(c, 'OIDC_ENABLED', False)
    return session


def _address():
    return f'{uuid.uuid4().hex}@example.com'


def _account_with_badge(session, email=None):
    account = AttendeeAccount(email=email or _address())
    attendee = Attendee(first_name='Jordan', last_name='Reyes', email=account.email,
                        badge_status=c.COMPLETED_STATUS, paid=c.NEED_NOT_PAY)
    session.add_all([account, attendee])
    session.flush()
    session.add_attendee_to_account(attendee, account)
    session.flush()
    return account, attendee


def _reassign(session, attendee, from_account, to_email, notify):
    original_method = cherrypy.request.method
    cherrypy.request.method = 'POST'
    try:
        with pytest.raises(HTTPRedirect) as redirect:
            reassign(Root(), session, id=attendee.id, account_id=from_account.id, account_email=to_email,
                     notify='true' if notify else '')
    finally:
        cherrypy.request.method = original_method
    return redirect.value


def _emails(session, ident, account):
    return session.query(Email).filter(Email.ident == ident, Email.fk_id == account.id).count()


def test_lookup_finds_an_existing_account_ignoring_case_and_spaces(session):
    this_account, _ = _account_with_badge(session)
    other_account, _ = _account_with_badge(session)

    result = lookup(Root(), session, account_email=f'  {other_account.email.upper()} ', account_id=this_account.id)

    assert result == {'success': True, 'exists': True, 'same_account': False, 'badge_count': 1,
                      'claim_email': False}


def test_lookup_reports_an_email_with_no_account(session):
    this_account, _ = _account_with_badge(session)

    result = lookup(Root(), session, account_email=_address(), account_id=this_account.id)

    assert result['success'] and not result['exists']


def test_lookup_says_when_the_email_is_this_account(session):
    this_account, _ = _account_with_badge(session)

    result = lookup(Root(), session, account_email=this_account.email, account_id=this_account.id)

    assert result['same_account']


def test_lookup_says_a_new_sso_account_gets_a_claim_email(session, monkeypatch):
    monkeypatch.setattr(c, 'OIDC_ENABLED', True)
    this_account, _ = _account_with_badge(session)

    result = lookup(Root(), session, account_email=_address(), account_id=this_account.id)

    assert result['claim_email'] is True


def test_lookup_rejects_an_invalid_email(session):
    this_account, _ = _account_with_badge(session)

    result = lookup(Root(), session, account_email='not-an-email', account_id=this_account.id)

    assert result == {'success': False, 'message': 'Enter a valid email.'}


def test_reassign_to_an_existing_account_emails_it_when_asked(session):
    from_account, attendee = _account_with_badge(session)
    attendee.badge_type = c.STAFF_BADGE
    to_account, _ = _account_with_badge(session)

    redirect = _reassign(session, attendee, from_account, to_account.email, notify=True)

    email = session.query(Email).filter(Email.ident == 'attendee_account_attendee_added',
                                        Email.fk_id == to_account.id).one()
    assert attendee.managers == [to_account]
    # The email stores its data as JSON columns, so properties like full_name must come from the live badge
    assert 'Jordan Reyes' in email.body
    assert attendee.badge_type_label in email.body
    assert 'queued' in str(redirect)


def test_reassign_without_notify_sends_nothing(session):
    from_account, attendee = _account_with_badge(session)
    to_account, _ = _account_with_badge(session)

    _reassign(session, attendee, from_account, to_account.email, notify=False)

    assert _emails(session, 'attendee_account_attendee_added', to_account) == 0
    assert attendee.managers == [to_account]


def test_reassign_to_a_new_sso_account_sends_the_claim_email_when_asked(session, monkeypatch):
    monkeypatch.setattr(c, 'OIDC_ENABLED', True)
    claimed = []
    monkeypatch.setattr(OIDC, 'send_claim_token', classmethod(lambda cls, session, account: claimed.append(account)))
    from_account, attendee = _account_with_badge(session)
    new_email = _address()
    session.expire(attendee)  # Reload managers on access, as a fresh request would

    _reassign(session, attendee, from_account, new_email, notify=True)

    assert [account.email for account in claimed] == [new_email]
    assert [account.email for account in attendee.managers] == [new_email]


def test_reassign_to_a_new_sso_account_without_notify_sends_nothing(session, monkeypatch):
    monkeypatch.setattr(c, 'OIDC_ENABLED', True)
    claimed = []
    monkeypatch.setattr(OIDC, 'send_claim_token', classmethod(lambda cls, session, account: claimed.append(account)))
    from_account, attendee = _account_with_badge(session)

    _reassign(session, attendee, from_account, _address(), notify=False)

    assert claimed == []


def test_reassign_that_cannot_move_the_badge_says_so_and_sends_nothing(session):
    from_account, attendee = _account_with_badge(session)
    to_account, _ = _account_with_badge(session)
    to_account.sso_id = 'login-one'
    session.add(AdminAccount(attendee=attendee, hashed='', sso_id='login-two'))
    session.flush()
    session.expire(attendee)

    redirect = _reassign(session, attendee, from_account, to_account.email, notify=True)

    assert _emails(session, 'attendee_account_attendee_added', to_account) == 0
    assert attendee.managers == [from_account]
    assert 'DevOps' in str(redirect)


def _render_badge_flags(monkeypatch, attendee, access, read_only_access=()):
    from uber.decorators import render
    from uber.forms import load_forms
    from uber.utils import request_cached_context

    def get_access_set(id=None, include_read_only=False, full=False):
        return set(access) | (set(read_only_access) if include_read_only else set())

    monkeypatch.setattr(AdminAccount, 'get_access_set', staticmethod(get_access_set))
    forms = load_forms({}, attendee, ['AdminBadgeFlags'])
    # c.ADMIN_*_ACCESS_SET values are cached per request; start and end each render with an empty cache
    with request_cached_context(clear_cache_on_start=True):
        return render('forms/attendee/admin_badge_flags.html', {'attendee': attendee, 'forms': forms, **forms},
                      encoding=None)


def test_badge_form_links_to_the_account_page_for_a_page_only_grant(session, monkeypatch):
    account, attendee = _account_with_badge(session)

    html = _render_badge_flags(monkeypatch, attendee, {'registration', 'reg_admin_attendee_account_form'})

    assert f'attendee_account_form?id={account.id}' in html


def test_badge_form_links_to_the_account_page_for_full_reg_admin(session, monkeypatch):
    account, attendee = _account_with_badge(session)

    html = _render_badge_flags(monkeypatch, attendee, {'registration', 'reg_admin'})

    assert f'attendee_account_form?id={account.id}' in html


def test_badge_form_shows_only_the_account_email_without_the_account_page(session, monkeypatch):
    account, attendee = _account_with_badge(session)

    html = _render_badge_flags(monkeypatch, attendee, {'registration'})

    assert account.email in html
    assert 'attendee_account_form' not in html


def test_badge_form_hides_the_account_link_for_a_read_only_grant(session, monkeypatch):
    account, attendee = _account_with_badge(session)

    html = _render_badge_flags(monkeypatch, attendee, {'registration'},
                               read_only_access={'reg_admin_attendee_account_form'})

    assert 'attendee_account_form' not in html
