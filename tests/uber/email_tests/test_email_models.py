"""
Tests for uber.models.email model classes.
"""

import pytest

from uber.config import c
from uber.models import Attendee, AutomatedEmail, Email, Group, Session

from tests.uber.email_tests.email_fixtures import ACTIVE_WHEN, ACTIVE_WHEN_LABELS, NOW, TOMORROW, YESTERDAY
from tests.uber.email_tests.email_fixtures import *  # noqa: F401,F403


@pytest.fixture
def set_email_fk_group(monkeypatch):
    monkeypatch.setattr(Email, 'fk', Group(leader=Attendee(email='testleader@example.com')))


@pytest.fixture
def set_email_fk_attendee(monkeypatch):
    monkeypatch.setattr(Email, 'fk', Attendee(email='testattendee@example.com'))


class TestAutomatedEmail(object):

    def _assert_all_active(self, emails, expected_count):
        assert len(emails) == expected_count
        for email in emails:
            assert email.active_when_label == ACTIVE_WHEN_LABELS[email.ordinal]
            assert all(when() for when in ACTIVE_WHEN[email.ordinal])

    @pytest.mark.parametrize('body,format,expected', [
        ('<body>HTML Content</body>', 'txt', '<body>HTML Content</body>'),
        ('<html><body>HTML Content</body></html>', 'txt', '<html><body>HTML Content</body></html>'),
        ('<html><body><p>HTML Content</p></body></html>', 'txt', '<html><body><p>HTML Content</p></body></html>'),
        ('Test\nContent', 'txt', 'Test<br>Content'),
        ('<body>HTML Content</body>', 'html', 'HTML Content'),
        ('<html><body>HTML Content</body></html>', 'html', 'HTML Content'),
        ('<html><body><p>HTML Content</p></body></html>', 'html', '<p>HTML Content</p>'),
        ('Test\nContent', 'html', 'Test\nContent'),
    ])
    def test_body_as_html(self, body, format, expected):
        assert AutomatedEmail(body=body, format=format).body_as_html == expected

    @pytest.mark.parametrize('model,expected', [
        pytest.param('', None),
        pytest.param('n/a', None),
        pytest.param('INVALID', None, marks=pytest.mark.xfail(raises=ValueError)),
        ('Attendee', Attendee),
        ('Group', Group),
    ])
    def test_model_class(self, model, expected):
        assert AutomatedEmail(model=model).model_class is expected

    def test_reconcile_fixtures(self, automated_email_fixtures):
        assert len(AutomatedEmail._fixtures) == 8
        with Session() as session:
            assert session.query(AutomatedEmail).count() == 8
            for automated_email in session.query(AutomatedEmail):
                assert automated_email.subject == 'CoolCon9000 2016 Jan 2016 {{ attendee.full_name }}'
                assert automated_email.active_when_label == ACTIVE_WHEN_LABELS[automated_email.ordinal]

    @pytest.mark.parametrize('at_the_con,post_con,expected', [
        (True, True, 0),
        (True, False, 0),
        (False, True, 0),
        (False, False, 8),
    ])
    def test_filters_for_allowed(self, automated_email_fixtures, monkeypatch, at_the_con, post_con, expected):
        monkeypatch.setattr(c, 'AT_THE_CON', at_the_con)
        monkeypatch.setattr(c, 'POST_CON', post_con)
        with Session() as session:
            assert session.query(AutomatedEmail).filter(*AutomatedEmail.filters_for_allowed).count() == expected
            for automated_email in session.query(AutomatedEmail):
                automated_email.allow_at_the_con = at_the_con
                automated_email.allow_post_con = post_con
            session.flush()
            assert session.query(AutomatedEmail).filter(*AutomatedEmail.filters_for_allowed).count() == 8

    @pytest.mark.parametrize('at_the_con,post_con,expected', [
        (True, True, 0),
        (True, False, 0),
        (False, True, 0),
        (False, False, 4),
    ])
    def test_filters_for_active(self, automated_email_fixtures, monkeypatch, fixed_localized_now,
                                at_the_con, post_con, expected):
        monkeypatch.setattr(c, 'AT_THE_CON', at_the_con)
        monkeypatch.setattr(c, 'POST_CON', post_con)
        with Session() as session:
            emails = session.query(AutomatedEmail).filter(*AutomatedEmail.filters_for_active).all()
            self._assert_all_active(emails, expected)
            for automated_email in session.query(AutomatedEmail):
                automated_email.allow_at_the_con = at_the_con
                automated_email.allow_post_con = post_con
            session.flush()
            emails = session.query(AutomatedEmail).filter(*AutomatedEmail.filters_for_active).all()
            self._assert_all_active(emails, 4)

    def test_filters_for_approvable(self, automated_email_fixtures, fixed_localized_now):
        with Session() as session:
            assert session.query(AutomatedEmail).filter(*AutomatedEmail.filters_for_approvable).count() == 0
            for automated_email in session.query(AutomatedEmail):
                automated_email.needs_approval = True
            session.flush()
            assert session.query(AutomatedEmail).filter(*AutomatedEmail.filters_for_approvable).count() == 6

    @pytest.mark.parametrize('needs_approval,unapproved_count,at_the_con,post_con,expected', [
        (True, 2, True, True, 4),
        (True, 0, True, False, 0),
        (False, 2, False, True, 0),
        (True, 2, False, False, 4),
        (False, 2, False, False, 0),
        (True, 0, False, False, 0),
        (False, 0, False, False, 0),
    ])
    def test_filters_for_pending(self, automated_email_fixtures, monkeypatch, fixed_localized_now,
                                 needs_approval, unapproved_count, at_the_con, post_con, expected):
        monkeypatch.setattr(c, 'AT_THE_CON', at_the_con)
        monkeypatch.setattr(c, 'POST_CON', post_con)
        with Session() as session:
            assert session.query(AutomatedEmail).filter(*AutomatedEmail.filters_for_pending).count() == 0
            for automated_email in session.query(AutomatedEmail):
                automated_email.needs_approval = needs_approval
                automated_email.unapproved_count = unapproved_count
                automated_email.allow_at_the_con = at_the_con
                automated_email.allow_post_con = post_con
            session.flush()
            emails = session.query(AutomatedEmail).filter(*AutomatedEmail.filters_for_pending).all()
            self._assert_all_active(emails, expected)

    @pytest.mark.parametrize('active_after,active_before,expected', [
        (None, None, ''),
        (None, NOW, 'before Aug 10'),
        (NOW, None, 'after Aug 10'),
        (YESTERDAY, TOMORROW, 'between Aug 9 and Aug 11'),
    ])
    def test_active_when_label(self, active_after, active_before, expected):
        assert AutomatedEmail(active_after=active_after, active_before=active_before).active_when_label == expected

    def test_emails_by_fk_id(self, send_emails_for_automated_email_fixture):
        with Session() as session:
            automated_email = session.query(AutomatedEmail).one()
            assert len(automated_email.emails_by_fk_id) == 5
            assert sorted(list(automated_email.emails_by_fk_id.keys())) == [
                '00000000-0000-0000-0000-000000000000',
                '00000000-0000-0000-0000-000000000001',
                '00000000-0000-0000-0000-000000000002',
                '00000000-0000-0000-0000-000000000003',
                '00000000-0000-0000-0000-000000000004']
            for fk_id, emails in automated_email.emails_by_fk_id.items():
                assert len(emails) == 2

    def test_email_count(self, send_emails_for_automated_email_fixture):
        with Session() as session:
            automated_email = session.query(AutomatedEmail).one()
            assert automated_email.email_count == 10
            assert len(automated_email.emails) == 10

    def test_email_count_expression(self):
        with Session() as session:
            session.query(AutomatedEmail.email_count).scalar() == 10

    @pytest.mark.parametrize('ident', [None, '', 'INVALID'])
    def test_fixture_is_none(self, ident):
        assert AutomatedEmail(ident=ident).fixture is None

    def test_ordinal(self, automated_email_fixtures):
        with Session() as session:
            for ordinal, (ident, fixture) in enumerate(AutomatedEmail._fixtures.items()):
                automated_email = session.query(AutomatedEmail).filter_by(ident=ident).one()
                assert automated_email.ordinal == ordinal

    @pytest.mark.parametrize('format,expected', [
        ('txt', False),
        ('text', False),
        ('html', True),
    ])
    def test_is_html(self, format, expected):
        assert AutomatedEmail(format=format).is_html == expected

    def test_render(self, automated_email_fixture):
        with Session() as session:
            email = session.query(AutomatedEmail).one()
            assert email.render_body(Attendee(first_name='A', last_name='Z')) == 'A Z\nCoolCon9000\nEXTRA DATA'
            assert email.render_subject(Attendee(first_name='A', last_name='Z')) == 'CoolCon9000 2016 Jan 2016 A Z'

    def test_would_send_if_approved(self, automated_email_fixture):
        with Session() as session:
            email = session.query(AutomatedEmail).one()

            attendee = Attendee(first_name='A', last_name='Z', email='')
            assert not email.would_send_if_approved(attendee)

            attendee.email = 'az@example.com'
            assert email.would_send_if_approved(attendee)

            email.fixture.filter = lambda x: False
            assert not email.would_send_if_approved(attendee)

            email.fixture.filter = lambda x: True
            assert email.would_send_if_approved(attendee)


