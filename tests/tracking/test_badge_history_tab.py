import inspect
from datetime import datetime, timedelta

import pytest
import pytz

from uber.config import c
from uber.decorators import render
from uber.models import Attendee, AttendeeAccount, Group, Session, _attendee_validity_check
from uber.site_sections.registration import Root

attendee_history = inspect.unwrap(Root.attendee_history)
full_history = inspect.unwrap(Root.history)

MOVE_NOTICE = 'Moves between attendee accounts are listed from'
POPUP_SCOPE = 'Account moves and changes to related records'


@pytest.fixture(scope='module', autouse=True)
def badge_lookup():
    """Install session.attendee's allow_invalid wrapper, which the server adds at startup."""
    original = Session.SessionMixin.attendee
    _attendee_validity_check()
    yield
    Session.SessionMixin.attendee = original


def _render_full_history(attendee, changes=(), pageviews=()):
    return render('registration/history.html',
                  {'attendee': attendee, 'changes': list(changes), 'pageviews': list(pageviews)}, encoding=None)


def _move(ids):
    with Session() as session:
        session.add_attendee_to_account(session.get(Attendee, ids['attendee']),
                                        session.get(AttendeeAccount, ids['new']))
        session.commit()


def test_popup_lists_the_badges_own_changes_only(committed_move):
    """The pop-up skips the links search, which scans the whole tracking table."""
    _move(committed_move)

    with Session() as session:
        changes = attendee_history(Root(), session, id=committed_move['attendee'])['changes']
        assert changes
        assert all(row.model == 'Attendee' and row.fk_id == committed_move['attendee'] for row in changes)


def test_full_history_page_lists_the_move(committed_move):
    _move(committed_move)

    with Session() as session:
        changes = full_history(Root(), session, id=committed_move['attendee'])['changes']
        assert any(row.action == c.ITEM_ADDED and row.fk_id == committed_move['new'] for row in changes)


def test_popup_points_to_the_full_history_page_instead_of_the_move_notice(committed_move, monkeypatch):
    monkeypatch.setattr(c, 'ACCOUNT_MOVES_HISTORY_START', datetime(2099, 1, 1, tzinfo=pytz.UTC), raising=False)

    with Session() as session:
        html = render('registration/attendee_history.html',
                      attendee_history(Root(), session, id=committed_move['attendee']), encoding=None)

    assert POPUP_SCOPE in html
    assert f"../registration/history?id={committed_move['attendee']}" in html
    assert MOVE_NOTICE not in html


def test_history_says_when_nothing_is_recorded():
    html = _render_full_history(Attendee(first_name='Quiet', last_name='Badge'))

    assert 'No changes have been recorded for this badge.' in html
    assert 'No page views have been recorded for this badge.' in html


def test_move_notice_shows_only_for_badges_older_than_the_setting(monkeypatch):
    start = datetime(2026, 11, 20, tzinfo=pytz.UTC)
    monkeypatch.setattr(c, 'ACCOUNT_MOVES_HISTORY_START', start, raising=False)

    older = Attendee(first_name='Older', last_name='Badge', created=start - timedelta(days=30))
    newer = Attendee(first_name='Newer', last_name='Badge', created=start + timedelta(days=1))

    assert MOVE_NOTICE in _render_full_history(older)
    assert MOVE_NOTICE not in _render_full_history(newer)


def test_move_notice_is_off_when_the_setting_is_empty(monkeypatch):
    monkeypatch.setattr(c, 'ACCOUNT_MOVES_HISTORY_START', None, raising=False)

    older = Attendee(first_name='Older', last_name='Badge', created=datetime(2020, 1, 1, tzinfo=pytz.UTC))

    assert MOVE_NOTICE not in _render_full_history(older)


def test_group_history_says_group_and_never_shows_the_move_notice(monkeypatch):
    monkeypatch.setattr(c, 'ACCOUNT_MOVES_HISTORY_START', datetime(2026, 11, 20, tzinfo=pytz.UTC), raising=False)
    group = Group(name='Quiet Group', created=datetime(2020, 1, 1, tzinfo=pytz.UTC))

    html = render('group_admin/history.html', {'group': group, 'changes': [], 'pageviews': []}, encoding=None)

    assert 'No changes have been recorded for this group.' in html
    assert 'No page views have been recorded for this group.' in html
    assert MOVE_NOTICE not in html
