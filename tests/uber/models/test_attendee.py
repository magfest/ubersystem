from datetime import datetime

import pytest
import pytz
from mock import Mock
from pytz import UTC

from uber import config
from uber.config import c
from uber.models import Attendee, Department, DeptMembership, DeptMembershipRequest, DeptRole, FoodRestrictions, \
    Group, Job, Session, Shift
from uber.models.commerce import StripeTransaction, StripeTransactionAttendee
from uber.model_checks import extra_donation_valid, _invalid_phone_number


@pytest.fixture()
def dept():
    yield Department(
        id='97cc0050-11e0-42eb-9a1b-83f27a1acf76',
        name='Console Challenges',
        description='Console Challenges')


@pytest.fixture()
def shiftless_dept():
    yield Department(
        id='27152595-2ea8-43ee-8edb-a68cefb2b2ac',
        name='Con Ops',
        description='Con Ops',
        is_shiftless=True)


@pytest.fixture()
def trusted_role(dept):
    yield DeptRole(
        id='45c3fd2a-df1d-46bd-a10c-7289bbfd1167',
        name='Trusted',
        description='Trusted',
        department=dept)


class TestCosts:
    @pytest.fixture(autouse=True)
    def mocked_prices(self, monkeypatch):
        monkeypatch.setattr(c, 'get_oneday_price', Mock(return_value=10))
        monkeypatch.setattr(c, 'get_attendee_price', Mock(return_value=20))

    def test_badge_cost(self):
        assert 10 == Attendee(badge_type=c.ONE_DAY_BADGE).badge_cost
        assert 20 == Attendee().badge_cost
        assert 30 == Attendee(overridden_price=30).badge_cost
        assert 0 == Attendee(paid=c.NEED_NOT_PAY).badge_cost
        assert 20 == Attendee(paid=c.PAID_BY_GROUP).badge_cost
        assert 30 == Attendee(base_badge_price=30).badge_cost

    def test_total_cost(self):
        assert 20 == Attendee().total_cost
        assert 25 == Attendee(amount_extra=5).total_cost

    def test_amount_unpaid(self, monkeypatch):
        monkeypatch.setattr(Attendee, 'total_cost', 50)
        assert 50 == Attendee().amount_unpaid
        assert 10 == Attendee(amount_paid=40).amount_unpaid
        assert 0 == Attendee(amount_paid=50).amount_unpaid
        assert 0 == Attendee(amount_paid=51).amount_unpaid

    def test_age_discount(self, monkeypatch):
        monkeypatch.setattr(Attendee, 'age_group_conf', {'discount': 5})
        assert 15 == Attendee().total_cost
        assert 20 == Attendee(amount_extra=5).total_cost
        assert 10 == Attendee(overridden_price=10).total_cost
        assert 15 == Attendee(overridden_price=10, amount_extra=5).total_cost

    def test_age_free(self, monkeypatch):
        # makes badge_cost free unless overridden_price is set
        monkeypatch.setattr(Attendee, 'age_group_conf', {'discount': 999})
        assert 0 == Attendee().total_cost
        assert 5 == Attendee(amount_extra=5).total_cost
        assert 10 == Attendee(overridden_price=10).total_cost
        assert 15 == Attendee(overridden_price=10, amount_extra=5).total_cost

    def test_age_discount_doesnt_stack(self, monkeypatch):
        monkeypatch.setattr(Attendee, 'age_group_conf', {'discount': 5})
        assert 10 == Attendee(badge_type=c.ONE_DAY_BADGE).badge_cost


class TestHalfPriceAgeDiscountCosts:
    @pytest.fixture(autouse=True)
    def mocked_prices(self, monkeypatch):
        monkeypatch.setattr(c, 'get_oneday_price', Mock(return_value=10))
        monkeypatch.setattr(c, 'get_attendee_price', Mock(return_value=40))

    def test_half_price_discount(self):
        # Age group discount not set: badge is half off
        assert 20 == Attendee(age_group=c.UNDER_13).badge_cost

    def test_half_price_overrides_age_discount(self, monkeypatch):
        # Age group discount is less than half off: badge is half off
        monkeypatch.setattr(Attendee, 'age_group_conf', {'val': c.UNDER_13, 'discount': 5})
        assert 20 == Attendee(age_group=c.UNDER_13).badge_cost

    def test_age_discount_overrides_half_price(self, monkeypatch):
        # Age group discount is greater than half off: badge price based on age discount instead
        monkeypatch.setattr(Attendee, 'age_group_conf', {'val': c.UNDER_13, 'discount': 30})
        assert 10 == Attendee(age_group=c.UNDER_13).badge_cost


