import threading
import time

import pytest
import sqlalchemy

import uber.models
from uber.models import Job, Session, Shift


def _start_assign(attendee_id, job_id):
    """Run Session.assign in a worker thread; the returned dict gets 'message' or 'error'."""
    result = {}

    def run():
        try:
            with Session() as session:
                result['message'] = session.assign(attendee_id, job_id)
        except Exception as e:
            result['error'] = e

    worker = threading.Thread(target=run)
    worker.start()
    return worker, result


def _wait_until_a_query_waits_on_a_lock(timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        # pg_stat_activity truncates query text at 1 KB, which cuts off the FOR UPDATE clause.
        with Session() as session:
            waiting = session.execute(sqlalchemy.text(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                "AND wait_event_type = 'Lock' AND query LIKE 'SELECT job.id %'")).scalar()
        if waiting:
            return
        time.sleep(0.05)
    raise AssertionError('no query waited on the job row lock')


def _lock_job_with_pending_shift(committed):
    holder = Session()
    holder.query(Job).filter(Job.id == committed['job']).with_for_update(of=Job).one()
    holder.add(Shift(job_id=committed['job'], attendee_id=committed['first']))
    holder.flush()
    return holder


def test_signup_waits_for_concurrent_signup_on_same_job(committed, shift_count):
    holder = _lock_job_with_pending_shift(committed)
    try:
        worker, result = _start_assign(committed['second'], committed['job'])
        _wait_until_a_query_waits_on_a_lock()
        holder.commit()
        worker.join(timeout=10)
    finally:
        holder.close()

    assert 'error' not in result, result.get('error')
    assert result['message'] == 'All slots for this job have already been filled.'
    assert shift_count(committed['job']) == 1


def test_signup_gives_up_when_job_stays_locked(committed, shift_count, monkeypatch):
    monkeypatch.setattr(uber.models, 'SHIFT_LOCK_TIMEOUT', '200ms')
    holder = _lock_job_with_pending_shift(committed)
    try:
        worker, result = _start_assign(committed['second'], committed['job'])
        worker.join(timeout=10)
        assert not worker.is_alive()
    finally:
        holder.rollback()
        holder.close()

    assert 'error' not in result, result.get('error')
    assert result['message'] == 'Someone else is signing up for this shift right now. Please try again.'
    assert shift_count(committed['job']) == 0


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
