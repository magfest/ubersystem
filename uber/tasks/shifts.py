from datetime import timedelta
import logging

from uber.config import c
from uber.models import Department, DeptMembership, Session
from uber.tasks import celery


log = logging.getLogger(__name__)


def add_synced_memberships(session):
    """Add members of each configured source department to its target department.

    A job is visible to one department's members or to all volunteers, so a
    department staffed from others needs those people as members. Membership only
    grows; DeptMembership does not record who created a row, so removal stays manual.
    Entries run in config order, and a chained entry sees earlier adds.
    """
    dept_ids = dict(session.query(Department.name, Department.id))
    for target_name, source_names in c.DEPT_MEMBERSHIP_SYNC.items():
        unknown = [name for name in [target_name, *source_names] if name not in dept_ids]
        if unknown:
            log.warning(f"Skipping membership sync into {target_name!r}: "
                        f"no department named {', '.join(repr(name) for name in unknown)}")
            continue

        target_id = dept_ids[target_name]
        source_ids = [dept_ids[name] for name in source_names]
        source_attendee_ids = {attendee_id for (attendee_id,) in session.query(DeptMembership.attendee_id)
                               .filter(DeptMembership.department_id.in_(source_ids))}
        existing_attendee_ids = {attendee_id for (attendee_id,) in session.query(DeptMembership.attendee_id)
                                 .filter(DeptMembership.department_id == target_id)}
        new_attendee_ids = source_attendee_ids - existing_attendee_ids
        if not new_attendee_ids:
            continue

        session.add_all(DeptMembership(attendee_id=attendee_id, department_id=target_id)
                        for attendee_id in new_attendee_ids)
        # Session has autoflush off; flushing here lets a chained entry query these rows.
        session.flush()
        log.info(f"Added {len(new_attendee_ids)} members to {target_name} from {', '.join(source_names)}")


@celery.schedule(timedelta(hours=1))
def sync_dept_memberships():
    if not c.DEPT_MEMBERSHIP_SYNC:
        return
    with Session() as session:
        add_synced_memberships(session)
        session.commit()
