"""uber.hotel.waitlist: attendee resize, the FIFO sweep, and the admin
single-row accept."""

from datetime import datetime, timezone

import pytest

from uber.config import c
from uber.hotel.queries import capacity_for
from uber.hotel.waitlist import (WaitlistError, accept_waitlist_entry,
                                 fulfill_waitlist, resize_assignment)

from tests.hotel.factories import (N, make_application, make_assignment,
                                   make_attendee, make_hotel, make_inventory,
                                   make_partition, make_partition_block)

T1 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)


def _setup(session, quantity=5):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel, quantity=quantity)
    return hotel, inv


def test_resize_extends_into_open_capacity(session):
    _, inv = _setup(session, quantity=5)
    ra = make_assignment(session, make_attendee(session), inv,
                         check_in=N[2], check_out=N[4], status=c.SECURED)

    result = resize_assignment(session, ra, N[1], N[5])

    assert (result.confirmed_ci, result.confirmed_co) == (N[1], N[5])
    assert result.waitlisted_nights == []
    assert (ra.assigned_check_in_date, ra.assigned_check_out_date) == (N[1], N[5])
    assert ra.waitlisted_check_in_date is None
    assert ra.waitlisted_check_out_date is None
    assert ra.waitlist_started_at is None


def test_resize_into_full_night_waitlists_and_stamps_started_at(session):
    _, inv = _setup(session, quantity=1)
    blocker = make_assignment(session, make_attendee(session), inv,
                              check_in=N[1], check_out=N[2])
    assert blocker.is_live
    ra = make_assignment(session, make_attendee(session), inv,
                         check_in=N[2], check_out=N[4], status=c.SECURED)

    result = resize_assignment(session, ra, N[1], N[4])

    assert (result.confirmed_ci, result.confirmed_co) == (N[2], N[4])
    assert result.waitlisted_nights == [N[1]]
    assert ra.waitlisted_check_in_date == N[1]
    assert ra.waitlisted_check_out_date == N[4]
    assert ra.waitlist_started_at is not None, \
        'entering the queue must stamp waitlist_started_at (FIFO key)'
    assert ra.waitlisted_gap_nights == [N[1]]


def test_resize_ignores_irrelevant_waitlisters(session):
    _, inv = _setup(session, quantity=4)
    partition = make_partition(session)
    make_partition_block(session, partition, inv, quantity=1)

    # Waitlister in a different partition scope, wanting our night.
    make_assignment(session, make_attendee(session), inv,
                    check_in=N[2], check_out=N[4], status=c.SECURED,
                    partition_id=partition.id,
                    waitlisted_check_in_date=N[1],
                    waitlist_started_at=T1)
    # Unpartitioned waitlister waiting on a NON-overlapping night (N5).
    make_assignment(session, make_attendee(session), inv,
                    check_in=N[6], check_out=N[8], status=c.SECURED,
                    waitlisted_check_in_date=N[5],
                    waitlist_started_at=T1)

    ra = make_assignment(session, make_attendee(session), inv,
                         check_in=N[2], check_out=N[4], status=c.SECURED)
    result = resize_assignment(session, ra, N[1], N[4])

    assert (result.confirmed_ci, result.confirmed_co) == (N[1], N[4]), \
        'queues in other partitions / on other nights must not block'
    assert result.waitlisted_nights == []


def test_resize_blocked_by_relevant_queued_waitlister(session):
    _, inv = _setup(session, quantity=4)
    # Same scope (unpartitioned), same inventory, wants exactly N1.
    earlier = make_assignment(session, make_attendee(session), inv,
                              check_in=N[2], check_out=N[4], status=c.SECURED,
                              waitlisted_check_in_date=N[1],
                              waitlist_started_at=T1)
    assert earlier.waitlisted_gap_nights == [N[1]]

    ra = make_assignment(session, make_attendee(session), inv,
                         check_in=N[2], check_out=N[4], status=c.SECURED)
    result = resize_assignment(session, ra, N[1], N[4])

    assert (result.confirmed_ci, result.confirmed_co) == (N[2], N[4]), \
        'an earlier queued entrant claims the night even with open capacity'
    assert result.waitlisted_nights == [N[1]]
    assert ra.waitlisted_check_in_date == N[1]

    # With respect_queue=False the same extension goes through.
    ra2 = make_assignment(session, make_attendee(session), inv,
                          check_in=N[2], check_out=N[4], status=c.SECURED)
    result2 = resize_assignment(session, ra2, N[1], N[4],
                                respect_queue=False)
    assert (result2.confirmed_ci, result2.confirmed_co) == (N[1], N[4])


