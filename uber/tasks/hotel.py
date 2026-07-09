"""Background tasks for the hotel lottery / room assignment system.

`expire_unsecured_assignments` enforces the per-run card deadline: any
RoomAssignment that needs a CC, hasn't gotten one, and is past its
deposit_cutoff_date flips to EXPIRED so the inventory frees up for the
next run, and the attendee is notified.
"""

from datetime import timedelta
import logging

from uber.config import c
from uber.email import EmailService
from uber.models import LotteryApplication, RoomAssignment, Session
from uber.tasks import celery
from uber.utils import localized_now

log = logging.getLogger(__name__)

__all__ = ['expire_unsecured_assignments']


@celery.schedule(timedelta(hours=1))
def expire_unsecured_assignments():
    """Move RoomAssignments past their card deadline to EXPIRED.

    Runs hourly. Targets only rows that:
      - are still ASSIGNED (not yet secured, expired, or cancelled),
      - require_cc (master-bill rooms are exempt),
      - have no CC token captured,
      - have a deposit_cutoff_date strictly in the past, measured in the
        event's timezone (deadlines are documented as end-of-day local).

    The inventory is freed by virtue of the status change (queries that
    count assigned rooms filter on status IN (ASSIGNED, SECURED)), and
    each impacted attendee is queued a hotel_lottery_room_expired email.
    """
    today = localized_now().date()
    expired_count = 0
    with Session() as session:
        candidates = session.query(RoomAssignment).filter(
            RoomAssignment.status == c.ASSIGNED,
            RoomAssignment.require_cc.is_(True),
            RoomAssignment.cc_captured_at.is_(None),
            RoomAssignment.deposit_cutoff_date.isnot(None),
            RoomAssignment.deposit_cutoff_date < today,
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

            # Notify each attendee, one email per released room (each room
            # is its own booking end to end). Rooms with no lottery
            # application (manual / partition grants) go to the attendee
            # directly.
            for ra in candidates:
                to_model = ra.lottery_application or ra.attendee
                if not to_model:
                    continue
                try:
                    EmailService.queue_email(
                        session, 'hotel_lottery_room_expired', to_model,
                        data={'assignment': ra,
                              'app': ra.lottery_application})
                except Exception:
                    log.exception(
                        'expire_unsecured_assignments: could not queue '
                        'expiry email for assignment %s', ra.id)
            session.commit()

            log.info("expire_unsecured_assignments: expired %d assignment(s), "
                     "%d application(s) reset to COMPLETE.",
                     expired_count, len(impacted_app_ids))
    return expired_count
