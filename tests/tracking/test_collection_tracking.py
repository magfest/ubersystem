import logging
import uuid

import cherrypy

from uber.config import c
from uber.models import AdminAccount, Attendee, AttendeeAccount, Session, Tracking

MOVE_PAGE = '/reg_admin/orphaned_attendees'


def _rows(session, ids):
    return session.query(Tracking).filter(Tracking.fk_id.in_([ids['old'], ids['new']]),
                                          Tracking.action.in_([c.ITEM_ADDED, c.ITEM_REMOVED])).all()


def _move(session, ids):
    session.add_attendee_to_account(session.get(Attendee, ids['attendee']), session.get(AttendeeAccount, ids['new']))


def _commit_move(ids):
    with Session() as session:
        _move(session, ids)
        session.commit()


def test_move_records_both_accounts(committed_move, monkeypatch):
    monkeypatch.setattr(cherrypy.request, 'app', object())
    monkeypatch.setattr(cherrypy.request, 'path_info', MOVE_PAGE)
    _commit_move(committed_move)

    with Session() as session:
        rows = [row for row in _rows(session, committed_move) if row.page == MOVE_PAGE]
        assert {(row.fk_id, row.action) for row in rows} == {
            (committed_move['old'], c.ITEM_REMOVED), (committed_move['new'], c.ITEM_ADDED)}
        assert all(row.model == 'AttendeeAccount' for row in rows)


def test_move_rows_identify_badge_and_account(committed_move):
    _commit_move(committed_move)

    with Session() as session:
        new_email = session.get(AttendeeAccount, committed_move['new']).email
        added = [row for row in _rows(session, committed_move) if row.action == c.ITEM_ADDED
                 and row.fk_id == committed_move['new']]
        assert len(added) == 1
        assert added[0].links == f"attendee({committed_move['attendee']})"
        assert committed_move['attendee'] in added[0].data
        assert new_email in added[0].which


def test_badge_history_query_finds_moves(committed_move):
    """The badge's history page (registration.history) matches rows by their links column."""
    _commit_move(committed_move)

    with Session() as session:
        rows = session.query(Tracking).filter(Tracking.links.like(f"%attendee({committed_move['attendee']})%"),
                                              Tracking.action.in_([c.ITEM_ADDED, c.ITEM_REMOVED])).all()
        assert {row.fk_id for row in rows} >= {committed_move['old'], committed_move['new']}




def test_move_rows_name_the_account_for_the_badge_history_page(committed_move):
    """model_history_base.html shows model and data, not which, so data must name the account."""
    _commit_move(committed_move)

    with Session() as session:
        new_email = session.get(AttendeeAccount, committed_move['new']).email
        added = [row for row in _rows(session, committed_move) if row.action == c.ITEM_ADDED
                 and row.fk_id == committed_move['new']]
        assert len(added) == 1
        assert new_email in added[0].data


def test_rolled_back_move_writes_nothing(committed_move):
    with Session() as session:
        before = len(_rows(session, committed_move))

    with Session() as session:
        _move(session, committed_move)
        session.flush()
        session.rollback()

    with Session() as session:
        assert len(_rows(session, committed_move)) == before


def test_tracking_failure_does_not_block_move(committed_move, monkeypatch, caplog):
    def broken_repr(self):
        raise RuntimeError('repr failed')

    monkeypatch.setattr(Attendee, '__repr__', broken_repr)
    with caplog.at_level(logging.ERROR):
        _commit_move(committed_move)

    with Session() as session:
        attendee = session.get(Attendee, committed_move['attendee'])
        assert [account.id for account in attendee.managers] == [committed_move['new']]
    assert 'Could not track' in caplog.text


def test_access_group_grant_recorded(committed_admin):
    """access_groups_ids converts to a collection change inside before_flush."""
    with Session() as session:
        admin = session.get(AdminAccount, committed_admin['admin'])
        admin.access_groups_ids = [committed_admin['group']]
        session.add(admin)
        session.commit()

    with Session() as session:
        rows = session.query(Tracking).filter(Tracking.fk_id == committed_admin['admin'],
                                              Tracking.action == c.ITEM_ADDED).all()
        assert [row.links for row in rows] == [f"access_group({committed_admin['group']})"]


def test_unsaved_change_is_logged_not_written(caplog):
    account = AttendeeAccount(email=f'{uuid.uuid4().hex}@example.com')
    with caplog.at_level(logging.WARNING):
        account.attendees.append(Attendee(first_name='Unsaved', last_name='Badge'))

    with Session() as session:
        assert session.query(Tracking).filter(Tracking.fk_id == account.id).count() == 0
    assert 'neither object is attached to a session' in caplog.text
