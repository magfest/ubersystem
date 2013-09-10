#!/bin/bash

cd /home/dom/hotel

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

echo "uploading data...."

# upload the data to the server
runit curl --data-urlencode hotel_report_data@hotel-results.json -d 'username=8734784jh' -d 'password=8762$$34bab' http://bitgengamerfest.com/hotel/index.php 

echo "done!"
