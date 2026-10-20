import inspect

import pytest

from uber.config import c
from uber.models import Session, Shift, Tracking
from uber.site_sections.staffing import Root

# The undecorated handler body; the account and CSRF decorators need a live request.
drop = inspect.unwrap(Root.drop)


def _drop(session, committed):
    return drop(Root(), session, id=committed['first'], job_id=committed['job'])


def test_drop_removes_shift_and_reports_new_hours(committed, shift_count):
    with Session() as session:
        assert session.assign(committed['first'], committed['job']) is None

    with Session() as session:
        assert _drop(session, committed) == {'success': True, 'message': 'Shift dropped.', 'hours': 0}
    assert shift_count(committed['job']) == 0


def test_drop_records_tracking_row(committed):
    with Session() as session:
        assert session.assign(committed['first'], committed['job']) is None
        shift_id = session.query(Shift).filter_by(job_id=committed['job']).one().id

    with Session() as session:
        _drop(session, committed)

    with Session() as session:
        assert session.query(Tracking).filter_by(fk_id=shift_id, action=c.DELETED).count() == 1


@pytest.mark.parametrize('committed', [2], indirect=True)
def test_drop_removes_duplicate_rows_for_one_job(committed, shift_count):
    with Session() as session:
        session.add_all([Shift(job_id=committed['job'], attendee_id=committed['first']) for _ in range(2)])
        session.commit()

    with Session() as session:
        assert _drop(session, committed)['message'] == 'Shift dropped.'
    assert shift_count(committed['job']) == 0


def test_drop_reports_shift_already_gone(committed):
    with Session() as session:
        result = _drop(session, committed)

    assert result['message'] == "You've already dropped or have been unassigned from this shift."


def test_drop_does_not_report_success_when_commit_fails(committed, shift_count, monkeypatch):
    with Session() as session:
        assert session.assign(committed['first'], committed['job']) is None

    with Session() as session:
        def fail():
            raise RuntimeError('commit failed')
        monkeypatch.setattr(session, 'commit', fail)

        with pytest.raises(RuntimeError):
            _drop(session, committed)
        session.rollback()

    assert shift_count(committed['job']) == 1
