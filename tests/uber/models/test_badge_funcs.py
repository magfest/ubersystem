from datetime import datetime, timedelta

import pytest
from pytz import UTC

from uber.badge_funcs import needs_badge_num, reset_badge_if_unchanged
from uber.config import c
from uber.models import Attendee, Session
from uber.decorators import presave_adjustment
from uber.utils import check


@pytest.fixture
def session(request):
    session = Session().session
    request.addfinalizer(session.close)
    check_ranges(session)
    for badge_type, badge_name in [(c.STAFF_BADGE, 'Staff'), (c.CONTRACTOR_BADGE, 'Contractor')]:
        for number in ['One', 'Two', 'Three', 'Four', 'Five']:
            setattr(session, '{}_{}'.format(badge_name, number).lower(),
                    session.attendee(badge_type=badge_type, first_name=number))
    setattr(session, 'regular_attendee', session.attendee(first_name='Regular', last_name='Attendee'))
    session.regular_attendee.paid = c.HAS_PAID
    session.regular_attendee.checked_in = datetime.now(UTC)
    session.regular_attendee.badge_num = 3000
    session.commit()
    return session


@pytest.fixture(autouse=True)
def teardown_range_check(request):
    def _check_range():
        if c.SHIFT_CUSTOM_BADGES:
            with Session() as session:
                check_ranges(session)
        request.addfinalizer(_check_range)


def check_ranges(session):
    for badge_type in [c.STAFF_BADGE, c.CONTRACTOR_BADGE]:
        actual = [a.badge_num for a in session.query(Attendee)
                                              .filter_by(badge_type=badge_type)
                                              .order_by(Attendee.badge_num).all()
                  if not a.is_unassigned]
        expected = list(range(*c.BADGE_RANGES[badge_type])[:len(actual)])
        assert actual == expected


def change_badge(session, attendee, new_type, new_num=None, expected_num=None):
    old_type, old_num = attendee.badge_type, attendee.badge_num
    attendee.badge_type, attendee.badge_num = new_type, new_num
    reset_badge_if_unchanged(attendee, old_type, old_num)
    session.commit()
    session.refresh(attendee)
    assert new_type == attendee.badge_type
    assert (new_num if expected_num is None else expected_num) == attendee.badge_num


class TestNeedsBadgeNum:
    def test_numbered_badges_off(self, session, monkeypatch):
        monkeypatch.setattr(c, 'NUMBERED_BADGES', False)
        assert not needs_badge_num(badge_type=c.STAFF_BADGE)
        assert not needs_badge_num(session.regular_attendee)

    def test_preassigned_by_type(self, session):
        assert needs_badge_num(badge_type=c.STAFF_BADGE)

    def test_non_preassigned_by_type(self, session):
        assert not needs_badge_num(badge_type=c.ATTENDEE_BADGE)

    def test_preassigned_ready(self, session):
        assert needs_badge_num(session.staff_one)

    def test_non_preassigned_ready(self, session):
        assert needs_badge_num(attendee=session.regular_attendee)

    def test_non_preassigned_not_checked_in(self, session):
        session.regular_attendee.checked_in = None
        assert session.regular_attendee.badge_type not in c.PREASSIGNED_BADGE_TYPES
        assert not needs_badge_num(attendee=session.regular_attendee)

    def test_preassigned_unassigned(self, session):
        session.staff_one.first_name = ''
        assert session.staff_one.badge_type in c.PREASSIGNED_BADGE_TYPES
        assert needs_badge_num(attendee=session.staff_one)

    def test_non_preassigned_unassigned(self, session):
        session.regular_attendee.first_name = ''
        assert session.regular_attendee.badge_type not in c.PREASSIGNED_BADGE_TYPES
        assert session.regular_attendee.checked_in
        assert needs_badge_num(attendee=session.regular_attendee)

    def test_preassigned_not_paid(self, session):
        session.staff_one.paid = c.NOT_PAID
        assert not needs_badge_num(attendee=session.staff_one)

    def test_non_preassigned_not_paid(self, session):
        session.regular_attendee.paid = c.NOT_PAID
        assert not needs_badge_num(attendee=session.regular_attendee)

    def test_preassigned_invalid_status(self, session):
        session.staff_one.badge_status = c.INVALID_STATUS
        assert not needs_badge_num(attendee=session.staff_one)

    def test_non_preassigned_invalid_status(self, session):
        session.regular_attendee.badge_status = c.INVALID_STATUS
        assert not needs_badge_num(attendee=session.regular_attendee)


