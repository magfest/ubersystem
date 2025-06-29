from datetime import timedelta

from uber.config import c
from uber.models import Event


def test_minutes():
    assert 0 == Event().minutes
    assert 30 == Event(duration=30).minutes
    assert 60 == Event(duration=60).minutes
    assert 150 == Event(duration=150).minutes

