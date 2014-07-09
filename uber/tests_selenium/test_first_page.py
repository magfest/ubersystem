import tst_globals
import tst_web_base

class FirstPage(tst_web_base.TestWebBase):
    @staticmethod
    def navigate_to():
        tst_globals.current_test.driver.get(tst_globals.base_url)
        tst_globals.current_test.waitForPageLoad()

        FirstPage.verify_on_page()

    @staticmethod
    def verify_on_page():
        tst_globals.current_test.assertInHtml("If you're an admin, you should")

    def test_first_page(self):
        FirstPage.navigate_to()

