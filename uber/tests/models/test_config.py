from uber import config
from uber.tests import *


class TestPrices:
    def test_initial_attendee(self, clear_price_bumps):
        assert 40 == c.get_attendee_price(datetime.now(UTC))

    def test_group_member(self, clear_price_bumps):
        assert 30 == c.get_group_price(datetime.now(UTC))


class TestPriceBumps:
    @pytest.fixture(autouse=True)
    def add_price_bump_day(request, monkeypatch):
        monkeypatch.setattr(c, 'PRICE_BUMPS', {(datetime.now(UTC) - timedelta(days=1)): 50})
        monkeypatch.setattr(c, 'PRICE_LIMITS', {})

    def test_after_date_price_bump(self):
        assert 50 == c.get_attendee_price(datetime.now(UTC))

    def test_before_date_no_price_bump(self):
        assert 40 == c.get_attendee_price((datetime.now(UTC) - timedelta(days=2)))

    def test_on_date_no_price_bump(self):
        assert 40 == c.get_attendee_price((datetime.now(UTC) - timedelta(days=1, hours=2)))


class TestPriceLimits:
    @pytest.fixture(autouse=True)
    def add_price_bump_limit(request, monkeypatch):
        monkeypatch.setattr(c, 'PRICE_LIMITS', {1: 50})
        monkeypatch.setattr(c, 'PRICE_BUMPS', {})

    def test_under_limit_no_price_bump(self):
        assert 40 == c.get_attendee_price()

    def test_over_limit_price_bump_before_event(self, monkeypatch):
        monkeypatch.setattr(c, 'EPOCH', localized_now() + timedelta(days=1))
        session = Session().session
        assert c.BADGES_SOLD == 0

        with request_cached_context():
            session.add(Attendee(paid=c.HAS_PAID, badge_status=c.COMPLETED_STATUS))
            session.commit()

        assert c.BADGES_SOLD == 1
        assert 50 == c.get_attendee_price()

    def test_over_limit_price_bump_during_event(self, monkeypatch):
        monkeypatch.setattr(c, 'EPOCH', localized_now() - timedelta(days=1))

        session = Session().session
        assert c.BADGES_SOLD == 0

        with request_cached_context():
            session.add(Attendee(paid=c.HAS_PAID, badge_status=c.COMPLETED_STATUS))
            session.commit()

        assert c.BADGES_SOLD == 1
        assert 40 == c.get_attendee_price()

    def test_refunded_badge_price_bump_before_event(self, monkeypatch):
        monkeypatch.setattr(c, 'EPOCH', localized_now() + timedelta(days=1))
        session = Session().session
        assert c.BADGES_SOLD == 0

        with request_cached_context():
            session.add(Attendee(paid=c.REFUNDED, badge_status=c.COMPLETED_STATUS))
            session.commit()

        assert c.BADGES_SOLD == 1
        assert 50 == c.get_attendee_price()

    def test_refunded_badge_price_bump_during_event(self, monkeypatch):
        monkeypatch.setattr(c, 'EPOCH', localized_now() - timedelta(days=1))
        session = Session().session
        assert c.BADGES_SOLD == 0

        with request_cached_context():
            session.add(Attendee(paid=c.REFUNDED, badge_status=c.COMPLETED_STATUS))
            session.commit()

        assert c.BADGES_SOLD == 1
        assert 40 == c.get_attendee_price()

    def test_invalid_badge_no_price_bump(self):
        session = Session().session
        assert c.BADGES_SOLD == 0

        with request_cached_context():
            session.add(Attendee(paid=c.HAS_PAID, badge_status=c.INVALID_STATUS))
            session.commit()

        assert c.BADGES_SOLD == 0
        assert 40 == c.get_attendee_price()

    def test_free_badge_no_price_bump(self):
        session = Session().session
        assert c.BADGES_SOLD == 0

        with request_cached_context():
            session.add(Attendee(paid=c.NEED_NOT_PAY, badge_status=c.COMPLETED_STATUS))
            session.commit()

        assert c.BADGES_SOLD == 0
        assert 40 == c.get_attendee_price()

    # todo: Test badges that are paid by group


class TestStaffGetFood:

    def test_job_locations_from_test_defaults_ini(self):
        config.Config.STAFF_GET_FOOD.fget.cache_clear()
        assert c.STAFF_GET_FOOD

    @pytest.mark.parametrize('job_locations,expected', [
        ({}, False),
        ({1: 'Job One'}, False),
        ({1: 'Job One', 2: 'Job Two'}, False),
        ({3: 'Staff Suite'}, True),
        ({1: 'Job One', 3: 'Staff Suite'}, True),
        ({1: 'Job One', 2: 'Job Two', 3: 'Staff Suite'}, True),
        ({3: 'Staff  Suite'}, True),
        ({3: ' Staff  Suite '}, True),
        ({3: '  staff  suite  '}, True),
        ({1: 'Job One', 2: 'Job Two', 3: '  STAFF  SUITE  '}, True),
        ({1: 'Job One', 2: 'Job Two', 3: '  sTAFf  sUITe  '}, True),
        ({3: 'Staffs Suite'}, False),
    ])
    def test_job_locations_monkeypatched(self, job_locations, expected, monkeypatch):
        monkeypatch.setattr(c, 'JOB_LOCATIONS', job_locations)
        config.Config.STAFF_GET_FOOD.fget.cache_clear()
        assert c.STAFF_GET_FOOD == expected
        config.Config.STAFF_GET_FOOD.fget.cache_clear()