def test_resize_shrink_releases_nights(session):
    _, inv = _setup(session, quantity=1)
    ra = make_assignment(session, make_attendee(session), inv,
                         check_in=N[1], check_out=N[5], status=c.SECURED,
                         waitlisted_check_out_date=N[6],
                         waitlist_started_at=T1)
    assert capacity_for(session, inv, N[1])[2] == 0, 'block is full on N1'

    result = resize_assignment(session, ra, N[2], N[4])

    assert (result.confirmed_ci, result.confirmed_co) == (N[2], N[4]), \
        'a shrink must actually shorten the stay (it used to be a silent no-op)'
    assert (ra.assigned_check_in_date, ra.assigned_check_out_date) == (N[2], N[4])
    assert result.released_nights == [N[1], N[4]]
    assert result.waitlisted_nights == []
    assert ra.waitlisted_check_in_date is None
    assert ra.waitlisted_check_out_date is None
    assert ra.waitlist_started_at is None, \
        'the narrower request is fully satisfied, so the old wider waitlist clears'
    assert capacity_for(session, inv, N[1])[2] == 1, \
        'the released night is open capacity again'
    assert capacity_for(session, inv, N[4])[2] == 1


def test_resize_extend_is_unchanged_by_release_support(session):
    _, inv = _setup(session, quantity=5)
    ra = make_assignment(session, make_attendee(session), inv,
                         check_in=N[2], check_out=N[4], status=c.SECURED)

    result = resize_assignment(session, ra, N[1], N[5])

    assert (result.confirmed_ci, result.confirmed_co) == (N[1], N[5])
    assert result.released_nights == []


def test_resize_shift_keeps_overlap_and_extends(session):
    _, inv = _setup(session, quantity=5)
    ra = make_assignment(session, make_attendee(session), inv,
                         check_in=N[1], check_out=N[3], status=c.SECURED)

    result = resize_assignment(session, ra, N[2], N[4])

    assert (result.confirmed_ci, result.confirmed_co) == (N[2], N[4])
    assert result.released_nights == [N[1]]
    assert result.waitlisted_nights == []
    assert (ra.assigned_check_in_date, ra.assigned_check_out_date) == (N[2], N[4])


def test_resize_shift_into_full_night_releases_and_waitlists(session):
    _, inv = _setup(session, quantity=1)
    make_assignment(session, make_attendee(session), inv,
                    check_in=N[3], check_out=N[4])  # N3 is full
    ra = make_assignment(session, make_attendee(session), inv,
                         check_in=N[1], check_out=N[3], status=c.SECURED)

    result = resize_assignment(session, ra, N[2], N[4])

    assert (result.confirmed_ci, result.confirmed_co) == (N[2], N[3]), \
        'the kept overlap anchors the stay; the dropped night goes regardless'
    assert result.released_nights == [N[1]]
    assert result.waitlisted_nights == [N[3]]
    assert (ra.waitlisted_check_in_date, ra.waitlisted_check_out_date) == (N[2], N[4])
    assert ra.waitlisted_gap_nights == [N[3]]


