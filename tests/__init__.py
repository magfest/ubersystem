from common import *
from creates import classes

from unittest import TestCase
from subprocess import check_call

class TestUber(TestCase):
    @classmethod
    def setUpClass(cls):
        command = "python creates.py | mysql -h localhost -u {TEST_USER} --password={TEST_PASS} {TEST_DB}".format(**globals())
        check_call(command, shell=True)
        cls.email = "magfestubersystem-{}@mailinator.com".format(randrange(100000))
    
    def setUp(self):
        self.prev_state = {k:v for k,v in state.__dict__.items() if re.match("^[_A-Z]+$", k)}
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
