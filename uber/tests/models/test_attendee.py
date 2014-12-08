from uber.tests import *

def test_badge_cost(monkeypatch):
    monkeypatch.setattr(state, 'get_oneday_price', Mock(return_value=111))
    monkeypatch.setattr(state, 'get_attendee_price', Mock(return_value=222))
    assert 111 == Attendee(badge_type=ONE_DAY_BADGE).badge_cost
    assert 222 == Attendee().badge_cost
    assert 333 == Attendee(overridden_price=333).badge_cost
    assert 0 == Attendee(paid=NEED_NOT_PAY).badge_cost
    assert 0 == Attendee(paid=PAID_BY_GROUP).badge_cost

def test_total_cost(monkeypatch):
    monkeypatch.setattr(state, 'get_attendee_price', Mock(return_value=10))
    assert 10 == Attendee().total_cost
    assert 15 == Attendee(amount_extra=5).total_cost

def test_amount_unpaid(monkeypatch):
    monkeypatch.setattr(Attendee, 'total_cost', 50)
    assert 50 == Attendee().amount_unpaid
    assert 10 == Attendee(amount_paid=40).amount_unpaid
    assert 0 == Attendee(amount_paid=50).amount_unpaid
    assert 0 == Attendee(amount_paid=51).amount_unpaid

def test_is_unpaid():
    assert Attendee().is_unpaid
    assert Attendee(paid=NOT_PAID).is_unpaid
    for status in [NEED_NOT_PAY, PAID_BY_GROUP, REFUNDED]:
        assert not Attendee(paid=status).is_unpaid

# we may eventually want to make this a little more explicit;
# at the moment I'm basically just testing an implementation detail
def test_is_unassigned():
    assert Attendee().is_unassigned
    assert not Attendee(first_name='x').is_unassigned

def test_is_dealer():
    assert not Attendee().is_dealer
    assert Attendee(ribbon=DEALER_RIBBON).is_dealer
    assert Attendee(badge_type=PSEUDO_DEALER_BADGE).is_dealer

    # not all attendees in a dealer group are necessarily dealers
    dealer_group = Group(tables=1)
    assert not Attendee(group=dealer_group).is_dealer

def test_is_dept_head():
    assert not Attendee().is_dept_head
    assert Attendee(ribbon=DEPT_HEAD_RIBBON).is_dept_head

def test_unassigned_name(monkeypatch):
    monkeypatch.setattr(Attendee, 'badge', 'BadgeType')
    assert not Attendee().unassigned_name
    assert not Attendee(group_id=1, first_name='x').unassigned_name
    assert '[Unassigned BadgeType]' == Attendee(group_id=1).unassigned_name

def test_full_name(monkeypatch):
    assert 'x y' == Attendee(first_name='x', last_name='y').full_name
    monkeypatch.setattr(Attendee, 'unassigned_name', 'xxx')
    assert 'xxx' == Attendee(first_name='x', last_name='y').full_name

def test_last_first(monkeypatch):
    assert 'y, x' == Attendee(first_name='x', last_name='y').last_first
    monkeypatch.setattr(Attendee, 'unassigned_name', 'xxx')
    assert 'xxx' == Attendee(first_name='x', last_name='y').last_first

def test_badge():
    assert Attendee().badge == 'Unpaid Attendee'
    assert Attendee(paid=HAS_PAID).badge == 'Attendee'
    assert Attendee(badge_num=123).badge == 'Unpaid Attendee'
    assert Attendee(badge_num=123, paid=HAS_PAID).badge == 'Attendee #123'
    assert Attendee(ribbon=VOLUNTEER_RIBBON).badge == 'Unpaid Attendee (Volunteer)'

def test_is_transferrable(monkeypatch):
    assert not Attendee(paid=HAS_PAID).is_transferrable
    monkeypatch.setattr(Attendee, 'is_new', False)

    assert Attendee(paid=HAS_PAID).is_transferrable
    assert Attendee(paid=PAID_BY_GROUP).is_transferrable
    assert not Attendee(paid=NOT_PAID).is_transferrable

    assert not Attendee(paid=HAS_PAID, trusted=True).is_transferrable
    assert not Attendee(paid=HAS_PAID, checked_in=datetime.now(UTC)).is_transferrable
    assert not Attendee(paid=HAS_PAID, badge_type=STAFF_BADGE).is_transferrable
    assert not Attendee(paid=HAS_PAID, badge_type=GUEST_BADGE).is_transferrable

