"""Every room issue must lead somewhere an admin can actually act."""

import inspect
import re
from datetime import date
from types import SimpleNamespace

import pytest

import uber.hotel.audit as audit
from uber.config import c
from uber.hotel.audit import (annotate_issues, collect_issues, _fix_url_for,
                              _inv_issue, _room_issue)

from tests.hotel.factories import (make_assignment, make_attendee, make_hotel,
                                   make_inventory, make_partition,
                                   make_partition_block, make_room_type)


def _annotated(session):
    room_issues, inv_issues = collect_issues(session)
    annotate_issues(room_issues, {})
    annotate_issues(inv_issues, {})
    return room_issues, inv_issues


def _by_kind(issues, kind):
    return [i for i in issues if i['kind'] == kind]


def _assert_well_formed(issue):
    assert issue['fixes'], f"{issue['kind']} has no fix target"
    for fix in issue['fixes']:
        assert fix['label'], f"{issue['kind']} has an unlabelled fix"
        url = fix['url']
        assert url, f"{issue['kind']} has an empty url"
        assert re.match(r'^[a-z_]+(\?\S+)?$', url), \
            f"{issue['kind']} has a malformed url: {url}"
    assert issue['fix_url'] == issue['fixes'][0]['url']


def test_manual_room_still_gets_a_link(session, no_cherrypy_session):
    """The original complaint: an under-capacity manual room had no
    application, so it got no fix link at all."""
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel, capacity=4, min_capacity=3)
    attendee = make_attendee(session)
    ra = make_assignment(session, attendee=attendee, inventory=inv,
                         check_in=date(2027, 1, 7), check_out=date(2027, 1, 10))
    assert ra.lottery_application_id is None
    session.flush()

    room_issues, _ = _annotated(session)
    under = _by_kind(room_issues, 'under_capacity')
    assert under, 'expected an under_capacity issue'
    issue = under[0]

    assert issue['fixes'], 'every issue needs at least one fix target'
    assert issue['fix_url']
    # The block is where min_capacity lives, so it leads.
    assert issue['fixes'][0]['label'] == 'Edit inventory block'
    assert str(inv.id) in issue['fixes'][0]['url']
    # The room itself is still reachable.
    assert any('edit_room_assignment' in f['url'] for f in issue['fixes'])


def test_fix_url_falls_back_to_the_assignment_editor(session, no_cherrypy_session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel)
    attendee = make_attendee(session)
    ra = make_assignment(session, attendee=attendee, inventory=inv)
    session.flush()

    assert _fix_url_for(ra) == f'edit_room_assignment?id={ra.id}'


def test_every_issue_has_a_usable_fix(session, no_cherrypy_session):
    """Build a deliberately broken set of rooms and assert nothing comes back
    unactionable."""
    hotel = make_hotel(session)
    room_type = make_room_type(session)
    inv = make_inventory(session, hotel, room_type=room_type,
                         quantity=1, capacity=2, min_capacity=2)
    partition = make_partition(session)
    make_partition_block(session, partition, inv, quantity=5)  # over-allocated

    for _ in range(3):  # oversubscribe the single-room block
        make_assignment(session, attendee=make_attendee(session), inventory=inv,
                        check_in=date(2027, 1, 7), check_out=date(2027, 1, 10))

    # A room with no dates at all.
    make_assignment(session, attendee=make_attendee(session), inventory=inv,
                    check_in=None, check_out=None)
    session.flush()

    room_issues, inv_issues = _annotated(session)
    assert room_issues or inv_issues, 'expected this setup to produce issues'

    for issue in room_issues + inv_issues:
        _assert_well_formed(issue)


def test_partition_overallocated_breakdown(session, no_cherrypy_session):
    """The over-allocation issue names each contributing partition, and the
    partition editor leads the fixes."""
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel, quantity=5)
    big = make_partition(session, name='Big Partition')
    small = make_partition(session, name='Small Partition')
    make_partition_block(session, big, inv, quantity=4)
    make_partition_block(session, small, inv, quantity=3)
    session.flush()

    _, inv_issues = _annotated(session)
    over = _by_kind(inv_issues, 'partition_overallocated')
    assert over, 'expected a partition_overallocated issue'
    issue = over[0]

    extra = issue['extra']
    assert extra['partition_total'] == 7
    assert extra['inventory_quantity'] == 5
    # Largest allocator first, each with name, id, and allocation.
    assert [(p['name'], p['id'], p['quantity']) for p in extra['partitions']] \
        == [('Big Partition', str(big.id), 4), ('Small Partition', str(small.id), 3)]

    assert issue['fixes'][0] == {'label': 'Edit partition',
                                 'url': f'edit_partition?id={big.id}'}
    assert issue['fix_url'] == f'edit_partition?id={big.id}'
    # The block itself stays reachable as a secondary target.
    assert any(f['url'] == f'edit_inventory_item?id={inv.id}'
               for f in issue['fixes'][1:])


