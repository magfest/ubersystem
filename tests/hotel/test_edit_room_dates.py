"""hotel_lottery.edit_room's stay check: at least one night, inside the
lottery check-in / check-out window. Minimum-night rules are not applied
here (they exist only as hardcoded entry-form checks, not on the models).

Attendee date edits never run the waitlist sweep - that is an admin
action (Process Waitlist / inventory save). A night someone else is
already queued for stays queue-blocked for everyone behind them, and
nights an attendee releases sit open until the next admin sweep.
"""

from datetime import datetime
from urllib.parse import unquote

import pytest

from uber.config import c
from uber.site_sections.hotel_lottery import _require_room_access

from tests.hotel.factories import N
from tests.hotel.test_inactive_rooms import _handler


def test_check_stay_window(monkeypatch):
    from uber.site_sections.hotel_lottery import _check_stay_window
    monkeypatch.setattr(c, 'HOTEL_LOTTERY_CHECKIN_START',
                        datetime.combine(N[1], datetime.min.time()), raising=False)
    monkeypatch.setattr(c, 'HOTEL_LOTTERY_CHECKOUT_END',
                        datetime.combine(N[6], datetime.min.time()), raising=False)

    assert _check_stay_window(N[2], N[4]) is None
    assert _check_stay_window(N[2], N[3]) is None, 'a single night is fine here'
    assert _check_stay_window(N[1], N[6]) is None, 'the bounds are inclusive'
    assert 'at least one night' in _check_stay_window(N[3], N[3])
    assert 'at least one night' in _check_stay_window(N[4], N[3])
    assert 'available from' in _check_stay_window(N[0], N[4])
    assert 'available from' in _check_stay_window(N[2], N[7])


def _partition_room(session, monkeypatch):
    from tests.hotel.factories import (make_assignment, make_attendee, make_hotel,
                                       make_inventory, make_partition,
                                       make_partition_block)

    monkeypatch.setattr(c, 'HOTEL_LOTTERY_CHECKIN_START',
                        datetime.combine(N[0], datetime.min.time()), raising=False)
    monkeypatch.setattr(c, 'HOTEL_LOTTERY_CHECKOUT_END',
                        datetime.combine(N[9], datetime.min.time()), raising=False)
    inv = make_inventory(session, make_hotel(session))
    partition = make_partition(session)
    make_partition_block(session, partition, inv, quantity=2)
    return make_assignment(session, make_attendee(session), inventory=inv,
                           partition_id=partition.id, check_in=N[1], check_out=N[4])


def test_edit_room_without_lottery_application(session, post_request, monkeypatch):
    from uber.errors import HTTPRedirect

    ra = _partition_room(session, monkeypatch)

    # room.html omits `id` when the room has no lottery application.
    with pytest.raises(HTTPRedirect):
        _handler('edit_room')(
            session, assignment_id=ra.id, attendee_id=ra.attendee_id,
            assigned_check_in_date=N[2].isoformat(),
            assigned_check_out_date=N[4].isoformat())

    assert (ra.assigned_check_in_date, ra.assigned_check_out_date) == (N[2], N[4])


def test_edit_room_without_lottery_application_checks_room_access(
        session, post_request, monkeypatch):
    from tests.hotel.factories import make_attendee
    from uber.errors import HTTPRedirect

    # post_request stubs the access check; this test needs the real one.
    monkeypatch.setattr(post_request, '_require_room_access', _require_room_access)
    ra = _partition_room(session, monkeypatch)
    stranger = make_attendee(session, first='Stranger')

    with pytest.raises(HTTPRedirect) as excinfo:
        _handler('edit_room')(
            session, assignment_id=ra.id, attendee_id=stranger.id,
            assigned_check_in_date=N[2].isoformat(),
            assigned_check_out_date=N[4].isoformat())

    assert 'do not have access' in unquote(excinfo.value.urls[0])
    assert (ra.assigned_check_in_date, ra.assigned_check_out_date) == (N[1], N[4])
