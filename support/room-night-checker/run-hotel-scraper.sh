#!/bin/bash

export ABSOLUTE_PATH=/home/dom/hotel
cd $ABSOLUTE_PATH

if [ -e secret_settings.sh ]
then
	echo "using secret settings"
	. secret_settings.sh
else
	export USER=CHANGEME
	export PASS=CHANGEME
	export API_URL=http://CHANGEME.COM/CHANGE/THIS.php
fi

# don't need to modify below this point

echo "writing all output to scraper-log.txt"

function runit {
    "$@" >> scraper-log.txt 2>&1
    status=$?
    if [ $status -ne 0 ]; then
	echo "error with $1"
	exit -1
    fi
    return $status
}			  


. env/bin/activate
export DISPLAY=:0

echo "starting new screen scrape"
runit date

# do the screen scraping
runit python run.py

echo "uploading data to: " $API_URL

# upload the data to the server
runit curl --data-urlencode hotel_report_data@hotel-results.json -d "username=$USER" -d "password=$PASS" $API_URL

echo "done!"
