import threading
import time
import uuid
from datetime import timedelta

import pytest
import sqlalchemy

import uber.models
from uber.config import c
from uber.models import Attendee, Department, Job, Session, Shift, Tracking


@pytest.fixture
def committed(request):
    """Commit a department, a job, and two staffers so separate connections can see them.

    Parametrize indirectly to set the job's slot count; the default is 1.
    """
    def staffer(session, first_name):
        attendee = Attendee(first_name=first_name, last_name='Assign', email=f'{uuid.uuid4().hex}@example.com',
                            badge_type=c.STAFF_BADGE, badge_status=c.COMPLETED_STATUS, paid=c.NEED_NOT_PAY,
                            staffing=True)
        session.add(attendee)
        return attendee

    slots = getattr(request, 'param', 1)
    with Session() as session:
        dept = Department(name=f'Assign {uuid.uuid4().hex[:8]}', description='Assign')
        session.add(dept)
        session.flush()
        job = Job(department_id=dept.id, name='Gate', start_time=c.EPOCH + timedelta(hours=2), duration=60, slots=slots)
        session.add(job)
        first, second = staffer(session, 'First'), staffer(session, 'Second')
        session.commit()
        ids = {'dept': dept.id, 'job': job.id, 'first': first.id, 'second': second.id}

    yield ids

    with Session() as session:
        session.query(Shift).filter(Shift.job_id == ids['job']).delete()
        session.query(Job).filter(Job.id == ids['job']).delete()
        session.query(Attendee).filter(Attendee.id.in_([ids['first'], ids['second']])).delete()
        session.query(Department).filter(Department.id == ids['dept']).delete()
        session.query(Tracking).filter(Tracking.fk_id.in_(list(ids.values()))).delete()
        # Shift rows are gone by now; their Tracking entries carry the job id in the repr.
        session.query(Tracking).filter(Tracking.model == 'Shift', Tracking.data.contains(ids['job'])).delete(
            synchronize_session=False)
        session.commit()


@pytest.fixture
def shift_count():
    """Return a function that counts committed shifts for a job."""
    def count(job_id):
        with Session() as session:
            return session.query(Shift).filter(Shift.job_id == job_id).count()
    return count


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