def test_double_booking_links_both_rooms(session, no_cherrypy_session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel, quantity=10, capacity=4, min_capacity=1)
    attendee = make_attendee(session)
    first = make_assignment(session, attendee=attendee, inventory=inv,
                            check_in=date(2027, 1, 7), check_out=date(2027, 1, 10))
    second = make_assignment(session, attendee=attendee, inventory=inv,
                             check_in=date(2027, 1, 8), check_out=date(2027, 1, 11))
    # The check keys on the occupants M2M, not the booker, since one person
    # may book several rooms but cannot sleep in two on the same night.
    first.occupants.append(attendee)
    second.occupants.append(attendee)
    session.flush()

    room_issues, _ = _annotated(session)
    doubles = _by_kind(room_issues, 'double_booked')
    assert doubles, 'expected a double_booked issue'

    urls = ' '.join(f['url'] for f in doubles[0]['fixes'])
    assert str(first.id) in urls
    assert str(second.id) in urls, 'the conflicting room must be reachable too'


# ---------------------------------------------------------------------------
# Systematic coverage: every kind the audit can emit must yield a
# non-empty, well-formed fixes list with the expected primary.

def _emitted_kinds():
    """The kind strings actually passed to _room_issue/_inv_issue."""
    src = inspect.getsource(audit)
    return set(re.findall(
        r"_(?:room|inv)_issue\(\s*'(?:error|warning)',\s*'([a-z_]+)'", src))


def _ra(**overrides):
    base = dict(id='ra-1', lottery_application_id=None, inventory_id=None,
                partition_id=None, physical_room_id=None)
    base.update(overrides)
    return SimpleNamespace(**base)


_INV = SimpleNamespace(id='inv-1', hotel_id='hotel-1')
_PARTITION = SimpleNamespace(id='part-1')
_ROOM_TYPE = SimpleNamespace(id='rt-1')
_PHYSICAL = SimpleNamespace(id='phys-1')
_APP = SimpleNamespace(id='app-1')
_OTHER_RA = SimpleNamespace(id='ra-2')

_FULL_RA = _ra(lottery_application_id='app-1', inventory_id='inv-1',
               partition_id='part-1', physical_room_id='phys-1')