def test_is_unpaid():
    assert Attendee().is_unpaid
    assert Attendee(paid=c.NOT_PAID).is_unpaid
    for status in [c.NEED_NOT_PAY, c.PAID_BY_GROUP, c.REFUNDED]:
        assert not Attendee(paid=status).is_unpaid


# we may eventually want to make this a little more explicit;
# at the moment I'm basically just testing an implementation detail
def test_is_unassigned():
    assert Attendee().is_unassigned
    assert not Attendee(first_name='x').is_unassigned


def test_is_dealer():
    assert not Attendee().is_dealer
    assert Attendee(ribbon=c.DEALER_RIBBON).is_dealer
    assert Attendee(badge_type=c.PSEUDO_DEALER_BADGE).is_dealer

    # not all attendees in a dealer group are necessarily dealers
    dealer_group = Group(tables=1)
    assert not Attendee(group=dealer_group).is_dealer
    assert Attendee(group=dealer_group, paid=c.PAID_BY_GROUP).is_dealer


def test_is_dept_head():
    assert not Attendee().is_dept_head
    dept_membership = DeptMembership(is_dept_head=True)
    assert Attendee(dept_memberships=[dept_membership]).is_dept_head


def test_dept_head_ribbon_label_from_ribbon_attr():
    a = Attendee()
    assert a.ribbon_labels == []

    a.ribbon = '{}'.format(c.DEPT_HEAD_RIBBON)
    assert a.ribbon_labels == ['Department Head']

    a.ribbon = '{},{}'.format(c.VOLUNTEER_RIBBON, c.DEPT_HEAD_RIBBON)
    assert a.ribbon_labels == ['Department Head', 'Volunteer']

    a.ribbon = '{}'.format(c.VOLUNTEER_RIBBON)
    assert a.ribbon_labels == ['Volunteer']


def test_dept_head_ribbon_label_from_dept_membership():
    with Session() as session:
        a = Attendee()
        session.add(a)

        a.presave_adjustments()
        assert a.ribbon_labels == []

        a.dept_memberships = [DeptMembership(is_dept_head=True)]
        a.presave_adjustments()
        assert a.ribbon_labels == ['Department Head']
        a.presave_adjustments()
        assert a.ribbon_labels == ['Department Head']

        a.badge_type = c.ATTENDEE_BADGE
        a.staffing = True
        a.ribbon = '{}'.format(c.DEALER_RIBBON)
        a.presave_adjustments()
        assert set(a.ribbon_labels) == set(['Department Head', 'Shopkeep'])
        a.presave_adjustments()
        assert set(a.ribbon_labels) == set(['Department Head', 'Shopkeep'])

        a.dept_memberships = [DeptMembership(is_dept_head=False)]
        a.presave_adjustments()
        assert set(a.ribbon_labels) == set(['Department Head', 'Shopkeep'])
        a.presave_adjustments()
        assert set(a.ribbon_labels) == set(['Department Head', 'Shopkeep'])

        session.expunge_all()


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


def test_legal_name_same_as_full_name():
    same_legal_name = Attendee(first_name='First', last_name='Last', legal_name='First Last')
    same_legal_name._misc_adjustments()
    assert '' == same_legal_name.legal_name


def test_legal_name_diff_from_full_name():
    diff_legal_name = Attendee(first_name='first', last_name='last', legal_name='diff name')
    diff_legal_name._misc_adjustments()
    assert 'diff name' == diff_legal_name.legal_name


