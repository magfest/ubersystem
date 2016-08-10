from uber.tests import *


class TestPrices:
    def test_initial_attendee(self):
        assert 40 == c.get_attendee_price(datetime.now(UTC))

    def test_group_member(self):
        assert 30 == c.get_group_price(datetime.now(UTC))


class TestPriceBumps:
    @pytest.fixture(autouse=True)
    def add_price_bump_day(request, monkeypatch):
        monkeypatch.setattr(c, 'PRICE_BUMPS', {(datetime.now(UTC) - timedelta(days=1)): 50})

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

    def test_under_limit_no_price_bump(self):
        assert 40 == c.get_attendee_price(datetime.now(UTC))

    def test_over_limit_price_bump(self):
        session = Session().session
        session.add(Attendee(paid=c.HAS_PAID, badge_status=c.COMPLETED_STATUS))
        session.commit()
        assert 50 == c.get_attendee_price(datetime.now(UTC))

    def test_refunded_badge_price_bump(self):
        session = Session().session
        session.add(Attendee(paid=c.REFUNDED, badge_status=c.COMPLETED_STATUS))
        session.commit()
        assert 50 == c.get_attendee_price(datetime.now(UTC))

    def test_invalid_badge_no_price_bump(self):
        session = Session().session
        session.add(Attendee(paid=c.HAS_PAID, badge_status=c.INVALID_STATUS))
        session.commit()
        assert 40 == c.get_attendee_price(datetime.now(UTC))

    def test_free_badge_no_price_bump(self):
        session = Session().session
        session.add(Attendee(paid=c.NEED_NOT_PAY, badge_status=c.COMPLETED_STATUS))
        session.commit()
        assert 40 == c.get_attendee_price(datetime.now(UTC))

    # todo: Test badges that are paid by group
