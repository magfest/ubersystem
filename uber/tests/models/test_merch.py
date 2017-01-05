from uber.tests import *


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


class TestMerchAttrs:
    def test_paid_for_a_swag_shirt(self):
        assert not Attendee(amount_extra=c.SHIRT_LEVEL - 1).paid_for_a_swag_shirt
        assert Attendee(amount_extra=c.SHIRT_LEVEL).paid_for_a_swag_shirt
        assert Attendee(amount_extra=c.SHIRT_LEVEL + 1).paid_for_a_swag_shirt

    def test_volunteer_swag_shirt_eligible(self):
        assert not Attendee().volunteer_swag_shirt_eligible
        assert Attendee(ribbon=c.VOLUNTEER_RIBBON).volunteer_swag_shirt_eligible
        assert not Attendee(ribbon=c.VOLUNTEER_RIBBON, badge_type=c.STAFF_BADGE).volunteer_swag_shirt_eligible

    def test_volunteer_swag_shirt_earned(self, monkeypatch):
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
            monkeypatch.setattr(Attendee, 'volunteer_swag_shirt_eligible', eligible)
            assert expected == Attendee(nonshift_hours=worked_hours).volunteer_swag_shirt_earned

    def test_num_swag_shirts_owed(self, monkeypatch):
        for paid, volunteer, owed in [
                (False, False, 0),
                (False, True, 1),
                (True, False, 1),
                (True, True, 2)]:
            monkeypatch.setattr(Attendee, 'paid_for_a_swag_shirt', paid)
            monkeypatch.setattr(Attendee, 'volunteer_swag_shirt_eligible', volunteer)
            assert owed == Attendee().num_swag_shirts_owed

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
            monkeypatch.setattr(Attendee, 'num_swag_shirts_owed', swag)
            assert expected == Attendee().gets_any_kind_of_shirt


class TestMerch:
    @pytest.fixture(autouse=True)
    def defaults(self, monkeypatch):
        for attr in ['volunteer_swag_shirt_eligible', 'paid_for_a_swag_shirt', 'volunteer_swag_shirt_earned', 'gets_staff_shirt']:
            monkeypatch.setattr(Attendee, attr, False)

    @pytest.fixture
    def paid_for_a_swag_shirt(self, monkeypatch):
        setattr(Attendee, 'paid_for_a_swag_shirt', True)

    @pytest.fixture
    def volunteer_swag_shirt_eligible(self, monkeypatch):
        monkeypatch.setattr(Attendee, 'volunteer_swag_shirt_eligible', True)

    @pytest.fixture
    def volunteer_swag_shirt_earned(self, monkeypatch):
        setattr(Attendee, 'volunteer_swag_shirt_earned', True)

    @pytest.fixture
    def gets_staff_shirt(self, monkeypatch):
        setattr(Attendee, 'gets_staff_shirt', True)

    def test_extra_merch(self):
        assert 'foo' == Attendee(extra_merch='foo').merch

    def test_normal_kickins(self, monkeypatch):
        monkeypatch.setattr(Attendee, 'donation_swag', ['some', 'stuff'])
        assert 'some and stuff' == Attendee().merch

    def test_comma_and(self, monkeypatch):
        monkeypatch.setattr(Attendee, 'donation_swag', ['some', 'stuff'])
        assert 'some, stuff, and more' == Attendee(extra_merch='more').merch

    def test_info_packet(self):
        assert 'Staffer Info Packet' == Attendee(staffing=True).merch

    def test_staff_shirts(self, gets_staff_shirt):
        assert '3 Staff Shirts' == Attendee().merch

    def test_volunteer(self, volunteer_swag_shirt_eligible):
        assert 'RedShirt' in Attendee().merch and 'will be reported' in Attendee().merch

    def test_volunteer_worked(self, volunteer_swag_shirt_eligible, volunteer_swag_shirt_earned):
        assert 'RedShirt' == Attendee().merch

    def test_two_swag_shirts(self, volunteer_swag_shirt_eligible, volunteer_swag_shirt_earned, paid_for_a_swag_shirt):
        assert 'RedShirt and a 2nd RedShirt' == Attendee(amount_extra=c.SHIRT_LEVEL).merch
