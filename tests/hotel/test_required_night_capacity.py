"""The inventory page's rooms column and the partitions page's Default row
count rooms free for a whole stay across the required (core) nights, not
the block's default per-night quantity."""

from datetime import date, datetime

import pytest

from uber.config import c

from tests.hotel.factories import (make_hotel, make_inventory, make_partition,
                                   make_partition_block, set_night_quantity)

THU, FRI, SAT, SUN = date(2027, 1, 7), date(2027, 1, 8), date(2027, 1, 9), date(2027, 1, 10)


@pytest.fixture
def admin_page(no_cherrypy_session, monkeypatch):
    import uber.site_sections.hotel_lottery_admin as admin_site
    from uber.models import initialize_db

    initialize_db()
    monkeypatch.setattr(c, 'HOTEL_LOTTERY_CHECKIN_START', datetime(2027, 1, 2))
    monkeypatch.setattr(c, 'HOTEL_LOTTERY_CHECKIN_END', datetime(2027, 1, 7))
    monkeypatch.setattr(c, 'HOTEL_LOTTERY_CHECKOUT_START', datetime(2027, 1, 10))
    monkeypatch.setattr(c, 'HOTEL_LOTTERY_CHECKOUT_END', datetime(2027, 1, 11))
    monkeypatch.setattr(admin_site, 'is_lottery_admin', lambda *a, **k: True)

    def call(name, session, **kwargs):
        func = getattr(admin_site.Root, name)
        while hasattr(func, '__wrapped__'):
            func = func.__wrapped__
        return func(admin_site.Root(), session, **kwargs)
    return call


def _shoulder_block(session):
    """Default 0 rooms, 30 Thu-Sat, 40 on Fri."""
    inv = make_inventory(session, make_hotel(session), quantity=0)
    for night, qty in ((THU, 30), (FRI, 40), (SAT, 30)):
        set_night_quantity(session, inv, night, qty)
    return inv


def test_required_nights_follow_lottery_dates(admin_page):
    from uber.site_sections.hotel_lottery_admin import _required_nights
    assert _required_nights() == [THU, FRI, SAT]


def test_inventory_rooms_column_is_the_fewest_core_night_rooms(session, admin_page):
    inv = _shoulder_block(session)

    page = admin_page('hotel_inventory', session)
    rows = [r for rows in page['room_inventory'].values() for r in rows if r['inventory'].id == inv.id]
    assert rows[0]['quantity'] == 30


def test_inventory_rooms_column_respects_default_partition_filter(session, admin_page):
    inv = _shoulder_block(session)
    make_partition_block(session, make_partition(session), inv, 12)

    page = admin_page('hotel_inventory', session, partition='default')
    rows = [r for rows in page['room_inventory'].values() for r in rows if r['inventory'].id == inv.id]
    assert rows[0]['quantity'] == 18


def test_default_partition_row_counts_core_night_rooms(session, admin_page):
    before = admin_page('manage_partitions', session)['non_partitioned_capacity']
    inv = _shoulder_block(session)
    make_partition_block(session, make_partition(session), inv, 12)
    over = make_inventory(session, make_hotel(session), quantity=5)
    make_partition_block(session, make_partition(session), over, 8)

    after = admin_page('manage_partitions', session)['non_partitioned_capacity']
    assert after - before == 18
