screen scraper to get us info about our hotels.
NOTE: by definition this is all a bit janky.

install instructions:

requires python2.7 (python 3 won't work because Splinter doesn't support it)

sudo apt-get install python python-pip python-virtualenv curl
./setup.sh

# then, run the following as the user you want to run as
crontab -e

*/15 * * * * /absolute/path/to/run-hotel-scraper.sh