def test_badge():
    assert Attendee().badge == 'Unpaid Attendee'
    assert Attendee(paid=c.HAS_PAID).badge == 'Attendee'
    assert Attendee(badge_num=123).badge == 'Unpaid Attendee'
    assert Attendee(badge_num=123, paid=c.HAS_PAID).badge == 'Attendee #123'
    assert Attendee(ribbon=c.VOLUNTEER_RIBBON).badge == 'Unpaid Attendee (Volunteer)'


def test_is_transferable(monkeypatch):
    assert not Attendee(paid=c.HAS_PAID).is_transferable
    monkeypatch.setattr(Attendee, 'is_new', False)

    assert Attendee(paid=c.HAS_PAID).is_transferable
    assert Attendee(paid=c.PAID_BY_GROUP).is_transferable
    assert not Attendee(paid=c.NOT_PAID).is_transferable

    assert not Attendee(paid=c.HAS_PAID, checked_in=datetime.now(UTC)).is_transferable
    assert not Attendee(paid=c.HAS_PAID, badge_type=c.STAFF_BADGE).is_transferable
    assert not Attendee(paid=c.HAS_PAID, badge_type=c.GUEST_BADGE).is_transferable


def test_is_not_transferable_trusted(monkeypatch, dept, trusted_role):
    monkeypatch.setattr(Attendee, 'is_new', False)
    with Session() as session:
        attendee = Attendee(paid=c.HAS_PAID)
        dept_membership = DeptMembership(
            attendee=attendee,
            department=dept,
            dept_roles=[trusted_role])
        session.add_all([attendee, dept, trusted_role, dept_membership])
        session.flush()
        assert not attendee.is_transferable


@pytest.mark.parametrize('open,expected', [
    (lambda s: False, False),
    (lambda s: True, True),
])
def test_self_service_refunds_if_on(monkeypatch, open, expected):
    monkeypatch.setattr(config.Config, 'SELF_SERVICE_REFUNDS_OPEN',
                        property(open))
    attendee = Attendee(paid=c.HAS_PAID, amount_paid=10)
    txn = StripeTransaction(amount=1000)
    attendee.stripe_txn_share_logs = [
        StripeTransactionAttendee(attendee_id=attendee.id, txn_id=txn.id, share=1000)]
    assert attendee.can_self_service_refund_badge == expected


@pytest.mark.parametrize('paid,expected', [
    (c.NEED_NOT_PAY, False),
    (c.REFUNDED, False),
    (c.NOT_PAID, True),
    (c.PAID_BY_GROUP, True),
    (c.HAS_PAID, True)
])
def test_self_service_refunds_payment_status(monkeypatch, paid, expected):
    monkeypatch.setattr(config.Config, 'SELF_SERVICE_REFUNDS_OPEN',
                        property(lambda s: True))
    attendee = Attendee(paid=paid, amount_paid=10)
    txn = StripeTransaction(amount=1000)
    attendee.stripe_txn_share_logs = [
        StripeTransactionAttendee(attendee_id=attendee.id, txn_id=txn.id, share=1000)]
    assert attendee.can_self_service_refund_badge == expected


@pytest.mark.parametrize('amount_paid,checked_in,expected', [
    (0, False, False),
    (-10, False, False),
    (None, False, None),
    (10, True, False),
    (10, False, True),
])
def test_self_service_refunds_misc(monkeypatch, amount_paid, checked_in, expected):
    monkeypatch.setattr(config.Config, 'SELF_SERVICE_REFUNDS_OPEN',
                        property(lambda s: True))
    attendee = Attendee(paid=c.HAS_PAID, amount_paid=amount_paid)
    txn = StripeTransaction(amount=1000)
    attendee.stripe_txn_share_logs = [
        StripeTransactionAttendee(attendee_id=attendee.id, txn_id=txn.id, share=1000)]
    attendee.checked_in = checked_in
    assert attendee.can_self_service_refund_badge == expected


def test_self_service_refunds_no_stripe(monkeypatch):
    monkeypatch.setattr(config.Config, 'SELF_SERVICE_REFUNDS_OPEN',
                        property(lambda s: True))
    attendee = Attendee(paid=c.HAS_PAID, amount_paid=10)
    attendee.stripe_txn_share_logs = []
    assert not attendee.can_self_service_refund_badge


