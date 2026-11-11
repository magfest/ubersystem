"""The partition matrix page: every active block against every active
partition, as raw allotments and as rooms left on the tightest core night."""

from datetime import date, datetime
from io import BytesIO

import pytest

from uber.config import c

from tests.hotel.factories import (make_assignment, make_attendee, make_hotel,
                                   make_inventory, make_partition,
                                   make_partition_block, set_night_quantity)

WED, THU, FRI, SAT, SUN = (date(2027, 1, 6), date(2027, 1, 7), date(2027, 1, 8),
                           date(2027, 1, 9), date(2027, 1, 10))


@pytest.fixture
def admin_page(no_cherrypy_session, monkeypatch):
    import uber.site_sections.hotel_lottery_admin as admin_site
    from uber.models import initialize_db

    initialize_db()
    # Event nights Wed-Sat; core nights Thu-Sat.
    monkeypatch.setattr(c, 'HOTEL_LOTTERY_CHECKIN_START', datetime(2027, 1, 6))
    monkeypatch.setattr(c, 'HOTEL_LOTTERY_CHECKIN_END', datetime(2027, 1, 7))
    monkeypatch.setattr(c, 'HOTEL_LOTTERY_CHECKOUT_START', datetime(2027, 1, 10))
    monkeypatch.setattr(c, 'HOTEL_LOTTERY_CHECKOUT_END', datetime(2027, 1, 10))
    monkeypatch.setattr(admin_site, 'is_lottery_admin', lambda *a, **k: True)

    def call(name, session, **kwargs):
        func = getattr(admin_site.Root, name)
        while hasattr(func, '__wrapped__'):
            func = func.__wrapped__
        return func(admin_site.Root(), session, **kwargs)
    return call


def _row(page, inv):
    return next(row for _, rows in page['sections'] for row in rows
                if row['inventory'].id == inv.id)


def _assign(session, inv, partition=None, check_in=THU, check_out=SUN):
    return make_assignment(session, make_attendee(session), inv,
                           check_in=check_in, check_out=check_out,
                           partition_id=partition.id if partition else None)


def test_allocation_shows_raw_allotment_and_default_remainder(session, admin_page):
    inv = make_inventory(session, make_hotel(session), quantity=20)
    staff, guests = make_partition(session), make_partition(session)
    make_partition_block(session, staff, inv, 12)
    make_partition_block(session, guests, inv, 3)

    row = _row(admin_page('partition_matrix', session), inv)
    assert row['rooms'] == 20
    assert row['cells'][staff.id]['allocated'] == 12
    assert row['cells'][guests.id]['allocated'] == 3
    assert row['default']['allocated'] == 5


def test_default_allocation_goes_negative_when_block_is_over_allotted(session, admin_page):
    inv = make_inventory(session, make_hotel(session), quantity=10)
    make_partition_block(session, make_partition(session), inv, 8)
    make_partition_block(session, make_partition(session), inv, 6)

    row = _row(admin_page('partition_matrix', session), inv)
    assert row['default']['allocated'] == -4


def test_partition_without_allotment_or_bookings_is_blank(session, admin_page):
    inv = make_inventory(session, make_hotel(session), quantity=10)
    unused = make_partition(session)

    row = _row(admin_page('partition_matrix', session), inv)
    assert row['cells'][unused.id] is None


def test_remaining_is_allotment_minus_assigned_on_tightest_core_night(session, admin_page):
    inv = make_inventory(session, make_hotel(session), quantity=20)
    staff = make_partition(session)
    make_partition_block(session, staff, inv, 5)
    for _ in range(3):
        _assign(session, inv, staff)
    _assign(session, inv, staff, check_in=FRI, check_out=SAT)

    cell = _row(admin_page('partition_matrix', session), inv)['cells'][staff.id]
    assert cell['remaining'] == 1
    by_night = {n['night']: n for n in cell['nights']}
    assert by_night[THU]['remaining'] == 2
    assert by_night[FRI] == {'night': FRI, 'capacity': 5, 'assigned': 4, 'remaining': 1}


def test_remaining_goes_negative_when_partition_is_over(session, admin_page):
    inv = make_inventory(session, make_hotel(session), quantity=20)
    staff = make_partition(session)
    make_partition_block(session, staff, inv, 2)
    for _ in range(3):
        _assign(session, inv, staff)

    cell = _row(admin_page('partition_matrix', session), inv)['cells'][staff.id]
    assert cell['remaining'] == -1


def test_bookings_without_an_allotment_show_as_negative(session, admin_page):
    inv = make_inventory(session, make_hotel(session), quantity=20)
    staff = make_partition(session)
    _assign(session, inv, staff)

    cell = _row(admin_page('partition_matrix', session), inv)['cells'][staff.id]
    assert cell['allocated'] == 0
    assert cell['remaining'] == -1


def test_default_remaining_counts_only_unpartitioned_bookings(session, admin_page):
    inv = make_inventory(session, make_hotel(session), quantity=10)
    staff = make_partition(session)
    make_partition_block(session, staff, inv, 4)
    _assign(session, inv, staff)
    _assign(session, inv)
    _assign(session, inv)

    row = _row(admin_page('partition_matrix', session), inv)
    assert row['default']['remaining'] == 4
    assert row['cells'][staff.id]['remaining'] == 3


def test_closed_shoulder_night_does_not_set_tightest_night(session, admin_page):
    inv = make_inventory(session, make_hotel(session), quantity=10)
    set_night_quantity(session, inv, WED, 0)
    staff = make_partition(session)
    make_partition_block(session, staff, inv, 4)

    cell = _row(admin_page('partition_matrix', session), inv)['cells'][staff.id]
    assert cell['remaining'] == 4
    assert {n['night'] for n in cell['nights']} == {WED, THU, FRI, SAT}


def test_inactive_partitions_and_blocks_are_left_out(session, admin_page):
    hotel = make_hotel(session)
    live = make_inventory(session, hotel, quantity=10)
    retired = make_inventory(session, hotel, quantity=10, active=False)
    old = make_partition(session, active=False)

    page = admin_page('partition_matrix', session)
    assert old.id not in {p.id for p in page['partitions']}
    block_ids = {row['inventory'].id for _, rows in page['sections'] for row in rows}
    assert live.id in block_ids
    assert retired.id not in block_ids


def test_download_has_allocation_and_remaining_sheets(session, admin_page):
    import openpyxl

    hotel = make_hotel(session, name='Matrix Test Hotel')
    inv = make_inventory(session, hotel, quantity=10)
    staff = make_partition(session, name='Matrix Test Staff')
    make_partition_block(session, staff, inv, 4)
    _assign(session, inv, staff)

    output = admin_page('partition_matrix_xlsx', session, set_headers=False)
    workbook = openpyxl.load_workbook(BytesIO(output))
    assert workbook.sheetnames == ['Allocation', 'Remaining']

    def cell_for(sheet):
        rows = list(workbook[sheet].iter_rows(values_only=True))
        column = rows[0].index('Matrix Test Staff')
        row = next(r for r in rows if r[0] == 'Matrix Test Hotel')
        return row[column]

    assert cell_for('Allocation') == 4
    assert cell_for('Remaining') == 3
