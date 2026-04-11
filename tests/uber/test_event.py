from datetime import timedelta
from datetime import datetime, timezone

from uber.config import c
from uber.models import Event


def test_minutes():
    now = datetime.now(timezone.utc)
    # minutes returns a set of datetime objects, one per minute of duration
    assert set() == Event(start_time=now, duration=0).minutes
    assert 30 == len(Event(start_time=now, duration=30).minutes)
    assert 60 == len(Event(start_time=now, duration=60).minutes)
    assert 150 == len(Event(start_time=now, duration=150).minutes)
    # Each minute in the set is start_time + timedelta(minutes=i)
    e = Event(start_time=now, duration=3)
    expected = {now + timedelta(minutes=i) for i in range(3)}
    assert expected == e.minutes