class TestGetNextBadgeNum:
    def test_preassigned(self, session):
        assert 6 == session.get_next_badge_num(c.STAFF_BADGE)

    def test_preassigned_with_new(self, session):
        session.add(Attendee(badge_type=c.STAFF_BADGE, badge_num=6))
        assert 7 == session.get_next_badge_num(c.STAFF_BADGE)

    def test_preassigned_two_new(self, session):
        session.add(Attendee(badge_type=c.STAFF_BADGE, badge_num=6))
        session.add(Attendee(badge_type=c.STAFF_BADGE, badge_num=7))
        assert 8 == session.get_next_badge_num(c.STAFF_BADGE)

    def test_preassigned_with_dirty(self, session):
        session.supporter_five.badge_type, session.supporter_five.badge_num = c.STAFF_BADGE, 6
        assert 7 == session.get_next_badge_num(c.STAFF_BADGE)
        session.expunge(session.supporter_five)

    def test_preassigned_two_dirty(self, session):
        session.supporter_five.badge_type, session.supporter_five.badge_num = c.STAFF_BADGE, 6
        session.supporter_four.badge_type, session.supporter_four.badge_num = c.STAFF_BADGE, 7
        assert 8 == session.get_next_badge_num(c.STAFF_BADGE)
        session.expunge(session.supporter_four)
        session.expunge(session.supporter_five)

    def test_non_preassigned(self, session):
        assert 3001 == session.get_next_badge_num(c.ATTENDEE_BADGE)

    def test_non_preassigned_with_new(self, session):
        session.add(Attendee(badge_type=c.ATTENDEE_BADGE, checked_in=datetime.now(UTC), badge_num=3001))
        assert 3002 == session.get_next_badge_num(c.ATTENDEE_BADGE)

    def test_non_preassigned_two_new(self, session):
        session.add(Attendee(badge_type=c.ATTENDEE_BADGE, checked_in=datetime.now(UTC), badge_num=3001))
        session.add(Attendee(badge_type=c.ATTENDEE_BADGE, checked_in=datetime.now(UTC), badge_num=3002))
        assert 3003 == session.get_next_badge_num(c.ATTENDEE_BADGE)

    def test_non_preassigned_with_dirty(self, session):
        session.supporter_five.badge_type, session.supporter_five.badge_num = c.ATTENDEE_BADGE, 3001
        assert 3002 == session.get_next_badge_num(c.ATTENDEE_BADGE)
        session.expunge(session.supporter_five)

    def test_non_preassigned_two_dirty(self, session):
        session.supporter_five.badge_type, session.supporter_five.badge_num = c.ATTENDEE_BADGE, 3001
        session.supporter_four.badge_type, session.supporter_five.badge_num = c.ATTENDEE_BADGE, 3002
        assert 3003 == session.get_next_badge_num(c.ATTENDEE_BADGE)
        session.expunge(session.supporter_four)
        session.expunge(session.supporter_five)

    def test_diff_type_new(self, session):
        session.add(Attendee(badge_type=c.ATTENDEE_BADGE, checked_in=datetime.now(UTC), badge_num=6))
        assert 7 == session.get_next_badge_num(c.STAFF_BADGE)

    def test_diff_type_dirty(self, session):
        session.supporter_five.badge_type, session.supporter_five.badge_num = c.ATTENDEE_BADGE, 6
        assert 7 == session.get_next_badge_num(c.STAFF_BADGE)
        session.expunge(session.supporter_five)

    def test_ignore_too_high(self, session):
        over_max = c.BADGE_RANGES[c.STAFF_BADGE][1] + 10
        session.add(Attendee(badge_type=c.STAFF_BADGE, badge_num=over_max))
        assert 6 == session.get_next_badge_num(c.STAFF_BADGE)

    def test_ignore_too_low(self, session):
        under_min = c.BADGE_RANGES[c.STAFF_BADGE][0] - 10
        session.add(Attendee(badge_type=c.STAFF_BADGE, badge_num=under_min))
        assert 6 == session.get_next_badge_num(c.STAFF_BADGE)

    def test_badge_range_full(self, session, monkeypatch):
        monkeypatch.setitem(c.BADGE_RANGES, c.STAFF_BADGE, [1, 5])
        with pytest.raises(AssertionError) as message:
            session.get_next_badge_num(c.STAFF_BADGE)
        assert 'There are no more badge numbers available in this range!' == str(message.value)


