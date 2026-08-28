"""Nightly rate resolution, stay totals, and the JSON-safe price matrix."""

import json
from datetime import date
from decimal import Decimal

import pytest

from uber.hotel import pricing
from uber.models.hotel import InventoryPrice

from tests.hotel.factories import make_hotel, make_inventory


N1 = date(2027, 1, 7)
N2 = date(2027, 1, 8)
N3 = date(2027, 1, 9)


def _price(session, inventory, amount, night=None, occupancy=None, is_staff=False):
    row = InventoryPrice(inventory_id=inventory.id, night_date=night,
                         occupancy=occupancy, is_staff=is_staff,
                         price=Decimal(amount))
    session.add(row)
    session.commit()
    return row


def _inventory(session, **overrides):
    inv = make_inventory(session, make_hotel(session), capacity=4, min_capacity=1)
    for key, value in overrides.items():
        setattr(inv, key, value)
    session.commit()
    return inv


def test_flat_block_uses_base_price(session):
    inv = _inventory(session, base_price=Decimal('199.00'))
    assert pricing.price_for(inv) == Decimal('199.00')
    assert pricing.price_for(inv, night=N1, occupancy=2) == Decimal('199.00')


def test_per_night_only(session):
    inv = _inventory(session, base_price=Decimal('199.00'), price_per_night=True)
    _price(session, inv, '249.00', night=N2)
    assert pricing.price_for(inv, night=N1) == Decimal('199.00')
    assert pricing.price_for(inv, night=N2) == Decimal('249.00')


def test_per_occupancy_only(session):
    inv = _inventory(session, base_price=Decimal('199.00'), price_per_occupancy=True)
    _price(session, inv, '229.00', occupancy=3)
    assert pricing.price_for(inv, occupancy=2) == Decimal('199.00')
    assert pricing.price_for(inv, occupancy=3) == Decimal('229.00')


def test_both_dimensions_prefer_the_most_specific_cell(session):
    inv = _inventory(session, base_price=Decimal('199.00'),
                     price_per_night=True, price_per_occupancy=True)
    _price(session, inv, '300.00', night=N2, occupancy=3)
    _price(session, inv, '260.00', night=N2)
    _price(session, inv, '230.00', occupancy=3)

    assert pricing.price_for(inv, night=N2, occupancy=3) == Decimal('300.00')
    assert pricing.price_for(inv, night=N2, occupancy=2) == Decimal('260.00')
    assert pricing.price_for(inv, night=N1, occupancy=3) == Decimal('230.00')
    assert pricing.price_for(inv, night=N1, occupancy=2) == Decimal('199.00')


def test_staff_scope_never_falls_back_to_standard(session):
    """A missing staff rate must read as unpriced, not as the public rate."""
    inv = _inventory(session, base_price=Decimal('199.00'))
    assert pricing.price_for(inv, is_staff=True) is None


def test_stay_total_sums_each_night(session):
    inv = _inventory(session, base_price=Decimal('199.00'), price_per_night=True)
    _price(session, inv, '249.00', night=N2)
    # N1 at 199 plus N2 at 249; the checkout night is not charged.
    assert pricing.stay_total(inv, N1, N3) == Decimal('448.00')


def test_stay_total_is_none_when_any_night_is_unpriced(session):
    inv = _inventory(session, price_per_night=True)
    _price(session, inv, '249.00', night=N1)
    assert pricing.stay_total(inv, N1, N3) is None


@pytest.mark.parametrize('check_in, check_out', [
    (None, N3), (N1, None), (N3, N1), (N1, N1),
])
def test_stay_total_rejects_unusable_ranges(session, check_in, check_out):
    inv = _inventory(session, base_price=Decimal('199.00'))
    assert pricing.stay_total(inv, check_in, check_out) is None


def test_price_matrix_is_json_serializable(session):
    inv = _inventory(session, base_price=Decimal('199.00'),
                     price_per_night=True, price_per_occupancy=True,
                     pricing_notes='Rates exclude tax.')
    _price(session, inv, '300.00', night=N2, occupancy=3)

    matrix = pricing.price_matrix(inv)
    json.dumps(matrix)

    assert matrix['nights'] == [N2.isoformat()]
    assert matrix['occupancies'] == [1, 2, 3, 4]
    assert matrix['cells'][N2.isoformat()]['3'] == '300.00'
    assert matrix['notes'] == 'Rates exclude tax.'


def test_price_matrices_covers_both_scopes(session):
    inv = _inventory(session, base_price=Decimal('199.00'),
                     base_staff_price=Decimal('149.00'))
    matrices = pricing.price_matrices(inv)
    assert matrices['standard']['base'] == '199.00'
    assert matrices['staff']['base'] == '149.00'


def test_duplicate_scope_is_rejected(session):
    """NULL means "any", so two all-scopes rows must collide rather than both
    being stored."""
    from sqlalchemy.exc import IntegrityError

    inv = _inventory(session)
    _price(session, inv, '199.00')
    with pytest.raises(IntegrityError):
        _price(session, inv, '249.00')
    session.rollback()


@pytest.mark.parametrize('amounts, expected', [
    ([], ''),
    ([Decimal('199')], '$199'),
    ([Decimal('199.50')], '$199.50'),
    ([Decimal('199'), Decimal('249')], '$199 - $249'),
])
def test_format_price_range(amounts, expected):
    assert pricing.format_price_range(amounts) == expected
