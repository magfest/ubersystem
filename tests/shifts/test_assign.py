import pytest

from uber.models import Session


@pytest.mark.parametrize('committed', [2], indirect=True)
def test_signup_refuses_duplicate_when_volunteer_was_loaded_earlier(committed, shift_count):
    stale, other = Session(), Session()
    try:
        # sign_up holds the volunteer like this, so the identity map keeps its shifts stale.
        volunteer = stale.volunteer_from_id(committed['first'])
        assert volunteer.shifts == []

        assert other.assign(committed['first'], committed['job']) is None

        assert stale.assign(committed['first'], committed['job']) == \
            'This volunteer is already signed up for this shift.'
    finally:
        stale.close()
        other.close()

    assert shift_count(committed['job']) == 1


def test_signup_sees_shifts_committed_after_job_was_loaded(committed, shift_count):
    stale, other = Session(), Session()
    try:
        # Holding the job keeps it, and its loaded shifts, in the stale session's identity map.
        job = stale.job(committed['job'])
        assert job.shifts == []

        assert other.assign(committed['first'], committed['job']) is None

        assert stale.assign(committed['second'], committed['job']) == \
            'All slots for this job have already been filled.'
    finally:
        stale.close()
        other.close()

    assert shift_count(committed['job']) == 1