class TestAutoBadgeNum:
    def test_preassigned_no_gap(self, session):
        assert 6 == session.auto_badge_num(c.STAFF_BADGE)

    def test_preassigned_with_gap(self, session):
        session.supporter_five.badge_type, session.supporter_five.badge_num = c.STAFF_BADGE, 12
        session.supporter_four.badge_type, session.supporter_four.badge_num = c.STAFF_BADGE, 6
        session.commit()
        assert 7 == session.auto_badge_num(c.STAFF_BADGE)

    def test_preassigned_with_two_gaps(self, session):
        session.supporter_five.badge_type, session.supporter_five.badge_num = c.STAFF_BADGE, 12
        session.supporter_four.badge_type, session.supporter_four.badge_num = c.STAFF_BADGE, 6
        session.supporter_three.badge_type, session.supporter_three.badge_num = c.STAFF_BADGE, 8
        session.commit()
        assert 7 == session.auto_badge_num(c.STAFF_BADGE)

    def test_non_preassigned_no_gap(self, session):
        assert 3001 == session.auto_badge_num(c.ATTENDEE_BADGE)

    def test_non_preassigned_with_gap(self, session):
        session.add(Attendee(
            badge_type=c.ATTENDEE_BADGE,
            checked_in=datetime.now(UTC),
            first_name="3002",
            paid=c.HAS_PAID,
            badge_num=3003))
        session.add(Attendee(
            badge_type=c.ATTENDEE_BADGE,
            checked_in=datetime.now(UTC),
            first_name="3000",
            paid=c.HAS_PAID,
            badge_num=3001))
        session.commit()
        assert 3002 == session.auto_badge_num(c.ATTENDEE_BADGE)

    def test_dupe_nums(self, session, monkeypatch):
        session.add(Attendee(
            badge_type=c.ATTENDEE_BADGE,
            checked_in=datetime.now(UTC),
            first_name="3002",
            paid=c.HAS_PAID,
            badge_num=3001))
        session.add(Attendee(
            badge_type=c.ATTENDEE_BADGE,
            checked_in=datetime.now(UTC),
            first_name="3000",
            paid=c.HAS_PAID,
            badge_num=3001))

        # Skip the badge adjustments here, which prevent us from setting duplicate numbers
        @presave_adjustment
        def _empty_adjustment(self):
            pass

        monkeypatch.setattr(Attendee, '_badge_adjustments', _empty_adjustment)
        session.commit()
        assert 3002 == session.auto_badge_num(c.ATTENDEE_BADGE)

    def test_diff_type_with_num_in_range(self, session, monkeypatch):
        session.add(Attendee(badge_type=c.CONTRACTOR_BADGE, badge_num=6))

        # We want to force the badge number we set even though it's incorrect
        @presave_adjustment
        def _empty_adjustment(self):
            pass

        monkeypatch.setattr(Attendee, '_badge_adjustments', _empty_adjustment)
        session.commit()
        assert 7 == session.auto_badge_num(c.STAFF_BADGE)

    def test_beginning_skip(self, session):
        session.add(Attendee(
            badge_type=c.ATTENDEE_BADGE,
            checked_in=datetime.now(UTC),
            first_name="3002",
            paid=c.HAS_PAID,
            badge_num=3002))
        session.commit()
        assert 3001 == session.auto_badge_num(c.ATTENDEE_BADGE)


