from driver import *
from utils import *
from time import gmtime, strftime
import datetime
import json
import sys
import os
import logging
from ses_handler import *

night_start = datetime.date(2013, 12, 31)
night_end = datetime.date(2014, 1, 7)

# test only
#night_start = datetime.date(2014, 1, 6)
#night_end = datetime.date(2014, 1, 7)

def setup_logging():
    aws_key = os.environ.get('AWS_KEY')
    aws_secret = os.environ.get('AWS_SECRET')
    to_addr = os.environ.get('AWS_TO_ADDRESS')
    from_addr = os.environ.get('AWS_FROM_ADDRESS')
    subject = "[screen scraper logging]"

    if aws_key == None or aws_secret == None or to_addr == None or from_addr == None:
        print "error: Amazon SES settings not set in environ variables"
        return False

    ses_handler = SESHandler(aws_key, aws_secret, from_addr, to_addr, subject)
    logging.getLogger().addHandler(ses_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.DEBUG)
    logging.getLogger().addHandler(stream_handler)

    return True

def init_hotel_checkers():

    hotels_to_check = []
    hotels_to_check.append(HamptonInnHotelRoomChecker())
    hotels_to_check.append(ALoftHotelRoomChecker())
    hotels_to_check.append(MarriottHotelRoomChecker())
    hotels_to_check.append(WestinHotelRoomChecker())
    hotels_to_check.append(GaylordHotelRoomChecker())

    return hotels_to_check

def run():
    hotels_to_check = init_hotel_checkers()
    with file_lock('/tmp/hotel-checker.lock'):

        report_start_time = strftime("%m/%d/%Y %H:%M:%S +0000", gmtime())

        results = CheckAllNights(hotels_to_check, night_start, night_end)
    
        report_end_time = strftime("%m/%d/%Y %H:%M:%S +0000", gmtime())

        data = [["report start time:", report_start_time], ["report end time:", report_end_time], results]

        with open('hotel-results.json', 'w') as outfile:
            json.dump(data, outfile)

setup_logging()
try:
    run()
except Exception:
    logging.exception('exception while running screen scraper')
