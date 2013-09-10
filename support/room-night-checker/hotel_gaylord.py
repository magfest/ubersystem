from hotel_base import *
from splinter import Browser
from datetime import timedelta
import datetime

class GaylordHotelRoomChecker(HotelRoomChecker):
    def check_nights(self, night_dates, browser):
        availability = []
        for night_date in night_dates:
            results = self.check_night(night_date, browser)
            availability.append([night_date.strftime("%m/%d/%y"), results])

        return ["Gaylord National", availability]

    def check_night(self, night_date, browser):
        print "Gaylord national|" + night_date.strftime("%m/%d/%y")

        browser.visit('https://resweb.passkey.com/go/MAGfest2014')
        browser.select('groupTypeCode', 'Attendee')

        browser.fill('checkinDate', night_date.strftime("%m/%d/%y"))
        browser.fill('checkoutDate', (night_date+timedelta(1)).strftime("%m/%d/%y"))

        browser.execute_script("onSubmitFrm();")

        form = browser.find_by_xpath('//*[@id="BodyTwo"]/form')

        rooms = [];

        for room_div in form.find_by_id('OutPointRoom1'):
            # get the room type (Deluxe room vs Atrium vs Suite)
            room_type_div = room_div.find_by_xpath('div[2]/div/div[1]')
            room_type = room_type_div[0].text.strip()

            # get the price, if it exists
            price_div = room_div.find_by_xpath('div[3]/div/div[1]')
            price = 0

            if "USD" in price_div.text:
                price = float(price_div.text[4:])
 
            # look for this text, as a safety measure
            room_not_available = "Your dates are not available." in room_div.html

            if price == 0:
                assert room_not_available
            else:
                assert not room_not_available

            print "found|" + room_type + "|" + str(price)

            rooms.append([room_type, price])

        return rooms
