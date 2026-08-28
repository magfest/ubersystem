"""Room pricing: nightly rates, stay totals, and the price tables the admin
grid and the attendee entry form render.

A block's rate can vary by night, by occupancy, both, or neither. The two
flags on HotelRoomInventory say which dimensions apply; InventoryPrice rows
carry the varying values, with NULL meaning "any". A block that varies in
neither dimension needs no rows at all and just uses its base price.

Everything here treats "one nightly rate" as the unit, so a stay total is
always the sum of each night's resolved rate. A block with price_per_night
off charges its one rate on every night; it is not a flat price for the stay.

Staff rates never fall back to standard rates, so callers can tell "the staff
rate happens to match" apart from "no staff rate is configured".
"""

from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta


CENTS = Decimal('0.01')


def quantize(amount):
    """Round to cents, half up. Decimal's default is banker's rounding, which
    is not what anyone quoting a room rate expects."""
    if amount is None:
        return None
    return Decimal(amount).quantize(CENTS, rounding=ROUND_HALF_UP)


def format_price(amount):
    """'$199' when the cents are zero, '$199.50' otherwise."""
    if amount is None:
        return ''
    amount = quantize(amount)
    if amount == amount.to_integral_value():
        return f"${amount.to_integral_value()}"
    return f"${amount}"


def format_price_range(amounts):
    """'$199', or '$199 - $249' across a spread."""
    amounts = [quantize(a) for a in amounts if a is not None]
    if not amounts:
        return ''
    low, high = min(amounts), max(amounts)
    if low == high:
        return format_price(low)
    return f"{format_price(low)} - {format_price(high)}"


def nights_between(check_in, check_out):
    """The nights a stay occupies: check-in through the night before checkout."""
    if not check_in or not check_out or check_out <= check_in:
        return []
    nights, night = [], check_in
    while night < check_out:
        nights.append(night)
        night += timedelta(days=1)
    return nights


def _base(inv, is_staff):
    return inv.base_staff_price if is_staff else inv.base_price


def price_for(inv, night=None, occupancy=None, is_staff=False):
    """The nightly rate for one scope, most specific match first. Returns None
    when nothing covers it, which callers must treat as unpriced rather than
    free."""
    by_night = inv.price_per_night and night is not None
    by_occupancy = inv.price_per_occupancy and occupancy is not None

    scopes = []
    if by_night and by_occupancy:
        scopes.append((night, occupancy))
    if by_night:
        scopes.append((night, None))
    if by_occupancy:
        scopes.append((None, occupancy))

    for want_night, want_occupancy in scopes:
        for row in inv.prices:
            if (row.is_staff == is_staff and row.night_date == want_night
                    and row.occupancy == want_occupancy):
                return quantize(row.price)

    return quantize(_base(inv, is_staff))


def stay_total(inv, check_in, check_out, occupancy=None, is_staff=False):
    """What the whole stay costs at room rate, excluding taxes and fees.
    Returns None if the dates are unusable or any night is unpriced, so a
    partial total is never mistaken for a real one."""
    nights = nights_between(check_in, check_out)
    if not nights:
        return None

    total = Decimal('0.00')
    for night in nights:
        rate = price_for(inv, night=night, occupancy=occupancy, is_staff=is_staff)
        if rate is None:
            return None
        total += rate
    return quantize(total)


def occupancy_range(inv):
    return list(range(inv.min_capacity, inv.capacity + 1))


def price_matrix(inv, is_staff=False):
    """One block's rates as JSON-safe data for a template or a script tag.

    `cells` is keyed by night ISO string then occupancy, both '' when that
    dimension does not vary, so a caller can look up any scope the same way.
    """
    nights = sorted({row.night_date for row in inv.prices
                     if row.is_staff == is_staff and row.night_date}) if inv.price_per_night else []
    occupancies = occupancy_range(inv) if inv.price_per_occupancy else []

    cells = {}
    for night in (nights or [None]):
        night_key = night.isoformat() if night else ''
        cells[night_key] = {}
        for occupancy in (occupancies or [None]):
            rate = price_for(inv, night=night, occupancy=occupancy, is_staff=is_staff)
            cells[night_key][str(occupancy) if occupancy else ''] = (
                str(rate) if rate is not None else None)

    base = quantize(_base(inv, is_staff))
    return {
        'per_night': bool(inv.price_per_night),
        'per_occupancy': bool(inv.price_per_occupancy),
        'nights': [night.isoformat() for night in nights],
        'occupancies': occupancies,
        'base': str(base) if base is not None else None,
        'cells': cells,
        'notes': inv.pricing_notes,
    }


def price_matrices(inv):
    """Both scopes in one call, for surfaces that render standard and staff
    rates side by side."""
    return {'standard': price_matrix(inv), 'staff': price_matrix(inv, is_staff=True)}
