import pytest
from selenium.webdriver.support.select import Select
import uuid
import time

# TODO: eventually, make this configurable
EVENT_NAME = "magstock"

STRIPE_FAKE_CREDIT_CARD = "4242"  # this will be repeated 4 times
STRIPE_FAKE_EXP_DATE = "12/25"  # MM/YY
STRIPE_FAKE_CSC = "111"
STRIPE_FAKE_ZIP = "54321"


def is_mobile(driver):
    # TODO: likely need to update this for IOS and other stuff, or maybe check for Appnium
    return driver.capabilities["platform"] == "ANDROID"


@pytest.fixture
def selenium(selenium):
    selenium.implicitly_wait(10)
    if not is_mobile(selenium):
        selenium.maximize_window()
    return selenium


@pytest.fixture
def clear_session_cookie(selenium):
    # this logs you out, or if you have unsaved prereg's, will clear them
    selenium.delete_cookie('session_id')


def ensure_text_in_error_message(driver, text):
    html = driver.find_elements_by_class_name("toast-message")[0].get_attribute("innerHTML")
    assert text in html


def innerhtml(driver, tag):
    return driver.find_element_by_tag_name(tag).get_attribute("innerHTML")


class ArgsBase:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class FormValidator(ArgsBase):
    def __init__(self, **kwargs):
        self.field_name = None
        self.field_value = None
        self.expected_error = None
        self.event_specific = None

        super(FormValidator, self).__init__(**kwargs)

    def check_for_expected_error(self, driver):
        if self.expected_error:
            ensure_text_in_error_message(driver, self.expected_error)

    def fill_if_needed(self, driver):
        form_element = None
        if self.field_name and (not self.event_specific or self.event_specific == EVENT_NAME):
            form_element = self.fill(driver)
        return form_element

    def run(self, driver, submit=False, check_expected_error=False):
        if check_expected_error:
            self.check_for_expected_error(driver)

        form_element = self.fill_if_needed(driver)

        if submit:
            form_element.submit()

        return form_element


class BirthdateFieldValidator(FormValidator):
    def fill(self, driver):
        date_values = self.field_value.split('-')
        assert len(self.field_name) == len(date_values)
        fields_and_values = zip(self.field_name, date_values)

        elem = None
        for field, text in fields_and_values:
            elem = driver.find_elements_by_class_name(field)[0]
            elem.send_keys(text)
        return elem


class InputFieldValidator(FormValidator):
    def fill(self, driver):
        """
        Fill out a field. Can be overridden, and must return an element that is part of the form
        that we are filling out.
        """
        elem = driver.find_element_by_xpath("//input[@name='{}']".format(self.field_name))
        if self.field_value:
            elem.clear()
            elem.send_keys(self.field_value)
        return elem


class DropDownValidator(FormValidator):
    def fill(self, driver):
        elem = driver.find_element_by_name(self.field_name)
        if self.field_value:
            Select(elem).select_by_visible_text(self.field_value)
        return elem


class EnsurePage(ArgsBase):
    def run(self, driver):
        assert self.expected_page in driver.current_url


def fill_and_submit_stripe_form(driver):
    """
    This function assumes you use a unique email address, if not, Stripe will try and verify you with
    an SMS message code, and we don't handle that case yet.
    """
    pay_button_xpath = "//form[@class='stripe']/button[@class='stripe-button-el']"
    button = driver.find_element_by_xpath(pay_button_xpath)
    button.click()

    if not is_mobile(driver):
        # mobile stripe doesn't use an iframe, just opens a new tab
        stripe_iframe = driver.find_element_by_xpath("//iframe[@name='stripe_checkout_app']")
        driver.switch_to_frame(stripe_iframe)
    else:
        driver.switch_to.window("stripe_checkout_tabview")

    # we can't just send the entire card# for some reason, send it in 4 chunks.
    for i in range(4):
        driver.find_element_by_id('card_number').send_keys(STRIPE_FAKE_CREDIT_CARD)

    for part in STRIPE_FAKE_EXP_DATE.split('/'):
        driver.find_element_by_id('cc-exp').send_keys(part)

    driver.find_element_by_id('cc-csc').send_keys(STRIPE_FAKE_CSC)
    zip_elem = driver.find_element_by_id('billing-zip')
    zip_elem.send_keys(STRIPE_FAKE_ZIP)
    zip_elem.submit()

    if not is_mobile(driver):
        driver.switch_to_default_content()

    time.sleep(4)  # hax.


