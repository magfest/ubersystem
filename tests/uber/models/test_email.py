from uber.models import Attendee, Email, Group, Session


def test_get_fk_from_id():
    with Session() as session:
        a = Attendee(first_name='Regular', last_name='Attendee')
        e = Email(fk_id=a.id, model='Attendee')
        session.add(a)
        session.add(e)
        session.commit()
        assert a == e.fk


def test_get_fk_no_id():
    assert None is Email().fk


def test_get_fk_fake_id():
    assert None is Email(fk_id="blah").fk


def test_group_email(monkeypatch):
    monkeypatch.setattr(Email, 'fk', Group(leader=Attendee(email="testleader@example.com")))
    assert "testleader@example.com" == Email(model='Group').fk_email


def test_attendee_email(monkeypatch):
    monkeypatch.setattr(Email, 'fk', Attendee(email="testattendee@example.com"))
    assert "testattendee@example.com" == Email(model='Attendee').fk_email


def test_no_email():
    assert None is Email().fk_email


def test_email_from_dest():
    assert "testattendee@example.com" == Email(to="testattendee@example.com").fk_email


def test_is_html():
    assert Email(body="<body").is_html


def test_is_not_html():
    assert not Email().is_html


def test_html_from_html():
    assert "HTML Content" == Email(body="<body>HTML Content</body>").body_as_html
    assert "HTML Content" == Email(body="<html><body>HTML Content</body></html>").body_as_html
    assert "<p>HTML Content</p>" == Email(body="<html><body><p>HTML Content</p></body></html>").body_as_html


def test_html_from_text():
    assert "Test<br>Content" == Email(body="Test\nContent").body_as_html
