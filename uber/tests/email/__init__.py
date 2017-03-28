from uber.common import *


class TestNormalizeEmail:
    def test_good_email(self):
        assert "joe@gmail.com" == normalize_email("joe@gmail.com")

    def test_gmail_fix(self):
        assert "joe@gmail.com" == normalize_email("j.o.e@gmail.com")

    def test_capitalized_beginning(self):
        assert "joe@gmail.com" == normalize_email("JOE@gmail.com")

    def test_capitalized_end(self):
        assert "joe@gmail.com" == normalize_email("joe@GMAIL.COM")

    def test_alternating_caps(self):
        assert "joe@gmail.com" == normalize_email("jOe@GmAiL.cOm")

    def test_non_gmail_email(self):
        assert "joe@yahoo.com" == normalize_email("joe@yahoo.com")

    def test_capitalized_non_gmail_email(self):
        assert "joe@yahoo.com" == normalize_email("JOE@YAHOO.COM")

    def test_non_gmail_with_dots(self):
        assert "j.o.e@yahoo.com" == normalize_email("j.o.e@yahoo.com")

    def test_empty_string(self):
        assert "" == normalize_email("")
