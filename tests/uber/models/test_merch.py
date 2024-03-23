import pytest

from uber.config import c
from uber.models import Attendee


@pytest.fixture(autouse=True)
def donation_tier_fixture(monkeypatch):
    shirt_level = 25
    supporter_level = 85

    monkeypatch.setattr(c, 'DONATION_TIERS', {
        0: 'No thanks',
        shirt_level: 'RedShirt',
        55: 'Cruiser',
        supporter_level: 'Supporter Package - Battleship',
        205: 'Aircraft Carrier',
    })

    # [integer_enums]
    monkeypatch.setattr(c, 'SHIRT_LEVEL', shirt_level)
    monkeypatch.setattr(c, 'SUPPORTER_LEVEL', supporter_level)

    monkeypatch.setattr(c, 'SHIRTS_PER_STAFFER', 3)
    monkeypatch.setattr(c, 'STAFF_EVENT_SHIRT_OPTS', '[]')


class TestMerchAttrs:
    def test_paid_for_a_shirt(self):
        assert not Attendee(amount_extra=c.SHIRT_LEVEL - 1).paid_for_a_shirt
        assert Attendee(amount_extra=c.SHIRT_LEVEL).paid_for_a_shirt
        assert Attendee(amount_extra=c.SHIRT_LEVEL + 1).paid_for_a_shirt

    def test_volunteer_event_shirt_eligible(self):
        assert not Attendee().volunteer_event_shirt_eligible
        assert Attendee(ribbon=c.VOLUNTEER_RIBBON).volunteer_event_shirt_eligible
        assert not Attendee(badge_type=c.STAFF_BADGE).volunteer_event_shirt_eligible
        assert not Attendee(ribbon=c.VOLUNTEER_RIBBON, badge_type=c.STAFF_BADGE).volunteer_event_shirt_eligible

    def test_staff_event_shirt_eligible(self, monkeypatch):
        monkeypatch.setattr(c, 'STAFF_EVENT_SHIRT_OPTS', 1)
        assert Attendee(badge_type=c.STAFF_BADGE).volunteer_event_shirt_eligible
        assert Attendee(badge_type=c.STAFF_BADGE, ribbon=c.VOLUNTEER_RIBBON).volunteer_event_shirt_eligible

    def test_volunteer_event_shirt_earned(self, monkeypatch):
        for (eligible, takes_shifts, worked_hours), expected in {
                (False, False, 5): False,
                (False, False, 6): False,
                (False, True, 5): False,
                (False, True, 6): False,
                (True, False, 5): True,
                (True, True, 5): False,
                (True, False, 6): True,
                (True, True, 6): True}.items():
            monkeypatch.setattr(Attendee, 'takes_shifts', takes_shifts)
            monkeypatch.setattr(Attendee, 'volunteer_event_shirt_eligible', eligible)
            assert expected == Attendee(nonshift_hours=worked_hours).volunteer_event_shirt_earned

    def test_num_event_shirts_owed(self, monkeypatch):
        for paid, volunteer, replacement, owed in [
                (False, False, 0, 0),
                (False, True, 0, 1),
                (True, False, 0, 1),
                (True, True, 0, 2),
                (False, False, 1, 1),
                (False, True, 1, 2),
                (True, False, 1, 2),
                (True, True, 1, 3)]:
            monkeypatch.setattr(Attendee, 'paid_for_a_shirt', paid)
            monkeypatch.setattr(Attendee, 'volunteer_event_shirt_eligible', volunteer)
            monkeypatch.setattr(Attendee, 'num_event_shirts', replacement)
            assert owed == Attendee().num_event_shirts_owed

    def test_num_staff_shirts_owed(self, monkeypatch):
        for gets_shirt, replacement, expected in [
                (False, 0, 0),
                (False, 1, 0),
                (True, 0, 3),
                (True, 1, 2),
                (True, 2, 1)]:
            monkeypatch.setattr(Attendee, 'gets_staff_shirt', gets_shirt)
            monkeypatch.setattr(Attendee, 'num_event_shirts', replacement)
            assert expected == Attendee().num_staff_shirts_owed

    def test_gets_staff_shirt(self):
        assert not Attendee().gets_staff_shirt
        assert Attendee(badge_type=c.STAFF_BADGE).gets_staff_shirt

    def test_gets_any_kind_of_shirt(self, monkeypatch):
        for staff, swag, expected in [
                (False, 0, False),
                (False, 1, True),
                (True, 0, True),
                (True, 1, True)]:
            monkeypatch.setattr(Attendee, 'gets_staff_shirt', staff)
            monkeypatch.setattr(Attendee, 'num_event_shirts_owed', swag)
            assert expected == Attendee().gets_any_kind_of_shirt

    def test_shirt_info_marked_event_shirtless(self, monkeypatch):
        monkeypatch.setattr(c, 'SHIRTS_PER_STAFFER', 0)
        for marked, gets_shirt, expected in [
                (False, False, False),
                (False, True, False),
                (True, False, True),
                (True, True, True)]:
            monkeypatch.setattr(Attendee, 'shirt_size_marked', marked)
            monkeypatch.setattr(Attendee, 'gets_staff_shirt', gets_shirt)
            assert expected == Attendee(second_shirt=c.UNKNOWN).shirt_info_marked

    def test_shirt_info_marked_before_deadline(self, monkeypatch):
        monkeypatch.setattr(c, 'AFTER_SHIRT_DEADLINE', False)
        for marked, gets_shirt, second_shirt, expected in [
                (False, False, c.UNKNOWN, False),
                (False, False, c.TWO_STAFF_SHIRTS, False),
                (False, True, c.UNKNOWN, False),
                (False, True, c.TWO_STAFF_SHIRTS, False),
                (True, False, c.UNKNOWN, True),
                (True, False, c.TWO_STAFF_SHIRTS, True),
                (True, True, c.UNKNOWN, False),
                (True, True, c.TWO_STAFF_SHIRTS, True)]:
            monkeypatch.setattr(Attendee, 'shirt_size_marked', marked)
            monkeypatch.setattr(Attendee, 'gets_staff_shirt', gets_shirt)
            assert expected == Attendee(second_shirt=second_shirt).shirt_info_marked

    def test_shirt_info_marked_after_deadline(self, monkeypatch):
        monkeypatch.setattr(c, 'AFTER_SHIRT_DEADLINE', True)
        for marked, gets_shirt, second_shirt, expected in [
                (False, False, c.UNKNOWN, False),
                (False, False, c.TWO_STAFF_SHIRTS, False),
                (False, True, c.UNKNOWN, False),
                (False, True, c.TWO_STAFF_SHIRTS, False),
                (True, False, c.UNKNOWN, True),
                (True, False, c.TWO_STAFF_SHIRTS, True),
                (True, True, c.UNKNOWN, True),
                (True, True, c.TWO_STAFF_SHIRTS, True)]:
            monkeypatch.setattr(Attendee, 'shirt_size_marked', marked)
            monkeypatch.setattr(Attendee, 'gets_staff_shirt', gets_shirt)
            assert expected == Attendee(second_shirt=second_shirt).shirt_info_marked


