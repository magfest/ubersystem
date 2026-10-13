"""Liveness endpoint for kubelet.

With liveness_checks_dependencies on (the default) the probe pings Redis and
runs SELECT 1, so a pod stuck behind a dead database gets restarted. Launch
events turn it off in RAMS-Config so a slow dependency cannot restart every
pod in a wave while people are watching.
"""
import cherrypy
import pytest

import uber.models
from uber.config import c
from uber.models import Session
from uber.redis_session import RedisSession
from tests.web.conftest import header_values


def test_alive_returns_ok_with_no_session_cookie(wsgi_get):
    status, headers, body = wsgi_get('/alive')

    assert status.startswith('200')
    assert body == b'ok'
    assert header_values(headers, 'Content-Type')[0].startswith('text/plain')
    assert not header_values(headers, 'Set-Cookie')


def test_alive_queries_the_database_when_dependency_checks_are_on(wsgi_get, monkeypatch):
    monkeypatch.setattr(c, 'LIVENESS_CHECKS_DEPENDENCIES', True)
    real_connect = Session.engine.connect
    calls = []
    monkeypatch.setattr(Session.engine, 'connect', lambda *a, **kw: calls.append(1) or real_connect(*a, **kw))

    status, _, body = wsgi_get('/alive')

    assert status.startswith('200')
    assert body == b'ok'
    assert calls, 'dependency checks are on but the database was never queried'


def test_alive_returns_503_when_the_database_is_unreachable(wsgi_get, monkeypatch):
    monkeypatch.setattr(c, 'LIVENESS_CHECKS_DEPENDENCIES', True)

    def refuse(*args, **kwargs):
        raise RuntimeError('database down')
    monkeypatch.setattr(Session.engine, 'connect', refuse)

    status, _, _ = wsgi_get('/alive')

    assert status.startswith('503')


def test_alive_returns_503_when_redis_is_unreachable(wsgi_get, monkeypatch):
    monkeypatch.setattr(c, 'LIVENESS_CHECKS_DEPENDENCIES', True)

    class DeadRedis:
        def ping(self):
            raise RuntimeError('redis down')
    monkeypatch.setattr(RedisSession, 'cache', DeadRedis(), raising=False)

    status, _, _ = wsgi_get('/alive')

    assert status.startswith('503')


def test_alive_touches_nothing_when_dependency_checks_are_off(wsgi_get, monkeypatch):
    """Launch mode: a restart cannot fix a slow dependency, so the probe must not depend on one."""
    monkeypatch.setattr(c, 'LIVENESS_CHECKS_DEPENDENCIES', False)

    def boom(*args, **kwargs):
        raise AssertionError('liveness check reached an external dependency')

    monkeypatch.setattr(uber.models, 'Session', boom)
    monkeypatch.setattr(Session.engine, 'connect', boom)
    for name in ('_exists', '_load', '_save', 'acquire_lock'):
        monkeypatch.setattr(RedisSession, name, boom)
    monkeypatch.setattr(c, 'OIDC_ENABLED', True)
    monkeypatch.setattr(cherrypy.tools.oidc, '_verify_token', boom)

    status, _, body = wsgi_get('/alive', cookie='session_token=not.a.jwt; session_id=stale')

    assert status.startswith('200')
    assert body == b'ok'
