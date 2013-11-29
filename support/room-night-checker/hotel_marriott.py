from hotel_base import *
from splinter import Browser
from datetime import timedelta
import datetime
import time
import re

class MarriottHotelRoomChecker(HotelRoomChecker):
    def check_nights(self, night_dates, browser):
        availability = []
        for night_date in night_dates:
            results = self.check_night(night_date, browser)
            availability.append([night_date.strftime("%m/%d/%y"), results])

        return ["Marriott Residence Inn", availability]

    def check_night(self, night_date, browser):
        print("Marriott|" + night_date.strftime("%m/%d/%y"))

        browser.visit('http://www.marriott.com/meeting-event-hotels/group-corporate-travel/groupCorp.mi?resLinkData=MAGFest%20%5EWASNH%60MAGMAGA%60135.00%60USD%60false%6012/31/13%601/6/14%6012/3/13&app=resvlink&stop_mobi=yes')

        # make sure the page has loaded, wait up to 10 seconds before bailing
        input_name = 'fromDate'
        browser.is_element_present_by_name(input_name, wait_time=10)

        # fill in the dates (note: hampton in will convert to another date format)
        browser.fill(input_name, night_date.strftime("%m/%d/%y"))
        browser.fill('toDate', (night_date+timedelta(1)).strftime("%m/%d/%y"))


        # click the submit button
        button = browser.find_by_id('check-availability-button1')
        button.click()

        # this hotel complains if you try out of range dates, so just skip
        try:
            alert = browser.get_alert()
            if alert != None and 'cannot' in alert.text:
                alert.dismiss()
                return []
        except Exception: #selenium.common.exceptions.NoAlertPresentException:
            pass
            # stupidity: you can't call get_alert() without it throwing this

        table_rows = browser.find_by_xpath('//*[@id="tab0"]/table/tbody/tr')
    
        rooms = []

        for tr in table_rows:
            #print tr.html.encode('ascii', 'ignore')

            if not 'USD' in tr.html:
                continue

            room_type = tr.find_by_xpath('td[2]/div/p[1]').text

            room_type = room_type.replace('"', ' ').strip()

            # get the price, if it exists
            price_text = tr.find_by_xpath('td[3]/div[2]/label/em').text
            price_text.strip()
            price = float(price_text)
 
            print("found: " + room_type + " " + str(price))

            rooms.append([room_type, price])

        return rooms
