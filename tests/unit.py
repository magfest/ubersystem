import sys
from io import StringIO
from urllib.parse import urlencode

import requests

sys.path.append(".")
from tests import *
from site_sections import preregistration

class TestGetModel(TestUber):
    def with_params(self, model=Attendee, **kwargs):
        return get_model(model, dict(kwargs, id = "None"))
    
    def test_basic(self):
        attendee = self.with_params(first_name = "Bob", last_name = "Loblaw")
        self.assertEqual("Bob Loblaw", attendee.full_name)
        
        self.assertEqual(0, self.with_params(age_group = "0").age_group)
        
        self.assertEqual(datetime(2001,2,3,4,5,6), self.with_params(checked_in = "2001-02-03 04:05:06").checked_in)


class TestGroupPrice(TestUber):
    def setUp(self):
        TestUber.setUp(self)
        self.group = Group.objects.create(name = "Test Group", tables = 0)
    
    def test_all_prebump(self):
        state.PRICE_BUMP = datetime.now() + timedelta(days = 1)
        assign_group_badges(self.group, 8)
        self.assertEqual(self.group.amount_owed, 8 * EARLY_GROUP_PRICE)
    
    def test_all_postbump(self):
        state.PRICE_BUMP = datetime.now() - timedelta(days = 1)
        assign_group_badges(self.group, 8)
        print([a.paid for a in self.group.attendee_set.all()], self.group.total_cost, self.group.amount_owed)
        self.assertEqual(self.group.amount_owed, 8 * LATE_GROUP_PRICE)
    
    def test_mixed(self):
        before = state.PRICE_BUMP - timedelta(days = 1)
        after  = state.PRICE_BUMP + timedelta(days = 1)
        assign_group_badges(self.group, 8)
        for attendee in self.group.attendee_set.all():
            attendee.registered = after if attendee.id % 2 else before
            attendee.save()
        self.group.save()
        self.assertEqual(self.group.amount_owed, 4 * EARLY_GROUP_PRICE + 4 * LATE_GROUP_PRICE)


class TestAttendeePrice(TestUber):
    def test_all(self):
        self.assertEqual(SUPPORTER_BADGE_PRICE, Attendee(badge_type = SUPPORTER_BADGE).total_cost)
        
        state.PRICE_BUMP = datetime.now() + timedelta(days = 1)
        self.assertEqual(EARLY_BADGE_PRICE, Attendee(badge_type = ATTENDEE_BADGE).total_cost)
        
        state.PRICE_BUMP = datetime.now() - timedelta(days = 1)
        self.assertEqual(LATE_BADGE_PRICE, Attendee(badge_type = ATTENDEE_BADGE).total_cost)
        
        state.AT_THE_CON = True
        self.assertEqual(DOOR_BADGE_PRICE, Attendee(badge_type = ATTENDEE_BADGE).total_cost)


class TestPaymentProgression(TestUber):
    def setUp(self):
        TestUber.setUp(self)
        state.SEND_EMAILS = False
        state.AUTO_EMAILS = True
    
    def make_group(self, **params):
        group = TestUber.make_group(self, **params)
        self.make_attendee(group = group, paid = PAID_BY_GROUP)
        assign_group_badges(group, 10)
        return group
    
    def assert_progress(self, days_ago, email_count):
        for model in [Attendee, Group]:
            model.objects.update(registered = datetime.now() - timedelta(days = days_ago))
        
        for i in range(2):
            Reminder.send_all()
            delete_unpaid()
        
        self.assertEqual(email_count, Email.objects.count())
        reg_count = Attendee.objects.count() + Group.objects.count()
        getattr(self, "assertEqual" if email_count == 3 else "assertNotEqual")(0, reg_count)
    
    def test_unpaid(self):
        for maker in [self.make_attendee, self.make_group]:
            maker()
            self.assert_progress(0, 0)
            self.assert_progress(6, 0)
            self.assert_progress(8, 1)
            self.assert_progress(13, 2)
            self.assert_progress(15, 3)
            Email.objects.all().delete()
    
    def test_payment_deadline(self):
        self.make_attendee()
        Attendee.objects.update(registered = datetime.now() - timedelta(days = 14))
        self.assertEqual(Attendee.objects.get().payment_deadline, datetime.combine(datetime.now().date(), time(23, 59)))
    
    def test_paid_attendee(self):
        self.make_attendee(paid = HAS_PAID, amount_paid = state.BADGE_PRICE)
        self.assert_progress(15, 1)
        self.assertIn("payment received", Email.objects.get().subject)
    
    def test_paid_group(self):
        self.make_group(amount_paid = 10 * state.GROUP_PRICE)
        self.assert_progress(15, 1)
        self.assertIn("payment received", Email.objects.get().subject)