# One representative synthetic issue per kind, shaped like the dicts the
# checks emit. Kinds with structurally different variants list several.
_SYNTHETIC_ISSUES = {
    'orphan_connector': [_room_issue('error', 'orphan_connector', 'x', _FULL_RA)],
    'missing_dates': [_room_issue('error', 'missing_dates', 'x', _FULL_RA)],
    'inverted_dates': [_room_issue('error', 'inverted_dates', 'x', _FULL_RA)],
    'too_short': [_room_issue('error', 'too_short', 'x', _FULL_RA)],
    'out_of_range': [_room_issue('warning', 'out_of_range', 'x', _FULL_RA)],
    'empty_room': [_room_issue('error', 'empty_room', 'x', _FULL_RA)],
    'over_capacity': [_room_issue('error', 'over_capacity', 'x', _FULL_RA)],
    'under_capacity': [
        _room_issue('warning', 'under_capacity', 'x', _FULL_RA),
        # No application at all: the manual-room case.
        _room_issue('warning', 'under_capacity', 'x', _ra(inventory_id='inv-1')),
    ],
    'secured_without_payment': [
        _room_issue('error', 'secured_without_payment', 'x', _FULL_RA)],
    'childless_parent': [_room_issue('error', 'childless_parent', 'x', _FULL_RA)],
    'status_mismatch': [
        _room_issue('warning', 'status_mismatch', 'x', None,
                    fix_url='form?id=app-1', extra={'application': _APP})],
    'double_booked': [
        _room_issue('warning', 'double_booked', 'x', _FULL_RA,
                    extra={'other_assignment': _OTHER_RA})],
    'physical_double_booked': [
        _room_issue('error', 'physical_double_booked', 'x', _FULL_RA,
                    extra={'other_assignment': _OTHER_RA,
                           'physical_room': _PHYSICAL})],
    'physical_block_mismatch': [
        _room_issue('warning', 'physical_block_mismatch', 'x', _FULL_RA)],
    'zero_quantity': [_inv_issue('warning', 'zero_quantity', 'x', inventory=_INV)],
    'inactive_parent': [
        _inv_issue('warning', 'inactive_parent', 'x', inventory=_INV,
                   extra={'parent_kind': 'hotel', 'parent_id': 'hotel-1'}),
        _inv_issue('warning', 'inactive_parent', 'x', inventory=_INV,
                   extra={'parent_kind': 'room_type', 'parent_id': 'rt-1'}),
    ],
    'type_mismatch': [_inv_issue('warning', 'type_mismatch', 'x', inventory=_INV)],
    'partition_overallocated': [
        _inv_issue('error', 'partition_overallocated', 'x', inventory=_INV,
                   extra={'partition_total': 7, 'inventory_quantity': 5,
                          'partitions': [
                              {'id': 'part-1', 'name': 'A', 'quantity': 4},
                              {'id': 'part-2', 'name': 'B', 'quantity': 3}]})],
    'oversubscribed_inventory': [
        _inv_issue('error', 'oversubscribed_inventory', 'x', inventory=_INV,
                   extra={'bad_nights': [(date(2027, 1, 7), 3, 1)]})],
    'partition_unconfigured': [
        _inv_issue('error', 'partition_unconfigured', 'x', inventory=_INV,
                   partition=_PARTITION),
        # Partition row itself is gone: falls back to the block.
        _inv_issue('error', 'partition_unconfigured', 'x', inventory=_INV),
    ],
    'oversubscribed_partition': [
        _inv_issue('error', 'oversubscribed_partition', 'x', inventory=_INV,
                   partition=_PARTITION,
                   extra={'bad_nights': [(date(2027, 1, 7), 3, 1)]})],
    'broken_connector_config': [
        _inv_issue('error', 'broken_connector_config', 'x', room_type=_ROOM_TYPE)],
    'insufficient_connectors': [
        _inv_issue('error', 'insufficient_connectors', 'x', room_type=_ROOM_TYPE)],
    'insufficient_connectors_at_hotel': [
        _inv_issue('error', 'insufficient_connectors_at_hotel', 'x',
                   room_type=_ROOM_TYPE)],
    'catalog_count_mismatch': [
        _inv_issue('warning', 'catalog_count_mismatch', 'x', inventory=_INV)],
    'physical_room_wrong_hotel': [
        _inv_issue('error', 'physical_room_wrong_hotel', 'x', inventory=_INV,
                   extra={'physical_room': _PHYSICAL})],
}

# fixes[0], per kind, where the primary is more specific than the default.
_EXPECTED_PRIMARY = {
    'over_capacity': 'edit_inventory_item?id=inv-1',
    'under_capacity': 'edit_inventory_item?id=inv-1',
    'childless_parent': 'form?id=app-1',
    'physical_block_mismatch': 'edit_physical_room?id=phys-1',
    'oversubscribed_partition': 'edit_partition?id=part-1',
    'partition_unconfigured': 'edit_partition?id=part-1',
    'partition_overallocated': 'edit_partition?id=part-1',
    'physical_room_wrong_hotel': 'edit_physical_room?id=phys-1',
}


def test_synthetic_issues_cover_every_emitted_kind():
    assert set(_SYNTHETIC_ISSUES) == _emitted_kinds(), \
        'update _SYNTHETIC_ISSUES to match the kinds audit.py emits'


@pytest.mark.parametrize('kind', sorted(_SYNTHETIC_ISSUES))
def test_every_kind_yields_well_formed_fixes(kind):
    for issue in _SYNTHETIC_ISSUES[kind]:
        issue = dict(issue)
        annotate_issues([issue], {})
        _assert_well_formed(issue)


def test_expected_primaries_hold():
    for kind, expected in _EXPECTED_PRIMARY.items():
        issue = dict(_SYNTHETIC_ISSUES[kind][0])
        annotate_issues([issue], {})
        assert issue['fixes'][0]['url'] == expected, \
            f"{kind} should lead with {expected}, got {issue['fixes'][0]['url']}"
        assert issue['fix_url'] == expected


def test_catalog_count_mismatch_links_the_hotel_filtered_catalog():
    issue = dict(_SYNTHETIC_ISSUES['catalog_count_mismatch'][0])
    annotate_issues([issue], {})
    assert any(f['url'] == 'physical_rooms?hotel_id=hotel-1'
               for f in issue['fixes'])


def test_physical_room_wrong_hotel_keeps_the_precise_room_link():
    issue = dict(_SYNTHETIC_ISSUES['physical_room_wrong_hotel'][0])
    annotate_issues([issue], {})
    assert issue['fixes'][0] == {'label': 'Edit physical room',
                                 'url': 'edit_physical_room?id=phys-1'}
    assert any(f['url'] == 'physical_rooms?hotel_id=hotel-1'
               for f in issue['fixes'][1:])
