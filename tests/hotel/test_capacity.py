"""uber.hotel.queries capacity math: per-night quantities, partition
carve-outs, self-exclusion, the batched grid, and the occupancy histogram's
checkout-day-exclusive boundary."""

from uber.config import c
from uber.hotel.queries import (capacity_for, capacity_night_map,
                                occupancy_by_block_night)

from tests.hotel.factories import (N, make_assignment, make_attendee,
                                   make_hotel, make_inventory,
                                   make_partition, make_partition_block,
                                   set_night_quantity)


def test_quantity_for_night_blank_vs_explicit_zero(session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel, quantity=10)
    set_night_quantity(session, inv, N[0], 0)   # explicitly closed night
    set_night_quantity(session, inv, N[1], 3)   # explicit override

    assert inv.quantity_for_night(N[0]) == 0, \
        'an explicit 0 row must close the night'
    assert inv.quantity_for_night(N[1]) == 3
    # A night with no row falls back to the block's flat quantity.
    assert inv.quantity_for_night(N[2]) == 10


def test_capacity_for_partition_carveout_and_main_pool(session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel, quantity=10)
    partition = make_partition(session)
    make_partition_block(session, partition, inv, quantity=4)
    set_night_quantity(session, inv, N[1], 3)

    # Main pool = night quantity minus every partition carve-out.
    cap, assigned, open_slots = capacity_for(session, inv, N[0])
    assert (cap, assigned, open_slots) == (6, 0, 6)

    # Partition scope = min(block allocation, night quantity).
    cap, assigned, open_slots = capacity_for(session, inv, N[0],
                                             partition_id=partition.id)
    assert (cap, assigned, open_slots) == (4, 0, 4)
    cap, _, _ = capacity_for(session, inv, N[1], partition_id=partition.id)
    assert cap == 3, 'partition capacity is bounded by the night quantity'

    # Main pool on the overridden night: 3 - 4 carve-out floors at 0.
    cap, _, _ = capacity_for(session, inv, N[1])
    assert cap == 0

    # A partition with no block on this inventory has zero capacity.
    other = make_partition(session)
    cap, _, _ = capacity_for(session, inv, N[0], partition_id=other.id)
    assert cap == 0


def test_capacity_for_counts_only_matching_scope(session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel, quantity=10)
    partition = make_partition(session)
    make_partition_block(session, partition, inv, quantity=4)

    a1 = make_attendee(session)
    a2 = make_attendee(session)
    a3 = make_attendee(session)
    # Two unpartitioned live rooms covering N0..N2, one partitioned.
    make_assignment(session, a1, inv, check_in=N[0], check_out=N[2])
    make_assignment(session, a2, inv, check_in=N[0], check_out=N[1])
    make_assignment(session, a3, inv, check_in=N[0], check_out=N[2],
                    partition_id=partition.id)
    # A cancelled row never counts.
    make_assignment(session, a1, inv, check_in=N[0], check_out=N[2],
                    status=c.CANCELLED)

    cap, assigned, open_slots = capacity_for(session, inv, N[0])
    assert (cap, assigned, open_slots) == (6, 2, 4)
    cap, assigned, open_slots = capacity_for(session, inv, N[1])
    assert (cap, assigned, open_slots) == (6, 1, 5), \
        'checkout day is exclusive: the N0..N1 stay does not occupy N1'

    cap, assigned, open_slots = capacity_for(session, inv, N[0],
                                             partition_id=partition.id)
    assert (cap, assigned, open_slots) == (4, 1, 3)


def test_capacity_for_self_exclusion(session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel, quantity=5)
    a1 = make_attendee(session)
    ra = make_assignment(session, a1, inv, check_in=N[0], check_out=N[2])

    _, assigned, _ = capacity_for(session, inv, N[0])
    assert assigned == 1
    _, assigned, open_slots = capacity_for(session, inv, N[0],
                                           exclude_assignment_id=ra.id)
    assert assigned == 0, \
        'exclude_assignment_id evaluates capacity as if the row were absent'
    assert open_slots == 5


def test_capacity_night_map_agrees_with_capacity_for(session):
    hotel = make_hotel(session)
    inv_a = make_inventory(session, hotel, quantity=8)
    inv_b = make_inventory(session, hotel, quantity=2)
    partition = make_partition(session)
    make_partition_block(session, partition, inv_a, quantity=3)
    set_night_quantity(session, inv_a, N[1], 2)
    set_night_quantity(session, inv_a, N[2], 0)

    a1 = make_attendee(session)
    a2 = make_attendee(session)
    make_assignment(session, a1, inv_a, check_in=N[0], check_out=N[3])
    make_assignment(session, a2, inv_a, check_in=N[1], check_out=N[2],
                    partition_id=partition.id)
    make_assignment(session, a1, inv_b, check_in=N[0], check_out=N[1])

    inventories = [inv_a, inv_b]
    nights = N[0:4]
    for part_id in (None, partition.id):
        grid = capacity_night_map(session, inventories, nights,
                                  partition_id=part_id)
        assert set(grid) == {(str(inv.id), night)
                             for inv in inventories for night in nights}
        for inv in inventories:
            for night in nights:
                assert grid[(str(inv.id), night)] == capacity_for(
                    session, inv, night, partition_id=part_id), \
                    f'grid disagrees with capacity_for at ({inv.id}, {night}, {part_id})'


def test_occupancy_by_block_night_boundary_and_shapes(session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel, quantity=5)
    partition = make_partition(session)
    make_partition_block(session, partition, inv, quantity=2)

    a1 = make_attendee(session)
    a2 = make_attendee(session)
    ra_plain = make_assignment(session, a1, inv, check_in=N[0], check_out=N[2])
    ra_part = make_assignment(session, a2, inv, check_in=N[1], check_out=N[3],
                              partition_id=partition.id)
    # Rows with no dates are skipped entirely.
    make_assignment(session, a1, inv)

    rows = [ra_plain, ra_part]

    hist = occupancy_by_block_night(rows)
    key = str(inv.id)
    assert hist[key][N[0]] == 1
    assert hist[key][N[1]] == 2
    assert hist[key][N[2]] == 1
    assert N[3] not in hist[key], 'checkout day is exclusive'

    by_part = occupancy_by_block_night(rows, by_partition=True)
    assert set(by_part) == {(key, None), (key, str(partition.id))}
    assert by_part[(key, None)] == {N[0]: 1, N[1]: 1}
    assert by_part[(key, str(partition.id))] == {N[1]: 1, N[2]: 1}

    iso = occupancy_by_block_night(rows, iso_keys=True)
    assert iso[key] == {N[0].isoformat(): 1, N[1].isoformat(): 2,
                        N[2].isoformat(): 1}
