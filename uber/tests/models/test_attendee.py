from uber.tests import *


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
        monkeypatch.setattr(Attendee, 'age_group_conf', {'discount': 999})  # makes badge_cost free unless overridden_price is set
        assert 0 == Attendee().total_cost
        assert 5 == Attendee(amount_extra=5).total_cost
        assert 10 == Attendee(overridden_price=10).total_cost
        assert 15 == Attendee(overridden_price=10, amount_extra=5).total_cost


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


def test_is_dept_head():
    assert not Attendee().is_dept_head
    assert Attendee(ribbon=c.DEPT_HEAD_RIBBON).is_dept_head


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


def test_is_not_transferable_trusted(monkeypatch):
    monkeypatch.setattr(Attendee, 'is_new', False)
    assert not Attendee(paid=c.HAS_PAID, trusted_depts=c.CONSOLE).is_transferable


def test_trusted_somewhere():
    assert Attendee(trusted_depts='{},{}'.format(c.ARCADE, c.CONSOLE)).trusted_somewhere
    assert Attendee(trusted_depts=str(c.CONSOLE)).trusted_somewhere
    assert not Attendee(trusted_depts='').trusted_somewhere


def test_has_personalized_badge():
    assert not Attendee().has_personalized_badge
    assert Attendee(badge_type=c.STAFF_BADGE).has_personalized_badge
    assert Attendee(badge_type=c.SUPPORTER_BADGE).has_personalized_badge
    for badge_type in [c.ATTENDEE_BADGE, c.ONE_DAY_BADGE, c.GUEST_BADGE]:
        assert not Attendee(badge_type=badge_type).has_personalized_badge


def test_takes_shifts():
    assert not Attendee().takes_shifts
    assert not Attendee(staffing=True).takes_shifts
    assert Attendee(staffing=True, assigned_depts=c.CONSOLE).takes_shifts
    assert not Attendee(staffing=True, assigned_depts=c.CON_OPS).takes_shifts
    assert Attendee(staffing=True, assigned_depts=','.join(map(str, [c.CONSOLE, c.CON_OPS]))).takes_shifts


class TestUnsetVolunteer:
    def test_basic(self):
        a = Attendee(staffing=True, trusted_depts=c.CONSOLE, requested_depts=c.CONSOLE, assigned_depts=c.CONSOLE, ribbon=c.VOLUNTEER_RIBBON, shifts=[Shift()])
        a.unset_volunteering()
        assert not a.staffing and not a.trusted_somewhere and not a.requested_depts and not a.assigned_depts and not a.shifts and a.ribbon == c.NO_RIBBON

    def test_different_ribbon(self):
        a = Attendee(ribbon=c.DEALER_RIBBON)
        a.unset_volunteering()
        assert a.ribbon == c.DEALER_RIBBON

    def test_staff_badge(self, monkeypatch):
        with Session() as session:
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

        monkeypatch.setattr(Attendee, 'is_new', False)
        a = Attendee(badge_num=1)
        a._misc_adjustments()
        assert a.checked_in

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

    def test_dept_head_invariants(self):
        a = Attendee(ribbon=c.DEPT_HEAD_RIBBON, assigned_depts=c.CONSOLE)
        a._staffing_adjustments()
        assert a.staffing
        assert a.badge_type == c.STAFF_BADGE

    def test_staffing_still_trusted_assigned(self):
        """
        After applying staffing adjustements:
        Any depts you are both trusted and assigned to should remain unchanged
        """
        a = Attendee(staffing=True,
                     assigned_depts='{},{}'.format(c.CONSOLE, c.CON_OPS),
                     trusted_depts='{},{}'.format(c.CONSOLE, c.CON_OPS))
        a._staffing_adjustments()
        assert a.assigned_to(c.CONSOLE) and a.trusted_in(c.CONSOLE)
        assert a.assigned_to(c.CON_OPS) and a.trusted_in(c.CON_OPS)

    def test_staffing_no_longer_trusted_unassigned(self):
        """
        After applying staffing adjustements:
        1) Any depts you are trusted in but not assigned to, you should not longer remain trusted in
        2) Any depts you are assigned to but not trusted in, you should remain untrusted in
        """
        a = Attendee(staffing=True,
                     assigned_depts='{},{}'.format(c.CONSOLE, c.CON_OPS),
                     trusted_depts='{},{}'.format(c.ARCADE, c.CON_OPS))
        a._staffing_adjustments()
        assert a.assigned_to(c.CONSOLE) and not a.trusted_in(c.CONSOLE)
        assert not a.assigned_to(c.ARCADE) and not a.trusted_in(c.ARCADE)
        assert a.assigned_to(c.CON_OPS) and a.trusted_in(c.CON_OPS)

    def test_unpaid_dept_head(self):
        a = Attendee(ribbon=c.DEPT_HEAD_RIBBON)
        a._staffing_adjustments()
        assert a.paid == c.NEED_NOT_PAY

    def test_under_18_at_con(self, at_con, unset_volunteering):
        a = Attendee(age_group=c.UNDER_18)
        a._staffing_adjustments()
        assert not unset_volunteering.called

    def test_staffers_need_no_volunteer_ribbon(self):
        a = Attendee(badge_type=c.STAFF_BADGE, ribbon=c.VOLUNTEER_RIBBON)
        a._staffing_adjustments()
        assert a.ribbon == c.NO_RIBBON

    def test_staffers_can_have_other_ribbons(self):
        a = Attendee(badge_type=c.STAFF_BADGE, ribbon=c.DEALER_RIBBON)
        a._staffing_adjustments()
        assert a.ribbon == c.DEALER_RIBBON

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
            assert a.ribbon == c.VOLUNTEER_RIBBON
            assert not unset_volunteering.called

    def test_yes_to_no_ribbon(self, unset_volunteering, prevent_presave_adjustments):
        with Session() as session:
            a = session.attendee(first_name='Regular', last_name='Volunteer')
            a.ribbon = c.NO_RIBBON
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
        assert a.badge_type == c.ATTENDEE_BADGE and a.ribbon == c.NO_RIBBON

    def test_dealer_to_attendee(self):
        a = Attendee(badge_type=c.PSEUDO_DEALER_BADGE)
        a._badge_adjustments()
        assert a.badge_type == c.ATTENDEE_BADGE and a.ribbon == c.DEALER_RIBBON


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
        a = Attendee(paid=c.PAID_BY_GROUP, badge_status=c.NEW_STATUS, first_name='Paid', placeholder=False, group=g, group_id=g.id)
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
            return attendee.id

    def test_search_not_found(self):
        with Session() as session:
            pytest.raises(ValueError, session.lookup_attendee, 'Searchable', 'Attendee', 'searchable@example.com', 'xxxxx')
            pytest.raises(ValueError, session.lookup_attendee, 'XXX', 'XXX', 'searchable@example.com', '12345')
            pytest.raises(ValueError, session.lookup_attendee, 'Searchable', 'Attendee', 'xxx', '12345')

    def test_search_basic(self, searchable):
        with Session() as session:
            assert str(searchable) == session.lookup_attendee('Searchable', 'Attendee', 'searchable@example.com', '12345').id

    def test_search_case_insensitive(self, searchable):
        with Session() as session:
            assert str(searchable) == session.lookup_attendee('searchablE', 'attendeE', 'seArchAble@exAmple.com', '12345').id

    def test_search_multi_word_names(self):
        with Session() as session:
            assert session.lookup_attendee('Two First', 'Names', 'searchable@example.com', '12345')
            assert session.lookup_attendee('Two', 'Last Names', 'searchable@example.com', '12345')
