"""The staff rooming Room Grid: edits are staged in the browser and sent as
one batch, which grid_save either checks (a dry run) or saves."""

import inspect
import json
from datetime import datetime, timedelta

import pytest

from uber.config import c

from tests.hotel.factories import (N, make_assignment, make_attendee, make_hotel, make_inventory,
                                   make_partition, make_partition_block)


@pytest.fixture
def grid(session, monkeypatch, no_cherrypy_session):
    from uber.site_sections import staff_rooming

    monkeypatch.setattr(session, 'commit', session.flush)
    root = staff_rooming.Root()
    return lambda name, **params: inspect.unwrap(getattr(staff_rooming.Root, name))(root, session, **params)


@pytest.fixture
def save(grid):
    return lambda edits, commit='1': grid('grid_save', edits=json.dumps(edits), commit=commit)


@pytest.fixture
def inv(session):
    return make_inventory(session, make_hotel(session))


def _staff(session, **kwargs):
    return make_attendee(session, badge_type=c.STAFF_BADGE, **kwargs)


def _room(session, inv, attendee=None, **kwargs):
    return make_assignment(session, attendee or _staff(session), inv, check_in=N[0], check_out=N[3], **kwargs)


def _errors(result):
    return [issue['text'] for issue in result['issues'] if issue['severity'] == 'error']


def test_grid_lists_every_staff_room_leader_first(session, grid, inv):
    room = _room(session, inv, _staff(session, first='Lena', last='Leader'))
    room.occupants.append(make_attendee(session, first='Aaron', last='Aardvark'))
    guest_room = _room(session, inv, make_attendee(session))
    session.flush()

    rows = {row['id']: row for row in grid('room_grid')['grid']['rows']}
    assert guest_room.id not in rows
    row = rows[room.id]
    assert [o['name'] for o in row['occupants']] == ['Lena Leader', 'Aaron Aardvark']
    assert (row['check_in'], row['check_out']) == (N[0].isoformat(), N[3].isoformat())
    assert row['hotel_id'] == inv.hotel_id and not row['source_locked']
    assert row['inventory_label'] == inv.name
    assert row['room_type'] == f'{inv.hotel.name} - {inv.display_name}'
    assert row['leader_badge'] == room.attendee.badge_type_label == row['occupants'][0]['badge']


def test_dry_run_reports_without_saving(session, save, inv):
    room = _room(session, inv)
    edits = {room.id: {'fields': {'assigned_check_out_date': N[2].isoformat()}}}

    result = save(edits, commit='')
    assert result == {'saved': False, 'issues': []}
    session.refresh(room)
    assert room.assigned_check_out_date == N[3]

    result = save(edits)
    assert result['saved'] and result['rows'][0]['check_out'] == N[2].isoformat()
    assert room.assigned_check_out_date == N[2]


def test_errors_block_the_whole_save(session, save, inv):
    good, bad = _room(session, inv), _room(session, inv)
    result = save({good.id: {'fields': {'assigned_check_out_date': N[2].isoformat()}},
                   bad.id: {'fields': {'assigned_check_out_date': N[0].isoformat()}}})
    assert not result['saved'] and 'after the check-in' in _errors(result)[0]
    session.refresh(good)
    assert good.assigned_check_out_date == N[3]

    assert _errors(save({good.id: {'fields': {'status': str(c.CANCELLED)}}})) == []
    assert good.status != c.CANCELLED


def test_rooms_can_trade_places_in_a_full_partition(session, save, inv):
    partition = make_partition(session)
    make_partition_block(session, partition, inv, 1)
    inside, outside = _room(session, inv, partition_id=partition.id), _room(session, inv)

    alone = save({outside.id: {'fields': {'partition_id': partition.id}}}, commit='')
    assert len(_errors(alone)) == 1 and 'over its' in _errors(alone)[0]

    result = save({outside.id: {'fields': {'partition_id': partition.id}},
                   inside.id: {'fields': {'partition_id': ''}}})
    assert result['saved']
    assert (inside.partition_id, outside.partition_id) == (None, partition.id)


def test_block_outside_the_partition_is_one_error(session, save, inv):
    partition = make_partition(session)
    room = _room(session, inv)
    errors = _errors(save({room.id: {'fields': {'partition_id': partition.id}}}))
    assert len(errors) == 1 and 'not allocated' in errors[0]


def test_roommates_and_leader_in_one_batch(session, save, inv):
    room = _room(session, inv)
    old_leader, staffer, guest = room.attendee_id, _staff(session), make_attendee(session)

    assert 'not staff' in _errors(save({room.id: {'add': [guest.id], 'leader': guest.id}}))[0]
    assert _errors(save({room.id: {'leader': _staff(session).id}}))   # not a roommate

    # The new leader arrives and the old one leaves in the same save.
    result = save({room.id: {'add': [staffer.id, guest.id], 'leader': staffer.id, 'remove': [old_leader]}})
    assert result['saved']
    row = result['rows'][0]
    assert row['leader_id'] == staffer.id
    assert [o['id'] for o in row['occupants']] == [staffer.id, guest.id]

    assert 'cannot be removed' in _errors(save({room.id: {'remove': [staffer.id]}}))[0]


