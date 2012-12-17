#!/usr/bin/python2.7
from bs4 import *
import cgi, cgitb 
import os
import time
from datetime import timedelta, datetime
import pickle
import json


# constants
query_string = "http://marriott.com/reservation/availabilitySearch.mi?fromDate={0}&toDate={1}&accountId=&propertyCode=wasgn&isHwsGroupSearch=true&isSearch=false&numberOfNights=1&miniStoreAvailabilitySearch=false&flexibleDateSearch=false&minDate=11%2F30%2F2012&maxDate=11%2F17%2F2013&monthNames=January%2CFebruary%2CMarch%2CApril%2CMay%2CJune%2CJuly%2CAugust%2CSeptember%2COctober%2CNovember%2CDecember&weekDays=S%2CM%2CT%2CW%2CT%2CF%2CS&dateFormatPattern=M%2Fd%2Fyy&lengthOfStay=1&populateTodateFromFromDate=true&defaultToDateDays=1&numberOfRooms=1&numberOfGuests=1&includeNearByLocation=false&marriottRewardsNumber=&useRewardsPoints=false&flushSelectedRoomType=true&corporateCode=&clusterCode=group&groupCode=mgfmgfa&displayableIncentiveType_Number"

rate_we_want="135.00"
search_month = 1
search_year = 2013
search_start_day = 1
search_end_day = 9

def open_page( url ):
	tmpfile = "/tmp/t876234.html"
	os.system("wget \"" + url + "\" -O "+tmpfile)
	soup = BeautifulSoup(open(tmpfile), "lxml")
	os.remove(tmpfile)
	return soup
	#return BeautifulSoup(open("/tmp/t876234.html"))

# returns 0 if not foud, 1 if found, and 2 on error
def validate_room_rate_available( soup ):
	for link in soup.find_all('a'):
		if "135.00" in link.text:
			return 1

	if "No rooms are available at this hotel for the dates you selected" in soup.title.string:
		return 0

	return 2

# note: breaks if date range goes across a month boundary.
# don't care. -Dom
def build_url_string( month, day, year, base_query_string):
	from_date = "{0}/{1}/{2}".format(month, day, year)
	to_date = "{0}/{1}/{2}".format(month, day+1, year)

	from_date.replace("/","%2F");
	to_date.replace("/","%2F");

	return base_query_string.format(from_date, to_date);
	

def check_if_room_rate_available( month, day, year ):
	url = build_url_string(month,day,year,query_string)
	soup = open_page(url);
	return validate_room_rate_available(soup);

def get_room_rate_availability( month, start_day, end_day, year ):
	results = [time.time(), []]
	for day in range(start_day, end_day+1):
		result = check_if_room_rate_available( month, day, year )
		results[1].append(["{0}/{1}/{2}".format(month,day,year),result])
	return results

def get_hotel_data_or_get_from_cache(force_refresh):
	dump_file = "/tmp/last-hotel-results.dump"
	should_refresh = False

	try:
		results = pickle.load( open(dump_file, "rb" ))
	except Exception:
		should_refresh = True
		pass

	if not should_refresh:
		date_of_last_get = datetime.fromtimestamp(results[0])
		now = datetime.fromtimestamp(time.time());
		delta = now - date_of_last_get
		minutes_old = delta.seconds / 60
		if minutes_old < 0 or minutes_old > 15:
			should_refresh = True

	if force_refresh:
		should_refresh = True

	if should_refresh:
		results = get_room_rate_availability(search_month, search_start_day, search_end_day, search_year)
		try:
			pickle.dump(results, open(dump_file, "wb"))
		except Exception:
			pass

	return results

def html_print_availabilities( results ):
	print "Content-Type: text/html\n\n";
	print("<h1>Results</h1><br/><table>")

	query_datetime = datetime.fromtimestamp(results[0]).strftime('%m-%d-%Y at %I:%M%p')
	print("<tr><td colspan=2>Hotel data last collected on: {0}. Refreshes every 15 minutes</td></tr>".format(query_datetime))

	for r in results[1]:
		if r[1] == 0:
			msg = "<font color=red>NOT AVAILABLE!</font>"
		elif r[1] == 1:
			msg = "<font color=green>Available</font>"
		else:
			msg = "<font color=orange>Unable to retrieve data, try again?</font>"
		print("<tr><td>{0}</td><td>{1}</td></tr>".format(r[0], msg))

	print("</table><br/><a href=\"?force_refresh=1\">Force a refresh</a>")	

def json_print_availabilities(results):
	print "Content-Type: text/plain\n\n"
	print json.dumps(results)
	

form = cgi.FieldStorage()
force_refresh = form.getvalue('force_refresh') == "1"
use_json = form.getvalue('use_json') == "1"

results = get_hotel_data_or_get_from_cache(force_refresh)
if use_json:
	json_print_availabilities(results)
else:
	html_print_availabilities(results)
	
