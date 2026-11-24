"""Static assets must not pay the per-request session and login costs.

Every static hit used to run the Redis session tool and the OIDC tool, and the
resulting Set-Cookie made the response uncacheable at CloudFront. During the
2026-09-16 badge launch that turned each page view into a dozen origin requests.
"""
import cherrypy

from tests.web.conftest import header_values
from uber.config import c


def test_static_file_response_sets_no_session_cookie(wsgi_get):
    status, headers, _ = wsgi_get('/static/images/favicon.png')

    assert status.startswith('200')
    assert not any('session_id=' in v for v in header_values(headers, 'Set-Cookie'))


def test_static_view_response_sets_no_session_cookie(wsgi_get):
    status, headers, _ = wsgi_get('/static_views/styles/main.css')

    assert status.startswith('200')
    assert not any('session_id=' in v for v in header_values(headers, 'Set-Cookie'))


def test_favicon_ico_serves_event_icon_with_long_cache(wsgi_get):
    status, headers, body = wsgi_get('/favicon.ico')

    assert status.startswith('200')
    # CherryPy mounts its own logo at /favicon.ico when the root has no handler.
    assert header_values(headers, 'Content-Type') == ['image/png']
    assert body.startswith(b'\x89PNG')
    assert any('max-age=' in v for v in header_values(headers, 'Cache-Control'))
    assert not header_values(headers, 'Set-Cookie')


def test_static_paths_skip_oidc_token_verification(wsgi_get, monkeypatch):
    calls = []
    monkeypatch.setattr(c, 'OIDC_ENABLED', True)
    monkeypatch.setattr(cherrypy.tools.oidc, '_verify_token', lambda token: calls.append(token))

    for path in ('/static/images/favicon.png', '/static_views/styles/main.css', '/favicon.ico'):
        status, _, _ = wsgi_get(path, cookie='session_token=not.a.jwt')
        assert status.startswith('200'), path

    assert calls == []


def test_page_request_still_sets_session_cookie(wsgi_get):
    """Guard the scope of the exemption: real pages keep their session."""
    _, headers, _ = wsgi_get('/')

    assert any('session_id=' in v for v in header_values(headers, 'Set-Cookie'))
