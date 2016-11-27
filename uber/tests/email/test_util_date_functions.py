from uber.tests.email.email_fixtures import *
from uber.utils import DateBase

"""
Tests for utils.py date-based functions.

These probably could go in test_utils.py, however, they're an integral part of the email subsystem,
and it's nice to be able to run all the email tests by running only the tests in this directory.
"""


sept_15th = localize_datetime(datetime(year=2016, month=9, day=15, hour=12, minute=30))


@pytest.fixture
def set_datebase_now_to_sept_15th(monkeypatch):

    # TODO: would love to be able to do this here:
    # monkeypatch.setattr(uber.utils, 'localized_now', Mock(return_value=fake_todays_date))
    # However, we can't override bare functions in modules and get it to propagate out to all the app code.
    # We could (and probably should) solve this in a larger sense by moving localized_now()
    # into a Util class and patching that class. For now, do it this way:
    monkeypatch.setattr(DateBase, 'now', Mock(return_value=sept_15th))


@pytest.fixture
def today_minus_10(set_datebase_now_to_sept_15th):
    return DateBase.now() - timedelta(days=10)


@pytest.fixture
def today_plus_10(set_datebase_now_to_sept_15th):
    return DateBase.now() + timedelta(days=10)


@pytest.mark.usefixtures("set_datebase_now_to_sept_15th")
class TestDaysBefore_DateFunctions:
    @pytest.mark.parametrize("todays_date_offset, deadline_offset, days, until, expected_result", [

        # deadline of 10 days from now
        (0, +10, 1,   None, False),
        (0, +10, 10,  None, False),
        (0, +10, 11,  None, True),
        (0, +10, 15,  None, True),

        # deadline of 10 days ago
        (0, -10, 1, None, False),
        (0, -10, 9, None, False),
        (0, -10, 10, None, False),
        (0, -10, 11, None, False),

        # deadline of right now
        (0, 0, 1, None, False),
    ])
    def test_until_before(self, monkeypatch, todays_date_offset, deadline_offset, days, until, expected_result):

        # change today's date as an offset from September 15th
        monkeypatch.setattr(DateBase, 'now', Mock(return_value=sept_15th + timedelta(days=todays_date_offset)))

        # change deadline as an offset from September 15th
        deadline = sept_15th + timedelta(days=deadline_offset)

        assert days_before(days=days, deadline=deadline, until=until)() == expected_result

    # -------------

    def test_no_deadline_set(self):
        assert not days_before(1, None)()

    def test_invalid_date_range(self):
        with pytest.raises(ValueError):
            days_before(days=3, deadline=DateBase.now(), until=5)

    def test_invalid_days(self):
        with pytest.raises(ValueError):
            days_before(days=0, deadline=DateBase.now())

        with pytest.raises(ValueError):
            days_after(days=-1, deadline=DateBase.now())


@pytest.mark.usefixtures("set_datebase_now_to_sept_15th")
class TestDaysAfter_DateFunctions:
    def test_after_tomorrow(self, today_plus_10):
        assert not days_after(1, today_plus_10)()
        assert not days_after(10, today_plus_10)()
        assert not days_after(11, today_plus_10)()
        assert not days_after(15, today_plus_10)()

    def test_not_after_yesterday(self, today_minus_10):
        assert days_after(1, today_minus_10)()
        assert days_after(9, today_minus_10)()
        assert not days_after(10, today_minus_10)()
        assert not days_after(11, today_minus_10)()
        assert not days_after(15, today_minus_10)()

    def test_not_after_today(self):
        assert not days_after(1, DateBase.now())()

    def test_no_deadline_set(self):
        assert not days_after(1, None)()

    def test_invalid_days(self):
        with pytest.raises(ValueError):
            days_after(days=0, deadline=DateBase.now())

        with pytest.raises(ValueError):
            days_after(days=-1, deadline=DateBase.now())