def test_self_service_refunds_group_leader(monkeypatch):
    monkeypatch.setattr(config.Config, 'SELF_SERVICE_REFUNDS_OPEN',
                        property(lambda s: True))
    attendee = Attendee(paid=c.HAS_PAID, amount_paid=10)
    attendee.group = Group(leader_id=attendee.id)
    txn = StripeTransaction(amount=1000)
    attendee.stripe_txn_share_logs = [
        StripeTransactionAttendee(attendee_id=attendee.id, txn_id=txn.id, share=1000)]
    assert not attendee.can_self_service_refund_badge


def test_has_role_somewhere(dept, trusted_role):
    with Session() as session:
        attendee = Attendee(paid=c.HAS_PAID)
        dept_membership = DeptMembership(
            attendee=attendee,
            department=dept,
            dept_roles=[trusted_role])
        session.add_all([attendee, dept, trusted_role, dept_membership])
        session.flush()
        assert attendee.has_role_somewhere

        dept_membership.dept_roles = []
        session.flush()
        session.refresh(attendee)
        assert not attendee.has_role_somewhere


def test_requested_any_dept():
    dept1 = Department(name='Dept1', description='Dept1')
    dept2 = Department(name='Dept2', description='Dept2')
    volunteer = Attendee(paid=c.HAS_PAID, first_name='V', last_name='One')
    volunteer.dept_membership_requests = [
        DeptMembershipRequest(attendee=volunteer)]

    with Session() as session:
        session.add_all([dept1, dept2, volunteer])
        session.commit()
        session.refresh(volunteer)
        all_depts = session.query(Department).order_by(Department.name).all()
        assert all_depts == volunteer.requested_depts


def test_must_contact():
    dept1 = Department(name='Dept1', description='Dept1')
    dept2 = Department(name='Dept2', description='Dept2')

    poc_dept1 = Attendee(
        paid=c.NEED_NOT_PAY, first_name='Poc', last_name='Dept1')
    poc_dept2 = Attendee(
        paid=c.NEED_NOT_PAY, first_name='Poc', last_name='Dept2')
    poc_both = Attendee(
        paid=c.NEED_NOT_PAY, first_name='Poc', last_name='Both')

    poc_dept1.dept_memberships = [DeptMembership(
        department=dept1,
        is_poc=True)]

    poc_dept2.dept_memberships = [DeptMembership(
        department=dept2,
        is_poc=True)]

    poc_both.dept_memberships = [
        DeptMembership(
            department=dept1,
            is_poc=True),
        DeptMembership(
            department=dept2,
            is_poc=True)]

    start_time = datetime.now(tz=pytz.UTC)

    job1 = Job(
        name='Job1',
        description='Job1',
        start_time=start_time,
        duration=1,
        weight=1,
        slots=1,
        department=dept1)

    job2 = Job(
        name='Job2',
        description='Job2',
        start_time=start_time,
        duration=1,
        weight=1,
        slots=1,
        department=dept2)

    volunteer = Attendee(paid=c.HAS_PAID, first_name='V', last_name='One')

    job1.shifts = [Shift(attendee=volunteer, job=job1)]
    job2.shifts = [Shift(attendee=volunteer, job=job2)]

    with Session() as session:
        session.add_all([
            dept1, dept2, poc_dept1, poc_dept2, poc_both, job1, job2,
            volunteer])
        session.commit()
        assert volunteer.must_contact == '(Dept1) Poc Both / Poc Dept1<br/>(Dept2) Poc Both / Poc Dept2'


def test_has_personalized_badge():
    assert not Attendee().has_personalized_badge
    assert Attendee(badge_type=c.STAFF_BADGE).has_personalized_badge
    assert Attendee(badge_type=c.CONTRACTOR_BADGE).has_personalized_badge
    for badge_type in [c.ATTENDEE_BADGE, c.ONE_DAY_BADGE, c.GUEST_BADGE]:
        assert not Attendee(badge_type=badge_type).has_personalized_badge