class TestShiftBadges:
    @pytest.fixture(autouse=True)
    def before_print_badges_deadline(self, before_printed_badge_deadline):
        pass

    def staff_badges(self, session):
        # This loads badges from the session, which isn't reloaded, so the result is not always what you'd expect
        staffers = session.query(Attendee).filter(
            Attendee.badge_status != c.INVALID_STATUS, Attendee.badge_type == c.STAFF_BADGE).all()
        return sorted(a.badge_num for a in staffers)

    def test_shift_not_enabled(self, session, monkeypatch, custom_badges_ordered):
        session.shift_badges(c.STAFF_BADGE, 2)
        assert [1, 2, 3, 4, 5] == self.staff_badges(session)

    def test_custom_badges_ordered(self, session, monkeypatch, after_printed_badge_deadline):
        assert c.AFTER_PRINTED_BADGE_DEADLINE
        session.shift_badges(c.STAFF_BADGE, 2)
        assert [1, 2, 3, 4, 5] == self.staff_badges(session)

    def test_shift_middle_to_end(self, session):
        session.shift_badges(c.STAFF_BADGE, 2)
        assert [1, 1, 2, 3, 4] == self.staff_badges(session)

    def test_shift_beginning_to_end(self, session):
        session.shift_badges(c.STAFF_BADGE, 1)
        assert [0, 1, 2, 3, 4] == self.staff_badges(session)

    def test_shift_middle_to_middle(self, session):
        session.shift_badges(c.STAFF_BADGE, 3, until=4)
        assert [1, 2, 2, 3, 5] == self.staff_badges(session)

    def test_shift_up_middle_to_end(self, session):
        session.shift_badges(c.STAFF_BADGE, 3, up=True)
        assert [1, 2, 4, 5, 6] == self.staff_badges(session)

    def test_shift_up_beginning_to_end(self, session):
        session.shift_badges(c.STAFF_BADGE, 1, up=True)
        assert [2, 3, 4, 5, 6] == self.staff_badges(session)

    def test_shift_up_middle_to_middle(self, session):
        session.shift_badges(c.STAFF_BADGE, 2, until=3, up=True)
        assert [1, 3, 4, 4, 5] == self.staff_badges(session)

    def test_shift_up_end(self, session):
        session.shift_badges(c.STAFF_BADGE, 5, up=True)
        assert [1, 2, 3, 4, 6] == self.staff_badges(session)


class TestBadgeTypeChange:
    def test_end_to_next(self, session):
        change_badge(session, session.supporter_five, c.STAFF_BADGE, expected_num=6)

    def test_end_to_end(self, session):
        change_badge(session, session.supporter_five, c.STAFF_BADGE, new_num=6)

    def test_end_to_boundary(self, session):
        change_badge(session, session.supporter_five, c.STAFF_BADGE, new_num=5)

    def test_end_to_middle(self, session):
        change_badge(session, session.supporter_five, c.STAFF_BADGE, new_num=3)

    def test_end_to_beginning(self, session):
        change_badge(session, session.supporter_five, c.STAFF_BADGE, new_num=1)

    def test_end_to_over(self, session):
        change_badge(session, session.supporter_five, c.STAFF_BADGE, new_num=7)

    def test_middle_to_next(self, session):
        change_badge(session, session.supporter_three, c.STAFF_BADGE, expected_num=6)

    def test_beginning_to_next(self, session):
        change_badge(session, session.supporter_one, c.STAFF_BADGE, expected_num=6)

    def test_to_non_preassigned(self, session):
        change_badge(session, session.supporter_five, c.ATTENDEE_BADGE)

    def test_from_non_preassigned(self, session):
        change_badge(session, session.regular_attendee, c.STAFF_BADGE, expected_num=6)


