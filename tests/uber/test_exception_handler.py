
import cherrypy
import pytest
from cherrypy._cpreqbody import Part
from mock import Mock

from uber import server
from uber.models import AdminAccount
from uber.utils import localized_now


class MockPart(Part):
    # fake a cherrypy attachment, make it able to create without constructor
    def __init__(self):
        pass


class TestExceptionHandler:
    @pytest.fixture(autouse=True)
    def setup_cherrypy_fake_env(self, monkeypatch):
        monkeypatch.setattr(AdminAccount, 'admin_name', Mock(return_value='Bruce'))
        monkeypatch.setattr(cherrypy.request, 'request_line', "/uber/location3/hello")
        monkeypatch.setattr(cherrypy.request, 'params', {
            'id': '32',
            'action': 'reload',
            'thing': 3,  # use a non-string
            'attachment': MockPart(),  # add fake attachment based on cherrypy's Part() class, make sure we handle OK
        })
        monkeypatch.setattr(cherrypy, 'session', {'session_id': '762876'})
        headers = [
            ('Content-Type', 'text/html'),
            ('Server', 'Null CherryPy'),
            ('Date', localized_now()),
            ('Content-Length', '80'),
        ]
        monkeypatch.setattr(cherrypy.request, 'header_list', headers)

    def test_exception_handler(self):
        for expected in ['Request', 'text/html', 'reload', 'Bruce', 'session_id', 'Content-Length']:
            assert expected in server.get_verbose_request_context()
