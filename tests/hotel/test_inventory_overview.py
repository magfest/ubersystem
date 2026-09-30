"""The inventory overview lists inactive blocks (marked in the template)
but counts only active blocks as offered."""

import uber.site_sections.hotel_lottery_admin as hla

from tests.hotel.factories import make_hotel, make_inventory


def _overview(session):
    func = hla.Root.hotel_inventory
    while hasattr(func, '__wrapped__'):
        func = func.__wrapped__
    return func(hla.Root(), session)


def test_inactive_blocks_are_listed_but_not_offered(session, no_cherrypy_session):
    hotel = make_hotel(session)
    active = make_inventory(session, hotel, quantity=10)
    inactive = make_inventory(session, hotel, quantity=7, active=False)
    nights = len(hla._event_nights())
    assert nights, 'the lottery window must span at least one night'

    ctx = _overview(session)

    rows = {info['inventory'].id: info for info in ctx['room_inventory'][hotel]}
    assert set(rows) == {active.id, inactive.id}
    assert not rows[inactive.id]['inventory'].active
    hotel_total = ctx['hotel_totals'][str(hotel.id)]
    assert hotel_total['remaining'] == 10 * nights, 'the inactive block adds no open rooms'
    assert ctx['summary']['blocks'] == 1
    assert ctx['summary']['offered'] == 10 * nights
