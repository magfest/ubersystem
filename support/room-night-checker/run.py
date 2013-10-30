from driver import *
from utils import *
from time import gmtime, strftime
import datetime
import json
import sys

night_start = datetime.date(2013, 12, 31)
night_end = datetime.date(2014, 1, 7)

# test only
#night_start = datetime.date(2014, 1, 2)
#night_end = datetime.date(2014, 1, 3)

hotels_to_check = []
hotels_to_check.append(ALoftHotelRoomChecker())
hotels_to_check.append(MarriottHotelRoomChecker())
hotels_to_check.append(WestinHotelRoomChecker())
hotels_to_check.append(GaylordHotelRoomChecker())
hotels_to_check.append(HamptonInnHotelRoomChecker())

with file_lock('/tmp/hotel-checker.lock'):

    report_start_time = strftime("%m/%d/%Y %H:%M:%S +0000", gmtime())

    results = CheckAllNights(hotels_to_check, night_start, night_end)
    
    report_end_time = strftime("%m/%d/%Y %H:%M:%S +0000", gmtime())

    data = [["report start time:", report_start_time], ["report end time:", report_end_time], results]

    with open('hotel-results.json', 'w') as outfile:
        json.dump(data, outfile)
