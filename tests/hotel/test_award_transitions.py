"""The COMPLETE <-> AWARDED transition: the RoomAssignment
after_insert/after_delete SQL listeners and the ORM-side
LotteryApplication.sync_award_status must implement the same rule.

The listeners run on the raw connection during flush, so the ORM object is
stale afterwards - tests flush and then expire/refresh the app to observe.
"""

from uber.config import c

from tests.hotel.factories import (N, make_application, make_assignment,
                                   make_attendee, make_hotel, make_inventory,
                                   make_run)


def _fixture(session, app_status):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel, quantity=5)
    attendee = make_attendee(session)
    app = make_application(session, attendee, status=app_status)
    return inv, attendee, app


def test_after_insert_cancelled_row_does_not_promote(session):
    inv, attendee, app = _fixture(session, c.COMPLETE)

    make_assignment(session, attendee, inv, status=c.CANCELLED,
                    lottery_application_id=app.id,
                    check_in=N[1], check_out=N[3])
    session.expire(app)
    assert app.status == c.COMPLETE, \
        'inserting a non-live row (imports, seeds) must not promote the app'


def test_after_insert_live_row_promotes_complete_to_awarded(session):
    inv, attendee, app = _fixture(session, c.COMPLETE)

    make_assignment(session, attendee, inv, status=c.ASSIGNED,
                    lottery_application_id=app.id,
                    check_in=N[1], check_out=N[3])
    session.expire(app)
    assert app.status == c.AWARDED


def test_after_insert_leaves_terminal_statuses_alone(session):
    inv, attendee, app = _fixture(session, c.WITHDRAWN)

    make_assignment(session, attendee, inv, status=c.ASSIGNED,
                    lottery_application_id=app.id,
                    check_in=N[1], check_out=N[3])
    session.expire(app)
    assert app.status == c.WITHDRAWN, \
        'only COMPLETE apps are promoted by the insert listener'


def test_after_delete_last_live_row_demotes_despite_expired_sibling(session):
    inv, attendee, app = _fixture(session, c.COMPLETE)
    run = make_run(session)

    live = make_assignment(session, attendee, inv, status=c.ASSIGNED,
                           lottery_application_id=app.id,
                           check_in=N[1], check_out=N[3])
    # An EXPIRED sibling lingers (the common case - expired rows are kept).
    make_assignment(session, attendee, inv, status=c.EXPIRED,
                    lottery_application_id=app.id,
                    check_in=N[1], check_out=N[3])
    session.expire(app)
    assert app.status == c.AWARDED
    app.lottery_run_id = run.id
    session.flush()

    session.delete(live)
    session.flush()
    session.expire(app)
    assert app.status == c.COMPLETE, \
        'deleting the last LIVE row demotes even with an EXPIRED sibling'
    assert app.lottery_run_id is None, 'demotion detaches the run'


def test_after_delete_with_remaining_live_row_keeps_awarded(session):
    inv, attendee, app = _fixture(session, c.COMPLETE)

    first = make_assignment(session, attendee, inv, status=c.ASSIGNED,
                            lottery_application_id=app.id,
                            check_in=N[1], check_out=N[3])
    make_assignment(session, attendee, inv, status=c.SECURED,
                    lottery_application_id=app.id,
                    check_in=N[1], check_out=N[3],
                    cc_token='test-token')
    session.expire(app)
    assert app.status == c.AWARDED

    session.delete(first)
    session.flush()
    session.expire(app)
    assert app.status == c.AWARDED, \
        'a remaining live row keeps the app AWARDED'


def test_sync_award_status_agrees_with_listeners(session):
    inv, attendee, app = _fixture(session, c.COMPLETE)
    run = make_run(session)

    ra = make_assignment(session, attendee, inv, status=c.ASSIGNED,
                         lottery_application_id=app.id,
                         check_in=N[1], check_out=N[3])
    session.expire(app)
    assert app.status == c.AWARDED

    # Manually knock it back to COMPLETE, then let sync re-derive AWARDED
    # from the live row (the ORM-side path used by admin status changes).
    app.status = c.COMPLETE
    session.flush()
    app.sync_award_status(session)
    assert app.status == c.AWARDED

    # Status flip without insert/delete (the expiry cron's path): the
    # listeners can't see it, sync_award_status must.
    app.lottery_run_id = run.id
    ra.status = c.EXPIRED
    session.flush()
    app.sync_award_status(session)
    assert app.status == c.COMPLETE
    assert app.lottery_run_id is None

    # Terminal app states are never overridden.
    ra.status = c.ASSIGNED
    app.status = c.WITHDRAWN
    session.flush()
    app.sync_award_status(session)
    assert app.status == c.WITHDRAWN
