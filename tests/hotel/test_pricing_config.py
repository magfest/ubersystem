"""Cross-check of the client-side totalling rule against stay_total.

The _js_* helpers below mirror the resolution chain in
uber/static/js/hotel-lottery-pricing.js (nights, rateSet, cellPrice,
blockTotal), operating on the same JSON entry_pricing_config ships to the
entry form, so a change to either side that lets the two totals disagree
fails here.
"""

from datetime import date, timedelta
from decimal import Decimal

from uber.hotel import pricing
from uber.hotel.pricing import entry_pricing_config, stay_total
from uber.models.hotel import InventoryPrice

from tests.hotel.factories import make_hotel, make_inventory


N1 = date(2027, 1, 7)
N2 = date(2027, 1, 8)
N3 = date(2027, 1, 9)
N4 = date(2027, 1, 10)


def _price(session, inventory, amount, night=None, occupancy=None, is_staff=False):
    row = InventoryPrice(inventory_id=inventory.id, night_date=night,
                         occupancy=occupancy, is_staff=is_staff,
                         price=Decimal(amount))
    session.add(row)
    session.flush()
    return row


def _inventory(session, **overrides):
    inv = make_inventory(session, make_hotel(session), capacity=4, min_capacity=1)
    for key, value in overrides.items():
        setattr(inv, key, value)
    session.flush()
    return inv


def _config_block(session, inv, show_staff_rates=True):
    config = entry_pricing_config(session, show_staff_rates=show_staff_rates)
    for hotel in config['hotels']:
        for block in hotel['blocks']:
            if block['id'] == inv.id:
                return block
    raise AssertionError('block missing from entry_pricing_config output')


def _js_nights(check_in, check_out):
    """Mirrors nights(): the occupied nights as ISO strings, empty for an
    inverted or zero-night range."""
    if not check_in or not check_out or check_out <= check_in:
        return []
    out, night = [], check_in
    while night < check_out:
        out.append(night.isoformat())
        night += timedelta(days=1)
    return out


def _js_cell_price(rates, night_iso, occupancy):
    """Mirrors cellPrice(): the most specific cell, then the generic column
    of the night row, then the base rate; None when nothing covers it."""
    night_key = night_iso if rates['per_night'] else ''
    occ_key = str(occupancy) if rates['per_occupancy'] else ''
    by_night = rates['cells'].get(night_key)
    if by_night is None:
        by_night = rates['cells'].get('')
    if by_night is None:
        by_night = {}
    value = by_night.get(occ_key)
    if value is None:
        value = by_night.get('')
    if value is None:
        value = rates['base']
    if value is None:
        return None
    return float(value)


def _js_block_total(block, check_in, check_out, occupancy, staff=False):
    """Mirrors rateSet() plus blockTotal(): staff rates when shipped and
    wanted, summed per night, None as soon as any night is unpriced."""
    rates = block['rates'].get('staff') if staff else None
    if not rates:
        rates = block['rates']['public']
    nights = _js_nights(check_in, check_out)
    if not nights:
        return None
    total = 0.0
    for night_iso in nights:
        rate = _js_cell_price(rates, night_iso, occupancy)
        if rate is None:
            return None
        total += rate
    return total


def _assert_totals_match(session, inv, check_in, check_out, occupancy):
    block = _config_block(session, inv)
    for staff in (False, True):
        expected = stay_total(inv, check_in, check_out,
                              occupancy=occupancy, is_staff=staff)
        actual = _js_block_total(block, check_in, check_out, occupancy, staff=staff)
        if expected is None:
            assert actual is None
        else:
            assert pricing.quantize(Decimal(str(actual))) == expected


def test_flat_rate(session):
    inv = _inventory(session, base_price=Decimal('199.00'),
                     base_staff_price=Decimal('149.50'))
    _assert_totals_match(session, inv, N1, N3, 2)


def test_per_night(session):
    inv = _inventory(session, base_price=Decimal('200.00'),
                     base_staff_price=Decimal('150.00'), price_per_night=True)
    _price(session, inv, '250.25', night=N2)
    _price(session, inv, '175.50', night=N2, is_staff=True)
    # N1 and N3 have no night row, so both sides fall back to the base rate.
    _assert_totals_match(session, inv, N1, N4, 2)


def test_per_occupancy(session):
    inv = _inventory(session, base_price=Decimal('200.00'),
                     base_staff_price=Decimal('150.00'), price_per_occupancy=True)
    _price(session, inv, '230.00', occupancy=3)
    _price(session, inv, '180.00', occupancy=3, is_staff=True)
    _assert_totals_match(session, inv, N1, N3, 3)
    # An occupancy with no row falls back to the base rate on both sides.
    _assert_totals_match(session, inv, N1, N3, 2)


def test_both_dimensions(session):
    inv = _inventory(session, base_price=Decimal('210.00'),
                     base_staff_price=Decimal('160.00'),
                     price_per_night=True, price_per_occupancy=True)
    for night in (N1, N2):
        for occ in (1, 2):
            _price(session, inv, f'{200 + occ * 25}.00', night=night, occupancy=occ)
            _price(session, inv, f'{150 + occ * 25}.00', night=night,
                   occupancy=occ, is_staff=True)
    _assert_totals_match(session, inv, N1, N3, 2)
    # An occupancy with no cells falls back to the base rate on both sides.
    _assert_totals_match(session, inv, N1, N3, 3)


def test_unconfigured_staff_scope_is_unpriced(session):
    """No staff rate at all must read as unpriced on both sides, never as
    the public rate."""
    inv = _inventory(session, base_price=Decimal('199.00'))
    _assert_totals_match(session, inv, N1, N3, 2)


def test_partial_block_hides_the_total_everywhere(session):
    """A night with no rate makes both sides refuse to total, rather than
    either one presenting a partial sum."""
    inv = _inventory(session, price_per_night=True)
    _price(session, inv, '249.00', night=N1)
    block = _config_block(session, inv)
    assert stay_total(inv, N1, N3) is None
    assert _js_block_total(block, N1, N3, 1) is None


def test_staff_rates_not_shipped_for_ineligible_entrants(session):
    """With show_staff_rates off the config has no staff scope, and the
    client's rateSet falls back to the public rates."""
    inv = _inventory(session, base_price=Decimal('199.00'),
                     base_staff_price=Decimal('149.00'))
    block = _config_block(session, inv, show_staff_rates=False)
    assert 'staff' not in block['rates']
    actual = _js_block_total(block, N1, N3, 2, staff=True)
    assert pricing.quantize(Decimal(str(actual))) == stay_total(inv, N1, N3, occupancy=2)
