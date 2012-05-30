from common import *
from tests import TestUber

from itertools import chain

from selenium import webdriver
from selenium.webdriver.common.keys import Keys

DEFAULT_TIMEOUT = 2

def tearDownModule():
    cherrypy.engine.exit()

def retry_on_failure(func):
    @wraps(func)
    def wrapped(self, *args, **kwargs):
        return self.wait_for(func, self, *args, **kwargs)
    return wrapped

def make_finder(get):
    def find_with(self, text, css_selector="body", context=None, *args, **kwargs):
        for e in self.all(css_selector, context, *args, **kwargs):
            if str(text).lower() in get(e).lower():
                return e
        self.fail("didn't find {!r} in {}".format(text, css_selector))
    return find_with

def make_waiter(name):
    def wait_for(self, text, css_selector="body", context=None, *args, **kwargs):
        return self.wait_for(getattr(self, "find_with_" + name), text, css_selector, context, *args, **kwargs)
    return wait_for

class TestBrowser(TestUber):
    links = []
    attendee = {}
    start_page = None
    at_the_con = False
    password = "password"
    
    ATTENDEE_REQUIRED = ["first_name","last_name","email","age_group","zip_code","ec_phone"]
    
    @classmethod
    def setUpClass(cls):
        super(TestBrowser, cls).setUpClass()
        cls.wd = webdriver.Firefox()
    
    @classmethod
    def tearDownClass(cls):
        try:
            cls.wd.quit()
        finally:
            super(TestBrowser, cls).tearDownClass()
    
    def setUp(self):
        TestUber.setUp(self)
        Account.objects.create(
            name   = "Selenium Testing",
            email  = self.email,
            access = ",".join(str(level) for level,name in ACCESS_OPTS),
            hashed = bcrypt.hashpw(self.password, bcrypt.gensalt())
        )
        if self.attendee:
            self.make_attendee(**self.attendee)
                
        if self.at_the_con:
            state.AT_THE_CON = True
        
        self.get(self.start_page or "/")
        if not self.start_page:
            self.login()
        
        self.click_links(*self.links)
    
    def tearDown(self):
        if not self.start_page:
            self.logout()
        TestUber.tearDown(self)
    
    def assert_attendee(self, **params):
        a = Attendee.objects.order_by("-id")[0]
        for attr,val in params.items():
            actual = getattr(a, attr)
            self.assertEqual(val, actual, "Attendee.{}: {!r} != {!r}".format(attr, val, actual))
    
    def goto_mailinator(self, email = None):
        self.wd.get("http://mailinator.com/maildir.jsp?email=" + (email or self.email).split("@")[0])
    
    @retry_on_failure
    def login(self, email=None, password=None):
        self.get("/accounts/login")
        self.send_keys(email or self.email, "email")
        self.send_keys(password or self.password, "password")
        self.submit("homepage")
    
    def logout(self):
        if self.all("#backlink"):
            self.find("#backlink").click()
        self.click_link("Logout")
    
    def submit(self, page=None, message=None, text=None, context=None, **kwargs):
        if text is not None:
            self.wait_for_value(text, "[type=submit]").click()
        else:
            self.wait_for("[type=submit]", context, **kwargs).click()
        
        if page:
            self.wait_for(lambda: self.assertTrue(self.wd.current_url.split("?")[0].endswith(page)))
        if message:
            self.assert_message(message)
    
    def get_email_info(self, subject, getters):
        self.goto_mailinator()
        self.reload_until(self.wait_for_text, subject, "a").click()
        self.wait_for("#message")
        results = []
        for getter in listify(getters):
            results.append(getter())
        self.find_with_text("Delete", "a").click()
        return results[0] if len(results) == 1 else results
    
    def get_email_text(self, subject, regex = None):
        text = self.get_email_info(subject, lambda: self.get("#message").text)
        if regex:
            [text] = re.findall(regex, text)
        return text
    
    def get_email_link(self, subject, link_text):
        return self.get_email_info(subject, lambda: self.find_with_text(link_text, "a").get_attribute("href"))
    
    def get(self, path="/"):
        self.wd.get(state.URL_BASE + path)
    
    def find(self, css_selector, context=None, *args, **kwargs):
        [result] = self.all(css_selector, context, *args, **kwargs)
        return result
    
    def all(self, css_selector, context=None, *args, **kwargs):
        if hasattr(context, "__call__"):
            context = context(*args, **kwargs)
        if isinstance(context, basestring):
            context = self.find(context)
        return (context or self.wd).find_elements_by_css_selector(css_selector)
    
    def click_link(self, text, context = None, *args, **kwargs):
        self.wait_for_text(text, "a", context, *args, **kwargs).click()
    
    def click_links(self, *links):
        map(self.click_link, links)
    
    def assert_message(self, text):
        self.wait_for_text(text, "#message")
    
    def send_keys(self, text, css_selector, context=None, *args, **kwargs):
        if css_selector[0] not in "[#.":
            css_selector = "[name=" + css_selector + "]"
        e = self.wait_for(css_selector, context, *args, **kwargs)
        e.click()
        if e.tag_name == "input":
            e.send_keys(Keys.LEFT * 25 + Keys.DELETE * 25 + text)
        elif e.tag_name == "select":
            e.click()
            self.find_with_text(text, "option", context = e).click()
    
    def select(self, text, css_selector, context=None, *args, **kwargs):
        self.send_keys(str(text) + "\n", css_selector, context, *args, **kwargs)
    
    def check(self, target, args, kwargs):
        if hasattr(target, "__call__"):
            return target(*args, **kwargs)
        else:
            return self.find(target, kwargs.get("context"))
    
    def wait_for(self, target, *args, **kwargs):
        timeout = kwargs.pop("timeout", DEFAULT_TIMEOUT)
        for i in range(10 * timeout):
            try:
                return self.check(target, args, kwargs)
            except:
                sleep(0.1)
        raise
    
    def reload_until(self, func, *args, **kwargs):
        for i in range(10):
            try:
                return func(*args, **kwargs)
            except:
                sleep(1)
                self.wd.refresh()
    
    def wait_for_text(self, text, css_selector="body", context=None, *args, **kwargs):
        return self.wait_for(self.find_with_text, text, css_selector, context, *args, **kwargs)
    
    find_with_text = make_finder(lambda e: e.text)
    find_with_value = make_finder(lambda e: e.get_attribute("value"))
    
    wait_for_text = make_waiter("text")
    wait_for_value = make_waiter("value")
    
    def checkbox(self, text, context=None, *args, **kwargs):
        return self.find("input", self.find_with_text, text, "nobr", context, *args, **kwargs)
    
    def click_checkbox(self, name, context=None, *args, **kwargs):
        self.wait_for("[name=" + name + "]", context, *args, **kwargs).click()
    
    def click_radio(self, value, context=None, *args, **kwargs):
        self.wait_for_value(value, "[type=radio]", context, *args, **kwargs).click()
    
    def enter_fields(self, *fields, **extra_fields):
        form_data = dict({
            "first_name": "Test",
            "last_name":  self._testMethodName,
            "email":      self.email,
            "zip_code":   "12345",
            "ec_phone":   "123-456-7890",
            "age_group":  "21 or over",
            "name":   "Test Group",
            "badges": 1,
        }, **extra_fields)
        for field in chain(fields, extra_fields):
            val = form_data[field]
            if isinstance(field, bool):
                self.click_checkbox("")
            else:
                self.send_keys(str(val), field)