def test_takes_shifts(dept, shiftless_dept):
    assert not Attendee().takes_shifts
    assert not Attendee(staffing=True).takes_shifts
    assert Attendee(staffing=True, assigned_depts=[dept]).takes_shifts
    assert not Attendee(staffing=True, assigned_depts=[shiftless_dept]).takes_shifts
    assert Attendee(staffing=True, assigned_depts=[dept, shiftless_dept]).takes_shifts


class TestAttendeeFoodRestrictionsFilledOut:
    @pytest.fixture
    def staff_get_food_true(self, monkeypatch):
        monkeypatch.setattr(config.Config, 'STAFF_GET_FOOD', property(lambda x: True))
        assert c.STAFF_GET_FOOD

    @pytest.fixture
    def staff_get_food_false(self, monkeypatch):
        monkeypatch.setattr(config.Config, 'STAFF_GET_FOOD', property(lambda x: False))
        assert not c.STAFF_GET_FOOD

    def test_food_restrictions_filled_out(self, staff_get_food_true):
        assert Attendee(food_restrictions=FoodRestrictions()).food_restrictions_filled_out

    def test_food_restrictions_not_filled_out(self, staff_get_food_true):
        assert not Attendee().food_restrictions_filled_out

    def test_food_restrictions_not_needed(self, staff_get_food_false):
        assert Attendee().food_restrictions_filled_out

    def test_shift_prereqs_complete(self, staff_get_food_true):
        assert Attendee(placeholder=False, shirt=1, food_restrictions=FoodRestrictions()).shift_prereqs_complete

    def test_shift_prereqs_placeholder(self, staff_get_food_true):
        assert not Attendee(placeholder=True, shirt=1, food_restrictions=FoodRestrictions()).shift_prereqs_complete

    def test_shift_prereqs_no_shirt(self, staff_get_food_true):
        assert not Attendee(
            placeholder=False, shirt=c.NO_SHIRT, food_restrictions=FoodRestrictions()).shift_prereqs_complete

        assert not Attendee(
            placeholder=False, shirt=c.SIZE_UNKNOWN, food_restrictions=FoodRestrictions()).shift_prereqs_complete

    def test_shift_prereqs_no_food(self, staff_get_food_true):
        assert not Attendee(placeholder=False, shirt=1).shift_prereqs_complete

    def test_shift_prereqs_food_not_needed(self, staff_get_food_false):
        assert Attendee(placeholder=False, shirt=1).shift_prereqs_complete