def generate_unique_email():
    return "testemail-{}@testemail.com".format(str(uuid.uuid4()))


birthdate_elements = ["jq-dte-month", "jq-dte-day", "jq-dte-year"]

# order matters
regform_validations = [
    InputFieldValidator(field_name="first_name"),
    InputFieldValidator(
        expected_error="First Name is a required field",
        field_name="first_name", field_value="FIRSTNAME_Attendee"),
    InputFieldValidator(
        expected_error="Last Name is a required field",
        field_name="last_name", field_value="LASTNAME_Attendee"),
    BirthdateFieldValidator(
        expected_error="Enter your date of birth.",
        field_name=birthdate_elements, field_value="12-09-1945"),
    InputFieldValidator(
        expected_error="Enter a valid email address",
        field_name="email", field_value=generate_unique_email()),
    InputFieldValidator(
        expected_error="Enter a 10-digit emergency contact number",
        field_name="ec_phone", field_value="410-765-9867"),
    InputFieldValidator(
        expected_error="Enter a valid zip code",
        field_name="zip_code", field_value="21211"),
    DropDownValidator(
        event_specific="magstock",
        expected_error="Noise Level is a required field",
        field_name="noise_level", field_value="As quiet as possible at night"),
    DropDownValidator(
        event_specific="magstock",
        expected_error="Site Type is a required field",
        field_name="site_type", field_value="Normal - has electric and water hookups"),
    DropDownValidator(
        event_specific="magstock",
        expected_error="Please tell us how you are camping",
        field_name="camping_type", field_value="Small Tent (6 or fewer)"),
    DropDownValidator(
        event_specific="magstock",
        expected_error="Please tell us whether you are leading a group",
        field_name="coming_as", field_value="I'm not the one coordinating my group"),
    InputFieldValidator(
        event_specific="magstock",
        expected_error="Please tell us who your camp leader is",
        field_name="coming_with", field_value="Marianne Testguy"),
]

stripe_payment_form = [

]


class FormFiller:
    def __init__(self, validations):
        self.validations = validations

    def run_each_then_submit_each(self, driver):
        """
        Run each field validation one at a time in sequence, then submit the form after each one.
        This will check that error messages pop up for required form elements.
        """
        for validator in self.validations:
            validator.run(driver, submit=True, check_expected_error=True)

    def fill_entire_form_then_submit(self, driver):
        """
        Fill in the entire form all at once and submit at the end.  Doesn't check for individual error
        messages.
        """
        last_form_element = None
        for validator in self.validations:
            last_form_element = validator.run(driver)

        last_form_element.submit()


# @pytest.mark.nondestructive  # not true anymore
@pytest.mark.skip
def test_full_validations_main_prereg_page(base_url, selenium):
    """
    Test all validations for one path through the front prereg page.
    Example: If you leave off "First Name", we want to see an error message about "First name is required"
    """

    selenium.get('{0}/uber/preregistration/form'.format(base_url))
    assert "Preregistration" in selenium.title

    FormFiller(regform_validations).run_each_then_submit_each(selenium)

    assert "/uber/preregistration/index" in selenium.current_url


def test_prereg_payment(base_url, selenium):
    """
    Test entire public registration workflow from filling out the form
    to then filling out the stripe credit card page
    """
    selenium.get('{0}/uber/preregistration/form'.format(base_url))
    assert "Preregistration" in selenium.title

    FormFiller(regform_validations).fill_entire_form_then_submit(selenium)

    assert "/uber/preregistration/index" in selenium.current_url

    fill_and_submit_stripe_form(selenium)

    assert "/uber/preregistration/paid_preregistrations" in selenium.current_url
    assert "The following preregistrations have been made from this computer" in innerhtml(selenium, "body")