class TestEmail(object):

    @pytest.mark.parametrize('body,expected', [
        ('<body>HTML Content</body>', 'HTML Content'),
        ('<html><body>HTML Content</body></html>', 'HTML Content'),
        ('<html><body><p>HTML Content</p></body></html>', '<p>HTML Content</p>'),
        ('Test\nContent', 'Test<br>Content'),
    ])
    def test_body_as_html(self, body, expected):
        assert Email(body=body).body_as_html == expected

    @pytest.mark.parametrize('model,expected', [
        pytest.param('', None),
        pytest.param('n/a', None),
        pytest.param('INVALID', None, marks=pytest.mark.xfail(raises=ValueError)),
        ('Attendee', Attendee),
        ('Group', Group),
    ])
    def test_model_class(self, model, expected):
        assert Email(model=model).model_class is expected

    def test_fk_from_database(self):
        with Session() as session:
            a = Attendee(first_name='Regular', last_name='Attendee')
            e = Email(fk_id=a.id, model='Attendee')
            session.add(a)
            session.add(e)
            session.commit()
            assert a == e.fk

    def test_fk_no_id(self):
        assert None is Email().fk

    def test_fk_invalid_id(self):
        assert None is Email(fk_id='invalid').fk

    def test_fk_email_with_attendee(self, set_email_fk_attendee):
        assert 'testattendee@example.com' == Email(model='Attendee').fk_email

    def test_fk_email_with_group(self, set_email_fk_group):
        assert 'testleader@example.com' == Email(model='Group').fk_email

    @pytest.mark.parametrize('kwargs,expected', [
        ({}, ''),
        ({'to': 'testattendee@example.com'}, 'testattendee@example.com')
    ])
    def test_fk_email(self, kwargs, expected):
        assert expected == Email(**kwargs).fk_email

    @pytest.mark.parametrize('body,expected', [
        ('', False),
        ('Some non-html text', False),
        ('<body', True),
        ('<body>', True),
        ('<body class="test">', True),
        ('<html>\n<body class="test"></body>\n</html>', True),
        ('<html>\n<body class="test">\n<p>test</p>\n</body>\n</html>', True),
    ])
    def test_is_html(self, body, expected):
        assert Email(body=body).is_html == expected