class TestGetsShirt:
    def test_basics(self, monkeypatch):
        assert not Attendee().gets_shirt
        assert Attendee(amount_extra=SHIRT_LEVEL).gets_shirt
        assert Attendee(ribbon=DEPT_HEAD_RIBBON).gets_shirt
        assert Attendee(badge_type=STAFF_BADGE).gets_shirt
        assert Attendee(badge_type=SUPPORTER_BADGE).gets_shirt

    def test_shiftless_depts(self, monkeypatch):
        monkeypatch.setattr(Attendee, 'takes_shifts', False)
        assert not Attendee().gets_shirt
        assert Attendee(staffing=True).gets_shirt

    def test_precon_hours(self, monkeypatch, precon):
        monkeypatch.setattr(Attendee, 'weighted_hours', 5)
        assert not Attendee().gets_shirt
        for amount in [6, 18, 24, 30]:
            monkeypatch.setattr(Attendee, 'weighted_hours', amount)
            assert Attendee().gets_shirt

    def test_atcon_hours(self, monkeypatch, at_con):
        monkeypatch.setattr(Attendee, 'worked_hours', 5)
        assert not Attendee().gets_shirt
        for amount in [6, 18, 24, 30]:
            monkeypatch.setattr(Attendee, 'worked_hours', amount)
            assert Attendee().gets_shirt

class TestShirtEligible:
    @pytest.fixture
    def gets_shirt(self, monkeypatch):
        monkeypatch.setattr(Attendee, 'gets_shirt', True)

    @pytest.fixture
    def gets_no_shirt(self, monkeypatch):
        monkeypatch.setattr(Attendee, 'gets_shirt', False)

    def test_gets_shirt_true(self, gets_shirt):
        assert Attendee(staffing=False).shirt_eligible
        assert Attendee(staffing=True).shirt_eligible

    def test_gets_shirt_false(self, gets_no_shirt):
        assert not Attendee(staffing=False).shirt_eligible
        assert Attendee(staffing=True).shirt_eligible

def test_has_personalized_badge():
    assert not Attendee().has_personalized_badge
    assert Attendee(badge_type=STAFF_BADGE).has_personalized_badge
    assert Attendee(badge_type=SUPPORTER_BADGE).has_personalized_badge
    for badge_type in [ATTENDEE_BADGE, ONE_DAY_BADGE, GUEST_BADGE]:
        assert not Attendee(badge_type=badge_type).has_personalized_badge

def test_takes_shifts():
    assert not Attendee().takes_shifts
    assert not Attendee(staffing=True).takes_shifts
    assert Attendee(staffing=True, assigned_depts=CONSOLE).takes_shifts
    assert not Attendee(staffing=True, assigned_depts=CON_OPS).takes_shifts
    assert Attendee(staffing=True, assigned_depts=','.join(map(str, [CONSOLE, CON_OPS]))).takes_shifts

def test_hotel_shifts_required(monkeypatch, shifts_created):
    assert not Attendee().hotel_shifts_required
    monkeypatch.setattr(Attendee, 'takes_shifts', True)
    monkeypatch.setattr(Attendee, 'hotel_nights', [THURSDAY, FRIDAY])
    assert Attendee().hotel_shifts_required
    assert not Attendee(ribbon=DEPT_HEAD_RIBBON).hotel_shifts_required

def test_hotel_shifts_required_preshifts(monkeypatch, shifts_not_created):
    monkeypatch.setattr(Attendee, 'takes_shifts', True)
    monkeypatch.setattr(Attendee, 'hotel_nights', [THURSDAY, FRIDAY])
    assert not Attendee().hotel_shifts_required

class TestUnsetVolunteer:
    def test_basic(self):
        a = Attendee(staffing=True, trusted=True, requested_depts=CONSOLE, assigned_depts=CONSOLE, ribbon=VOLUNTEER_RIBBON, shifts=[Shift()])
        a.unset_volunteering()
        assert not a.staffing and not a.trusted and not a.requested_depts and not a.assigned_depts and not a.shifts and a.ribbon == NO_RIBBON

    def test_different_ribbon(self):
        a = Attendee(ribbon=DEALER_RIBBON)
        a.unset_volunteering()
        assert a.ribbon == DEALER_RIBBON

    def test_staff_badge(self, monkeypatch):
        with Session() as session:
            monkeypatch.setattr(Attendee, 'session', Mock())
            a = Attendee(badge_type=STAFF_BADGE, badge_num=123)
            a.unset_volunteering()
            assert a.badge_type == ATTENDEE_BADGE
            a.session.shift_badges.assert_called_with(STAFF_BADGE, 123, down=True)

    def test_affiliate_with_extra(self):
        a = Attendee(affiliate='xxx', amount_extra=1)
        a._misc_adjustments()
        assert a.affiliate == 'xxx'

    def test_affiliate_without_extra(self):
        a = Attendee(affiliate='xxx')
        a._misc_adjustments()
        assert a.affiliate == ''

    def test_gets_shirt_with_enough_extra(self):
        a = Attendee(shirt=1, amount_extra=SHIRT_LEVEL)
        a._misc_adjustments()
        a.shirt == 1

    def test_gets_shirt_without_enough_extra(self):
        a = Attendee(shirt=1, amount_extra=1)
        a._misc_adjustments()
        assert a.shirt == NO_SHIRT

    def test_amount_refunded_when_refunded(self):
        a = Attendee(amount_refunded=123, paid=REFUNDED)
        a._misc_adjustments()
        assert a.amount_refunded == 123

    def test_amount_refunded_when_not_refunded(self):
        a = Attendee(amount_refunded=123)
        a._misc_adjustments()
        assert not a.amount_refunded

    def test_badge_precon(self, precon):
        a = Attendee(badge_num=1)
        a._misc_adjustments()
        assert not a.checked_in

    def test_badge_at_con(self, monkeypatch, at_con):
        a = Attendee()
        a._misc_adjustments()
        assert not a.checked_in

        a = Attendee(badge_num=1)
        a._misc_adjustments()
        assert a.checked_in

        monkeypatch.setattr(Attendee, 'is_new', False)
        a = Attendee(badge_num=1)
        a._misc_adjustments()
        assert not a.checked_in

    def test_names(self):
        a = Attendee(first_name='nac', last_name='mac Feegle')
        a._misc_adjustments()
        assert a.full_name == 'Nac mac Feegle'

        a = Attendee(first_name='NAC', last_name='mac feegle')
        a._misc_adjustments()
        assert a.full_name == 'Nac Mac Feegle'

