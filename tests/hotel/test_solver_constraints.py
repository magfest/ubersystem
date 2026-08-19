"""uber.hotel.solver.solve_lottery capacity constraints on a tiny mixed
inventory configuration:

  * a block with per-night quantities alongside a flat-quantity-only block
    (the flat block must still be capacity-constrained per night), and
  * a night with an explicit 0 quantity (closed night: zero awards touch it).

solve_lottery only reads plain attributes off the application objects
(id, entry_type, room_opt_out, preferences, dates), so we construct
unsaved LotteryApplication instances - no DB involvement, deterministic
inventory dicts in the shape of HotelRoomInventory.to_inventory_dict.
"""

from collections import defaultdict
from datetime import date, timedelta

import pytest

from uber.config import c
from uber.hotel.solver import solve_lottery

N1 = date(2026, 1, 8)
N2 = N1 + timedelta(days=1)
N3 = N1 + timedelta(days=2)

HOTEL_ID = 'hotel-1'
TYPE_ID = 'type-standard'


def _app(check_in, check_out):
    from uber.models.hotel import LotteryApplication

    app = LotteryApplication(
        entry_type=c.ROOM_ENTRY,
        room_opt_out=False,
        hotel_preference=HOTEL_ID,
        room_type_preference=TYPE_ID,
        earliest_checkin_date=check_in,
        latest_checkout_date=check_out,
    )
    return app


def _block(block_id, quantity, night_quantities=None):
    """Same shape as HotelRoomInventory.to_inventory_dict."""
    return {
        'id': block_id,
        'hotel_id': HOTEL_ID,
        'capacity': 4,
        'min_capacity': 1,
        'room_type': TYPE_ID,
        'quantity': quantity,
        'night_quantities': ({d.isoformat(): q
                              for d, q in night_quantities.items()}
                             if night_quantities else {}),
        'name': block_id,
    }


def _per_block_night_counts(allocations, apps, blocks):
    """Count awards per (block, night) from solver output, using each
    awarded app's stay range."""
    apps_by_id = {a.id: a for a in apps}
    nights = defaultdict(lambda: defaultdict(int))
    for app_id, inv_id, role in allocations:
        app = apps_by_id[app_id]
        day = app.earliest_checkin_date
        while day < app.latest_checkout_date:
            nights[inv_id][day] += 1
            day += timedelta(days=1)
    return nights


def test_flat_quantity_block_is_capped_per_night_in_mixed_config():
    # Block A has per-night data; block B is flat-quantity-only. B must
    # still be capacity-constrained on every night (quantity 1), even
    # though the per-night constraint loop is driven by A's nights.
    blocks = [
        _block('block-A', quantity=5, night_quantities={N1: 1, N2: 1}),
        _block('block-B', quantity=1),
    ]
    apps = [_app(N1, N3) for _ in range(4)]  # stays cover nights N1, N2

    allocations = solve_lottery(list(apps), blocks,
                                lottery_type=c.ROOM_ENTRY)
    assert allocations is not None, 'solver must find a feasible solution'

    counts = _per_block_night_counts(allocations, apps, blocks)
    for night in (N1, N2):
        assert counts['block-B'][night] <= 1, \
            'flat-quantity block over-awarded past its quantity'
        assert counts['block-A'][night] <= 1

    # Per-app cap: nobody gets two primary rooms.
    per_app = defaultdict(int)
    for app_id, _inv, role in allocations:
        assert role == 'primary'
        per_app[app_id] += 1
    assert all(n == 1 for n in per_app.values())

    # With 2 rooms per night total and 4 identical full-stay apps,
    # exactly 2 apps get an award.
    assert len(allocations) == 2


def test_explicit_zero_night_forbids_awards_touching_it():
    # Block A's N2 is explicitly closed; any stay covering N2 must get
    # nothing from it. Block A is the only inventory.
    blocks = [
        _block('block-A', quantity=5, night_quantities={N2: 0}),
    ]
    apps = [_app(N1, N3) for _ in range(3)]  # every stay covers N2

    allocations = solve_lottery(list(apps), blocks,
                                lottery_type=c.ROOM_ENTRY)
    assert allocations is not None
    assert allocations == [], \
        'an explicit-0 night must forbid every award touching it'


def test_explicit_zero_night_still_allows_stays_avoiding_it():
    # Same closed night, but apps checking out on N2 (nights: N1 only,
    # which falls back to the flat quantity 5) can still be awarded.
    blocks = [
        _block('block-A', quantity=5, night_quantities={N2: 0}),
    ]
    apps = [_app(N1, N2) for _ in range(2)]  # single night N1

    allocations = solve_lottery(list(apps), blocks,
                                lottery_type=c.ROOM_ENTRY)
    assert allocations is not None
    assert len(allocations) == 2, \
        'stays avoiding the closed night use the flat-quantity fallback'
    counts = _per_block_night_counts(allocations, apps, blocks)
    assert counts['block-A'][N2] == 0


def test_unlisted_nights_still_capped_by_flat_quantity():
    # Block A: quantity 2, per-night data ONLY for N3. Six one-night
    # stays on N1 (a night listed in no block's night_quantities) should
    # be capped at 2 awards, but currently all six win.
    blocks = [
        _block('block-A', quantity=2, night_quantities={N3: 1}),
    ]
    apps = [_app(N1, N2) for _ in range(6)]

    allocations = solve_lottery(list(apps), blocks,
                                lottery_type=c.ROOM_ENTRY)
    assert allocations is not None
    assert len(allocations) <= 2, \
        'nights absent from every night_quantities map must still be ' \
        'capped by the flat block quantity'