class TestUnsetVolunteer:
    def test_basic(self, dept, trusted_role):
        a = Attendee(
            staffing=True,
            requested_depts=[dept],
            ribbon=c.VOLUNTEER_RIBBON,
            shifts=[Shift()])
        a.dept_memberships = [DeptMembership(
            attendee=a,
            department=dept,
            dept_roles=[trusted_role])]
        a.assigned_depts = [dept]
        a.unset_volunteering()
        assert not a.staffing
        assert not a.has_role_somewhere
        assert not a.requested_depts
        assert not a.dept_memberships
        assert not a.shifts
        assert a.ribbon == ''

    def test_different_ribbon(self):
        a = Attendee(ribbon=c.DEALER_RIBBON)
        a.unset_volunteering()
        assert c.DEALER_RIBBON in a.ribbon_ints

    def test_staff_badge(self, monkeypatch):
        with Session() as session:
            assert session
            monkeypatch.setattr(Attendee, 'session', Mock())
            a = Attendee(badge_type=c.STAFF_BADGE, badge_num=123)
            a.unset_volunteering()
            assert a.badge_type == c.ATTENDEE_BADGE and a.badge_num is None

    def test_affiliate_with_extra(self):
        a = Attendee(affiliate='xxx', amount_extra=1)
        a._misc_adjustments()
        assert a.affiliate == 'xxx'

    def test_affiliate_without_extra(self):
        a = Attendee(affiliate='xxx')
        a._misc_adjustments()
        assert a.affiliate == ''

    def test_amount_refunded_when_refunded(self):
        a = Attendee(amount_refunded=123, paid=c.REFUNDED)
        a._misc_adjustments()
        assert a.amount_refunded == 123

    def test_amount_refunded_when_not_refunded(self):
        a = Attendee(amount_refunded=123)
        a._misc_adjustments()
        assert not a.amount_refunded

    def test_badge_precon(self):
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

        a = Attendee(badge_num=1, badge_type=c.PREASSIGNED_BADGE_TYPES[0])
        a._misc_adjustments()
        assert not a.checked_in

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

    @pytest.fixture(autouse=True)
    def prevent_presave_adjustments(self, monkeypatch):
        """ Prevent some tests from crashing on exit by not invoking presave_adjustements() """
        monkeypatch.setattr(Attendee, 'presave_adjustments', Mock())
        return Attendee.presave_adjustments

    def test_dept_head_invariants(self, dept):
        dept_membership = DeptMembership(
            department=dept,
            is_dept_head=True)
        a = Attendee(dept_memberships=[dept_membership])
        a._staffing_adjustments()
        assert a.staffing
        assert a.badge_type == c.STAFF_BADGE

    def test_staffing_still_trusted_assigned(self, dept, shiftless_dept):
        """
        After applying staffing adjustements:
        Any depts you are both trusted and assigned to should remain unchanged
        """
        a = Attendee(staffing=True)
        dept_memberships = [
            DeptMembership(
                attendee=a,
                attendee_id=a.id,
                department=dept,
                department_id=dept.id,
                is_dept_head=True),
            DeptMembership(
                attendee=a,
                attendee_id=a.id,
                department=shiftless_dept,
                department_id=shiftless_dept.id,
                dept_roles=[DeptRole()])]
        a.assigned_depts = [dept, shiftless_dept]
        a.dept_memberships_with_role = dept_memberships
        a._staffing_adjustments()
        assert a.assigned_to(dept) and a.trusted_in(dept)
        assert a.assigned_to(shiftless_dept) and a.trusted_in(shiftless_dept)

    def test_unpaid_dept_head(self, dept):
        dept_membership = DeptMembership(
            department=dept,
            is_dept_head=True)
        a = Attendee(dept_memberships=[dept_membership])
        a._staffing_adjustments()
        assert a.paid == c.NEED_NOT_PAY

    def test_under_18_at_con(self, at_con, unset_volunteering):
        a = Attendee(age_group=c.UNDER_18)
        a._staffing_adjustments()
        assert not unset_volunteering.called

    def test_staffers_need_no_volunteer_ribbon(self):
        a = Attendee(badge_type=c.STAFF_BADGE, ribbon=c.VOLUNTEER_RIBBON)
        a._staffing_adjustments()
        assert a.ribbon == ''

    def test_staffers_can_have_other_ribbons(self):
        a = Attendee(badge_type=c.STAFF_BADGE, ribbon=c.DEALER_RIBBON)
        a._staffing_adjustments()
        assert c.DEALER_RIBBON in a.ribbon_ints

    def test_no_to_yes_ribbon(self, unset_volunteering, prevent_presave_adjustments):
        with Session() as session:
            a = session.attendee(first_name='Regular', last_name='Attendee')
            a.ribbon = c.VOLUNTEER_RIBBON
            a._staffing_adjustments()
            assert a.staffing
            assert not unset_volunteering.called

    def test_no_to_yes_volunteering(self, unset_volunteering, prevent_presave_adjustments):
        with Session() as session:
            a = session.attendee(first_name='Regular', last_name='Attendee')
            a.staffing = True
            a._staffing_adjustments()
            assert a.ribbon_ints == [c.VOLUNTEER_RIBBON]
            assert not unset_volunteering.called

    def test_yes_to_no_ribbon(self, unset_volunteering, prevent_presave_adjustments):
        with Session() as session:
            a = session.attendee(first_name='Regular', last_name='Volunteer')
            a.ribbon = ''
            a._staffing_adjustments()
            assert unset_volunteering.called

    def test_yes_to_no_volunteering(self, unset_volunteering, prevent_presave_adjustments):
        with Session() as session:
            a = session.attendee(first_name='Regular', last_name='Volunteer')
            a.staffing = False
            a._staffing_adjustments()
            assert unset_volunteering.called