class TestLogin(TestBrowser):
    start_page = "/accounts/login"
    
    def test_success(self):
        self.login()
        self.logout()
    
    def test_failure(self):
        self.assertRaises(self.login, password = "incorrect")


class TestPasswordReset(TestBrowser):
    start_page = "/accounts/login"
    links = ["Forgot Your Password?"]
    
    def test_failure(self):
        self.send_keys("DoesNotExist@example.com", "email")
        self.submit(message = "No account exists for")
    
    def test_success(self):
        self.send_keys(self.email, "email")
        self.submit("login")
        temp_password = self.get_email_text("MAGFest Admin Password Reset", "Your new password is: (.{8})")
        self.get("/accounts/login")
        self.login(password = temp_password)


class TestChangePassword(TestBrowser):
    def change_password(self, old_password, new_password, should_work=True):
        self.click_link("Change Password")
        self.send_keys(old_password, "old_password")
        self.send_keys(new_password, "new_password")
        self.submit("homepage" if should_work else "change_password")
    
    def test_success(self):
        self.change_password(self.password, "abcdef")
        self.logout()
        self.login(password = "abcdef")
        self.change_password("abcdef", self.password)
        self.logout()
        self.login()
    
    def test_failure(self):
        self.change_password("123456", "abcdef", should_work = False)
        self.assert_message("Incorrect old password")


