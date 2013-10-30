from utils import *
from splinter import Browser
from datetime import timedelta
import datetime
import sys, traceback

from hotel_base import *
from hotel_gaylord import *
from hotel_hamptoninn import *
from hotel_westin import *
from hotel_aloft import *
from hotel_marriott import *

def CheckAllNights(hotels_to_check, night_start, night_end):

    nights = []
    hotel_results = []

    for night in daterange(night_start, night_end):
        nights.append(night)

    browser = Browser()

    try:
        for hotel_to_check in hotels_to_check:
            results = hotel_to_check.check_nights(nights, browser)
            hotel_results.append(results)
    except:
        print "Exception encountered!"
        traceback.print_exc(file=sys.stdout)
        raise
    else:
        browser.quit()

    return hotel_results