def test_leader_change_warns_about_the_card(session, save, inv):
    room = _room(session, inv)
    staffer = _staff(session)
    room.occupants.append(staffer)
    room.cc_token, room.status = 'tok_123', c.SECURED
    session.flush()

    result = save({room.id: {'leader': staffer.id}})
    assert result['saved'] and 'resets the payment information' in result['issues'][0]['text']
    assert room.cc_token is None and room.status == c.ASSIGNED


def test_billing_and_source_are_editable(session, save, inv):
    room = _room(session, inv)
    other_type = next(key for key, _ in c.HOTEL_PAYMENT_TYPE_OPTS if key != room.payment_type)
    result = save({room.id: {'fields': {'payment_type': other_type,
                                        'assignment_reason': str(c.STAFF_CRASH_SPACE)}}})
    assert result['saved']
    assert room.payment_type == other_type and room.shift_requirements_apply
    assert result['rows'][0]['source'] == 'Staff Crash Space'

    assert _errors(save({room.id: {'fields': {'assignment_reason': str(c.SUITE_CONNECTOR)}}}))
    lottery = _room(session, inv, assignment_reason=c.SUITE_CONNECTOR)
    assert _errors(save({lottery.id: {'fields': {'assignment_reason': str(c.MANUAL)}}}))


def test_grid_ignores_non_staff_rooms(session, grid, save, inv):
    other = _room(session, inv, make_attendee(session))
    assert _errors(save({other.id: {'fields': {'assigned_check_out_date': N[2].isoformat()}}}))
    assert grid('grid_search_roommates', id=other.id, q='anyone') == []
    assert grid('grid_rows', ids=other.id) == []


def test_grid_search_skips_current_roommates(session, grid, inv):
    room = _room(session, inv)
    inside = make_attendee(session, first='Zebulon', last='Inside')
    outside = make_attendee(session, first='Zebulon', last='Outside')
    room.occupants.append(inside)
    session.flush()
    found = [r['id'] for r in grid('grid_search_roommates', id=room.id, q='Zebulon')]
    assert outside.id in found and inside.id not in found


def test_text_columns_and_cancellation(session, save, inv):
    room = _room(session, inv)
    result = save({room.id: {'fields': {'hotel_confirmation_number': 'H123', 'room_number': '412',
                                        'special_requests': 'Low floor', 'admin_notes': 'VIP',
                                        'deposit_cutoff_date': N[0].isoformat()}}})
    row = result['rows'][0]
    assert result['saved'] and row['live']
    assert (row['hotel_confirmation_number'], row['room_number'], row['special_requests'], row['admin_notes'],
            row['deposit_cutoff_date']) == ('H123', '412', 'Low floor', 'VIP', N[0].isoformat())

    result = save({room.id: {'fields': {'cancellation_confirmation_number': 'X9'}}})
    assert result['saved'] and not result['rows'][0]['live']
    assert 'cancels the room' in result['issues'][0]['text']


@pytest.mark.parametrize('field,value', [
    ('inventory_id', ''), ('inventory_id', 'Some Hotel - King'), ('partition_id', 'nonsense'),
    ('assigned_check_in_date', ''), ('assigned_check_out_date', 'next tuesday'),
    ('deposit_cutoff_date', 'soon'), ('payment_type', ''), ('payment_type', 'nonsense'),
    ('assignment_reason', ''), ('assignment_reason', 'nonsense'),
])
def test_unsavable_values_block_the_save(session, save, inv, field, value):
    room = _room(session, inv)
    before = getattr(room, field)
    result = save({room.id: {'fields': {field: value}}})
    assert not result['saved'] and len(_errors(result)) == 1
    session.refresh(room)
    assert getattr(room, field) == before


def test_unpartitioned_pool_is_held_to_its_limit(session, save):
    hotel = make_hotel(session)
    small, other = make_inventory(session, hotel, quantity=1), make_inventory(session, hotel)
    _room(session, small)
    mover = _room(session, other)
    errors = _errors(save({mover.id: {'fields': {'inventory_id': small.id}}}))
    assert len(errors) == 1 and 'unpartitioned pool is over' in errors[0]


def test_roommate_may_be_in_overlapping_rooms(session, save, inv):
    first, second = _room(session, inv), _room(session, inv)
    shared = make_attendee(session, first='Dee', last='Double')
    first.occupants.append(shared)
    session.flush()

    result = save({second.id: {'add': [shared.id]}})
    assert result['saved'] and result['issues'] == []


def test_stay_outside_the_event_window_blocks_the_save(session, save, inv, monkeypatch):
    room = _room(session, inv)
    monkeypatch.setattr(c, 'HOTEL_LOTTERY_CHECKOUT_END', datetime.combine(N[3], datetime.min.time()))
    late = (N[3] + timedelta(days=30)).isoformat()
    result = save({room.id: {'fields': {'assigned_check_out_date': late}}})
    assert not result['saved'] and any('event window closes' in text for text in _errors(result))
    assert room.assigned_check_out_date == N[3]


def test_ineligible_roommate_is_refused(session, save, inv):
    room = _room(session, inv)
    refunded = make_attendee(session, badge_status=c.REFUNDED_STATUS)
    errors = _errors(save({room.id: {'add': [refunded.id]}}))
    assert len(errors) == 1 and 'does not have a badge' in errors[0]
