"""Request-pipeline tests that drive the mounted CherryPy app over WSGI.

No socket and no browser: `cherrypy.tree` is a WSGI callable, so a request built
here runs every hook and tool exactly as production does. Importing `uber.server`
mounts the app and loads the configured plugins, which needs the container's
config and Redis. Run inside the `magprime-python` container:

    docker exec -w /app magprime-python python -m pytest tests/web -q
"""
import io
import sys

import cherrypy
import pytest


@pytest.fixture(scope='session')
def app():
    import uber.server  # noqa: F401  mounts Root and loads plugins as a side effect
    cherrypy.log.screen = False
    return cherrypy.tree


@pytest.fixture
def wsgi_get(app):
    """Return a callable that GETs a path and yields (status, headers, body)."""
    def _get(path, cookie=None):
        environ = {
            'REQUEST_METHOD': 'GET', 'PATH_INFO': path, 'SCRIPT_NAME': '', 'QUERY_STRING': '',
            'SERVER_NAME': 'localhost', 'SERVER_PORT': '80', 'SERVER_PROTOCOL': 'HTTP/1.1',
            'HTTP_HOST': 'localhost', 'REQUEST_URI': path, 'REMOTE_ADDR': '127.0.0.1', 'REMOTE_PORT': '1',
            'wsgi.url_scheme': 'http', 'wsgi.input': io.BytesIO(b''), 'wsgi.errors': sys.stderr,
            'wsgi.version': (1, 0), 'wsgi.multithread': False, 'wsgi.multiprocess': False,
            'wsgi.run_once': False,
        }
        if cookie:
            environ['HTTP_COOKIE'] = cookie
        captured = {}

        def start_response(status, headers, exc_info=None):
            captured['status'] = status
            captured['headers'] = headers

        body = b''.join(app(environ, start_response))
        return captured['status'], captured['headers'], body
    return _get


def header_values(headers, name):
    return [value for key, value in headers if key.lower() == name.lower()]
