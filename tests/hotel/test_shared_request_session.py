"""Session() joins the request's session inside a page handler instead of taking a second connection."""
import pytest
from sqlalchemy import event, text

from uber.models import Session


@pytest.fixture
def checkouts(database):
    held = {'now': 0, 'peak': 0}

    def on_checkout(dbapi_conn, record, proxy):
        held['now'] += 1
        held['peak'] = max(held['peak'], held['now'])

    def on_checkin(dbapi_conn, record):
        held['now'] -= 1

    event.listen(Session.engine, 'checkout', on_checkout)
    event.listen(Session.engine, 'checkin', on_checkin)
    yield held
    event.remove(Session.engine, 'checkout', on_checkout)
    event.remove(Session.engine, 'checkin', on_checkin)


def test_sessions_are_separate_outside_a_request(checkouts):
    with Session() as outer:
        outer.execute(text('SELECT 1'))
        with Session() as inner:
            inner.execute(text('SELECT 1'))
            assert inner is not outer
    assert checkouts['peak'] == 2


def test_helper_sessions_join_the_request_session(checkouts):
    with Session.for_request() as request_session:
        request_session.execute(text('SELECT 1'))
        with Session() as helper:
            assert helper is request_session
            helper.execute(text('SELECT 1'))
        # Leaving the helper block must not end the request's transaction
        assert request_session.in_transaction()
        assert checkouts['now'] == 1
    assert checkouts['peak'] == 1
    assert checkouts['now'] == 0


def test_unmanaged_helper_session_joins_and_ignores_close(checkouts):
    with Session.for_request() as request_session:
        helper = Session()
        helper.execute(text('SELECT 1'))
        helper.close()
        assert request_session.in_transaction()
    assert checkouts['peak'] == 1


def test_independent_session_is_separate(checkouts):
    with Session.for_request() as request_session:
        request_session.execute(text('SELECT 1'))
        with Session(independent=True) as own:
            assert own is not request_session
            own.execute(text('SELECT 1'))
    assert checkouts['peak'] == 2


def test_nested_request_restores_the_outer_session(database):
    with Session.for_request() as outer:
        with Session.for_request() as inner:
            assert inner is not outer
            with Session() as helper:
                assert helper is inner
        with Session() as helper:
            assert helper is outer
    with Session() as after:
        assert after is not outer


def test_request_session_is_released_when_the_handler_raises(checkouts):
    with pytest.raises(RuntimeError):
        with Session.for_request() as request_session:
            request_session.execute(text('SELECT 1'))
            raise RuntimeError('handler failed')
    assert checkouts['now'] == 0
    with Session() as after:
        assert after is not request_session


@pytest.fixture
def probe_email(database):
    from uber.models import AttendeeAccount
    email = 'commit-on-exit-probe@example.com'

    def cleanup():
        s = Session.session_factory()
        s.query(AttendeeAccount).filter_by(email=email).delete()
        s.commit()
        s.close()

    cleanup()
    yield email
    cleanup()


def _saved(email):
    from uber.models import AttendeeAccount
    s = Session.session_factory()
    try:
        return s.query(AttendeeAccount).filter_by(email=email).count()
    finally:
        s.close()


def test_clean_exit_commits(probe_email):
    from uber.models import AttendeeAccount
    with Session() as session:
        session.add(AttendeeAccount(email=probe_email))
    assert _saved(probe_email) == 1


def test_exit_on_exception_discards(probe_email):
    from uber.models import AttendeeAccount
    with pytest.raises(RuntimeError):
        with Session() as session:
            session.add(AttendeeAccount(email=probe_email))
            session.flush()
            raise RuntimeError('task failed')
    assert _saved(probe_email) == 0


def test_request_session_commits_flushed_work_on_clean_exit(probe_email):
    from uber.models import AttendeeAccount
    with Session.for_request() as session:
        session.add(AttendeeAccount(email=probe_email))
        session.flush()
        session.expunge_all()
    assert _saved(probe_email) == 1


def test_request_session_discards_on_exception(probe_email):
    from uber.models import AttendeeAccount
    with pytest.raises(RuntimeError):
        with Session.for_request() as session:
            session.add(AttendeeAccount(email=probe_email))
            session.flush()
            raise RuntimeError('handler failed')
    assert _saved(probe_email) == 0


def test_helper_exit_does_not_commit_the_request(probe_email):
    from uber.models import AttendeeAccount
    with pytest.raises(RuntimeError):
        with Session.for_request():
            with Session() as helper:
                helper.add(AttendeeAccount(email=probe_email))
                helper.flush()
            assert _saved(probe_email) == 0
            raise RuntimeError('handler failed after the helper returned')
    assert _saved(probe_email) == 0
