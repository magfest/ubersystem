from uber.tests import *


@pytest.fixture
def base_url(monkeypatch):
    monkeypatch.setattr(c, 'URL_BASE', 'https://server.com/uber')


def test_absolute_urls(base_url):
    assert convert_to_absolute_url('../somepage.html') == 'https://server.com/uber/somepage.html'


def test_absolute_urls_empty(base_url):
    assert convert_to_absolute_url(None) == ''
    assert convert_to_absolute_url('') == ''


def test_absolute_url_error(base_url):
    with pytest.raises(ValueError) as e_info:
        convert_to_absolute_url('..')

    with pytest.raises(ValueError) as e_info:
        convert_to_absolute_url('.')

    with pytest.raises(ValueError) as e_info:
        convert_to_absolute_url('////')
