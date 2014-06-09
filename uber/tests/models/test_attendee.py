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

def test_is_transferrable():
    assert not Attendee().is_transferrable
    assert Attendee(registered=datetime.now(UTC), paid=HAS_PAID).is_transferrable
    assert Attendee(registered=datetime.now(UTC), paid=PAID_BY_GROUP).is_transferrable

    assert not Attendee(paid=HAS_PAID).is_transferrable
    assert not Attendee(paid=HAS_PAID, checked_in=datetime.now()).is_transferrable
    assert not Attendee(registered=datetime.now(UTC), paid=HAS_PAID, badge_type=STAFF_BADGE).is_transferrable
    assert not Attendee(registered=datetime.now(UTC), paid=HAS_PAID, badge_type=GUEST_BADGE).is_transferrable

def test_gets_shirt(monkeypatch):
    assert not Attendee().gets_shirt
    assert Attendee(amount_extra=SHIRT_LEVEL).gets_shirt
    assert Attendee(ribbon=DEPT_HEAD_RIBBON).gets_shirt
    assert Attendee(badge_type=SUPPORTER_BADGE).gets_shirt

    monkeypatch.setattr(Attendee, 'worked_hours', 5)
    assert not Attendee().gets_shirt
    monkeypatch.setattr(Attendee, 'worked_hours', 18)
    assert not Attendee().gets_shirt
    monkeypatch.setattr(Attendee, 'worked_hours', 6)
    assert Attendee().gets_shirt
    monkeypatch.setattr(Attendee, 'worked_hours', 24)
    assert Attendee().gets_shirt

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

def test_hotel_shifts_required(monkeypatch):
    assert not Attendee().hotel_shifts_required
    monkeypatch.setattr(Attendee, 'takes_shifts', True)
    monkeypatch.setattr(Attendee, 'hotel_nights', [THURSDAY, FRIDAY])
    assert Attendee().hotel_shifts_required
    assert not Attendee(ribbon=DEPT_HEAD_RIBBON).hotel_shifts_required

def test_unset_volunteer():
    a = Attendee(staffing=True, trusted=True, requested_depts=CONSOLE, assigned_depts=CONSOLE, ribbon=VOLUNTEER_RIBBON, shifts=[Shift()])
    a.unset_volunteering()
    assert not a.staffing and not a.trusted and not a.requested_depts and not a.assigned_depts and not a.shifts and a.ribbon == NO_RIBBON

def test_unset_volunteer_with_different_ribbon():
    a = Attendee(ribbon=DEALER_RIBBON)
    a.unset_volunteering()
    assert a.ribbon == DEALER_RIBBON

def test_unset_volunteer_with_staff_badge(monkeypatch):
    with Session() as session:
        monkeypatch.setattr(Attendee, 'session', Mock())
        a = Attendee(badge_type=STAFF_BADGE, badge_num=123)
        a.unset_volunteering()
        assert a.badge_type == ATTENDEE_BADGE
        a.session.shift_badges.assert_called_with(a, down=True)

def test_misc_adjustments_amount_extra():
    a = Attendee(affiliate='xxx', amount_extra=1)
    a._misc_adjustments()
    assert a.affiliate == 'xxx'

    a = Attendee(affiliate='xxx')
    a._misc_adjustments()
    assert a.affiliate == ''

def test_misc_adjustments_gets_shirt():
    a = Attendee(shirt=1, amount_extra=SHIRT_LEVEL)
    a._misc_adjustments()
    a.shirt == 1

    a = Attendee(shirt=1)
    a._misc_adjustments()
    assert a.shirt == NO_SHIRT

def test_misc_adjustments_amount_refunded():
    a = Attendee(amount_refunded=123, paid=REFUNDED)
    a._misc_adjustments()
    assert a.amount_refunded == 123

    a = Attendee(amount_refunded=123)
    a._misc_adjustments()
    assert not a.amount_refunded

def test_misc_adjustments_badge_at_con(precon):
    a = Attendee(badge_num=1)
    a._misc_adjustments()
    assert a.checked_in

def test_misc_adjustments_badge_at_con(at_the_con):
    a = Attendee()
    a._misc_adjustments()
    assert not a.checked_in

    a = Attendee(badge_num=1, registered=datetime.now(UTC))
    a._misc_adjustments()
    assert not a.checked_in

    a = Attendee(badge_num=1)
    a._misc_adjustments()
    assert a.checked_in

def test_misc_adjustments_names():
    a = Attendee(first_name='nac', last_name='mac Feegle')
    a._misc_adjustments()
    assert a.full_name == 'Nac mac Feegle'

    a = Attendee(first_name='NAC', last_name='mac feegle')
    a._misc_adjustments()
    assert a.full_name == 'Nac Mac Feegle'
