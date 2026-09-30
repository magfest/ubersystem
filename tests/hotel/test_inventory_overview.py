"""The inventory overview lists inactive blocks (marked in the template)
but counts only active blocks as offered, and loads in a fixed number of
queries however many rooms there are."""

import sqlalchemy as sa

import uber.site_sections.hotel_lottery_admin as hla
from uber.config import c
from uber.models import Session

from tests.hotel.factories import (make_application, make_assignment,
                                   make_attendee, make_hotel, make_inventory)


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


def test_overview_query_count_does_not_grow_with_rooms(session, no_cherrypy_session):
    nights = hla._event_nights()
    ci, co = nights[0], nights[-1]
    hotel = make_hotel(session)
    blocks = [make_inventory(session, hotel, quantity=30) for _ in range(3)]
    for i in range(90):
        attendee = make_attendee(session)
        app = make_application(session, attendee, status=c.AWARDED)
        make_assignment(session, attendee, blocks[i % 3], check_in=ci, check_out=co,
                        status=c.SECURED if i % 3 else c.ASSIGNED,
                        lottery_application_id=app.id,
                        waitlisted_check_out_date=co if i % 10 == 0 else None)
    session.flush()
    session.expire_all()

    statements = []

    def record(conn, cursor, statement, *args):
        statements.append(statement)
    sa.event.listen(Session.engine, 'before_cursor_execute', record)
    try:
        ctx = _overview(session)
    finally:
        sa.event.remove(Session.engine, 'before_cursor_execute', record)

    assert ctx['summary']['assigned'] == 90 * (co - ci).days
    assert len(statements) <= 15, \
        f'{len(statements)} queries for 90 rooms; loading per room again?'
