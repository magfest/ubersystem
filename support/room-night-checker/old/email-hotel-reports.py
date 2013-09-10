#!/usr/bin/python2.7

# activate virtualenv
activate_this = '/home/dom/hotel-emailer/env/bin/activate_this.py'
execfile(activate_this, dict(__file__=activate_this))

from boto.ses.connection import SESConnection
import urllib
import json
import datetime
from datetime import timedelta
from datetime import date
import time
import sys

excluded_dates=["1/1/2013", "1/7/2013", "1/8/2013", "1/9/2013"]

# edit these for your setup
AWS_ACCESS_KEY_ID = "CHANGEME"
AWS_SECRET_KEY =  "CHANGEME"
ADMIN_EMAIL =  "CHANGEME"
TO_EMAIL =  "CHANGEME"
ERROR_EMAIL = "CHANGEME"

BASE_URL="http://magfestubersystem.com/cgi-bin/hotel/check_hotel_room_block_availability.py"
URL=BASE_URL+"?use_json=1"

def download_data_at(url):
	return urllib.urlopen(url).read()

def listify(x):
    return x if isinstance(x, (list,tuple,set,frozenset)) else [x]

def send_email(source, dest, subject, body, format = "text", cc = [], bcc = []):
    dest, cc, bcc = map(listify, [dest, cc, bcc])
    
    if dest:
        SESConnection(AWS_ACCESS_KEY_ID, AWS_SECRET_KEY).send_email(
            subject = subject,
            body = body,
            source = source,
            to_addresses = dest,
            cc_addresses = cc,
            bcc_addresses = bcc,
            format = format,
            return_path = source
        )

def print_err(*args):
	sys.stderr.write(' '.join(map(str,args)) + '\n')
 
json_data = download_data_at(URL)

try:
	data = json.loads(json_data)
except ValueError:
	errmsg = "couldn't parse hotel report data, JSON data was '{0}'".format(json_data) 
	print_err("error with JSON data, emailing details to Dom. error was:\n" + errmsg)
	send_email(ADMIN_EMAIL, ERROR_EMAIL, "report error", errmsg)
	raise SystemExit

query_datetime = datetime.datetime.fromtimestamp(data[0]).strftime('%m-%d-%Y at %I:%M%p')

should_email = False
force_email = True if len(sys.argv) > 1 and sys.argv[1] == "force_send" else False

problems = False
	
body="Tried to book Magfest room rates on Gaylord/Mariott's site on {0} and results were:\n\n".format(query_datetime)

for result in data[1]:
	date = result[0]
	is_ok = result[1]

	if is_ok != 1 and not date in excluded_dates:
		problems = True

	if is_ok == 0:
		msg = "***ROOMS NOT AVAILABLE***"
	elif is_ok == 1:
		msg = "Rooms available (OK)"
	else:
		msg = "Unable to retrieve room status. Try again later? Or, get Dom"
	
	body += "\n{0} ".format(date)
	body += msg

body += "\n\nFull report here: {0}\n".format(BASE_URL)
body += "NOTE: PLEASE CHECK AVAILABILITY ON THE MARIOTT SITE BEFORE ACTING ON THESE RESULTS\n"
body += "Alerts are currently being excluded for the following dates: "

for i in excluded_dates:
	body+= i + " "

should_email = problems

if not problems:
	subject = "Gaylord Mariott Hotel Room Block Status Report"
else:
	subject = "*ALERT* Gaylord Mariott Hotel Room Block Problems!"

if force_email:
	should_email = True

if should_email:
	print_err("sending email:\n" + body)
	send_email(ADMIN_EMAIL, TO_EMAIL, subject, body)
else:
	print_err("not sending email, no problems,results:\n" + body)
