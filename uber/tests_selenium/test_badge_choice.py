from unittest import TestCase
import tst_globals
import tst_web_base
import test_first_page

class BadgeChoice(tst_web_base.TestWebBase):
    @staticmethod
    def navigate_to():
        test_first_page.FirstPage.navigate_to()
        prereg_link = tst_globals.driver.find_element_by_link_text("preregister")
        prereg_link.click()
        tst_globals.current_test.waitForPageLoad()

        BadgeChoice.verify_on_page()

    @staticmethod
    def verify_on_page():
        tst_globals.current_test.assertInHtml("Continue to Preregistration Form")

    def test_on_page(self):
        BadgeChoice.navigate_to()