class TestAccountAdmin(TestBrowser):
    links = ["Manage Accounts"]
    
    def setUp(self):
        TestBrowser.setUp(self)
        self.create()
    
    def row_context(self, form = "update"):
        return "#" + re.sub(r"\W", "_", self.test_email) + " ." + form
    
    def create(self):
        self.send_keys("Test Admin", "name")
        self.send_keys(self.email, "email")
        self.checkbox("Registration and Staffing", "#new_admin").click()
        self.submit(context = "#new_admin", message = "Account settings uploaded")
    
    def test_create(self):
        password = self.get_email_text("New MAGFest Ubersystem Account", "Your password is: (.{8})")
        self.login(self.test_email, password)
        self.find_with_text("Attendees", "a")
    
    def test_update(self):
        admin = lambda: self.checkbox("Account Management", self.row_context)
        self.assertFalse( admin().get_attribute("checked") )
        admin().click()
        self.submit(context = self.row_context, message = "Account settings uploaded")
        self.assertTrue( admin().get_attribute("checked") )
    
    def test_delete(self):
        self.submit(context = lambda: self.row_context("delete"), message = "Account deleted")
        self.assertFalse( self.all(self.row_context()) )



class TestAddAttendee(TestBrowser):
    links = ["Attendees", "Add an attendee"]
    
    def test_required(self):
        self.submit(message = "First Name and Last Name")
        self.enter_fields("first_name", "last_name")
        self.submit(message = "email address")
        self.enter_fields("email")
        self.submit(message = "zip code")
        self.enter_fields("zip_code")
        self.submit(message = "emergency contact")
        self.enter_fields("ec_phone")
        self.submit(page = "index", message = "has been uploaded")
    
    def test_placeholder_required(self):
        self.click_checkbox("placeholder")
        self.submit(message = "First Name and Last Name")
        self.enter_fields("first_name", "last_name")
        self.submit(page = "index", message = "has been uploaded")
    
    def test_group_required(self):
        g = self.make_group()
        self.wd.refresh()
        self.select(g.name + "\n", "group_opt")
        self.submit(page = "index", message = "has been uploaded")
    
    def test_success(self):
        self.enter_fields(*self.ATTENDEE_REQUIRED)
        self.submit(page = "index", message = "has been uploaded")
        self.click_link("Test test_success")
    
    def test_dealer(self):
        g = self.make_group(tables = 1)
        self.enter_fields(*self.ATTENDEE_REQUIRED)
        self.select("Dealer", "ribbon")
        self.submit(message = "Dealers must be associated with a group")
        self.select(g.name, "group_opt")
        self.submit(page = "index", message = "has been uploaded")

class TestAddAttendeeAtTheCon(TestBrowser):
    at_the_con = True
    
    links = ["Attendees", "Add an attendee"]
    
    def test_required(self):
        self.submit(message = "Badge Number")
        self.enter_fields("badge_num")
        self.submit(message = "First Name and Last Name")
        self.enter_fields("first_name", "last_name")
        self.submit(message = "age")
        self.enter_fields("age_group")
        self.submit(page = "index", message = "has been uploaded")
    
    def test_unassigned_badge(self):
        self.enter_fields("first_name", "last_name", "age_group", badge_num = 0)
        self.submit(page = "index", message = "has been uploaded")
    
    def test_badge_ranges(self):
        for badge_type, badge_range in BADGE_RANGES.items():
            self.enter_fields("first_name", "last_name", "age_group")
            badge_type_label = dict(BADGE_OPTS)[badge_type]
            min_num, max_num = badge_range
            for num in [min_num - 1, max_num + 1]:
                if num:
                    self.enter_fields(badge_type = badge_type_label, badge_num = num)
                    self.submit(message = "must fall within")


