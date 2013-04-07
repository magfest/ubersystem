import os
import sys
from unittest import TestCase
from subprocess import check_call

from common import *
from creates import classes

def tearDownModule():
    cherrypy.engine.exit()
    for fname in glob("sessions/session-*"):
        os.remove(fname)

class TestUber(TestCase):
    @classmethod
    def setUpClass(cls):
        command = "python creates.py | PGPASSWORD={TEST_PASS} psql --host=localhost --user={TEST_USER} {TEST_DB} >/dev/null 2>/dev/null".format(**globals())
        check_call(command, shell=True)
        cls.email = "magfestubersystem-{}@mailinator.com".format(randrange(100000))
        cherrypy.engine.start()
        cherrypy.engine.wait(cherrypy.engine.states.STARTED)
    
    @classmethod
    def tearDownClass(cls):
        cherrypy.engine.stop()
        cherrypy.engine.wait(cherrypy.engine.states.STOPPED)
    
    def setUp(self):
        self.prev_state = {k:v for k,v in State.__dict__.items()
                               if not isinstance(v, property) and re.match("^[_A-Z]+$", k)}
        state.HOSTNAME = "localhost:{}".format(PORT)
    
    def tearDown(self):
        for k,v in self.prev_state.items():
            setattr(state, k, v)
        
        for model in reversed(classes):
            model.objects.all().delete()
    
    def make_attendee(self, **params):
        params = dict({
            "first_name": "Test",
            "last_name":  "McTesterson",
            "badge_type": ATTENDEE_BADGE,
            "badge_num":  next_badge_num(ATTENDEE_BADGE),
            "email":      self.email,
            "zip_code":   "00000",
            "ec_phone":   "1234567890"
        }, **params)
        return Attendee.objects.create(**params)
    
    def make_group(self, **params):
        params = dict({
            "name": "Some Group",
            "tables": 0,
        }, **params)
        return Group.objects.create(**params)
