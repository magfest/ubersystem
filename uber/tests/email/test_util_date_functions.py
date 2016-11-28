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
class Test_DateFunctions:
    @pytest.mark.parametrize("which_class, todays_date_offset, deadline_offset, days, until, expected_result", [

        # ------- days_before tests ----------

        # deadline of 10 days from now
        (days_before, 0, +10, 1,   None, False),
        (days_before, 0, +10, 10,  None, False),
        (days_before, 0, +10, 11,  None, True),
        (days_before, 0, +10, 15,  None, True),

        # deadline of 10 days ago
        (days_before, 0, -10, 1, None, False),
        (days_before, 0, -10, 9, None, False),
        (days_before, 0, -10, 10, None, False),
        (days_before, 0, -10, 11, None, False),

        # deadline of right now
        (days_before, 0, 0, 1, None, False),

        # change the date of now() and then run this:
        # days_before(days=5, deadline=now+7, until=2)()
        (days_before,  0, +7, 5, 2, False),
        (days_before, +1, +7, 5, 2, False),
        (days_before, +2, +7, 5, 2, False),
        (days_before, +3, +7, 5, 2, True),
        (days_before, +4, +7, 5, 2, True),
        (days_before, +5, +7, 5, 2, False),
        (days_before, +6, +7, 5, 2, False),
        (days_before, +7, +7, 5, 2, False),

        # ------- days_after tests ----------

        # deadline of 10 days from now
        (days_after, 0, +10, 1, None, False),
        (days_after, 0, +10, 10, None, False),
        (days_after, 0, +10, 11, None, False),
        (days_after, 0, +10, 15, None, False),

        # deadline of 10 days ago
        (days_after, 0, -10, 1,  None, True),
        (days_after, 0, -10, 9,  None, True),
        (days_after, 0, -10, 10, None, False),
        (days_after, 0, -10, 11, None, False),
        (days_after, 0, -10, 15, None, False),

        # deadline of right now
        (days_after, 0, 0, 1, None, False),

        # ---------- after -----------

        (after, 0, -10, None, None, True),
        (after, 0, -1, None, None, True),
        (after, 0, -100, None, None, True),

        (after, 0, +10, None, None, False),
        (after, 0, +1, None, None, False),
        (after, 0, +100, None, None, False),

        (after, 0, 0, None, None, False),

        # ---------- before -----------

        (before, 0, -10, None, None, False),
        (before, 0, -1, None, None, False),
        (before, 0, -100, None, None, False),

        (before, 0, +10, None, None, True),
        (before, 0, +1, None, None, True),
        (before, 0, +100, None, None, True),

        (before, 0, 0, None, None, False),
    ])
    def test_until_before(self, monkeypatch, which_class, todays_date_offset, deadline_offset, days, until, expected_result):

        # run a bunch of setup code, then run the test.

        # change today's date as an offset from September 15th
        monkeypatch.setattr(DateBase, 'now', Mock(return_value=sept_15th + timedelta(days=todays_date_offset)))

        # change deadline as an offset from September 15th
        deadline = sept_15th + timedelta(days=deadline_offset)

        kwargs = {'deadline': deadline}

        if until:
            assert which_class == days_before
            kwargs['until'] = until

        if days:
            assert which_class in [days_before, days_after]
            kwargs['days'] = days

        assert which_class in [days_before, days_after, after, before]

        # setup code is done, run the actual test:
        assert which_class(**kwargs)() == expected_result


@pytest.mark.usefixtures("set_datebase_now_to_sept_15th")
class TestDaysBefore_DateFunctions:
    def test_no_deadline_set(self):
        assert not days_before(1, None)()
        assert not before(None)()

    def test_invalid_date_range(self):
        with pytest.raises(ValueError):
            days_before(days=3, deadline=DateBase.now(), until=5)

    def test_invalid_days(self):
        with pytest.raises(ValueError):
            days_before(days=0, deadline=DateBase.now())

        with pytest.raises(ValueError):
            days_after(days=-1, deadline=DateBase.now())

    def test_representation_days_before(self):
        assert days_before(days=1, deadline=DateBase.now()).active_when == 'between 09/14 and 09/15'

    def test_representation_days_before_until(self):
        assert days_before(days=10, deadline=DateBase.now(), until=5).active_when == 'between 09/05 and 09/10'

    def test_representation_before(self):
        assert before(deadline=DateBase.now()).active_when == 'before 09/15'


@pytest.mark.usefixtures("set_datebase_now_to_sept_15th")
class TestDaysAfter_DateFunctions:
    def test_no_deadline_set(self):
        assert not days_after(1, None)()
        assert not after(None)()

    def test_invalid_days(self):
        with pytest.raises(ValueError):
            days_after(days=0, deadline=DateBase.now())

        with pytest.raises(ValueError):
            days_after(days=-1, deadline=DateBase.now())

    def test_representation_days_before(self):
        assert days_after(days=1, deadline=DateBase.now()).active_when == 'after 09/16'

    def test_representation_days_before_until(self):
        assert after(deadline=DateBase.now()).active_when == 'after 09/15'