class TestBadgeAdjustments:
    @pytest.fixture(autouse=True)
    def mock_attendee_session(self, monkeypatch):
        monkeypatch.setattr(Attendee, 'session', Mock())
        Attendee.session.get_next_badge_num = Mock(return_value=123)

    @pytest.fixture
    def fully_paid(self, monkeypatch):
        monkeypatch.setattr(Attendee, 'paid', c.HAS_PAID)
        monkeypatch.setattr(Attendee, 'amount_unpaid', 0)

    def test_group_to_attendee(self):
        a = Attendee(badge_type=c.PSEUDO_GROUP_BADGE)
        a._badge_adjustments()
        assert a.badge_type == c.ATTENDEE_BADGE and a.ribbon == ''

    def test_dealer_to_attendee(self):
        a = Attendee(badge_type=c.PSEUDO_DEALER_BADGE)
        a._badge_adjustments()
        assert a.badge_type == c.ATTENDEE_BADGE and a.ribbon_ints == [c.DEALER_RIBBON]


class TestStatusAdjustments:
    def test_set_paid_to_complete(self):
        a = Attendee(paid=c.HAS_PAID, badge_status=c.NEW_STATUS, first_name='Paid', placeholder=False)
        a._status_adjustments()
        assert a.badge_status == c.COMPLETED_STATUS

    def test_set_comped_to_complete(self):
        a = Attendee(paid=c.NEED_NOT_PAY, badge_status=c.NEW_STATUS, first_name='Paid', placeholder=False)
        a._status_adjustments()
        assert a.badge_status == c.COMPLETED_STATUS

    def test_set_group_paid_to_complete(self, monkeypatch):
        monkeypatch.setattr(Group, 'amount_unpaid', 0)
        g = Group()
        a = Attendee(
            paid=c.PAID_BY_GROUP,
            badge_status=c.NEW_STATUS,
            first_name='Paid',
            placeholder=False,
            group=g,
            group_id=g.id)

        a._status_adjustments()
        assert a.badge_status == c.COMPLETED_STATUS

    def test_unpaid_group_not_completed(self, monkeypatch):
        monkeypatch.setattr(Group, 'amount_unpaid', 100)
        g = Group()
        a = Attendee(paid=c.PAID_BY_GROUP, badge_status=c.NEW_STATUS, first_name='Paid', placeholder=False, group=g)
        a._status_adjustments()
        assert a.badge_status == c.NEW_STATUS

    def test_placeholder_not_completed(self):
        a = Attendee(paid=c.NEED_NOT_PAY, badge_status=c.NEW_STATUS, first_name='Paid', placeholder=True)
        a._status_adjustments()
        assert a.badge_status == c.NEW_STATUS

    def test_unassigned_not_completed(self):
        a = Attendee(paid=c.NEED_NOT_PAY, badge_status=c.NEW_STATUS, first_name='')
        a._status_adjustments()
        assert a.badge_status == c.NEW_STATUS

    def test_banned_to_deferred(self, monkeypatch):
        a = Attendee(paid=c.HAS_PAID, badge_status=c.NEW_STATUS, first_name='Paid', placeholder=False)
        monkeypatch.setattr(Attendee, 'banned', True)
        a._status_adjustments()
        assert a.badge_status == c.WATCHED_STATUS


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

            for status in [c.NEW_STATUS, c.INVALID_STATUS, c.REFUNDED_STATUS]:
                session.add(Attendee(
                    placeholder=True,
                    first_name='Duplicate',
                    last_name=c.BADGE_STATUS[status],
                    email='duplicate@example.com',
                    zip_code='12345',
                    badge_status=status
                ))
                session.add(Attendee(
                    placeholder=True,
                    first_name='Duplicate',
                    last_name=c.BADGE_STATUS[status],
                    email='duplicate@example.com',
                    zip_code='12345',
                    badge_status=c.COMPLETED_STATUS
                ))

            return attendee.id

    def test_search_not_found(self):
        with Session() as session:
            pytest.raises(
                ValueError, session.lookup_attendee, 'Searchable', 'Attendee', 'searchable@example.com', 'xxxxx')
            pytest.raises(ValueError, session.lookup_attendee, 'XXX', 'XXX', 'searchable@example.com', '12345')
            pytest.raises(ValueError, session.lookup_attendee, 'Searchable', 'Attendee', 'xxx', '12345')

    def test_search_basic(self, searchable):
        with Session() as session:
            assert str(searchable) == session.lookup_attendee(
                'Searchable', 'Attendee', 'searchable@example.com', '12345').id

    def test_search_case_insensitive(self, searchable):
        with Session() as session:
            assert str(searchable) == session.lookup_attendee(
                'searchablE', 'attendeE', 'seArchAble@exAmple.com', '12345').id

    def test_search_multi_word_names(self):
        with Session() as session:
            assert session.lookup_attendee('Two First', 'Names', 'searchable@example.com', '12345')
            assert session.lookup_attendee('Two', 'Last Names', 'searchable@example.com', '12345')

    def test_search_ordered_by_badge_status(self):
        with Session() as session:
            for status in [c.NEW_STATUS, c.INVALID_STATUS, c.REFUNDED_STATUS]:
                attendee = session.lookup_attendee(
                    'Duplicate', c.BADGE_STATUS[status], 'duplicate@example.com', '12345')
                assert attendee.badge_status == c.COMPLETED_STATUS


