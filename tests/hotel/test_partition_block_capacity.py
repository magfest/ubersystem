"""edit_partition refuses block allocations that, together with every other
partition's, would exceed the inventory block's busiest night or overbook
rooms already assigned outside any partition, and won't shrink one below
the rooms the partition already has booked."""

from datetime import timedelta

import pytest

from uber.config import c
from uber.errors import HTTPRedirect

from tests.hotel.factories import (make_assignment, make_attendee, make_hotel, make_inventory,
                                   make_partition, make_partition_block, set_night_quantity)


@pytest.fixture
def edit_partition(post_request, monkeypatch):
    import uber.site_sections.hotel_lottery_admin as admin_site

    monkeypatch.setattr(admin_site, 'is_lottery_admin', lambda *a, **k: True)
    func = admin_site.Root.edit_partition
    while hasattr(func, '__wrapped__'):
        func = func.__wrapped__
    return lambda session, partition, inv, qty: func(
        admin_site.Root(), session, id=partition.id, name=partition.name,
        active='1', **{f'block_qty_{inv.id}': str(qty)})


def _block_qty(session, partition, inv):
    session.refresh(partition)
    return {str(pb.inventory_id): pb.quantity for pb in partition.blocks}.get(str(inv.id))


def test_rejects_allocation_over_remaining_capacity(session, edit_partition):
    inv = make_inventory(session, make_hotel(session), quantity=10)
    make_partition_block(session, make_partition(session), inv, 6)
    partition = make_partition(session)

    result = edit_partition(session, partition, inv, 5)

    assert 'only 4 rooms available' in result['message']
    assert _block_qty(session, partition, inv) is None


def test_allows_allocation_that_fits(session, edit_partition):
    inv = make_inventory(session, make_hotel(session), quantity=10)
    make_partition_block(session, make_partition(session), inv, 6)
    partition = make_partition(session)

    with pytest.raises(HTTPRedirect):
        edit_partition(session, partition, inv, 4)

    assert _block_qty(session, partition, inv) == 4


def test_capacity_is_the_busiest_night(session, edit_partition):
    from uber.site_sections.hotel_lottery_admin import _event_nights

    inv = make_inventory(session, make_hotel(session), quantity=5)
    set_night_quantity(session, inv, _event_nights()[0], 8)
    partition = make_partition(session)

    with pytest.raises(HTTPRedirect):
        edit_partition(session, partition, inv, 8)
    assert _block_qty(session, partition, inv) == 8

    assert 'only 8 rooms available' in edit_partition(session, partition, inv, 9)['message']


def test_existing_over_allocation_can_shrink_but_not_grow(session, edit_partition):
    inv = make_inventory(session, make_hotel(session), quantity=10)
    make_partition_block(session, make_partition(session), inv, 6)
    partition = make_partition(session)
    make_partition_block(session, partition, inv, 7)

    assert 'only 4 rooms available' in edit_partition(session, partition, inv, 8)['message']

    with pytest.raises(HTTPRedirect):
        edit_partition(session, partition, inv, 5)
    assert _block_qty(session, partition, inv) == 5


def _book_unpartitioned(session, inv, night, count=1, status=None):
    for _ in range(count):
        make_assignment(session, make_attendee(session), inventory=inv, status=status or c.ASSIGNED,
                        check_in=night, check_out=night + timedelta(days=1))


def test_unpartitioned_bookings_reduce_availability(session, edit_partition):
    from uber.site_sections.hotel_lottery_admin import _event_nights

    inv = make_inventory(session, make_hotel(session), quantity=10)
    make_partition_block(session, make_partition(session), inv, 2)
    _book_unpartitioned(session, inv, _event_nights()[0], count=5)
    partition = make_partition(session)

    message = edit_partition(session, partition, inv, 4)['message']
    assert 'only 3 rooms available' in message
    assert '5 booked outside partitions' in message

    with pytest.raises(HTTPRedirect):
        edit_partition(session, partition, inv, 3)
    assert _block_qty(session, partition, inv) == 3


def test_tightest_night_wins(session, edit_partition):
    from uber.site_sections.hotel_lottery_admin import _event_nights

    first, second = _event_nights()[:2]
    inv = make_inventory(session, make_hotel(session), quantity=10)
    set_night_quantity(session, inv, second, 6)
    _book_unpartitioned(session, inv, first, count=3)
    _book_unpartitioned(session, inv, second, count=2)
    partition = make_partition(session)

    assert 'only 4 rooms available' in edit_partition(session, partition, inv, 5)['message']


def test_dead_and_partitioned_bookings_do_not_count(session, edit_partition):
    from uber.site_sections.hotel_lottery_admin import _event_nights

    night = _event_nights()[0]
    inv = make_inventory(session, make_hotel(session), quantity=10)
    other = make_partition(session)
    make_partition_block(session, other, inv, 4)
    _book_unpartitioned(session, inv, night, count=3, status=c.CANCELLED)
    make_assignment(session, make_attendee(session), inventory=inv, partition_id=other.id,
                    check_in=night, check_out=night + timedelta(days=1))
    partition = make_partition(session)

    with pytest.raises(HTTPRedirect):
        edit_partition(session, partition, inv, 6)
    assert _block_qty(session, partition, inv) == 6


def _book_in_partition(session, inv, partition, night, count):
    for _ in range(count):
        make_assignment(session, make_attendee(session), inventory=inv, partition_id=partition.id,
                        check_in=night, check_out=night + timedelta(days=1))


def test_cannot_shrink_below_rooms_in_use(session, edit_partition):
    from uber.site_sections.hotel_lottery_admin import _event_nights

    inv = make_inventory(session, make_hotel(session), quantity=10)
    partition = make_partition(session)
    make_partition_block(session, partition, inv, 5)
    _book_in_partition(session, inv, partition, _event_nights()[0], 3)

    assert "can't go below 3" in edit_partition(session, partition, inv, 2)['message']
    assert "can't go below 3" in edit_partition(session, partition, inv, 0)['message']

    with pytest.raises(HTTPRedirect):
        edit_partition(session, partition, inv, 3)
    assert _block_qty(session, partition, inv) == 3


def test_allocation_already_below_usage_can_stay(session, edit_partition):
    from uber.site_sections.hotel_lottery_admin import _event_nights

    inv = make_inventory(session, make_hotel(session), quantity=10)
    partition = make_partition(session)
    make_partition_block(session, partition, inv, 2)
    _book_in_partition(session, inv, partition, _event_nights()[0], 3)

    assert "can't go below 2" in edit_partition(session, partition, inv, 1)['message']
    with pytest.raises(HTTPRedirect):
        edit_partition(session, partition, inv, 2)
    assert _block_qty(session, partition, inv) == 2