class TestStaffingAdjustments:
    @pytest.fixture(autouse=True)
    def unset_volunteering(self, monkeypatch):
        monkeypatch.setattr(Attendee, 'unset_volunteering', Mock())
        return Attendee.unset_volunteering

    def test_dept_head_invariants(self):
        a = Attendee(ribbon=DEPT_HEAD_RIBBON)
        a._staffing_adjustments()
        assert a.staffing and a.trusted

    def test_unpaid_dept_head(self):
        a = Attendee(ribbon=DEPT_HEAD_RIBBON)
        a._staffing_adjustments()
        assert a.paid == NEED_NOT_PAY

    def test_dept_head_before_custom_badges(self, custom_badges_not_ordered):
        a = Attendee(ribbon=DEPT_HEAD_RIBBON, badge_type=ATTENDEE_BADGE)
        a._staffing_adjustments()
        assert a.badge_type == STAFF_BADGE

    def test_dept_head_after_custom_badges(self, custom_badges_ordered):
        a = Attendee(ribbon=DEPT_HEAD_RIBBON, badge_type=ATTENDEE_BADGE)
        a._staffing_adjustments()
        assert a.badge_type == ATTENDEE_BADGE

        a = Attendee(ribbon=DEPT_HEAD_RIBBON, badge_type=STAFF_BADGE)
        a._staffing_adjustments()
        assert a.badge_type == STAFF_BADGE

    def test_under_18_at_con(self, at_con, unset_volunteering):
        a = Attendee(age_group=UNDER_18)
        a._staffing_adjustments()
        assert not unset_volunteering.called

    def staffers_need_no_volunteer_ribbon(self):
        a = Attendee(badge_type=STAFF_BADGE, ribbon=VOLUNTEER_RIBBON)
        a._staffing_adjustments()
        assert a.ribbon == NO_RIBBON

    def staffers_can_have_other_ribbons(self):
        a = Attendee(badge_type=STAFF_BADGE, ribbon=DEALER_RIBBON)
        a._staffing_adjustments()
        assert a.ribbon == DEALER_RIBBON

    def no_to_yes_ribbon(self, unset_volunteering):
        with Session() as session:
            a = session.attendee(first_name='Regular', last_name='Attendee')
            a.ribbon = VOLUNTEER_RIBBON
            a._staffing_adjustments()
            assert a.staffing
            assert not unset_volunteering.called

    def no_to_yes_volunteering(self, unset_volunteering):
        with Session() as session:
            a = session.attendee(first_name='Regular', last_name='Attendee')
            a.staffing = True
            a._staffing_adjustments()
            assert a.ribbon == VOLUNTEER_RIBBON
            assert not unset_volunteering.called

    def yes_to_no_volunteering(self, unset_volunteering):
        with Session() as session:
            a = session.attendee(first_name='Regular', last_name='Volunteer')
            a.ribbon = NO_RIBBON
            a._staffing_adjustments()
            assert unset_volunteering.called

    def yes_to_no_volunteering(self, unset_volunteering):
        with Session() as session:
            a = session.attendee(first_name='Regular', last_name='Volunteer')
            a.staffing = False
            a._staffing_adjustments()
            assert unset_volunteering.called

