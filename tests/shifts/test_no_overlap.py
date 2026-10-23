from datetime import datetime, timedelta

import pytest
import pytz

from uber.models import Attendee, Job, Shift

START = datetime(2027, 1, 8, 12, tzinfo=pytz.UTC)


def _volunteer_holding(start, duration):
    volunteer = Attendee()
    volunteer.shifts = [Shift(job=Job(start_time=start, duration=duration))]
    return volunteer


@pytest.mark.parametrize('offset, duration, expected', [
    (-60, 60, True),   # ends as the held shift starts
    (120, 60, True),   # starts as the held shift ends
    (-60, 61, False),  # one minute into the held shift
    (119, 60, False),  # starts in its last minute
    (30, 30, False),   # inside it
    (-30, 240, False),  # covers it
])
def test_no_overlap_compares_intervals(offset, duration, expected):
    volunteer = _volunteer_holding(START, 120)
    job = Job(start_time=START + timedelta(minutes=offset), duration=duration)

    assert job.no_overlap(volunteer) is expected


def test_zero_minute_jobs_overlap_nothing():
    assert Job(start_time=START + timedelta(minutes=30), duration=0).no_overlap(_volunteer_holding(START, 120))
    assert Job(start_time=START - timedelta(minutes=30), duration=120).no_overlap(_volunteer_holding(START, 0))
