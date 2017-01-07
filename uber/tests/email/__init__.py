from uber.common import *

def test_good_email():
    assert "joe@gmail.com" == normalize_email("joe@gmail.com")

def test_gmail_fix():
    assert "joe@gmail.com" == normalize_email("j.o.e@gmail.com")

def test_capitalized_beginning():
    assert "joe@gmail.com" == normalize_email("JOE@gmail.com")

def test_capitalized_end():
    assert "joe@gmail.com" == normalize_email("joe@GMAIL.COM")

def test_alternating_caps():
    assert "joe@gmail.com" == normalize_email("jOe@GmAiL.cOm")

def test_non_gmail_email():
    assert "joe@yahoo.com" == normalize_email("joe@yahoo.com")

def test_capitalized_non_gmail_email():
    assert "joe@yahoo.com" == normalize_email("JOE@YAHOO.COM")

def test_non_gmail_with_dots():
    assert "j.o.e@yahoo.com" == normalize_email("j.o.e@yahoo.com")

def test_empty_string():
    assert "" == normalize_email("")
