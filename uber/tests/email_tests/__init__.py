from uber.common import *


class TestNormalizeEmail:
    def test_good_email(self):
        attendee = Attendee(email="joe@gmail.com")
        assert attendee.normalized_email == "joe@gmailcom"

    def test_dots(self):
        attendee = Attendee(email="j.o.e@gmail.com")
        assert attendee.normalized_email == "joe@gmailcom"

    def test_capitalized_beginning(self):
        attendee = Attendee(email="JOE@gmail.com")
        assert attendee.normalized_email == "joe@gmailcom"

    def test_capitalized_end(self):
        attendee = Attendee(email="joe@GMAIL.COM")
        assert attendee.normalized_email == "joe@gmailcom"

    def test_alternating_caps(self):
        attendee = Attendee(email="jOe@GmAiL.cOm")
        assert attendee.normalized_email == "joe@gmailcom"

    def test_empty_string(self):
        attendee = Attendee(email="")
        assert attendee.normalized_email == ""
