"""
Auth and permission tests.

Verifies that:
1. Unauthenticated requests to protected routes redirect to the login page.
2. Authenticated requests return valid HTML.
3. POST requests without a CSRF token raise a CSRF redirect (with DEV_BOX=False).
4. POST requests with a valid CSRF token succeed.

Uses the conftest-level `admin_attendee`, `GET`, `POST`, and `csrf_token`
fixtures so each test exercises the real decorator chain.
"""

import cherrypy
import pytest
from functools import wraps

from tests.uber.conftest import (  # noqa: F401 — imported for fixture collection
    admin_attendee,
    GET,
    POST,
    csrf_token,
    extract_message_from_html,
)
from uber.config import c
from uber.decorators import renderable
from uber.errors import CSRFException, HTTPRedirect
from uber.site_sections import promo_codes
from uber.utils import check_csrf


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _promo_index(**params):
    response = promo_codes.Root().index(**params)
    if isinstance(response, bytes):
        response = response.decode('utf-8')
    return response.strip()


def _promo_generate(**params):
    response = promo_codes.Root().generate_promo_codes(**params)
    if isinstance(response, bytes):
        response = response.decode('utf-8')
    return response.strip()


@pytest.fixture(autouse=True)
def wsgi_environ(monkeypatch):
    """
    HTTPRedirect.__init__ accesses cherrypy.request.wsgi_environ['REQUEST_URI']
    when save_location=True (used for unauthenticated GET redirects).
    Set a minimal stub so unit tests don't fail with AttributeError.
    """
    monkeypatch.setattr(
        cherrypy.request, 'wsgi_environ',
        {'REQUEST_URI': '/uber/promo_codes/index'},
        raising=False,
    )


# ---------------------------------------------------------------------------
# Unauthenticated access
# ---------------------------------------------------------------------------

class TestUnauthenticatedAccess:

    def test_get_index_redirects_to_login(self, GET):
        """GET to a protected page without auth should redirect to login."""
        with pytest.raises(HTTPRedirect) as exc_info:
            _promo_index()
        redirect_url = exc_info.value.urls[0]
        assert 'login' in redirect_url.lower()

    def test_get_generate_redirects_to_login(self, GET, monkeypatch):
        monkeypatch.setattr(cherrypy.request, 'path_info', '/promo_codes/generate_promo_codes')
        with pytest.raises(HTTPRedirect) as exc_info:
            _promo_generate()
        redirect_url = exc_info.value.urls[0]
        assert 'login' in redirect_url.lower()

    def test_post_without_auth_redirects_to_login(self, POST, monkeypatch):
        """Auth check runs before CSRF; unauthenticated POST redirects to login."""
        monkeypatch.setattr(cherrypy.request, 'path_info', '/promo_codes/generate_promo_codes')
        with pytest.raises(HTTPRedirect) as exc_info:
            _promo_generate()
        redirect_url = exc_info.value.urls[0]
        assert 'login' in redirect_url.lower()


# ---------------------------------------------------------------------------
# Authenticated access
# ---------------------------------------------------------------------------

class TestAuthenticatedAccess:

    def test_index_returns_html(self, GET, admin_attendee, monkeypatch):
        monkeypatch.setattr(cherrypy.request, 'path_info', '/promo_codes/index')
        response = _promo_index()
        assert '<!DOCTYPE' in response.upper()

    def test_generate_returns_html(self, GET, admin_attendee, monkeypatch):
        monkeypatch.setattr(cherrypy.request, 'path_info', '/promo_codes/generate_promo_codes')
        response = _promo_generate()
        assert '<!DOCTYPE' in response.upper()
        assert extract_message_from_html(response) == ''


# ---------------------------------------------------------------------------
# CSRF protection
# ---------------------------------------------------------------------------

class TestCSRFProtection:
    """
    Tests for the CSRF protection mechanism.

    Note: Not all handlers enforce CSRF — it's opt-in via check_csrf() or apply(ignore_csrf=False).
    These tests verify the underlying check_csrf() utility and the renderable() decorator's
    CSRFException handling, independent of any specific handler.
    """

    def test_check_csrf_raises_with_missing_token(self):
        """check_csrf() raises CSRFException when no token is provided."""
        cherrypy.session['csrf_token'] = 'expected-token'
        with pytest.raises(CSRFException, match='missing'):
            check_csrf(None)

    def test_check_csrf_raises_with_wrong_token(self):
        """check_csrf() raises CSRFException when the token doesn't match the session."""
        cherrypy.session['csrf_token'] = 'correct-token'
        with pytest.raises(CSRFException, match="don't match"):
            check_csrf('wrong-token')

    def test_check_csrf_passes_with_valid_token(self):
        """check_csrf() succeeds when the token matches the session."""
        cherrypy.session['csrf_token'] = 'my-csrf-token'
        check_csrf('my-csrf-token')  # should not raise

    def test_renderable_catches_csrf_and_redirects_in_non_dev_mode(self, monkeypatch):
        """
        When a handler raises CSRFException and DEV_BOX=False, renderable()
        catches the exception and raises HTTPRedirect.
        """
        monkeypatch.setattr(c, 'DEV_BOX', False)

        @renderable
        def csrf_raising_handler():
            raise CSRFException('test csrf failure')

        csrf_raising_handler.public = True  # bypass auth for this unit test
        csrf_raising_handler.ajax = False

        with pytest.raises(HTTPRedirect) as exc_info:
            csrf_raising_handler()
        assert 'invalid' in exc_info.value.urls[0].lower()

    def test_renderable_swallows_csrf_in_dev_box_mode(self, monkeypatch):
        """
        When a handler raises CSRFException and DEV_BOX=True, renderable()
        catches the exception, logs it, and returns None (no redirect).
        """
        assert c.DEV_BOX is True  # confirm we're in dev mode

        @renderable
        def csrf_raising_handler():
            raise CSRFException('test csrf failure')

        csrf_raising_handler.public = True
        csrf_raising_handler.ajax = False

        result = csrf_raising_handler()
        assert result is None

    def test_post_with_valid_csrf_succeeds(self, POST, csrf_token, admin_attendee, monkeypatch):
        """Authenticated POST with valid CSRF should not raise auth/CSRF error."""
        monkeypatch.setattr(cherrypy.request, 'path_info', '/promo_codes/generate_promo_codes')
        response = _promo_generate(
            is_single_promo_code=1,
            count=1,
            use_words=False,
            expiration_date='2999-01-01',
            code='auth-test-csrf-code',
            uses_allowed=1,
        )
        assert '<!DOCTYPE' in response.upper()


# ---------------------------------------------------------------------------
# Session account_id gate
# ---------------------------------------------------------------------------

class TestSessionGate:

    def test_no_account_id_in_session_denies_access(self, GET):
        """account_id absent from session → redirect to login."""
        assert cherrypy.session.get('account_id') is None
        with pytest.raises(HTTPRedirect) as exc_info:
            _promo_index()
        assert 'login' in exc_info.value.urls[0].lower()

    def test_removing_account_id_revokes_access(self, GET, admin_attendee, monkeypatch):
        """
        While admin_attendee is set, access succeeds.
        After clearing account_id from session, access is denied.
        """
        monkeypatch.setattr(cherrypy.request, 'path_info', '/promo_codes/index')
        response = _promo_index()
        assert '<!DOCTYPE' in response.upper()

        cherrypy.session.pop('account_id', None)
        with pytest.raises(HTTPRedirect) as exc_info:
            _promo_index()
        assert 'login' in exc_info.value.urls[0].lower()
