from hotel_starwood_base import *

class WestinHotelRoomChecker(StarwoodHotelRoomChecker):
    def __init__(self):
        self.hotel_url = 'https://www.starwoodmeeting.com/StarGroupsWeb/res?id=1310219832&key=DE27A'
        self.hotel_name = 'Westin'
