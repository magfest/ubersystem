from uber.tests import *
from uber.tests.conftest import *


def test_get_fk_from_id():
    with Session() as session:
        a = Attendee(first_name='Regular', last_name='Attendee')
        e = Email(fk_id=a.id, model='Attendee')
        session.add(a)
        session.add(e)
        session.commit()
        assert a == e.fk


def test_get_fk_no_id():
    assert None == Email().fk


def test_get_fk_fake_id():
    assert None == Email(fk_id="blah").fk


def test_group_name(monkeypatch):
    monkeypatch.setattr(Email, 'fk', Group(leader=Attendee(first_name="Test", last_name="Leader")))
    assert "Test Leader" == Email(model='Group').rcpt_name


def test_attendee_name(monkeypatch):
    monkeypatch.setattr(Email, 'fk', Attendee(first_name="Test", last_name="Attendee"))
    assert "Test Attendee" == Email(model='Attendee').rcpt_name


def test_no_name():
    assert None == Email().rcpt_name


def test_group_email(monkeypatch):
    monkeypatch.setattr(Email, 'fk', Group(leader=Attendee(email="testleader@example.com")))
    assert "testleader@example.com" == Email(model='Group').rcpt_email


def test_attendee_email(monkeypatch):
    monkeypatch.setattr(Email, 'fk', Attendee(email="testattendee@example.com"))
    assert "testattendee@example.com" == Email(model='Attendee').rcpt_email


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
