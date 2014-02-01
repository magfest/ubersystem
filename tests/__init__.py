from unittest import TestCase

from uber.common import *
from uber import creates

def setUpModule():
    creates.drop_and_create()

class TestUber(TestCase):
    def tearDown(self):
        for model in reversed(creates.classes):
            model.objects.all().delete()

    def make_attendee(self, **params):
        params = dict({
            'first_name': 'Testie',
            'last_name':  'McTesterson',
            'badge_type': ATTENDEE_BADGE,
            'badge_num':  next_badge_num(ATTENDEE_BADGE),
            'email':      self.email,
            'zip_code':   '00000',
            'ec_phone':   '1234567890'
        }, **params)
        return Attendee.objects.create(**params)

    def make_group(self, **params):
        params = dict({
            'name': 'Some Group',
            'tables': 0,
        }, **params)
        return Group.objects.create(**params)
