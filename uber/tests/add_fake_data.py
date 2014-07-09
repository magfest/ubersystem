__author__ = 'Dom'

from uber.common import *

def add_fake_attendee():
    params = dict({
            'placeholder': True,
            'first_name':  'Testie',
            'last_name':   'McTesterson',
            'badge_type':  ATTENDEE_BADGE,
            'paid': HAS_PAID,
            'amount_paid': 40,
        })

    attendee = Attendee.objects.create(**params)

    print("attendee created: " + attendee.last_first)
    return

def run():
    print("Fake Data Utility: TESTING ONLY.")

    if len(sys.argv) <= 1:
        print('''This utility adds fake data to the ubersystem database for testing purposes only.

        Please specify one of the following options:
        -a Add a fake attendee
        ''')
        return

    add_attendee = '-a' in sys.argv
    if add_attendee:
        add_fake_attendee()

if __name__ == '__main__':
    run()
