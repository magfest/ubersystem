from uber.tests import *


@pytest.fixture()
def session(request):
    session = Session().session
    request.addfinalizer(session.close)
    setattr(session, 'watchlist_entry', session.watch_list(first_names='Banned, Alias, Nickname', last_name='Attendee'))
    return session


class TestIfBanned:
    def test_no_last_name_match(self, session):
        a = Attendee(first_name='Banned', last_name='Not')
        session.add(a)
        assert not a.banned

    def test_only_last_name_match(self, session):
        a = Attendee(first_name='NotBanned', last_name='Attendee')
        session.add(a)
        assert not a.banned

    def test_first_and_last_name_match(self, session):
        a = Attendee(first_name='Banned', last_name='Attendee')
        session.add(a)
        assert a.banned

    def test_email_and_last_name_match(self, session):
        a = Attendee(email='banned@mailinator.com', last_name='Attendee')
        session.add(a)
        assert a.banned

    def test_dob_and_last_name_match(self, session):
        a = Attendee(last_name='Attendee', birthdate=datetime.strptime('1980-07-10', '%Y-%m-%d').date())
        session.add(a)
        assert a.banned

    def test_has_watchlist_entry(self, session):
        a = Attendee(watchlist_id=session.watchlist_entry.id, first_name='Banned', last_name='Not')
        session.add(a)
        assert a.banned

    def test_no_active_entries(self, session):
        session.watchlist_entry.active = False
        a = Attendee(first_name='Banned', last_name='Attendee')
        session.add(a)
        session.commit()
        assert not a.banned

    def test_entry_assigned_elsewhere(self, session):
        a = Attendee(first_name='Banned', last_name='Attendee', watchlist_id=session.watchlist_entry.id)
        session.add(a)
        b = Attendee(first_name='Banned', last_name='Attendee')
        session.add(b)
        session.commit()
        assert not b.banned