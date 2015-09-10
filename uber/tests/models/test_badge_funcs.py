from uber.tests import *


@pytest.fixture
def session(request):
    session = Session().session
    request.addfinalizer(session.close)
    check_ranges(session)
    for badge_type, badge_name in [(c.STAFF_BADGE, 'Staff'), (c.SUPPORTER_BADGE, 'Supporter')]:
        for number in ['One', 'Two', 'Three', 'Four', 'Five']:
            setattr(session, '{}_{}'.format(badge_name, number).lower(),
                             session.attendee(badge_type=badge_type, first_name=number))
    return session


@pytest.fixture(autouse=True)
def teardown_range_check(request):
    def _check_range():
        with Session() as session:
            check_ranges(session)
    request.addfinalizer(_check_range)


def check_ranges(session):
    for badge_type in [c.STAFF_BADGE, c.SUPPORTER_BADGE]:
        actual = [a.badge_num for a in session.query(Attendee)
                                              .filter_by(badge_type=badge_type)
                                              .order_by(Attendee.badge_num).all()
                  if not a.is_unassigned]
        expected = list(range(*c.BADGE_RANGES[badge_type])[:len(actual)])
        assert actual == expected


def change_badge(session, attendee, new_type, new_num=0, expected_num=None):
    session.change_badge(attendee, new_type, new_num)
    session.commit()
    session.refresh(attendee)
    assert new_type == attendee.badge_type
    assert (new_num if expected_num is None else expected_num) == attendee.badge_num


class TestNextBadgeNum:
    def test_non_preassigned(self, session):
        assert 0 == session.next_badge_num(c.ATTENDEE_BADGE, old_badge_num=0)

    def test_next_basic(self, session):
        assert 6 == session.next_badge_num(c.STAFF_BADGE, old_badge_num=0)

    def test_next_with_new(self, session):
        session.add(Attendee(badge_type=c.STAFF_BADGE, badge_num=6))
        assert 7 == session.next_badge_num(c.STAFF_BADGE, old_badge_num=0)

    def test_next_with_dirty(self, session):
        session.supporter_five.badge_type, session.supporter_five.badge_num = c.STAFF_BADGE, 6
        assert 7 == session.next_badge_num(c.STAFF_BADGE, old_badge_num=0)
        session.expunge(session.supporter_five)

    def test_ignore_too_high(self, session):
        over_max = c.BADGE_RANGES[c.STAFF_BADGE][1] + 10
        session.add(Attendee(badge_type=c.STAFF_BADGE, badge_num=over_max))
        assert 6 == session.next_badge_num(c.STAFF_BADGE, old_badge_num=0)

    def test_ignore_too_low(self, session):
        under_min = c.BADGE_RANGES[c.STAFF_BADGE][0] - 10
        session.add(Attendee(badge_type=c.STAFF_BADGE, badge_num=under_min))
        assert 6 == session.next_badge_num(c.STAFF_BADGE, old_badge_num=0)

    def next_badge_when_already_highest(self, session):
        assert 5 == session.next_badge_num(session.staff_five.badge_type, session.staff_five.badge_num)


class TestShiftBadges:
    def staff_badges(self, session):
        return sorted(a.badge_num for a in session.query(Attendee).filter_by(badge_type=c.STAFF_BADGE).all())

    def test_invalid_parameters(self, session):
        pytest.raises(AssertionError, session.shift_badges, c.STAFF_BADGE, 1, invalid='param')
        pytest.raises(AssertionError, session.shift_badges, c.STAFF_BADGE, 1, up=True, down=False)

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


class TestPreassignedBadgeChange:
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
        change_badge(session, session.supporter_five, c.STAFF_BADGE, new_num=7, expected_num=6)

    def test_middle_to_next(self, session):
        change_badge(session, session.supporter_three, c.STAFF_BADGE, expected_num=6)

    def test_beginning_to_next(self, session):
        change_badge(session, session.supporter_one, c.STAFF_BADGE, expected_num=6)


class TestInternalBadgeChange:
    def test_beginning_to_end(self, session):
        change_badge(session, session.staff_one, c.STAFF_BADGE, new_num=5)

    def test_beginning_to_next(self, session):
        change_badge(session, session.staff_one, c.STAFF_BADGE, expected_num=5)

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
        change_badge(session, session.staff_one,   c.STAFF_BADGE, new_num=1)
        change_badge(session, session.staff_three, c.STAFF_BADGE, new_num=3)
        change_badge(session, session.staff_five,  c.STAFF_BADGE, new_num=5)


class TestNonShiftChecks:
    @pytest.fixture(autouse=True)
    def set_shift_badges_off(self, monkeypatch):
        monkeypatch.setattr(c, 'SHIFT_CUSTOM_BADGES', False)

    @pytest.fixture(autouse=True)
    def teardown_range_check(request):
        return True  # TODO: make this actually check ranges

    def test_duplicate_warning(self, session):
        change_badge(session, session.staff_one, c.STAFF_BADGE, new_num=1)
        change_badge(session, session.staff_two, c.STAFF_BADGE, new_num=2)
        change_badge(session, session.staff_two, c.STAFF_BADGE, new_num=1, expected_num=2)
        assert session.staff_one.badge_num == 1
        assert session.staff_two.badge_num == 2

    def test_duplicate_zero(self, session):
        change_badge(session, session.staff_one, c.ATTENDEE_BADGE, expected_num=0)


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

# TODO: more unit tests for changes/deletions after custom badges have been ordered

# TODO: assign to same number