class TestInternalBadgeChange:
    def test_beginning_to_end(self, session):
        change_badge(session, session.staff_one, c.STAFF_BADGE, new_num=5)

    def test_beginning_to_next(self, session):
        change_badge(session, session.staff_one, c.STAFF_BADGE, expected_num=1)

    def test_beginning_plus_one(self, session):
        change_badge(session, session.staff_one, c.STAFF_BADGE, new_num=2)

    def test_beginning_to_middle(self, session):
        change_badge(session, session.staff_one, c.STAFF_BADGE, new_num=4)

    def test_end_to_beginning(self, session):
        change_badge(session, session.staff_five, c.STAFF_BADGE, new_num=1)

    def test_end_minus_one(self, session):
        change_badge(session, session.staff_five, c.STAFF_BADGE, new_num=4)

    def test_end_to_middle(self, session):
        change_badge(session, session.staff_five, c.STAFF_BADGE, new_num=2)

    def test_middle_plus_one(self, session):
        change_badge(session, session.staff_three, c.STAFF_BADGE, new_num=4)

    def test_middle_minus_one(self, session):
        change_badge(session, session.staff_three, c.STAFF_BADGE, new_num=2)

    def test_middle_up(self, session):
        change_badge(session, session.staff_two, c.STAFF_BADGE, new_num=4)

    def test_middle_down(self, session):
        change_badge(session, session.staff_four, c.STAFF_BADGE, new_num=2)

    def test_self_assignment(self, session):
        assert 'Attendee is already Staff with badge 1' == reset_badge_if_unchanged(
            session.staff_one, c.STAFF_BADGE, 1)
        assert 'Attendee is already Staff with badge 3' == reset_badge_if_unchanged(
            session.staff_three, c.STAFF_BADGE, 3)
        assert 'Attendee is already Staff with badge 5' == reset_badge_if_unchanged(
            session.staff_five, c.STAFF_BADGE, 5)


class TestBadgeDeletion:
    def test_beginning_delete(self, session):
        session.delete(session.staff_one)
        session.commit()

    def test_middle_delete(self, session):
        session.delete(session.staff_three)
        session.commit()

    def test_end_delete(self, session):
        session.delete(session.staff_five)
        session.commit()

    def test_non_preassigned_deletion(self, session):
        session.delete(session.query(Attendee).filter_by(badge_type=c.ATTENDEE_BADGE).first())
        session.commit()

    def test_delete_shift_not_enabled(self, session, monkeypatch):
        monkeypatch.setattr(c, 'SHIFT_CUSTOM_BADGES', False)
        session.delete(session.staff_one)
        session.commit()

    def test_delete_custom_badges_ordered(self, session, monkeypatch):
        monkeypatch.setattr(c, 'PRINTED_BADGE_DEADLINE', datetime.now(UTC)-timedelta(days=1))
        session.delete(session.staff_one)
        session.commit()


