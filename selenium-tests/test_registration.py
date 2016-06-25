import pytest
import uuid

@pytest.fixture
def selenium(selenium):
    selenium.implicitly_wait(10)
    selenium.maximize_window()
    return selenium


def text_in_error_message(driver, text):
    html = driver.find_elements_by_class_name("toast-message")[0].get_attribute("innerHTML")
    return text in html


def text_exists_in_head(driver, text):
    head_html = driver.find_element_by_tag_name("head").get_attribute("innerHTML")
    return text in head_html


def fill_in_text_field(driver, field_name, text):
    elem = driver.find_element_by_name(field_name)
    elem.send_keys(text)
    return elem


def fill_in_birthdate_field(driver, field_names, date_text):
    date_values = date_text.split('-')
    assert len(field_names) == len(date_values)
    fields_and_values = zip(field_names, date_values)

    elem = None
    for field,text in fields_and_values:
        elem = driver.find_elements_by_class_name(field)[0]
        elem.send_keys(text)
    return elem


class FormValidator:
    def __init__(self, **kwargs):
        self.field_name = None
        self.field_value = None
        self.expected_error = None
        self.fill_fn = fill_in_text_field
        self.submit_only = False

        for key, value in kwargs.items():
            setattr(self, key, value)

    def ensure_found_error(self, driver):
        if self.expected_error:
            assert text_in_error_message(driver, self.expected_error)

    def run(self, driver):
        if self.field_name:
            if self.submit_only:
                elem = driver.find_element_by_name(self.field_name)
            else:
                elem = self.fill_fn(driver, self.field_name, self.field_value)
            elem.submit()


def generate_unique_email():
    return "testemail-{}@testemail.com".format(str(uuid.uuid4()))

birthdate_elements = ["jq-dte-month", "jq-dte-day", "jq-dte-year"]

regform_validations = [
    FormValidator(field_name="first_name", submit_only=True),
    FormValidator(
        expected_error="First Name is a required field",
        field_name="first_name", field_value="FIRSTNAME_Attendee"),
    FormValidator(
        expected_error="Last Name is a required field",
        field_name="last_name", field_value="LASTNAME_Attendee"),
    FormValidator(
        expected_error="Enter your date of birth.", fill_fn=fill_in_birthdate_field,
        field_name=birthdate_elements, field_value = "12-09-1945"),
    FormValidator(
        expected_error="Enter a valid email address",
        field_name="email", field_value=generate_unique_email()),
    FormValidator(
        expected_error="Enter a 10-digit emergency contact number",
        field_name="ec_phone", field_value="410-765-9867"),
    FormValidator(
        expected_error="Enter a valid zip code",
        field_name="zip_code", field_value="21211"),
    # magstock-specific stuff, need a way to filter this out
    FormValidator(
        expected_error="Noise Level is a required field",
        field_name="noise_level", field_value="as"),

    # ------------------- #
    FormValidator(expected_error="Site Type is a required field"),
]


def validate_form(driver, validators):
    for validator in regform_validations:
        validator.ensure_found_error(driver)
        validator.run(driver)


# @pytest.mark.nondestructive  # not true anymore
def test_regfield_validations(base_url, selenium):
    selenium.get('{0}/uber/preregistration/form'.format(base_url))
    assert "Preregistration" in selenium.title

    validate_form(selenium, regform_validations)