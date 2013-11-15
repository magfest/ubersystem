from hotel_base import *
from splinter import Browser
from datetime import timedelta
import datetime
import time
import re

class HamptonInnHotelRoomChecker(HotelRoomChecker):
    def check_nights(self, night_dates, browser):
        availability = []
        for night_date in night_dates:
            results = self.check_night(night_date, browser)
            availability.append([night_date.strftime("%m/%d/%y"), results])

        return ["Hampton Inn and Suites", availability]

    def check_night(self, night_date, browser):
        print "Hampton Inn and Suites|" + night_date.strftime("%m/%d/%y")

        browser.visit('http://hamptoninn.hilton.com/en/hp/groups/personalized/W/WASOXHX-MAG-20140101/index.jhtml')

        # wait for all javascript to load
        loaded_javascript = False
        num_seconds_to_wait = 15
        while num_seconds_to_wait != 0:
            loaded_javascript = browser.evaluate_script("typeof getDates === 'function'")
            if loaded_javascript:
                break
            time.sleep(1)
            --num_seconds_to_wait

        if not loaded_javascript:
            raise ValueError('javascript didnt load, Hampton Inn page')

        # go to next page
        browser.execute_script("getDates(document.forms['dateForm'].date0.value);")

        # make sure the page has loaded, wait up to 10 seconds before bailing
        browser.is_element_present_by_name('arrivalDate', wait_time=10)

        # fill in the dates (note: hampton in will convert to another date format)
        browser.fill('arrivalDate', night_date.strftime("%m/%d/%y"))
        browser.fill('departureDate', (night_date+timedelta(1)).strftime("%m/%d/%y"))
        
        # HACK: do this one more time, so the date from departureDate is 
        # auto-filled
        browser.fill('arrivalDate', night_date.strftime("%m/%d/%y"))
        browser.fill('departureDate', (night_date+timedelta(1)).strftime("%m/%d/%y"))

        # click the submit button
        # browser.execute_script("submitForm(this, '_eventId_findRoom', true);")
        browser.find_by_name('_eventId_findRoom').first.click()

        list_items = browser.find_by_xpath('//*[@id="sortByRoom"]/div/ul/li')
    
        if "The requested rate is not available" in browser.html:
            return []
        
        rooms = []

        # NOTE: not all list items are visible.
        for list_item in list_items:
            #print list_item.html.encode('ascii', 'ignore')

            raw_room_info_str = list_item['class']
            style = list_item['style']

            # if it says "display: hidden;", ignore it.
            if not "display: block;" in style:
                break

            room_type = list_item.find_by_xpath("div[1]/h2").text
            room_type = room_type.replace('"', ' ').strip()

            # get the price, if it exists
            price_text = list_item.find_by_xpath('descendant::form/span').text
            price_text.strip()
            price = 0

            if "$" in price_text:
                price = float(price_text[1:])
 
            print "found: " + room_type + " " + str(price)

            rooms.append([room_type, price])

        return rooms