class TestBadgeChange(TestBrowser):
    attendee = {"last_name": "McBadgeChange"}
    links = ["Attendees", "McBadgeChange, Test"]
    
    def test_badge_change(self):
        for badge_type,label in reversed(BADGE_OPTS):
            self.click_link("Change")
            self.select(label, "badge_type")
            self.submit(message = "Badge updated")
            
            self.assert_attendee(badge_type = badge_type)
            self.assertFalse(check_range(Attendee.objects.get().badge_num, badge_type))

class TestBadgeChangeAtTheCon(TestBrowser):
    at_the_con = True
    attendee = {"last_name": "McBadgeChange"}
    links = ["Attendees", "McBadgeChange, Test"]
    
    def test_change_to_floating(self):
        for badge_type,label in reversed(BADGE_OPTS):
            self.click_link("Change")
            self.select(label, "badge_type")
            self.send_keys("0", "newnum")
            if badge_type in PREASSIGNED_BADGE_TYPES:
                self.submit(message = "must assign a badge number")
            else:
                self.submit(message = "Badge updated")
                self.assert_attendee(badge_type = badge_type, badge_num = 0)


class TestPlaceholder(TestBrowser):
    links = ["Attendees", "Add an attendee"]
    
    def make_and_check(self, subject, **params):
        self.enter_fields("first_name", "last_name", "email", placeholder = True, **self.params)
        self.submit("index")
        Reminder.send_all(raise_errors = True)
        self.get_email_text("MAGFest Panelist Badge Confirmation")
        self.get("/accounts/homepage")
    
    def test_basic(self):
        self.enter_fields("first_name", "last_name", placeholder = True)
        self.submit("index")
        self.click_links("Test test_basic", "register themself")
        self.assert_message("You are not yet registered")
        self.enter_fields("email", "zip_code", "ec_phone")
        self.submit(message = "You have been registered")
        self.get("/accounts/homepage")
    
    def test_panelist_email(self):
        self.make_and_check("MAGFest Panelist Badge Confirmation", ribbon = PANELIST_RIBBON)
    
    def test_guest_email(self):
        self.make_and_check("MAGFest Panelist Badge Confirmation", badge_type = GUEST_BADGE)
    
    def test_volunteer_email(self):
        self.make_and_check("MAGFest Volunteer Confirmation", ribbon = VOLUNTEER_RIBBON)
    
    def test_staff_email(self):
        self.make_and_check("MAGFest Volunteer Confirmation", badge_type = STAF_BADGE)
    
    def test_other_email(self):
        self.make_and_check("MAGFest Registration Confirmation Required")


class TestPreregCheck(TestBrowser):
    start_page = "/preregistration"
    links = ["Click here"]
    info = {"first_name": "Eli", "last_name": "Courtwright", "zip_code": "12345"}
    
    def assert_paid(self):
        self.assertRaises(Exception, self.assert_unpaid)
    
    def assert_unpaid(self):
        self.find_with_text("you are marked as not having paid")
        self.find_with_text("please pay using Paypal")
    
    def make_and_check(self, message = "You are registered", **params):
        self.make_attendee(**dict(self.info, **params))
        self.enter_fields(**self.info)
        self.submit(message = message)
    
    def test_missing(self):
        self.enter_fields(**self.info)
        self.submit(message = "No attendee matching")
    
    def test_paid(self):
        self.make_and_check(paid = HAS_PAID, amount_paid = 40)
        self.assert_paid()
    
    def test_comped(self):
        self.make_and_check(paid = NEED_NOT_PAY)
        self.assert_paid()
    
    def test_placeholder(self):
        self.make_and_check(placeholder = True)
        self.click_link("confirm your registration")
        self.assert_message("You are not yet registered")
    
    def test_unpaid(self):
        self.make_and_check()
        self.assert_unpaid()
    
    def test_unpaid_group(self):
        g = self.make_group(amount_owed = 150, auto_recalc = False)
        self.make_and_check(paid = PAID_BY_GROUP, group = g)
        self.assert_unpaid()
    
    def test_paid_group(self):
        g = self.make_group(amount_owed = 0, amount_paid = 150, auto_recalc = False)
        self.make_and_check(paid = PAID_BY_GROUP, group = g)
        self.assert_paid()
    
    def test_comped_group(self):
        g = self.make_group(amount_owed = 0, amount_paid = 0, auto_recalc = False)
        self.make_and_check(paid = PAID_BY_GROUP, group = g)
        self.assert_paid()


