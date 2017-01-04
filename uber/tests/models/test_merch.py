from uber.tests import *


"""
Scenario: A staffer who has not kicked in extra is picking up their merch
Current behavior: uber reports that the staffer should receive a t-shirt bundle
Desired behavior: uber reports that the staffer should receive two staff t-shirts, and a staffer info packet

Scenario: A staffer who has kicked in for the t-shirt bundle is picking up their merch
Current behavior: uber reports that the staffer should receive a t-shirt bundle, and a 2nd t-shirt bundle
Desired behavior: uber reports that the staffer should receive an attendee t-shirt bundle, two staff t-shirts, and a staffer info packet

Scenario: A staffer who has kicked in for the I <3 magfest is picking up their merch
Current behavior: uber reports that the staffer should receive a t-shirt bundle, i <3 magfest, and a 2nd t-shirt bundle
Desired behavior: uber reports that the staffer should receive an attendee t-shirt bundle, i <3 magfest, two staff t-shirts, and a staffer info packet
"""


class TestMerch:
    @pytest.fixture(autouse=True)
    def donation_tier_fixture(self, monkeypatch):
        shirt_level = 25
        supporter_level = 85

        monkeypatch.setattr(c, 'DONATION_TIERS', {
            0: 'No thanks',
            shirt_level: 'RedShirt T-Shirt Bundle',
            55: 'Cruiser',
            supporter_level: 'Supporter Package - Battleship',
            205: 'Aircraft Carrier',
        })

        # [integer_enums]
        monkeypatch.setattr(c, 'SHIRT_LEVEL', shirt_level)
        monkeypatch.setattr(c, 'SUPPORTER_LEVEL', supporter_level)

        monkeypatch.setattr(c, 'SHIRTS_PER_STAFFER', 3)

        monkeypatch.setattr(c, 'get_attendee_price', Mock(return_value=20))

    def test_merch_setup(self):
        assert 20 == Attendee(amount_extra=0).total_cost

    def test_merch_setup(self):
        att = Attendee(amount_extra=0)

    # Scenario: A staffer who has not kicked in extra is picking up their merch
    # Current behavior: uber reports that the staffer should receive a t-shirt bundle
    # Desired behavior: uber reports that the staffer should receive two staff t-shirts, and a staffer info packet
    def test_staff_shirt_merch(self):
        staffer = Attendee(badge_type=c.STAFF_BADGE)
        staffer._staffing_adjustments()

        assert 'RedShirt T-Shirt Bundle' not in staffer.merch

        assert '3 Staff Shirts' in staffer.merch
        assert 'Staffer Info Packet' in staffer.merch

    def test_staff_shirt_properties(self):
        staffer = Attendee(badge_type=c.STAFF_BADGE)
        staffer._staffing_adjustments()

        assert staffer.gets_staff_shirt
        assert staffer.gets_any_kind_of_shirt
        assert not staffer.paid_for_a_swag_shirt
        assert not staffer.eligible_for_free_swag_shirt

    # att = Attendee(amount_extra=c.SHIRT_LEVEL) TODO

    def test_volunteer_has_enough_hours_gets_swag_shirt(self):
        volunteer = Attendee(ribbon=c.VOLUNTEER_RIBBON)
        volunteer._staffing_adjustments()

        assert 'RedShirt T-Shirt Bundle' in volunteer.merch

    # ----------------------------------------------------------------

    def test_basics(self):
        # TODO: needs refactoring.
        assert not Attendee().paid_for_a_swag_shirt
        assert Attendee(amount_extra=c.SHIRT_LEVEL).paid_for_a_swag_shirt
        assert Attendee(ribbon=c.DEPT_HEAD_RIBBON).paid_for_a_swag_shirt
        assert Attendee(badge_type=c.STAFF_BADGE).paid_for_a_swag_shirt
        # assert Attendee(badge_type=c.SUPPORTER_BADGE).paid_for_a_swag_shirt  # TODO: should this be true? (original comment)

    def test_shiftless_depts(self, monkeypatch):
        monkeypatch.setattr(Attendee, 'takes_shifts', False)
        assert not Attendee(assigned_depts='x').paid_for_a_swag_shirt # TODO not sure if right property
        assert Attendee(staffing=True, assigned_depts='x').paid_for_a_swag_shirt # TODO not sure if right property

    @pytest.mark.parametrize("attendee_kwargs, weighted_hours, expected_result", [
        ({'ribbon': c.VOLUNTEER_RIBBON, 'assigned_depts': c.CONSOLE}, 5, False),
        ({'ribbon': c.VOLUNTEER_RIBBON, 'assigned_depts': c.CONSOLE}, 6, True),
        ({'ribbon': c.VOLUNTEER_RIBBON, 'assigned_depts': c.CONSOLE}, 18, True),
        ({'ribbon': c.VOLUNTEER_RIBBON, 'assigned_depts': c.CONSOLE}, 24, True),
        ({'ribbon': c.VOLUNTEER_RIBBON, 'assigned_depts': c.CONSOLE}, 30, True),

        ({'ribbon': c.VOLUNTEER_RIBBON}, 30, True),

        ({}, 5, False),
        ({}, 30, False),

        ({'badge_type': c.STAFF_BADGE, 'assigned_depts': c.CONSOLE}, 5, False),
        ({'badge_type': c.STAFF_BADGE, 'assigned_depts': c.CONSOLE}, 30, False),
    ])
    def test_shirt_hours(self, monkeypatch, attendee_kwargs, weighted_hours, expected_result):
        monkeypatch.setattr(Attendee, 'weighted_hours', weighted_hours)
        attendee = Attendee(**attendee_kwargs)
        attendee._staffing_adjustments()
        assert attendee.eligible_for_free_swag_shirt == expected_result













    @pytest.fixture
    def gets_shirt(self, monkeypatch):
        monkeypatch.setattr(Attendee, 'gets_shirt', True)

    @pytest.fixture
    def gets_no_shirt(self, monkeypatch):
        monkeypatch.setattr(Attendee, 'gets_shirt', False)

    def test_gets_shirt_true(self, gets_shirt):
        assert Attendee(staffing=False).gets_any_kind_of_shirt
        assert Attendee(staffing=True).gets_any_kind_of_shirt

    def test_gets_shirt_false(self, gets_no_shirt):
        assert not Attendee(staffing=False).gets_any_kind_of_shirt
        assert Attendee(staffing=True).gets_any_kind_of_shirt

    def test_gets_shirt_with_enough_extra(self):
        a = Attendee(shirt=1, amount_extra=c.SHIRT_LEVEL)
        a._misc_adjustments()
        assert a.shirt == 1

    def test_gets_shirt_without_enough_extra(self):
        a = Attendee(shirt=1, amount_extra=1)
        a._misc_adjustments()
        assert a.shirt == c.NO_SHIRT