def test_resize_disjoint_move_confirms_when_open(session):
    _, inv = _setup(session, quantity=1)
    ra = make_assignment(session, make_attendee(session), inv,
                         check_in=N[1], check_out=N[3], status=c.SECURED)

    result = resize_assignment(session, ra, N[4], N[6])

    assert (result.confirmed_ci, result.confirmed_co) == (N[4], N[6])
    assert result.released_nights == [N[1], N[2]]
    assert result.waitlisted_nights == []
    assert (ra.assigned_check_in_date, ra.assigned_check_out_date) == (N[4], N[6])


def test_resize_disjoint_move_takes_longest_open_run_and_waitlists_rest(session):
    _, inv = _setup(session, quantity=1)
    make_assignment(session, make_attendee(session), inv,
                    check_in=N[5], check_out=N[6])  # N5 is full
    ra = make_assignment(session, make_attendee(session), inv,
                         check_in=N[1], check_out=N[3], status=c.SECURED)

    result = resize_assignment(session, ra, N[4], N[8])

    assert (result.confirmed_ci, result.confirmed_co) == (N[6], N[8]), \
        'N4 alone vs N6+N7: the longer run wins'
    assert result.released_nights == [N[1], N[2]]
    assert result.waitlisted_nights == [N[4], N[5]]
    assert (ra.waitlisted_check_in_date, ra.waitlisted_check_out_date) == (N[4], N[8])
    assert ra.waitlisted_gap_nights == [N[4], N[5]]


def test_resize_refuses_when_no_requested_night_is_open(session):
    _, inv = _setup(session, quantity=1)
    make_assignment(session, make_attendee(session), inv,
                    check_in=N[4], check_out=N[6])
    ra = make_assignment(session, make_attendee(session), inv,
                         check_in=N[1], check_out=N[3], status=c.SECURED)

    with pytest.raises(WaitlistError) as exc:
        resize_assignment(session, ra, N[4], N[6])

    assert 'current dates were kept' in exc.value.message
    assert (ra.assigned_check_in_date, ra.assigned_check_out_date) == (N[1], N[3])
    assert ra.waitlisted_check_in_date is None


def test_resize_rejects_empty_range(session):
    _, inv = _setup(session, quantity=5)
    ra = make_assignment(session, make_attendee(session), inv,
                         check_in=N[1], check_out=N[3], status=c.SECURED)

    with pytest.raises(WaitlistError):
        resize_assignment(session, ra, N[2], N[2])
    with pytest.raises(WaitlistError):
        resize_assignment(session, ra, N[3], N[2])
    assert (ra.assigned_check_in_date, ra.assigned_check_out_date) == (N[1], N[3])


def test_resize_shrink_cascades_to_connector_children(session):
    _, inv = _setup(session, quantity=2)
    attendee = make_attendee(session)
    parent = make_assignment(session, attendee, inv,
                             check_in=N[1], check_out=N[5], status=c.SECURED)
    child = make_assignment(session, attendee, inv,
                            check_in=N[1], check_out=N[5], status=c.ASSIGNED,
                            parent_assignment_id=parent.id,
                            assignment_reason=c.SUITE_CONNECTOR)

    resize_assignment(session, parent, N[2], N[4])

    assert (child.assigned_check_in_date, child.assigned_check_out_date) == (N[2], N[4])


def test_fulfill_closes_multi_night_front_gap_in_one_sweep(session):
    _, inv = _setup(session, quantity=1)
    ra = make_assignment(session, make_attendee(session), inv,
                         check_in=N[3], check_out=N[5], status=c.SECURED,
                         waitlisted_check_in_date=N[1],
                         waitlist_started_at=T1)
    assert ra.waitlisted_gap_nights == [N[1], N[2]]

    result = fulfill_waitlist(session)

    assert ra.assigned_check_in_date == N[1], \
        'a multi-night front gap must complete in a single sweep'
    assert result.fulfilled == 2
    assert ra in result.fulfilled_assignments
    assert ra.waitlisted_check_in_date is None
    assert ra.waitlisted_check_out_date is None
    assert ra.waitlist_started_at is None


