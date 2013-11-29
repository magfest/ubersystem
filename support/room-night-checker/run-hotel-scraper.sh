#!/bin/bash

# when run from cron, the path is wherever cron feels like running from
ABSOLUTE_PATH=$(dirname $(readlink -f ${BASH_SOURCE[0]}))
START_X_SERVER=1
export DISPLAY=:2    # keep a different number if you're doing other X stuff

# don't need to modify below this point

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

# this is kinda hacky. but probably works. YMMV
# if in doubt, just have your X server started up already
if [ $START_X_SERVER -eq "1" ]
then
	if [[ -n "$(pgrep startx)" ]]
	then
		killall xinit
		#killall x11vnc
		sleep 5
	fi

	startx -- $DISPLAY &
	sleep 5
	#x11vnc -display $DISPLAY -passwd test &
fi

killall firefox

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

echo "starting new screen scrape"
runit date

# do the screen scraping
runit python run.py

echo "uploading data to: " $API_URL

# upload the data to the server
runit curl --data-urlencode hotel_report_data@hotel-results.json -d "username=$USER" -d "password=$PASS" $API_URL

echo "done!"
