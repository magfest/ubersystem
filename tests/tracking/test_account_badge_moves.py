import uuid
from datetime import datetime, timedelta

import pytz

from uber.config import c
from uber.decorators import render
from uber.models import Attendee, AttendeeAccount, Session, Tracking
from uber.site_sections.reg_admin import account_badge_moves, move_page_label

MOVE_NOTICE = 'may be missing'


def _move(ids):
    with Session() as session:
        session.add_attendee_to_account(session.get(Attendee, ids['attendee']),
                                        session.get(AttendeeAccount, ids['new']))
        session.commit()


def _render(account, moves=()):
    return render('reg_admin/account_badge_moves.html', {'account': account, 'badge_moves': list(moves)},
                  encoding=None)


def test_receiving_account_lists_the_badge_as_added(committed_move):
    _move(committed_move)

    with Session() as session:
        moves = account_badge_moves(session, session.get(AttendeeAccount, committed_move['new']))

        assert [(move.added, move.badge_name) for move in moves] == [(True, 'Moved Badge')]
        assert moves[0].badge.id == committed_move['attendee']


def test_old_account_lists_the_removal_first_and_where_the_badge_is_now(committed_move):
    _move(committed_move)

    with Session() as session:
        moves = account_badge_moves(session, session.get(AttendeeAccount, committed_move['old']))
        new_email = session.get(AttendeeAccount, committed_move['new']).email

        assert [move.added for move in moves] == [False, True]
        assert [account.email for account in moves[0].now_on] == [new_email]


def _log_row(account_id, links, data):
    return Tracking(model='AttendeeAccount', fk_id=account_id, which='', who='Test Admin',
                    page='/reg_admin/orphaned_attendees', links=links, action=c.ITEM_REMOVED, data=data)


def test_a_deleted_badge_is_named_from_the_log_even_with_an_apostrophe(committed_move):
    gone_id = str(uuid.uuid4())
    logged = repr(Attendee(first_name='Pat', last_name="O'Brien"))
    with Session() as session:
        session.add(_log_row(committed_move['new'], f'attendee({gone_id})', f'{logged} id={gone_id}; x'))
        session.commit()

        moves = account_badge_moves(session, session.get(AttendeeAccount, committed_move['new']))

    assert [(move.badge, move.badge_name, move.badge_recorded, move.who) for move in moves] == [
        (None, "Pat O'Brien", True, 'Test Admin')]


def test_an_older_row_without_a_badge_id_keeps_its_name(committed_move):
    """Rows from before the collection tracking fix logged only the badge's repr."""
    with Session() as session:
        session.add(_log_row(committed_move['new'], '', repr(Attendee(first_name='Early', last_name='Move'))))
        session.commit()

        account = session.get(AttendeeAccount, committed_move['new'])
        moves = account_badge_moves(session, account)
        html = _render(account, moves)

    assert [(move.badge, move.badge_name, move.badge_recorded) for move in moves] == [(None, 'Early Move', False)]
    assert 'Early Move' in html
    assert 'older entry' in html
    assert 'badge deleted' not in html


def test_page_labels_name_the_action_and_fall_back_to_the_path():
    assert move_page_label('/reg_admin/orphaned_attendees').startswith('Reassign')
    assert move_page_label('/guest_admin/open_checklist') == 'Open Checklist'
    assert move_page_label('/some_section/new_page') == '/some_section/new_page'
    assert move_page_label('') == 'Background task or script'
    assert move_page_label('/') == 'Background task or script'


def test_section_says_when_no_badges_have_moved(monkeypatch):
    monkeypatch.setattr(c, 'ACCOUNT_MOVES_HISTORY_START', None, raising=False)

    html = _render(AttendeeAccount(email='quiet@example.com'))

    assert 'No badges have been moved on or off this account.' in html


def test_notice_shows_only_for_accounts_older_than_the_setting(monkeypatch):
    start = datetime(2026, 11, 20, tzinfo=pytz.UTC)
    monkeypatch.setattr(c, 'ACCOUNT_MOVES_HISTORY_START', start, raising=False)

    older = AttendeeAccount(email='older@example.com', created=start - timedelta(days=30))
    newer = AttendeeAccount(email='newer@example.com', created=start + timedelta(days=1))

    assert MOVE_NOTICE in _render(older)
    assert MOVE_NOTICE not in _render(newer)


def test_rows_escape_names_and_show_how_the_move_happened(committed_move):
    _move(committed_move)

    with Session() as session:
        account = session.get(AttendeeAccount, committed_move['new'])
        moves = account_badge_moves(session, account)
        moves[0].who = '<b>Admin</b>'
        html = _render(account, moves)

    assert '&lt;b&gt;Admin&lt;/b&gt;' in html
    assert 'Moved Badge' in html
    assert 'Added' in html
