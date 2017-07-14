from uber.tests import *
from uber.tests.conftest import *


@pytest.fixture
def session(request, monkeypatch):
    session = Session().session
    request.addfinalizer(session.close)
    monkeypatch.setattr(session, 'add', Mock())
    monkeypatch.setattr(session, 'delete', Mock())
    return session


def test_get_fk_from_id():
    a = Attendee()
    assert a == Email(fk_id=a.id).fk


def test_get_fk_no_id():
    assert None == Email().fk


def test_get_fk_fake_id():
    assert None == Email(fk_id="blah").fk


def test_group_name():
    assert "Test Leader" == Email(fk_id=Group(leader=Attendee(first_name="Test", last_name="Leader")).id).rcpt_name


def test_attendee_name():
    assert "Test Attendee" == Email(fk_id=Attendee(first_name="Test", last_name="Attendee").id).rcpt_name


def test_no_name():
    assert None == Email().rcpt_name


def test_group_email():
    assert "testleader@example.com" == Email(fk_id=Group(leader=Attendee(email="testleader@example.com")).id).rcpt_email


def test_attendee_email():
    assert "testattendee@example.com" == Email(fk_id=Attendee(email="testattendee@example.com").id).rcpt_email


def test_no_email():
    assert None == Email().rcpt_email


def test_email_from_dest():
    assert "testattendee@example.com" == Email(dest="testattendee@example.com").rcpt_email


def test_is_html():
    assert True == Email(body="<body").is_html


def test_is_not_html():
    assert False == Email().is_html


def test_html_from_html():
    assert "HTML Content" == Email(body="<body>HTML Content</body>").html


def test_html_from_text():
    assert "Test<br/>Content" == Email(body="Test\nContent").html
