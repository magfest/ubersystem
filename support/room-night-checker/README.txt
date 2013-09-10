screen scraper to get us info about our hotels.
NOTE: by definition this is all a bit janky.

install instructions:

sudo apt-get install python python-pip python-virtualenv curl
virtualenv env
. env/bin/activate
pip install selenium splinter

# edit run-hotel-scraper.sh, adjust the path at the top

# then, run the following as the user you want to run as
crontab -e

*/15 * * * * /home/dom/hotel/run-hotel-scraper.sh