def test_fulfill_serves_fifo_by_waitlist_started_at(session):
    _, inv = _setup(session, quantity=1)
    # Later entrant created FIRST so id/creation order can't mask FIFO.
    later = make_assignment(session, make_attendee(session), inv,
                            check_in=N[2], check_out=N[4], status=c.SECURED,
                            waitlisted_check_in_date=N[1],
                            waitlist_started_at=T2)
    earlier = make_assignment(session, make_attendee(session), inv,
                              check_in=N[2], check_out=N[4], status=c.SECURED,
                              waitlisted_check_in_date=N[1],
                              waitlist_started_at=T1)

    result = fulfill_waitlist(session)

    assert earlier.assigned_check_in_date == N[1]
    assert earlier.waitlist_started_at is None
    assert later.assigned_check_in_date == N[2], \
        'only one open slot on N1: the earlier entrant wins'
    assert later.waitlisted_check_in_date == N[1], 'the loser keeps waiting'
    assert result.fulfilled == 1


def test_fulfill_cascades_to_connector_children(session):
    _, inv = _setup(session, quantity=2)
    attendee = make_attendee(session)
    parent = make_assignment(session, attendee, inv,
                             check_in=N[2], check_out=N[4], status=c.SECURED,
                             waitlisted_check_in_date=N[1],
                             waitlist_started_at=T1)
    child = make_assignment(session, attendee, inv,
                            check_in=N[2], check_out=N[4], status=c.ASSIGNED,
                            parent_assignment_id=parent.id,
                            assignment_reason=c.SUITE_CONNECTOR)

    fulfill_waitlist(session)

    assert parent.assigned_check_in_date == N[1]
    assert child.assigned_check_in_date == N[1]
    assert child.assigned_check_out_date == parent.assigned_check_out_date
    assert child.waitlisted_check_in_date == parent.waitlisted_check_in_date
    assert child.waitlist_started_at == parent.waitlist_started_at, \
        'the cascade includes waitlist_started_at'


def test_fulfill_skips_export_locked_rows(session):
    _, inv = _setup(session, quantity=5)
    attendee = make_attendee(session)
    # entry_type must be non-NULL: the sweep's SQL prefilter
    # (`entry_type != GROUP_ENTRY`) silently drops NULL-entry_type apps
    # (SQL NULL semantics), unlike the python-side sweep_eligible.
    app = make_application(session, attendee, export_locked=True,
                           entry_type=c.ROOM_ENTRY)
    ra = make_assignment(session, attendee, inv,
                         check_in=N[2], check_out=N[4], status=c.SECURED,
                         lottery_application_id=app.id,
                         waitlisted_check_in_date=N[1],
                         waitlist_started_at=T1)

    result = fulfill_waitlist(session)

    assert result.skipped_locked == 1
    assert result.fulfilled == 0
    assert ra.assigned_check_in_date == N[2], 'locked rows are untouched'
    assert ra.waitlisted_check_in_date == N[1]


def test_accept_works_on_assigned_row(session):
    _, inv = _setup(session, quantity=5)
    ra = make_assignment(session, make_attendee(session), inv,
                         check_in=N[2], check_out=N[4], status=c.ASSIGNED,
                         waitlisted_check_in_date=N[1],
                         waitlisted_check_out_date=N[5],
                         waitlist_started_at=T1)

    result = accept_waitlist_entry(session, ra)

    assert (result.nights_front, result.nights_back) == (1, 1)
    assert result.still_waiting is False
    assert (ra.assigned_check_in_date, ra.assigned_check_out_date) == (N[1], N[5])
    assert ra.waitlist_started_at is None


def test_accept_refuses_export_locked(session):
    _, inv = _setup(session, quantity=5)
    attendee = make_attendee(session)
    app = make_application(session, attendee, export_locked=True)
    ra = make_assignment(session, attendee, inv,
                         check_in=N[2], check_out=N[4], status=c.SECURED,
                         lottery_application_id=app.id,
                         waitlisted_check_in_date=N[1],
                         waitlist_started_at=T1)

    with pytest.raises(WaitlistError):
        accept_waitlist_entry(session, ra)
