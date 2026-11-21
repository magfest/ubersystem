import cherrypy
import pytest

from uber.config import c
from uber.models import Attendee, Session, Tracking


@pytest.fixture
def sessions_started(monkeypatch):
    """Create the cherrypy.session proxy without a request on this thread.

    CherryPy creates the proxy on the first request any thread serves, so startup hooks that run while the
    server is already accepting requests see it with nothing behind it.
    """
    monkeypatch.setattr(cherrypy, 'session', cherrypy._ThreadLocalProxy('session'), raising=False)
    monkeypatch.setattr(c, 'ATTENDEE_ACCOUNTS_ENABLED', True)


def test_no_account_outside_request(sessions_started):
    with Session() as session:
        assert session.current_attendee_account() is None
        assert session.current_admin_account() is None


def test_tracks_update_outside_request(committed_move, sessions_started):
    with Session() as session:
        session.get(Attendee, committed_move['attendee']).first_name = 'Renamed'
        session.commit()

    with Session() as session:
        rows = session.query(Tracking).filter(Tracking.fk_id == committed_move['attendee'],
                                              Tracking.action == c.UPDATED).all()
        assert [row.who for row in rows] == ['non-admin']


def test_reads_account_from_request_session(committed_move, monkeypatch):
    monkeypatch.setattr(cherrypy, 'session', {'attendee_account_id': committed_move['old']}, raising=False)
    monkeypatch.setattr(c, 'ATTENDEE_ACCOUNTS_ENABLED', True)

    with Session() as session:
        assert session.current_attendee_account().id == committed_move['old']
