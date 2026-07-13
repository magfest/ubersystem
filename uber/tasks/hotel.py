"""Background tasks for the hotel lottery / room assignment system.

`expire_unsecured_assignments` enforces the per-run card deadline: any
RoomAssignment that needs a CC, hasn't gotten one, and is past its
deposit_cutoff_date flips to EXPIRED so the inventory frees up for the
next run (and the cancellation email fires).
"""

from datetime import datetime, timedelta
import logging

from pytz import UTC

from uber.config import c
from uber.models import LotteryApplication, RoomAssignment, Session
from uber.tasks import celery

log = logging.getLogger(__name__)

__all__ = ['expire_unsecured_assignments']


@celery.schedule(timedelta(hours=1))
def expire_unsecured_assignments():
    """Move RoomAssignments past their card deadline to EXPIRED.

    Runs hourly. Targets only rows that:
      - are still ASSIGNED (not yet secured, expired, or cancelled),
      - require_cc (master-bill rooms are exempt),
      - have no CC token captured,
      - have a deposit_cutoff_date strictly in the past.

    Status flip triggers the existing cancellation_flips_status presave on
    the model in subsequent cancellation flows, and the inventory is freed
    by virtue of the status change (queries that count assigned rooms
    filter on status IN (ASSIGNED, SECURED)).

    Email notification is handled by the room_cancelled email, which is
    wired against status transitions.
    """
    now = datetime.now(UTC).date()
    expired_count = 0
    with Session() as session:
        candidates = session.query(RoomAssignment).filter(
            RoomAssignment.status == c.ASSIGNED,
            RoomAssignment.require_cc.is_(True),
            RoomAssignment.cc_captured_at.is_(None),
            RoomAssignment.deposit_cutoff_date.isnot(None),
            RoomAssignment.deposit_cutoff_date < now,
        ).all()

        # Group expired assignments by their source application so we move
        # each LotteryApplication back to COMPLETE only once (and only when
        # ALL of its assignments expire - not while a sibling is still in
        # ASSIGNED or SECURED).
        impacted_app_ids = set()
        for ra in candidates:
            ra.status = c.EXPIRED
            session.add(ra)
            expired_count += 1
            if ra.lottery_application_id:
                impacted_app_ids.add(ra.lottery_application_id)

        for app_id in impacted_app_ids:
            app = session.query(LotteryApplication).get(app_id)
            if not app:
                continue
            live_siblings = session.query(RoomAssignment).filter(
                RoomAssignment.lottery_application_id == app_id,
                RoomAssignment.status.in_([c.ASSIGNED, c.SECURED]),
            ).count()
            if live_siblings == 0 and app.status in (c.AWARDED, c.PROCESSED):
                # Reset the application so it re-enters the next run. To gate
                # re-eligibility behind opt-in, the admin configures
                # confirmation_window_start on the next run.
                app.status = c.COMPLETE
                app.lottery_run_id = None
                session.add(app)

        if expired_count:
            session.commit()
            log.info("expire_unsecured_assignments: expired %d assignment(s), "
                     "%d application(s) reset to COMPLETE.",
                     expired_count, len(impacted_app_ids))
    return expired_count
