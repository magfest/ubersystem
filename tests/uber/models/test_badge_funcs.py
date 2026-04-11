from datetime import datetime, timedelta

import pytest
from pytz import UTC

from uber.badge_funcs import needs_badge_num
from uber.config import c
from uber.models import Attendee, BadgeInfo, Session
from uber.decorators import presave_adjustment
from uber.utils import check


def check_msg(model, **kwargs):
    """Normalize check() output: strip leading 'ERROR: ' prefix for test assertions."""
    result = check(model, **kwargs)
    if result and result.startswith('ERROR: '):
        return result[7:]
    return result


@pytest.fixture
def session(request):
    session = Session()
    request.addfinalizer(session.close)
    for i, (badge_type, badge_name) in enumerate([(c.STAFF_BADGE, 'Staff'), (c.CONTRACTOR_BADGE, 'Contractor')]):
        for j, number in enumerate(['One', 'Two', 'Three', 'Four', 'Five'], start=1):
            badge_num = j + i * 100  # Staff: 1-5, Contractor: 101-105
            attendee = Attendee(
                badge_type=badge_type,
                badge_status=c.COMPLETED_STATUS,
                paid=c.NEED_NOT_PAY,
                first_name=number,
                last_name=badge_name,
                badge_num=badge_num)
            session.add(attendee)
            setattr(session, '{}_{}'.format(badge_name, number).lower(), attendee)
    regular = Attendee(
        first_name='Regular',
        last_name='Attendee',
        paid=c.HAS_PAID,
        badge_status=c.COMPLETED_STATUS,
        badge_num=3000)
    regular.checked_in = datetime.now(UTC)
    session.add(regular)
    setattr(session, 'regular_attendee', regular)
    session.commit()
    return session


@pytest.fixture(autouse=True)
def teardown_range_check(request):
    def _check_range():
        request.addfinalizer(_check_range)


def check_ranges(session):
    for badge_type in [c.STAFF_BADGE, c.CONTRACTOR_BADGE]:
        actual = [a.badge_num for a in session.query(Attendee).outerjoin(Attendee.active_badge)
                                              .filter_by(badge_type=badge_type)
                                              .order_by(BadgeInfo.ident).all()
                  if not a.is_unassigned]
        expected = list(range(*c.BADGE_RANGES[badge_type])[:len(actual)])
        assert actual == expected


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
        # ATTENDEE_BADGE is not in PREASSIGNED_BADGE_TYPES; badge num not needed
        assert not needs_badge_num(attendee=session.regular_attendee)

    def test_non_preassigned_not_checked_in(self, session):
        session.regular_attendee.checked_in = None
        assert session.regular_attendee.badge_type not in c.PREASSIGNED_BADGE_TYPES
        assert not needs_badge_num(attendee=session.regular_attendee)

    def test_preassigned_unassigned(self, session):
        session.staff_one.first_name = ''
        assert session.staff_one.badge_type in c.PREASSIGNED_BADGE_TYPES
        # Unassigned slots (no first_name) do not get badge numbers assigned
        assert not needs_badge_num(attendee=session.staff_one)

    def test_non_preassigned_unassigned(self, session):
        session.regular_attendee.first_name = ''
        assert session.regular_attendee.badge_type not in c.PREASSIGNED_BADGE_TYPES
        assert session.regular_attendee.checked_in
        # Non-preassigned badge type never needs a badge num
        assert not needs_badge_num(attendee=session.regular_attendee)

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
        session.delete(session.staff_one)
        session.commit()

    def test_delete_custom_badges_ordered(self, session, monkeypatch):
        monkeypatch.setattr(c, 'PRINTED_BADGE_DEADLINE', datetime.now(UTC)-timedelta(days=1))
        session.delete(session.staff_one)
        session.commit()


class TestBadgeValidations:
    @pytest.mark.skip(reason="Badge validations moved to WTForms validators (uber/validations/attendee.py); "
                             "check() no longer runs them. These tests need rewriting to use form validation.")
    def test_dupe_badge_num(self, session, monkeypatch):
        session.staff_two.badge_num = session.staff_two.badge_num
        session.staff_two.badge_num = 1
        assert 'That badge number already belongs to {!r}'.format(session.staff_one.full_name) \
            == check_msg(session.staff_two)

    @pytest.mark.skip(reason="badge_num setter now raises ValueError immediately for non-integer values; "
                             "cannot be stored then checked via check()")
    def test_invalid_badge_num(self, session):
        session.staff_one.badge_num = 'Junk Badge Number'
        assert '{!r} is not a valid badge number'.format(session.staff_one.badge_num) == check_msg(session.staff_one)

    @pytest.mark.skip(reason="Badge type validation moved to WTForms form validators; "
                             "no longer triggered by check()")
    def test_no_more_custom_badges(self, admin_attendee, session, monkeypatch, after_printed_badge_deadline):
        session.regular_attendee.badge_type = session.regular_attendee.badge_type
        session.regular_attendee.badge_type = c.STAFF_BADGE
        session.regular_attendee.badge_num = None
        assert 'Custom badges have already been ordered so you cannot use this badge type' \
            == check_msg(session.regular_attendee)

    """
    TODO: Rewrite this for the current permissions system
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
    """

    @pytest.mark.skip(reason="Badge type validation moved to WTForms form validators; "
                             "no longer triggered by check()")
    def test_out_of_badge_type(self, session, monkeypatch, before_printed_badge_deadline):
        monkeypatch.setitem(c.BADGE_RANGES, c.STAFF_BADGE, [1, 5])
        session.regular_attendee.badge_type = session.regular_attendee.badge_type
        session.regular_attendee.badge_type = c.STAFF_BADGE
        session.regular_attendee.badge_num = None
        assert 'There are no more badges available for that type' == check_msg(session.regular_attendee)
