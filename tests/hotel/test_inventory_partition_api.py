"""The read-only hotel.inventory and hotel.partitions API methods, which a
client (tuber's room export) uses to pick the inventory_id and partition_id
it passes to hotel.update_assignment."""
import inspect

from tests.hotel.factories import (make_hotel, make_inventory, make_partition,
                                   make_partition_block, make_room_type)


class _SessionCM:
    """Stand-in for uber.api.Session() that yields the test session and
    never commits, so the per-test rollback still isolates everything."""
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, *args):
        return False


def _call(session, monkeypatch, method):
    import uber.api

    monkeypatch.setattr(uber.api, 'Session', lambda: _SessionCM(session))
    fn = inspect.unwrap(getattr(uber.api.HotelLookup, method))
    return fn(uber.api.HotelLookup())


def test_inventory_lists_every_block_with_its_hotel(session, monkeypatch):
    hotel = make_hotel(session)
    room_type = make_room_type(session)
    named = make_inventory(session, hotel, room_type, capacity=4, quantity=7)
    # A block with no name of its own is listed under its room type's.
    unnamed = make_inventory(session, hotel, room_type, name='')
    inactive = make_inventory(session, hotel, active=False)

    result = _call(session, monkeypatch, 'inventory')
    by_id = {entry['id']: entry for entry in result}

    assert by_id[named.id] == {
        'id': named.id,
        'name': named.name,
        'hotel_id': hotel.id,
        'hotel_name': hotel.name,
        'room_type_name': room_type.name,
        'capacity': 4,
        'quantity': 7,
        'is_suite': False,
        'active': True,
    }
    assert by_id[unnamed.id]['name'] == room_type.name
    assert by_id[inactive.id]['active'] is False, \
        'inactive blocks are listed, so a room already assigned to one still resolves'
    assert result == sorted(result, key=lambda entry: (entry['hotel_name'], entry['name']))


def test_partitions_list_the_blocks_they_draw_from(session, monkeypatch):
    hotel = make_hotel(session)
    king = make_inventory(session, hotel)
    double = make_inventory(session, hotel)
    partition = make_partition(session, description='Staff rooms', bill_reference='SECRET-1')
    make_partition_block(session, partition, king, 5)
    make_partition_block(session, partition, double, 2)
    empty = make_partition(session, active=False)

    result = _call(session, monkeypatch, 'partitions')
    by_id = {entry['id']: entry for entry in result}

    entry = by_id[partition.id]
    assert sorted(entry.pop('blocks'), key=lambda block: block['quantity']) == [
        {'inventory_id': double.id, 'quantity': 2},
        {'inventory_id': king.id, 'quantity': 5},
    ]
    assert entry == {
        'id': partition.id,
        'name': partition.name,
        'description': 'Staff rooms',
        'active': True,
    }, 'the bill reference stays out of the API'
    assert by_id[empty.id]['blocks'] == []
    assert by_id[empty.id]['active'] is False


def test_both_methods_are_read_only_api_calls():
    import uber.api

    for method in ('inventory', 'partitions'):
        fn = inspect.unwrap(getattr(uber.api.HotelLookup, method))
        assert fn.required_access == {'api_read'}