class TestShiftOnChange:
    @pytest.fixture(autouse=True)
    def before_print_badges_deadline(self, before_printed_badge_deadline):
        pass

    def staff_badges(self, session):
        # This loads badges from the session, which isn't reloaded, so the result is not always what you'd expect
        staffers = session.query(Attendee).filter(
            Attendee.badge_status != c.INVALID_STATUS, Attendee.badge_type == c.STAFF_BADGE).all()
        return sorted(a.badge_num for a in staffers)

    def test_shift_on_add(self, session):
        assert 'Badge updated' == session.update_badge(Attendee(
            first_name='NewStaff', paid=c.NEED_NOT_PAY, badge_type=c.STAFF_BADGE, badge_num=2), None, None)
        assert session.staff_two.badge_num == 3
        assert [1, 3, 4, 5, 6] == self.staff_badges(session)

    def test_shift_on_badge_type_change(self, session):
        session.staff_one.badge_type = c.CONTRACTOR_BADGE
        session.staff_one.badge_num = None
        assert 'Badge updated' == session.update_badge(session.staff_one, c.STAFF_BADGE, 1)
        assert session.staff_two.badge_num == 1
        assert [1, 2, 3, 4, 505] == self.staff_badges(session)

    def test_shift_both_badge_types(self, session):
        session.staff_one.badge_type = c.CONTRACTOR_BADGE
        session.staff_one.badge_num = 503
        assert 'Badge updated' == session.update_badge(session.staff_one, c.STAFF_BADGE, 1)
        assert session.staff_two.badge_num == 1
        assert session.supporter_three.badge_num == 502
        assert [1, 2, 3, 4, 503] == self.staff_badges(session)

    def test_shift_on_remove(self, session):
        session.delete(session.staff_one)
        session.commit()
        assert session.staff_two.badge_num == 1
        assert [1, 2, 3, 4] == self.staff_badges(session)

    def test_shift_on_invalidate(self, session):
        session.staff_one.badge_status = c.INVALID_STATUS
        session.commit()
        assert not session.staff_one.badge_num
        assert session.staff_two.badge_num == 1
        assert [1, 2, 3, 4] == self.staff_badges(session)

    def test_dont_shift_if_gap(self, session):
        session.staff_five.badge_num = 10
        session.commit()
        session.update_badge(Attendee(
            first_name='NewStaff', paid=c.NEED_NOT_PAY, badge_type=c.STAFF_BADGE, badge_num=5), None, None)
        session.commit()
        assert [1, 2, 3, 4, 10] == self.staff_badges(session)

    def test_no_double_shift(self, session):
        # Regression test -- presave adjustments used to try shifting badges
        # after they'd already been shifted by update_badge()
        change_badge(session, session.staff_three, c.ATTENDEE_BADGE)
        assert session.staff_four.badge_num == 3
        assert session.staff_five.badge_num == 4


class TestBadgeValidations:
    def test_dupe_badge_num(self, session, monkeypatch):
        monkeypatch.setattr(c, 'SHIFT_CUSTOM_BADGES', False)
        session.staff_two.badge_num = session.staff_two.badge_num
        session.staff_two.badge_num = 1
        assert 'That badge number already belongs to {!r}'.format(session.staff_one.full_name) \
            == check(session.staff_two)

    def test_invalid_badge_num(self, session):
        session.staff_one.badge_num = 'Junk Badge Number'
        assert '{!r} is not a valid badge number'.format(session.staff_one.badge_num) == check(session.staff_one)

    def test_no_more_custom_badges(self, admin_attendee, session, monkeypatch, after_printed_badge_deadline):
        session.regular_attendee.badge_type = session.regular_attendee.badge_type
        session.regular_attendee.badge_type = c.STAFF_BADGE
        session.regular_attendee.badge_num = None
        assert 'Custom badges have already been ordered so you cannot use this badge type' \
            == check(session.regular_attendee)

    @pytest.mark.parametrize('department,expected', [
        (c.STOPS, None),
        (c.REGDESK, None),
        (c.CONSOLE, 'Custom badges have already been ordered so you cannot use this badge type'),
    ])
    def test_more_custom_badges_for_dept_head(
            self, admin_attendee, session, monkeypatch, after_printed_badge_deadline, department, expected):

        monkeypatch.setattr(Attendee, 'is_dept_head_of', lambda s, d: d == department)
        session.regular_attendee.badge_type = session.regular_attendee.badge_type
        session.regular_attendee.badge_type = c.STAFF_BADGE
        session.regular_attendee.badge_num = None
        assert expected == check(session.regular_attendee)

    def test_out_of_badge_type(self, session, monkeypatch, before_printed_badge_deadline):
        monkeypatch.setitem(c.BADGE_RANGES, c.STAFF_BADGE, [1, 5])
        session.regular_attendee.badge_type = session.regular_attendee.badge_type
        session.regular_attendee.badge_type = c.STAFF_BADGE
        session.regular_attendee.badge_num = None
        assert 'There are no more badges available for that type' == check(session.regular_attendee)
