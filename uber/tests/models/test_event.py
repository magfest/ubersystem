from uber.tests import *


def test_minutes():
    assert 0 == Event().minutes
    assert 30 == Event(duration=1).minutes
    assert 60 == Event(duration=2).minutes
    assert 150 == Event(duration=5).minutes


def test_start_slot():
    assert None is Event().start_slot
    assert 0 == Event(start_time=c.EPOCH).start_slot
    assert 2 == Event(start_time=c.EPOCH + timedelta(hours=1)).start_slot
    assert 6 == Event(start_time=c.EPOCH + timedelta(hours=3)).start_slot


def test_half_hours():
    assert Event(start_time=c.EPOCH, duration=3).half_hours == {
        c.EPOCH,
        c.EPOCH + timedelta(minutes=30),
        c.EPOCH + timedelta(minutes=60)
    }
