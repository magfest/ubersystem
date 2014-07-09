from unittest import TestCase
from selenium import webdriver
#from selenium.common.exceptions import TimeoutException
#from selenium.webdriver.support.ui import WebDriverWait # available since 2.4.0
#from selenium.webdriver.support import expected_conditions as EC # available since 2.26.0

import tst_globals
import time

reset_webdriver_each_run = False

class TestWebBase(TestCase):
    def init_webdriver(self):
        if tst_globals.driver is not None:
            tst_globals.driver.quit()
            tst_globals.driver = None

        self.driver = tst_globals.driver = webdriver.Firefox()

    def setUp(self):
        if tst_globals.driver is None or reset_webdriver_each_run:
            self.init_webdriver()

        self.driver = tst_globals.driver
        tst_globals.current_test = self

    def tearDown(self):
        if reset_webdriver_each_run and self.driver is not None:
            tst_globals.driver.quit()
            self.driver = tst_globals.driver = None

        tst_globals.current_test = None

    # all uber pages that inherit from base.html should include <div id="bottomAnchor" /> at the bottom
    def waitForPageLoad(self):
        found_element = False
        remaining_tries = 50
        while not found_element and remaining_tries > 0:
            found_element = self.driver.find_element_by_id("bottomAnchor")
            time.sleep(0.25)
            remaining_tries -= 1

        self.assertTrue(remaining_tries != 0, "Error: Timeout: page failed to load, or, couldn't find div with ID of 'bottomAnchor'")

    def assertInHtml(self, str):
        html = self.driver.page_source
        found_in_html = str.lower() in html.lower()
        self.assertTrue(found_in_html, "FAIL: {} not in HTML, {}".format(str, html))