class TestGroupAdmin(TestBrowser):
    links = ["Groups", "Add a group"]
    
    def test_required(self):
        self.submit(message = "is a required field")
    
    def test_dealer(self, badges = 1):
        self.enter_fields("name", badges = badges)
        self.submit("index")
        self.assert_attendee(badge_type = ATTENDEE_BADGE, ribbon = DEALER_RIBBON)
    
    def test_add_dealer(self):
        self.test_dealer()
        self.click_link("Test Group")
        self.select(2, "badges")
        self.submit("index", text = "Upload")
        self.assert_attendee(badge_type = ATTENDEE_BADGE, ribbon = DEALER_RIBBON)
    
    def test_add_guest(self):
        self.test_dealer()
        Attendee.objects.update(badge_type = GUEST_BADGE, ribbon = NO_RIBBON)
        self.click_link("Test Group")
        self.enter_fields(badges = 2)
        self.submit("index", text = "Upload")
        self.assert_attendee(badge_type = GUEST_BADGE, ribbon = NO_RIBBON)
    
    def test_remove_badges(self):
        self.test_dealer(badges = 2)
        self.assertEqual(2, Attendee.objects.count())
        self.click_link("Test Group")
        self.enter_fields(badges = "0\n1")      # TODO: fix select to make this unnecessary
        self.submit("index", text = "Upload")
        self.assertEqual(1, Attendee.objects.count())
    
    def test_remove_badges_failure(self):
        self.test_dealer()
        self.make_attendee(paid = PAID_BY_GROUP, group = Group.objects.get())
        self.click_link("Test Group")
        self.enter_fields(badges = 0)
        self.submit(text = "Upload", message = "You can't reduce the number of badges for a group to below the number of assigned badges")
    
    def test_delete_failure(self):
        self.test_dealer()
        self.make_attendee(group = Group.objects.get())
        self.click_link("Test Group")
        self.submit(text = "Delete", message = "You can't delete a group without first unassigning its badges")
    
    def test_delete(self):
        self.test_dealer()
        Attendee.objects.get().delete()
        self.click_link("Test Group")
        self.submit(text = "Delete", message = "Group deleted")
    
    def test_links(self):
        self.test_dealer()
        a = self.make_attendee(group = Group.objects.get())
        self.click_link("Test Group")
        self.click_link(a.full_name)
        self.click_link("Test Group")
        self.click_link("Link for group leader")
        self.wait_for_text('Members of "Test Group"')
        self.get("/accounts/homepage")


class TestGroupAssignments(TestBrowser):
    def setUp(self):
        self.group = Group.objects.create(name = "Test Group", tables = 0)
        self.make_attendee(group = self.group)
        assign_group_badges(self.group, 10)
        self.start_page = state.URL_BASE + "/preregistration/group_members?id=" + obfuscate(self.group.id)
        TestBrowser.setUp(self)
    
    def test_assign(self):
        self.wait_for_text("Register someone for this badge", "a").click()
        self.enter_fields(*self.ATTENDEE_REQUIRED)
        self.submit(message = "Badge registered successfully")
        self.find_with_text("Test test_", "td")
    
    def test_unassign(self):
        self.test_assign()
        self.find_with_value("This person isn't coming", "input").click()
        self.assert_message("Attendee unset")
        self.assertRaises(Exception, self.find_with_text, "Test test_", "td")


