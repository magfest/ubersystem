from splinter import Browser
from selenium.common.exceptions import NoAlertPresentException
import time

class HotelRoomChecker(object):
    def check_nights(self, night_dates, browser):
        raise 'dont call this directly'

    # complete stupidity. you can't call get_alert() without 
    # it throwing an exception if no alert is present. work around it.
    def get_alert_if_present(self):
        try:
            alert = self.browser.get_alert()
            if alert != None:
                return alert
        except NoAlertPresentException:
            pass
        return None

    def dismiss_alert(self):
        alert = self.get_alert_if_present()
        if alert != None:
            alert.dismiss()

    def wait_for_javascript_function_to_load(self, javascript_fn_name):
        
        loaded_javascript = False
        num_seconds_to_wait = 15
        while num_seconds_to_wait != 0:
            loaded_javascript = self.browser.evaluate_script("typeof "+javascript_fn_name+" === 'function'")
            if loaded_javascript:
                break
            time.sleep(1)
            num_seconds_to_wait -= 1

        return loaded_javascript
