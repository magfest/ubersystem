import pytest
from selenium.webdriver.support.select import Select
import uuid

# TODO: eventually, make this configurable
EVENT_NAME = "magstock"

@pytest.fixture
def selenium(selenium):
    selenium.implicitly_wait(10)
    selenium.maximize_window()
    return selenium


def ensure_text_in_error_message(driver, text):
    html = driver.find_elements_by_class_name("toast-message")[0].get_attribute("innerHTML")
    assert text in html


def ensure_text_exists_in_head(driver, text):
    head_html = driver.find_element_by_tag_name("head").get_attribute("innerHTML")
    assert text in head_html


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

    def run(self, driver):
        if self.expected_error:
            ensure_text_in_error_message(driver, self.expected_error)

        if self.field_name and (not self.event_specific or self.event_specific == EVENT_NAME):
            elem = self.fill(driver)
            elem.submit()

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


class TextFieldValidator(FormValidator):
    pass


class DropDownValidator(TextFieldValidator):
    def fill(self, driver):
        elem = driver.find_element_by_name(self.field_name)
        if self.field_value:
            Select(elem).select_by_visible_text(self.field_value)
        return elem


class EnsurePage(ArgsBase):
    def run(self, driver):
        assert self.expected_page in driver.current_url


def generate_unique_email():
    return "testemail-{}@testemail.com".format(str(uuid.uuid4()))

birthdate_elements = ["jq-dte-month", "jq-dte-day", "jq-dte-year"]

# order matters
regform_validations = [
    TextFieldValidator(field_name="first_name"),
    TextFieldValidator(
        expected_error="First Name is a required field",
        field_name="first_name", field_value="FIRSTNAME_Attendee"),
    TextFieldValidator(
        expected_error="Last Name is a required field",
        field_name="last_name", field_value="LASTNAME_Attendee"),
    BirthdateFieldValidator(
        expected_error="Enter your date of birth.",
        field_name=birthdate_elements, field_value = "12-09-1945"),
    TextFieldValidator(
        expected_error="Enter a valid email address",
        field_name="email", field_value=generate_unique_email()),
    TextFieldValidator(
        expected_error="Enter a 10-digit emergency contact number",
        field_name="ec_phone", field_value="410-765-9867"),
    TextFieldValidator(
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
    TextFieldValidator(
        event_specific="magstock",
        expected_error="Please tell us who your camp leader is",
        field_name="coming_with", field_value="Marianne Testguy"),
    EnsurePage(
        expected_page="/uber/preregistration/index"
    )
]


def validate_form(driver, validators):
    for validator in regform_validations:
        validator.run(driver)


# @pytest.mark.nondestructive  # not true anymore
def test_regfield_validations(base_url, selenium):
    selenium.get('{0}/uber/preregistration/form'.format(base_url))
    assert "Preregistration" in selenium.title

    validate_form(selenium, regform_validations)