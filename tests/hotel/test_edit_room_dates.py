"""hotel_lottery.edit_room's stay check: at least one night, inside the
lottery check-in / check-out window. Minimum-night rules are not applied
here (they exist only as hardcoded entry-form checks, not on the models).

Attendee date edits never run the waitlist sweep - that is an admin
action (Process Waitlist / inventory save). A night someone else is
already queued for stays queue-blocked for everyone behind them, and
nights an attendee releases sit open until the next admin sweep.
"""

from datetime import datetime

from uber.config import c

from tests.hotel.factories import N


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
