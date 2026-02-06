from datetime import date

import pytest
from dateutil import parser as dateparser

from uber.models import Attendee, Session, WatchList


@pytest.fixture()
def session(request):
    session = Session()
    request.addfinalizer(session.close)
    setattr(session, 'watchlist_entry', session.watch_list(first_names='Banned, Alias, Nickname', last_name='Attendee'))
    return session


@pytest.fixture()
def watchlist_session():
    with Session() as session:
        watch_list = WatchList(
            first_names='Martin, Marty, Calvin',
            last_name='McFly',
            email='88mph@example.com',
            birthdate=dateparser.parse('June 12, 1968').date())
        session.add(watch_list)
        session.commit()
        yield session
        session.delete(watch_list)


@pytest.mark.parametrize('first_names,last_name,expected', [
    ('', '', 'Unknown'),
    ('', 'Last', 'Last'),
    ('First', '', 'First'),
    ('First', 'Last', 'First Last'),
    ('First, Second', 'Last', 'First, Second Last'),
    ('First, Second, Third', 'Last', 'First, Second, Third Last'),
])
def test_full_name(first_names, last_name, expected):
    assert WatchList(first_names=first_names, last_name=last_name).full_name == expected


class TestIfBanned:
    def test_no_last_name_match(self, session):
        assert not Attendee(first_name='Banned', last_name='Not').banned

    def test_only_last_name_match(self, session):
        assert not Attendee(first_name='NotBanned', last_name='Attendee').banned

    def test_first_and_last_name_match(self, session):
        assert Attendee(first_name='Banned', last_name='Attendee').banned

    def test_email_and_last_name_match(self, session):
        assert Attendee(email='banned@mailinator.com', last_name='Attendee').banned

    def test_dob_and_last_name_match(self, session):
        assert Attendee(last_name='Attendee', birthdate=date(1980, 7, 10)).banned

    def test_has_watchlist_entry(self, session):
        assert Attendee(watch_list=session.watchlist_entry, first_name='Banned', last_name='Not').banned

    def test_no_active_entries(self, session):
        session.watchlist_entry.active = False
        session.commit()
        assert not Attendee(first_name='Banned', last_name='Attendee').banned


class TestGuessWatchListEntry:
    @pytest.mark.parametrize('attendee_attrs', [
        dict(last_name='MCFLY', first_name='MARTY'),
        dict(last_name='MCFLY', first_name='MARTIN'),
        dict(last_name='MCFLY', first_name='CALVIN'),
        dict(last_name='MCFLY', first_name='MARTIN, MARTY, CALVIN'),
        dict(
            last_name='MCFLY',
            first_name='ANONYMOUS',
            email='88MPH@EXAMPLE.COM'),
        dict(
            last_name='MCFLY',
            first_name='ANONYMOUS',
            email='88MPH@EXAMPLE.COM',
            birthdate=None),
        dict(
            last_name='MCFLY',
            first_name='ANONYMOUS',
            email='88MPH@EXAMPLE.COM',
            birthdate=''),
        dict(
            last_name='MCFLY',
            first_name='ANONYMOUS',
            email='88MPH@EXAMPLE.COM',
            birthdate='INVALID_DATE'),
        dict(
            last_name='MCFLY',
            first_name='ANONYMOUS',
            birthdate=dateparser.parse('June 12, 1968').date()),
        dict(
            last_name='MCFLY',
            first_name='ANONYMOUS',
            birthdate=dateparser.parse('June 12, 1968')),
        dict(
            last_name='MCFLY',
            first_name='ANONYMOUS',
            birthdate='June 12, 1968')
    ])
    def test_partial_match(self, attendee_attrs, watchlist_session):
        attendee = Attendee(**attendee_attrs)
        entries = watchlist_session.guess_attendee_watchentry(attendee)
        assert len(entries) == 1
        assert entries[0].first_names == 'Martin, Marty, Calvin'

    @pytest.mark.parametrize('attendee_attrs', [
        dict(last_name='McFly', first_name='Anonymous'),
        dict(last_name='McFly', first_name='Anonymous', birthdate=None),
        dict(last_name='McFly', first_name='Anonymous', birthdate=''),
        dict(
            last_name='McFly',
            first_name='Anonymous',
            birthdate='INVALID_DATE'),
        dict(
            last_name='McFly',
            first_name='Anonymous',
            email='outatime@example.com'),
        dict(
            last_name='McFly',
            first_name='Anonymous',
            birthdate=dateparser.parse('June 13, 1968').date()),
        dict(
            last_name='Smith',
            first_name='Marty',
            email='88mph@example.com',
            birthdate=dateparser.parse('June 12, 1968').date()),
    ])
    def test_no_match(self, attendee_attrs, watchlist_session):
        attendee = Attendee(**attendee_attrs)
        entries = watchlist_session.guess_attendee_watchentry(attendee)
        assert len(entries) == 0
