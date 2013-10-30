from hotel_base import *
from splinter import Browser
from datetime import timedelta
import datetime
import time
import re

class StarwoodHotelRoomChecker(HotelRoomChecker):

    def __init__(self):
        self.hotel_name = "CHANGE ME!"
        self.hotel_url = "http://CHANGE.ME"

    def check_nights(self, night_dates, browser):
        availability = []
        for night_date in night_dates:
            results = self.check_night(night_date, browser)
            availability.append([night_date.strftime("%m/%d/%y"), results])

        return [self.hotel_name, availability]

    def check_night(self, night_date, browser):
        print self.hotel_name + "|" + night_date.strftime("%m/%d/%y")

        browser.visit(self.hotel_url)

        browser.click_link_by_partial_href('beginReservation.go')

        # wait for all javascript to load
        loaded_javascript = False
        num_seconds_to_wait = 15
        while num_seconds_to_wait != 0:
            loaded_javascript = browser.evaluate_script("typeof doSearchForm() === 'function'")
            if loaded_javascript:
                break
            time.sleep(1)
            --num_seconds_to_wait

        if not loaded_javascript:
            raise ValueError('javascript didnt load, Westin page')

        with browser.get_alert() as alert:
            if alert != None:
                alert.dismiss()

        # go to next page
        browser.execute_script("doSearchForm()")

        with browser.get_alert() as alert:
            if alert != None:
                alert.dismiss()

        # make sure the page has loaded, wait up to 10 seconds before bailing
        input_name = 'resStartDate'
        browser.is_element_present_by_name(input_name, wait_time=10)

        # fill in the dates (note: hampton in will convert to another date format)
        browser.fill(input_name, night_date.strftime("%Y-%m-%d"))
        browser.fill('resEndDate', (night_date+timedelta(1)).strftime("%Y-%m-%d"))


        # click the submit button
        browser.execute_script("doSearchForm()")

        # this hotel complains if you try out of range dates, so just skip
        try:
            alert = browser.get_alert()
            if alert != None and 'cannot' in alert.text:
                alert.dismiss()
                return []
        except Exception: #selenium.common.exceptions.NoAlertPresentException:
            pass
            # stupidity: you can't call get_alert() without it throwing this

        table_rows = browser.find_by_xpath('//*[@id="resultstable"]/table/tbody/tr')
    
        rooms = []

        for tr in table_rows:
            #print tr.html.encode('ascii', 'ignore')

            if 'resultshead' in tr['class']:
                continue

            if not 'USD' in tr.html:
                continue

            room_type = tr.find_by_xpath('td[2]').text

            room_type = room_type.replace('"', ' ').strip()

            # get the price, if it exists
            price_text = tr.find_by_xpath('td[4]').text
            price_text.strip()
            price_text = price_text.split()[1]
            price = float(price_text)
 
            print "found: " + room_type + " " + str(price)

            rooms.append([room_type, price])

        return rooms
