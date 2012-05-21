from common import *

import random
import requests
import itertools
from time import time, sleep
from threading import current_thread

names = list(Attendee.objects.values_list("first_name", flat=True)) + list(Attendee.objects.values_list("last_name", flat=True))
names = [s for s in names if s]

ids = list(Attendee.objects.filter(badge_type = ATTENDEE_BADGE).values_list("id", flat=True))
random.shuffle(ids)

URL_BASE = "http://localhost:4321/magfest"

next_badge_num = itertools.count(2000).next

def get(path, *args, **kwargs): return requests.get(URL_BASE + path, *args, **kwargs)

def post(path, *args, **kwargs): return requests.post(URL_BASE + path, *args, **kwargs)

def get_session_cookie():
    session_id = post("/accounts/login", data={
        "email": "eli@courtwright.org",
        "password": "RPGs7CCG"
    }).cookies["session_id"]
    return {"session_id": session_id}

def make_downloader(url_func, expected=None, name=None):
    cookies = get_session_cookie()
    def getter():
        before = time()
        text = quote(random.choice(names))
        resp = get(url_func(), cookies=cookies)
        diff = time() - before
        print("%02f => %s" % (diff, name or current_thread().name))
        if expected:
            assert expected in resp.content, resp.content
    return getter

def get_search_path():
    search_text = quote(random.choice(names))
    return "/registration/index?show=some&order=last_name&search_text=" + search_text

def get_checkin_path():
    id = ids.pop()
    badge_num = next_badge_num()
    return "/registration/check_in?id={}&badge_num={}&age_group=3".format(id, badge_num)

if __name__ == "__main__":
    Attendee.objects.filter(badge_type = ATTENDEE_BADGE).update(checked_in = None, badge_num = 0)
    
    for i in range(8):
        daemonize(make_downloader(get_search_path, name="searcher", expected="Attendee Search Results"), interval=1)
    
    for i in range(4):
        daemonize(make_downloader(get_checkin_path, name="checkin", expected="checked in as"), interval=1)
    
    for i in range(2):
        daemonize(make_downloader(lambda: "/accounts/homepage", name="homepage", expected="Ubersystem Administration"), interval=1)
    
    while True:
        sleep(1)
