"""Attendee-facing lottery handlers that take a second object id must check
the caller owns that object, not just the entry `requires_account` vouched for."""

from urllib.parse import unquote

import pytest

from uber.config import c
from uber.errors import HTTPRedirect
from uber.site_sections.hotel_lottery import _require_room_access, _require_view_as_attendee

from tests.hotel.factories import (N, make_application, make_assignment, make_attendee,
                                   make_attendee_account, make_hotel, make_inventory)

NO_PERMISSION = {'error': 'You do not have permission to edit that entry.'}


def _call(name, session, **kwargs):
    from uber.site_sections.hotel_lottery import Root
    func = getattr(Root, name)
    while hasattr(func, '__wrapped__'):
        func = func.__wrapped__
    try:
        return func(Root(), session, **kwargs)
    except HTTPRedirect as e:
        return unquote(e.urls[0])


@pytest.fixture
def login(post_request, login_as, monkeypatch):
    """post_request with the real ownership gates; returns a log-in-as-entry helper."""
    monkeypatch.setattr(post_request, '_require_room_access', _require_room_access)
    monkeypatch.setattr(post_request, '_require_view_as_attendee', _require_view_as_attendee)

    def log_in(session, attendee):
        login_as(make_attendee_account(session, attendee))
    return log_in


def _entry(session, **overrides):
    return make_application(session, make_attendee(session), can_edit=True, **overrides)


@pytest.mark.parametrize('by', ['id', 'attendee_id'])
def test_validate_lottery_refuses_someone_elses_entry(session, login, by):
    victim = _entry(session)
    login(session, make_attendee(session))
    target = {'id': victim.id} if by == 'id' else {'id': 'None', 'attendee_id': victim.attendee_id}

    result = _call('validate_hotel_lottery', session, form_list='LotteryInfo', current_step=1,
                   earliest_room_checkin_date=N[1].isoformat(), **target)

    assert result == NO_PERMISSION
    assert victim.entry_started is None


def test_validate_lottery_rejects_admin_only_forms(session, login):
    app = _entry(session)
    login(session, app.attendee)

    result = _call('validate_hotel_lottery', session, id=app.id, form_list='LotteryAdminInfo',
                   current_step=1, status=c.WITHDRAWN, is_staff_entry='1')

    assert result != NO_PERMISSION, 'the owner passes the ownership gate'
    assert 'error' in result
    assert (app.status, app.is_staff_entry) == (c.COMPLETE, False)


def test_remove_group_member_refuses_someone_outside_the_group(session, login):
    leader = _entry(session, room_group_name='Ours')
    victim = _entry(session, confirmation_num='VICTIM-1')
    login(session, leader.attendee)

    result = _call('remove_group_member', session, id=leader.id, member_id=victim.id)

    assert 'not a member' in result
    assert (victim.status, victim.confirmation_num) == (c.COMPLETE, 'VICTIM-1')


@pytest.mark.parametrize('confirmation_num', [None, 'WRONG'])
def test_join_group_needs_the_confirmation_number(session, login, monkeypatch, confirmation_num):
    monkeypatch.setattr(c, 'SHOW_HOTEL_LOTTERY_GROUPS', True, raising=False)
    group = _entry(session, room_group_name='Theirs', confirmation_num='GRP-123')
    joiner = _entry(session, status=c.PARTIAL)
    login(session, joiner.attendee)
    extra = {'confirmation_num': confirmation_num} if confirmation_num else {}

    result = _call('join_group', session, id=joiner.id, room_group_id=group.id, **extra)

    assert 'Group ID invalid' in result
    assert joiner.parent_application_id is None


def test_join_group_with_the_confirmation_number(session, login, monkeypatch):
    monkeypatch.setattr(c, 'SHOW_HOTEL_LOTTERY_GROUPS', True, raising=False)
    group = _entry(session, room_group_name='Theirs', confirmation_num='GRP-123')
    joiner = _entry(session, status=c.PARTIAL)
    login(session, joiner.attendee)

    _call('join_group', session, id=joiner.id, room_group_id=group.id, confirmation_num='GRP-123')

    assert joiner.parent_application_id == group.id


def test_join_room_group_refuses_an_entry_that_is_not_a_group(session, no_cherrypy_session):
    from uber.site_sections.hotel_lottery import _join_room_group
    target = _entry(session)
    joiner = _entry(session, status=c.PARTIAL)

    message, _ = _join_room_group(session, joiner, target.id)

    assert 'found' in message
    assert joiner.parent_application_id is None


def test_terms_only_joins_groups_led_from_the_callers_account(session, login, monkeypatch):
    monkeypatch.setattr(c, 'SHOW_HOTEL_LOTTERY_GROUPS', True, raising=False)
    stranger_group = _entry(session, room_group_name='Theirs')
    joiner = _entry(session, status=c.PARTIAL)
    login(session, joiner.attendee)

    result = _call('terms', session, attendee_id=joiner.attendee_id, group_id=stranger_group.id,
                   terms_accepted='1', data_policy_accepted='1')

    assert 'Group lookup failed' in result
    assert joiner.parent_application_id is None


def _room_for(session, application, leader):
    inv = make_inventory(session, make_hotel(session), quantity=2)
    return make_assignment(session, leader, inv, check_in=N[1], check_out=N[3],
                           lottery_application_id=application.id)


def test_former_leader_cannot_edit_a_transferred_room(session, login):
    old = _entry(session)
    ra = _room_for(session, old, make_attendee(session))  # make_room_leader keeps the app link
    login(session, old.attendee)

    result = _call('edit_room', session, id=old.id, assignment_id=ra.id,
                   assigned_check_in_date=N[2].isoformat(), assigned_check_out_date=N[3].isoformat())

    assert 'do not have access' in result
    assert ra.assigned_check_in_date == N[1]


def test_confirm_only_redirects_the_rooms_leader(session, login):
    old = _entry(session)
    ra = _room_for(session, old, make_attendee(session))
    login(session, old.attendee)
    assert 'do not have access' in _call('confirm', session, id=old.id, assignment_id=ra.id)

    ra.attendee_id = old.attendee_id
    session.flush()
    assert 'do not have access' not in _call('confirm', session, id=old.id, assignment_id=ra.id)
