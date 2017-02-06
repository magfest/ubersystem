from uber.tests.email.email_fixtures import *
from uber.utils import DateBase

"""
Tests for utils.py date-based functions.

These probably could go in test_utils.py, however, they're an integral part of the email subsystem,
and it's nice to be able to run all the email tests by running only the tests in this directory.
"""


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

        # is deadline of now 1 day after now?
        (days_after, 0, 0, 1, None, False),

        # is deadline of now 0 days after now?
        (days_after, 0, 0, 0, None, False),

        # ---------- days_after with days=None -----------

        (days_after, 0, -10, None, None, True),
        (days_after, 0, -1, None, None, True),
        (days_after, 0, -100, None, None, True),

        (days_after, 0, +10, None, None, False),
        (days_after, 0, +1, None, None, False),
        (days_after, 0, +100, None, None, False),

        (days_after, 0, 0, None, None, False),

        # ---------- before -----------

        (before, 0, -10, None, None, False),
        (before, 0, -1, None, None, False),
        (before, 0, -100, None, None, False),

        (before, 0, +10, None, None, True),
        (before, 0, +1, None, None, True),
        (before, 0, +100, None, None, True),

        (before, 0, 0, None, None, False),
    ])
    def test_dates(self, monkeypatch, which_class, todays_date_offset, deadline_offset, days, until, expected_result):

        # run a bunch of setup code, then run the test.

        # change today's date as an offset from September 15th
        monkeypatch.setattr(DateBase, 'now', Mock(return_value=sept_15th + timedelta(days=todays_date_offset)))

        # change deadline as an offset from September 15th
        deadline = sept_15th + timedelta(days=deadline_offset)

        kwargs = {'deadline': deadline}

        if until is not None:
            assert which_class == days_before
            kwargs['until'] = until

        if days is not None:
            assert which_class != before

        if which_class != before:
            kwargs['days'] = days

        assert which_class in [days_before, days_after, before]

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

    def test_representation_days_empty(self):
        assert days_before(days=1, deadline=None).active_when == ''

    def test_representation_days_before_until(self):
        assert days_before(days=10, deadline=DateBase.now(), until=5).active_when == 'between 09/05 and 09/10'

    def test_representation_before(self):
        assert before(deadline=DateBase.now()).active_when == 'before 09/15'

    def test_representation_before_empty(self):
        assert before(deadline=None).active_when == ''


@pytest.mark.usefixtures("set_datebase_now_to_sept_15th")
class TestDaysAfter_DateFunctions:
    def test_no_deadline_set(self):
        assert not days_after(1, None)()

    def test_invalid_days(self):
        with pytest.raises(ValueError):
            days_after(days=-1, deadline=DateBase.now())

    def test_representation_days_after(self):
        assert days_after(days=1, deadline=DateBase.now()).active_when == 'after 09/16'