class TestPrereg(TestBrowser):
    start_page = "/preregistration"
    
    SUCCESS_MESSAGE = "Your preregistration will be complete when you pay"
    
    SUPPORTER_FIELDS = ["badge_printed_name", "aff_select"]
    GROUP_FIELDS = ["name", "badges"]
    DEALER_FIELDS = GROUP_FIELDS + ["tables"]
    ALL_FIELDS = SUPPORTER_FIELDS + GROUP_FIELDS + DEALER_FIELDS
    STAFFING_FIELDS = ['[name=requested_depts][value="{}"]'.format(i) for i,desc in JOB_INTEREST_OPTS]
    
    def setUp(self):
        TestBrowser.setUp(self)
        self.click_radio(ATTENDEE_BADGE)
        self.submit()
    
    def tearDown(self):
        Attendee.objects.all().delete()
        Group.objects.all().delete()
    
    def assert_visibility(self, hidden = [], visible = []):
        for expected,fields in [(True, visible), (False, hidden)]:
            for field in fields:
                sel = field if "[" in field else ("[name=" + field + "]")
                self.assertEqual(expected, self.find(sel).is_displayed(), "{}.is_visible != {}".format(field, expected))
    
    def test_field_visibility(self):
        self.assert_visibility(hidden = self.ALL_FIELDS)
        self.click_radio(SUPPORTER_BADGE)
        self.assert_visibility(visible = self.SUPPORTER_FIELDS, hidden = self.DEALER_FIELDS + ["aff_text"])
        self.enter_fields(aff_select = "--Other--")
        self.assert_visibility(visible = ["aff_text"])
        self.click_radio(PSEUDO_GROUP_BADGE)
        self.assert_visibility(visible = self.GROUP_FIELDS,
                               hidden = self.SUPPORTER_FIELDS + list(set(self.DEALER_FIELDS) - set(self.GROUP_FIELDS)))
        self.click_radio(PSEUDO_DEALER_BADGE)
        self.assert_visibility(hidden = self.SUPPORTER_FIELDS)
        self.assert_visibility(hidden = self.STAFFING_FIELDS)
        self.click_checkbox("staffing")
        self.assert_visibility(visible = self.STAFFING_FIELDS)
    
    def test_required(self):
        self.submit(message = "First Name and Last Name are required")
        self.enter_fields("first_name", "last_name")
        self.submit(message = "email address")
        self.enter_fields("email")
        self.submit(message = "zip code")
        self.enter_fields("zip_code")
        self.submit(message = "emergency contact")
        self.enter_fields("ec_phone")
        self.submit(message = "age category")
        self.enter_fields("age_group")
        self.submit(message = self.SUCCESS_MESSAGE)
    
    def test_group_required(self):
        self.click_radio(PSEUDO_GROUP_BADGE)
        self.enter_fields(*self.ATTENDEE_REQUIRED)
        self.submit(message = "Group name")
        self.enter_fields("name", badges = 10)
        self.submit(message = self.SUCCESS_MESSAGE)
    
    def test_paypal_link(self):
        self.enter_fields(*self.ATTENDEE_REQUIRED)
        self.submit(message = self.SUCCESS_MESSAGE)
        href = self.get_email_link("MAGFest Preregistration", "on this page")
        self.wd.get(href)
        self.wait_for_text("Paypal")
    
    def test_group_email_link(self):
        self.enter_fields(*self.ATTENDEE_REQUIRED)
        self.click_radio(PSEUDO_GROUP_BADGE)
        self.enter_fields("name", badges = 10)
        self.submit(message = self.SUCCESS_MESSAGE)
        href = self.get_email_link("MAGFest Preregistration", "preassign your badges here")
        self.wd.get(href)
        self.wait_for_text("Register someone for this badge", "a")



"""
import os, atexit, unittest
os.environ["TESTING"] = ""
from tests.browser import *

def exit():
    cherrypy.engine.stop()
    cherrypy.engine.exit()
    try:
        self.wd.quit()
    finally:
        sys.exit(0)

class Test(TestLogin):
    def __init__(self):
        unittest.TestCase.__init__(self, "__init__")
        self.setUpClass()
        self.setUp()
        atexit.register(self.tearDown)
        atexit.register(self.tearDownClass)
        atexit.register(tearDownModule)

self = Test()
"""