class TestBadgeAdjustments:
    @pytest.fixture(autouse=True)
    def mock_attendee_session(self, monkeypatch):
        monkeypatch.setattr(Attendee, 'session', Mock())
        Attendee.session.next_badge_num = Mock(return_value=123)

    @pytest.fixture
    def fully_paid(self, monkeypatch):
        monkeypatch.setattr(Attendee, 'paid', HAS_PAID)
        monkeypatch.setattr(Attendee, 'amount_unpaid', 0)

    def test_group_to_attendee(self):
        a = Attendee(badge_type=PSEUDO_GROUP_BADGE)
        a._badge_adjustments()
        assert a.badge_type == ATTENDEE_BADGE and a.ribbon == NO_RIBBON

    def test_dealer_to_attendee(self):
        a = Attendee(badge_type=PSEUDO_DEALER_BADGE)
        a._badge_adjustments()
        assert a.badge_type == ATTENDEE_BADGE and a.ribbon == DEALER_RIBBON

    def test_attendee_to_supporter(self, custom_badges_not_ordered, fully_paid):
        for amount_extra in [SUPPORTER_LEVEL, SUPPORTER_LEVEL + 10]:
            a = Attendee(amount_extra=amount_extra, paid=HAS_PAID)
            a._badge_adjustments()
            assert a.badge_type == SUPPORTER_BADGE

    def test_supporter_after_badge_order(self, custom_badges_ordered, fully_paid):
        a = Attendee(amount_extra=SUPPORTER_LEVEL)
        a._badge_adjustments()
        assert a.badge_type == ATTENDEE_BADGE

    def test_not_fully_paid_supporter(self, custom_badges_not_ordered):
        a = Attendee(amount_extra=SUPPORTER_LEVEL, paid=HAS_PAID)
        a._badge_adjustments()
        assert a.badge_type == ATTENDEE_BADGE

    def test_non_attendee_badges_do_not_upgrade_to_supporter(self, custom_badges_not_ordered, fully_paid):
        for badge_type in [GUEST_BADGE, STAFF_BADGE]:
            a = Attendee(amount_extra=SUPPORTER_LEVEL, badge_type=badge_type)
            a._badge_adjustments()
            assert a.badge_type == badge_type

    def test_unpaid_badges_reset_to_zero(self, precon):
        a = Attendee(badge_type=SUPPORTER_BADGE, badge_num=1)
        a._badge_adjustments()
        assert a.badge_num == 0

    def test_preassigned_badge_assignment(self, precon):
        for paid in [HAS_PAID, NEED_NOT_PAY, REFUNDED]:
            a = Attendee(badge_type=SUPPORTER_BADGE, paid=paid)
            a._badge_adjustments()
            assert a.badge_num == 123  # mocked next badge num

    def test_preassigned_badge_after_badge_order(self, precon, custom_badges_ordered, fully_paid):
        a = Attendee(badge_type=SUPPORTER_BADGE, paid=HAS_PAID)
        a._badge_adjustments()
        assert a.badge_type == ATTENDEE_BADGE

        a = Attendee(badge_type=SUPPORTER_BADGE, paid=HAS_PAID, badge_num=1)
        a._badge_adjustments()
        assert a.badge_type == SUPPORTER_BADGE and a.badge_num == 1

class TestLookupAttendee:
    @pytest.fixture(autouse=True)
    def searchable(self):
        with Session() as session:
            attendee = Attendee(
                placeholder=True,
                first_name='Searchable',
                last_name='Attendee',
                email='searchable@example.com',
                zip_code='12345'
            )
            session.add(attendee)
            session.add(Attendee(
                placeholder=True,
                first_name='Two First',
                last_name='Names',
                email='searchable@example.com',
                zip_code='12345'
            ))
            session.add(Attendee(
                placeholder=True,
                first_name='Two',
                last_name='Last Names',
                email='searchable@example.com',
                zip_code='12345'
            ))
            return attendee.id

    def test_search_not_found(self):
        with Session() as session:
            pytest.raises(ValueError, session.lookup_attendee, 'Searchable Attendee', 'searchable@example.com', 'xxxxx')
            pytest.raises(ValueError, session.lookup_attendee, 'XXX XXX', 'searchable@example.com', '12345')
            pytest.raises(ValueError, session.lookup_attendee, 'Searchable Attendee', 'xxx', '12345')

    def test_search_basic(self, searchable):
        with Session() as session:
            assert str(searchable) == session.lookup_attendee('Searchable Attendee', 'searchable@example.com', '12345').id

    def test_search_case_insensitive(self, searchable):
        with Session() as session:
            assert str(searchable) == session.lookup_attendee('searchablE attendeE', 'seArchAble@exAmple.com', '12345').id

    def test_search_multi_word_names(self):
        with Session() as session:
            assert session.lookup_attendee('Two First Names', 'searchable@example.com', '12345')
            assert session.lookup_attendee('Two Last Names', 'searchable@example.com', '12345')
