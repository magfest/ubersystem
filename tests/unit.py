from common import *
from tests import TestUber
from site_sections import preregistration

from urllib import urlencode
from StringIO import StringIO

import requests

class TestGetModel(TestUber):
    def with_params(self, model=Attendee, **kwargs):
        return get_model(model, dict(kwargs, id = "None"))
    
    def test_basic(self):
        attendee = self.with_params(first_name = "Bob", last_name = "Loblaw")
        self.assertEqual("Bob Loblaw", attendee.full_name)
        
        self.assertEqual(0, self.with_params(age_group = "0").age_group)
        
        self.assertEqual(datetime(2001,2,3,4,5,6), self.with_params(checked_in = "2001-02-03 04:05:06").checked_in)


class TestPaypalCallback(TestUber):
    patched_funcs = ["check_payment","send_callback_email"]
    
    def setUp(self):
        TestUber.setUp(self)
        
        self.attendee = self.make_attendee()
        self.group = self.make_group(tables = 1, amount_owed = 125)
        
        for func in self.patched_funcs:
            setattr(self, func, getattr(preregistration, func))
        
        self.callback_email = None
        preregistration.send_callback_email = self.mock_send_callback_email
        preregistration.check_payment = lambda qs: False
    
    def tearDown(self):
        for func in self.patched_funcs:
            setattr(preregistration, func, getattr(self, func))
        TestUber.tearDown(self)
    
    def callback(self, cost=None, item_number=None, status="completed"):
        return requests.post(state.URL_BASE + "/preregistration/callback", data = {
            PAYPAL_STATUS: status,
            PAYPAL_ITEM: item_number or self.attendee_id,
            PAYPAL_COST: str(cost or state.BADGE_PRICE)
        }).text
    
    def id(self, model):
        return ("a" if isinstance(model, Attendee) else "g") + str(model.id)
    
    @property
    def attendee_id(self):
        return self.id(self.attendee)
    
    @property
    def group_id(self):
        return self.id(self.group)
    
    def mock_send_callback_email(self, subject, params):
        self.callback_email = subject
    
    def assert_callback(self, retval, email, *args, **kwargs):
        self.assertEqual(retval, self.callback(*args, **kwargs))
        self.assertIn(email, self.callback_email)
    
    def assert_paid(self, paid, *models):
        for model in models:
            assertion = getattr(self, "assertNotEqual" if paid else "assertEqual")
            assertion(0, model.__class__.objects.get(id = model.id).amount_paid)
    
    def test_attendee_success(self):
        self.assert_callback("ok", "Paypal callback payments marked")
        self.assert_paid(True, self.attendee)
    
    def test_attendee_unverified(self):
        preregistration.check_payment = lambda qs: "Paypal server indicates bad callback"
        self.assert_callback("ok", "Paypal callback unverified")
        self.assert_paid(False, self.attendee)
    
    def test_attendee_incomplete(self):
        self.assert_callback("ok", "Paypal callback incomplete", status = "pending")
        self.assert_paid(False, self.attendee)
    
    def test_attendee_underpaid(self):
        self.assert_callback("ok", "Paypal callback with non-matching payment", cost = 10)
        self.assert_paid(True, self.attendee)
    
    def test_attendee_overpaid(self):
        self.assert_callback("ok", "Paypal callback with non-matching payment", cost = 100)
        self.assert_paid(True, self.attendee)
    
    def test_unknown(self):
        self.assert_callback("ok", "Paypal callback with unknown item number", item_number = "xyz")
        self.assert_paid(False, self.attendee)
    
    def test_exception(self):
        preregistration.check_payment = lambda qs: [][0]
        self.assert_callback("error", "Paypal callback error")
        self.assert_paid(False, self.attendee)
    
    def test_group_success(self):
        self.assert_callback("ok", "Paypal callback payments marked", item_number = self.group_id, cost = self.group.amount_owed)
        self.assert_paid(True, self.group)
    
    def test_group_unverified(self):
        preregistration.check_payment = lambda qs: "Paypal server indicates bad callback"
        self.assert_callback("ok", "Paypal callback unverified", item_number = self.group_id, cost = self.group.amount_owed)
        self.assert_paid(False, self.group)
    
    def test_group_incomplete(self):
        self.assert_callback("ok", "Paypal callback incomplete", status = "pending", item_number = self.group_id, cost = self.group.amount_owed)
        self.assert_paid(False, self.group)
    
    def test_group_underpaid(self):
        self.assert_callback("ok", "Paypal callback with non-matching payment", item_number = self.group_id, cost = self.group.amount_owed - 10)
        self.assert_paid(True, self.group)
    
    def test_group_overpaid(self):
        self.assert_callback("ok", "Paypal callback with non-matching payment", item_number = self.group_id, cost = self.group.amount_owed + 10)
        self.assert_paid(True, self.group)
    
    def test_multiple_success(self):
        self.assert_callback("ok", "Paypal callback payments marked",
                                   item_number = ",".join([self.attendee_id, self.group_id]),
                                   cost = self.group.amount_owed + self.attendee.total_cost)
        self.assert_paid(True, self.attendee, self.group)
    
    def test_multiple_underpaid(self):
        self.assert_callback("ok", "Paypal callback with non-matching payment",
                                   item_number = ",".join([self.attendee_id, self.group_id]),
                                   cost = self.group.amount_owed + self.attendee.total_cost - 10)
        self.assert_paid(True, self.attendee, self.group)
    
    def test_multiple_overpaid(self):
        self.assert_callback("ok", "Paypal callback with non-matching payment",
                                   item_number = ",".join([self.attendee_id, self.group_id]),
                                   cost = self.group.amount_owed + self.attendee.total_cost + 10)
        self.assert_paid(True, self.attendee, self.group)
    
    def test_callback_tracking(self):
        self.test_attendee_success()
        self.assertEqual("Paypal callback", Tracking.objects.order_by("-id")[0].who)


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
        
        state.EPOCH = datetime.now()
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
    end_ranges = ([1,2,3,4,5,6], [600,601,602,603])
    
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
    end_ranges = ([1,2,3,4,5], [600,601,602,603,604])
    
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
    end_ranges = ([1,2,3,4], [600,601,602,603,604])
    
    def test_delete_first(self):
        self.staff_one.delete()
    
    def test_delete_middle(self):
        self.staff_three.delete()
    
    def test_delete_end(self):
        self.staff_five.delete()
