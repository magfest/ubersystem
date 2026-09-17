"""Liveness endpoint for kubelet. Proves the process can serve without any external dependency."""
import cherrypy

import uber.models
from uber.config import c
from uber.redis_session import RedisSession
from tests.web.conftest import header_values


def test_alive_returns_ok_with_no_session_cookie(wsgi_get):
    status, headers, body = wsgi_get('/alive')

    assert status.startswith('200')
    assert body == b'ok'
    assert header_values(headers, 'Content-Type')[0].startswith('text/plain')
    assert not header_values(headers, 'Set-Cookie')


def test_alive_touches_no_database_redis_or_oidc(wsgi_get, monkeypatch):
    """A restart cannot fix a slow dependency, so the probe must not depend on one."""
    def boom(*args, **kwargs):
        raise AssertionError('liveness check reached an external dependency')

    monkeypatch.setattr(uber.models, 'Session', boom)
    for name in ('_exists', '_load', '_save', 'acquire_lock'):
        monkeypatch.setattr(RedisSession, name, boom)
    monkeypatch.setattr(c, 'OIDC_ENABLED', True)
    monkeypatch.setattr(cherrypy.tools.oidc, '_verify_token', boom)

    status, _, body = wsgi_get('/alive', cookie='session_token=not.a.jwt; session_id=stale')

    assert status.startswith('200')
    assert body == b'ok'
