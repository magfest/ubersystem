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


class TestBadgeOpts:
    def test_prereg_badge_opts_with_group(self, monkeypatch):
        monkeypatch.setattr(c, 'GROUP_PREREG_TAKEDOWN', localized_now() + timedelta(days=1))
        assert c.PREREG_BADGE_TYPES == [c.ATTENDEE_BADGE, c.PSEUDO_DEALER_BADGE, c.PSEUDO_GROUP_BADGE]

    def test_prereg_badge_opts_no_group(self):
        assert c.PREREG_BADGE_TYPES == [c.ATTENDEE_BADGE, c.PSEUDO_DEALER_BADGE]

    def test_prereg_badge_opts_with_extra(self, monkeypatch):
        monkeypatch.setattr(c, 'BADGE_TYPE_PRICES', {c.SUPPORTER_BADGE: 55})
        assert c.PREREG_BADGE_TYPES == [c.ATTENDEE_BADGE, c.PSEUDO_DEALER_BADGE, c.SUPPORTER_BADGE]

    def test_at_door_badge_opts_plain(self, monkeypatch):
        monkeypatch.setattr(c, 'ONE_DAYS_ENABLED', False)
        assert dict(c.AT_THE_DOOR_BADGE_OPTS).keys() == {c.ATTENDEE_BADGE}

    def test_at_door_badge_opts_simple_one_days(self):
        assert dict(c.AT_THE_DOOR_BADGE_OPTS).keys() == {c.ATTENDEE_BADGE, c.ONE_DAY_BADGE}

    def test_at_door_badge_opts_presold_one_days(self, monkeypatch):
        monkeypatch.setattr(c, 'PRESELL_ONE_DAYS', True)
        assert dict(c.AT_THE_DOOR_BADGE_OPTS).keys() == {c.ATTENDEE_BADGE, c.FRIDAY, c.SATURDAY, c.SUNDAY}

    def test_at_door_badge_opts_with_extra(self, monkeypatch):
        monkeypatch.setattr(c, 'BADGE_TYPE_PRICES', {c.SUPPORTER_BADGE: 55})
        assert dict(c.AT_THE_DOOR_BADGE_OPTS).keys() == {c.ATTENDEE_BADGE, c.ONE_DAY_BADGE, c.SUPPORTER_BADGE}


class TestStaffGetFood:

    def test_job_locations_with_food_prep(self):
        assert c.STAFF_GET_FOOD

    def test_job_locations_without_food_prep(self, monkeypatch):
        job_locations = dict(c.JOB_LOCATIONS)
        del job_locations[c.FOOD_PREP]
        monkeypatch.setattr(c, 'JOB_LOCATIONS', job_locations)
        assert not c.STAFF_GET_FOOD