class TestExtraDonationValidations:

    def test_extra_donation_nan(self):
        assert "What you entered for Extra Donation (blah) isn't even a number" \
            == extra_donation_valid(Attendee(extra_donation="blah"))

    def test_extra_donation_below_zero(self):
        assert "Extra Donation must be a number that is 0 or higher." \
            == extra_donation_valid(Attendee(extra_donation=-10))

    def test_extra_donation_valid(self):
        assert None is extra_donation_valid(Attendee(extra_donation=10))


class TestPhoneNumberValidations:

    @pytest.mark.parametrize('number', [
        # valid US numbers
        '7031234567',
        '703 123 4567',
        '(641) 123 4567',
        '803-123-4567',
        '(210)123-4567',
        '12071234567',
        '(202)fox-trot',
        '+1 (202) 123-4567',

        # valid international numbers
        # all international numbers must have a leading +
        '+44 20 7946 0974',
        '+442079460974',
        '+44 7700 900927',
        '+61 491 570 156',
        '+36 55 889 752',
        '+353 20 914 9510',
        '+49 033933-88213'
    ])
    def test_valid_number(self, number):
        assert not _invalid_phone_number(number)

    @pytest.mark.parametrize('number', [
        # invalid US numbers
        # missing digits
        '304123456',
        '(864) 123 456',
        '228-12-4567',
        # too many digits
        '405 123 45678',
        '701 1234 4567',
        # invalid characters
        'f',
        '404\\404 4040',
        # normally a valid US number, but we want the area code
        '123-4567',

        # invalid international numbers
        '+1234567890',
        '+41458d98e5',
        '+44,4930222'
    ])
    def test_invalid_number(selfself, number):
        assert _invalid_phone_number(number)


class TestNormalizedEmail:
    def test_good_email(self):
        attendee = Attendee(email='joe@gmail.com')
        assert attendee.normalized_email == 'joe@gmailcom'

    def test_dots(self):
        attendee = Attendee(email='j.o.e@gmail.com')
        assert attendee.normalized_email == 'joe@gmailcom'

    def test_capitalized_beginning(self):
        attendee = Attendee(email='JOE@gmail.com')
        assert attendee.normalized_email == 'joe@gmailcom'

    def test_capitalized_end(self):
        attendee = Attendee(email='joe@GMAIL.COM')
        assert attendee.normalized_email == 'joe@gmailcom'

    def test_alternating_caps(self):
        attendee = Attendee(email='jOe@GmAiL.cOm')
        assert attendee.normalized_email == 'joe@gmailcom'

    def test_empty_string(self):
        attendee = Attendee(email='')
        assert attendee.normalized_email == ''
