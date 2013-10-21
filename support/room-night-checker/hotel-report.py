from time import gmtime, strftime, strptime
import time
import datetime
import json
import sys
from pprint import pprint
from datetime import tzinfo,timedelta,datetime

room_type_nameswaps = {
'1 KING BED NONSMOKING': '1 King Bed',
'1 KING BED STUDIO SUITE W/ SOFABED NONSMOKING': '1 King Bed Suite w/Sofabed',
'2 QUEEN BEDS NONSMOKING': '2 Queen Beds'
}

hotel_name_nameswaps = {
'Gaylord National': '<a href="https://resweb.passkey.com/go/MAGfest2014" target="_blank">Gaylord National</a>',
'Hampton Inn and Suites': '<a href="http://hamptoninn.hilton.com/en/hp/groups/personalized/W/WASOXHX-MAG-20140101/index.jhtml" target="_blank">Hampton Inn And Suites</a>'
}

raw_json_data=open('hotel-results.json')
json_data = json.load(raw_json_data)
raw_json_data.close()

#pprint(json_data)

report_start_time = json_data[0][1]
report_end_time = json_data[1][1]

print report_start_time

run_date_utc = datetime.strptime(report_end_time.encode('ascii', 'ignore').strip('+0000') + ' GMT', '%m/%d/%Y %H:%M:%S %Z')

td = datetime.utcnow() - run_date_utc
duration = td.seconds + (td.days * 24 * 3600)

#Get the date into the correct TZ
run_date_local = run_date_utc + timedelta(hours=-4)



hotels = json_data[2]

_all_dates = dict()
_report = dict()

# pass 1 - collect all unique dates
for hotel in hotels:
    nights = hotel[1]
    for night in nights:
        night_date = datetime.strptime(night[0], "%m/%d/%y")
        _all_dates.setdefault(night_date)


# pass 2 - populate report
for hotel in hotels:
    hotel_name = hotel[0]
    nights = hotel[1]
    _all_room_types = dict()
    _hotel = _report.setdefault(hotel_name, dict())

    for night in nights:
        night_date = datetime.strptime(night[0], "%m/%d/%y")

        for room_entry in night[1]:
            room_type = room_entry[0]
            price = room_entry[1]

            #print night_date + hotel_name + room_type + " " + str(price)
            _all_room_types.setdefault(room_type)

            _room_type = _hotel.setdefault(room_type, dict())
            _room_type.setdefault(night_date, price > 0)
            


    # pass 3 - make sure all unique room types and dates 
    # are present in every entry. i.e. fill in the gaps in data
    for _room_type_def in _all_room_types:
        _room_type =_hotel.setdefault(_room_type_def, dict())

        for _date_def in _all_dates:
            _night = _room_type.setdefault(_date_def, False)



# data cleansing COMPLETE, now generate the HTML

html = "<html><body><h2>Current Hotel Availability</h2>\n"

html+= "<table border=1>\n"

dates = _all_dates.keys()
dates.sort()
html+= "<tr><td></td>"
for _date in dates:
    html+= "<td>" + _date.strftime("%m/%d/%y") + "</td>"

html+= "</tr>\n"

for _hotel_name,_hotel in _report.items():


    # swap out crappy names for better ones
    if _hotel_name in hotel_name_nameswaps:
        _hotel_name = hotel_name_nameswaps[_hotel_name]

    html+= "<tr><td>" + _hotel_name + "</td></tr>\n"

    for _room_type_name,_room_entry in _hotel.items():

        # swap out crappy names for better ones
        if _room_type_name in room_type_nameswaps:
            _room_type_name = room_type_nameswaps[_room_type_name]

        _nights = _room_entry.items()
        _nights.sort()

        html+= "<tr><td>" + _room_type_name + "</td>"

        for _night_date,_available in _nights:
            if _available:
                html+= '<td style="background: green; color: white">'
            else:
                html+= '<td style="background: red; color: white">'

        html += "</tr>\n"

html += "</table>\n\n"

html += '<p>Report Last Updated ' + run_date_local.strftime("%m/%d/%Y %I:%M:%S %p") + '</p>'

html += "</body>"

print html

# pprint(_report)
