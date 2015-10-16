from uber.tests import *


@pytest.fixture()
def session(request):
    session = Session().session
    request.addfinalizer(session.close)
    setattr(session, 'watchlist_entry', session.watch_list(first_names='Banned, Alias, Nickname', last_name='Attendee'))
    return session


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