class TestMerch:
    @pytest.fixture(autouse=True)
    def defaults(self, monkeypatch):
        monkeypatch.setattr(c, 'SEPARATE_STAFF_MERCH', True)
        attrs = [
            'volunteer_event_shirt_eligible',
            'paid_for_a_shirt',
            'volunteer_event_shirt_earned',
            'gets_staff_shirt']

        for attr in attrs:
            monkeypatch.setattr(Attendee, attr, False)

    @pytest.fixture
    def paid_for_a_shirt(self, monkeypatch):
        setattr(Attendee, 'paid_for_a_shirt', True)

    @pytest.fixture
    def volunteer_event_shirt_eligible(self, monkeypatch):
        monkeypatch.setattr(Attendee, 'volunteer_event_shirt_eligible', True)

    @pytest.fixture
    def volunteer_event_shirt_earned(self, monkeypatch):
        setattr(Attendee, 'volunteer_event_shirt_earned', True)

    @pytest.fixture
    def gets_staff_shirt(self, monkeypatch):
        setattr(Attendee, 'gets_staff_shirt', True)

    def test_extra_merch(self):
        assert 'foo' == Attendee(extra_merch='foo').merch
        assert 'more' == Attendee(extra_merch='more').merch

    def test_normal_kickins(self, monkeypatch):
        monkeypatch.setattr(Attendee, 'merch_items', ['some', 'stuff'])
        assert 'some and stuff' == Attendee().merch

    def test_nested_kickins(self, monkeypatch):
        monkeypatch.setattr(Attendee, 'merch_items', ['some', ['mildly', 'nested'], 'stuff'])
        assert 'some and stuff' == Attendee().merch

    def test_comma_and(self, monkeypatch):
        monkeypatch.setattr(Attendee, 'merch_items', ['some', 'stuff', 'more'])
        assert 'some, stuff, and more' == Attendee().merch

    def test_info_packet(self):
        assert '' == Attendee(staffing=True).merch
        assert 'Staffer Info Packet' == Attendee(staffing=True).staff_merch

    def test_staff_shirts(self, gets_staff_shirt):
        assert 'tshirt' in Attendee().merch
        assert '2 Staff Shirts' in Attendee().staff_merch

        a = Attendee(second_shirt=c.TWO_STAFF_SHIRTS)
        assert '' == a.merch
        assert '3 Staff Shirts' in a.staff_merch

    def test_volunteer(self, volunteer_event_shirt_eligible):
        assert 'tshirt' in Attendee().merch and 'will be reported' in Attendee().merch

    def test_paid_volunteer(self, paid_for_a_shirt, volunteer_event_shirt_eligible):
        assert 'RedShirt' in Attendee(amount_extra=c.SHIRT_LEVEL).merch
        assert '2nd tshirt' in Attendee(amount_extra=c.SHIRT_LEVEL).merch

    def test_volunteer_worked(self, volunteer_event_shirt_eligible, volunteer_event_shirt_earned):
        assert 'tshirt' in Attendee().merch

    def test_two_swag_shirts(self, volunteer_event_shirt_eligible, volunteer_event_shirt_earned, paid_for_a_shirt):
        assert 'RedShirt and a 2nd tshirt' == Attendee(amount_extra=c.SHIRT_LEVEL).merch