class TestBadgeChange(TestUber):
    def setUp(self):
        TestUber.setUp(self)
        state.STAFF_BADGE_DEADLINE = datetime.now() + timedelta(days = 1)
        for badge_type in [STAFF_BADGE, SUPPORTER_BADGE]:
            for i,last_name in enumerate(["one","two","three","four","five"]):
                a = self.make_attendee(first_name = dict(BADGE_OPTS)[badge_type], last_name = last_name,
                        badge_type = badge_type, badge_num = range(*BADGE_RANGES[badge_type])[i],
                        paid = HAS_PAID, amount_paid = state.BADGE_PRICE)
                setattr(self, "{}_{}".format(a.first_name.lower(), last_name), a)
    
    def tearDown(self):
        try:
            self.assert_ranges(*self.end_ranges)
        finally:
            TestUber.tearDown(self)
    
    def change_badge(self, attendee, new_type, new_num = 0, expected_num = None):
        attendee.badge_type, attendee.badge_num = new_type, new_num
        change_badge(attendee)
        self.assertEqual(Attendee.objects.get(id = attendee.id).badge_num, new_num if expected_num is None else expected_num)
    
    def assert_ranges(self, staff_badges, supporter_badges):
        self.assertEqual(staff_badges, [a.badge_num for a in Attendee.objects.filter(badge_type = STAFF_BADGE).order_by("badge_num")])
        self.assertEqual(supporter_badges, [a.badge_num for a in Attendee.objects.filter(badge_type = SUPPORTER_BADGE).order_by("badge_num")])

class TestPreassignedBadgeChange(TestBadgeChange):
    end_ranges = ([1,2,3,4,5,6], [500,501,502,503])
    
    def test_end_to_next(self):
        self.change_badge(self.supporter_five, STAFF_BADGE, expected_num = 6)
    
    def test_end_to_end(self):
        self.change_badge(self.supporter_five, STAFF_BADGE, 6)
    
    def test_end_to_boundary(self):
        self.change_badge(self.supporter_five, STAFF_BADGE, 5)
    
    def test_end_to_middle(self):
        self.change_badge(self.supporter_five, STAFF_BADGE, 3)
    
    def test_end_to_beginning(self):
        self.change_badge(self.supporter_five, STAFF_BADGE, 1)
    
    def test_end_to_over(self):
        self.change_badge(self.supporter_five, STAFF_BADGE, new_num = 7, expected_num = 6)
    
    def test_middle_to_next(self):
        self.change_badge(self.supporter_three, STAFF_BADGE, expected_num = 6)
    
    def test_beginning_to_next(self):
        self.change_badge(self.supporter_one, STAFF_BADGE, expected_num = 6)

class TestInternalBadgeChange(TestBadgeChange):
    end_ranges = ([1,2,3,4,5], [500,501,502,503,504])
    
    def test_beginning_to_end(self):
        self.change_badge(self.staff_one, STAFF_BADGE, 5)
    
    def test_beginning_to_next(self):
        self.change_badge(self.staff_one, STAFF_BADGE, expected_num = 5)
    
    def test_beginning_plus_one(self):
        self.change_badge(self.staff_one, STAFF_BADGE, 2)
    
    def test_beginning_to_middle(self):
        self.change_badge(self.staff_one, STAFF_BADGE, 4)
    
    def test_end_to_beginning(self):
        self.change_badge(self.staff_five, STAFF_BADGE, 1)
    
    def test_end_minus_one(self):
        self.change_badge(self.staff_five, STAFF_BADGE, 4)
    
    def test_end_to_middle(self):
        self.change_badge(self.staff_five, STAFF_BADGE, 2)
    
    def test_middle_plus_one(self):
        self.change_badge(self.staff_three, STAFF_BADGE, 4)
    
    def test_middle_minus_one(self):
        self.change_badge(self.staff_three, STAFF_BADGE, 2)
    
    def test_middle_up(self):
        self.change_badge(self.staff_two, STAFF_BADGE, 4)
    
    def test_middle_down(self):
        self.change_badge(self.staff_four, STAFF_BADGE, 2)
    
    def test_self_assignment(self):
        self.change_badge(self.staff_one,   STAFF_BADGE, 1)
        self.change_badge(self.staff_three, STAFF_BADGE, 3)
        self.change_badge(self.staff_five,  STAFF_BADGE, 5)

class TestPreassignedBadgeDeletion(TestBadgeChange):
    end_ranges = ([1,2,3,4], [500,501,502,503,504])
    
    def test_delete_first(self):
        self.staff_one.delete()
    
    def test_delete_middle(self):
        self.staff_three.delete()
    
    def test_delete_end(self):
        self.staff_five.delete()
