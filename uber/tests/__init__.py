from uber.common import *

import pytest
from mock import Mock


'''
class TestModelGet(TestUber):
    def with_params(self, model=Attendee, **kwargs):
        return model.get(dict(kwargs, id='None'), ignore_csrf=True)

    def test_basic(self):
        attendee = self.with_params(first_name='Bob', last_name='Loblaw')
        self.assertEqual('Bob Loblaw', attendee.full_name)

    def test_integer(self):
        self.assertEqual(123, self.with_params(amount_paid='123').amount_paid)

    def test_datetime(self):
        self.assertEqual(datetime(2001, 2, 3, 4, 5, 6), self.with_params(checked_in='2001-02-03 04:05:06').checked_in)


class TestBadgeChange(TestUber):
    delete_on_teardown = True

    def setUp(self):
        TestUber.setUp(self)
        for badge_type in PREASSIGNED_BADGE_TYPES:
            for i,last_name in enumerate(['one', 'two', 'three', 'four', 'five']):
                a = self.make_attendee(first_name=dict(BADGE_OPTS)[badge_type],
                                       last_name=last_name,
                                       badge_type=badge_type)
                setattr(self, '{}_{}'.format(a.first_name.lower(), last_name), a)
        self.check_ranges()

    def tearDown(self):
        try:
            self.check_ranges()
        finally:
            TestUber.tearDown(self)

    def change_badge(self, attendee, new_type, new_num=0, expected_num=None):
        attendee.badge_type, attendee.badge_num = new_type, new_num
        change_badge(attendee)
        self.assertEqual(Attendee.objects.get(id=attendee.id).badge_type, new_type)
        self.assertEqual(Attendee.objects.get(id=attendee.id).badge_num, new_num if expected_num is None else expected_num)

    def check_ranges(self):
        for badge_type in PREASSIGNED_BADGE_TYPES:
            actual = [a.badge_num for a in Attendee.objects.filter(badge_type=badge_type).order_by('badge_num')]
            expected = list(range(*BADGE_RANGES[badge_type])[:len(actual)])
            self.assertEqual(actual, expected, '{} badge numbers were {}, expected {}'.format(dict(BADGE_OPTS)[badge_type], actual, expected))


class TestPreassignedBadgeChange(TestBadgeChange):
    def test_end_to_next(self):
        self.change_badge(self.supporter_five, STAFF_BADGE, expected_num=6)

    def test_end_to_end(self):
        self.change_badge(self.supporter_five, STAFF_BADGE, new_num=6)

    def test_end_to_boundary(self):
        self.change_badge(self.supporter_five, STAFF_BADGE, new_num=5)

    def test_end_to_middle(self):
        self.change_badge(self.supporter_five, STAFF_BADGE, new_num=3)

    def test_end_to_beginning(self):
        self.change_badge(self.supporter_five, STAFF_BADGE, new_num=1)

    def test_end_to_over(self):
        self.change_badge(self.supporter_five, STAFF_BADGE, new_num=7, expected_num=6)

    def test_middle_to_next(self):
        self.change_badge(self.supporter_three, STAFF_BADGE, expected_num=6)

    def test_beginning_to_next(self):
        self.change_badge(self.supporter_one, STAFF_BADGE, expected_num=6)


class TestInternalBadgeChange(TestBadgeChange):
    def test_beginning_to_end(self):
        self.change_badge(self.staff_one, STAFF_BADGE, new_num=5)

    def test_beginning_to_next(self):
        self.change_badge(self.staff_one, STAFF_BADGE, expected_num=5)

    def test_beginning_plus_one(self):
        self.change_badge(self.staff_one, STAFF_BADGE, new_num=2)

    def test_beginning_to_middle(self):
        self.change_badge(self.staff_one, STAFF_BADGE, new_num=4)

    def test_end_to_beginning(self):
        self.change_badge(self.staff_five, STAFF_BADGE, new_num=1)

    def test_end_minus_one(self):
        self.change_badge(self.staff_five, STAFF_BADGE, new_num=4)

    def test_end_to_middle(self):
        self.change_badge(self.staff_five, STAFF_BADGE, new_num=2)

    def test_middle_plus_one(self):
        self.change_badge(self.staff_three, STAFF_BADGE, new_num=4)

    def test_middle_minus_one(self):
        self.change_badge(self.staff_three, STAFF_BADGE, new_num=2)

    def test_middle_up(self):
        self.change_badge(self.staff_two, STAFF_BADGE, new_num=4)

    def test_middle_down(self):
        self.change_badge(self.staff_four, STAFF_BADGE, new_num=2)

    def test_self_assignment(self):
        self.change_badge(self.staff_one,   STAFF_BADGE, new_num=1)
        self.change_badge(self.staff_three, STAFF_BADGE, new_num=3)
        self.change_badge(self.staff_five,  STAFF_BADGE, new_num=5)


class TestPreassignedBadgeDeletion(TestBadgeChange):
    def test_delete_first(self):
        self.staff_one.delete()

    def test_delete_middle(self):
        self.staff_three.delete()

    def test_delete_end(self):
        self.staff_five.delete()
'''
