"""Test data builders shared by the self_lookup tests."""

import uuid

from uber.config import c
from uber.models import Attendee, AttendeeAccount, Department, DeptMembership


def dept(session, label):
    d = Department(name=f'{label} {uuid.uuid4().hex[:8]}', description=label)
    session.add(d)
    session.flush()
    return d


def attendee(session, **overrides):
    fields = dict(first_name='Pat', last_name='Guest', email=f'{uuid.uuid4().hex}@example.com')
    fields.update(overrides)
    a = Attendee(**fields)
    session.add(a)
    session.flush()
    return a


def staffer(session, first_name, *depts, **membership_flags):
    a = attendee(session, first_name=first_name, last_name='Staff', badge_type=c.STAFF_BADGE,
                 badge_status=c.COMPLETED_STATUS, paid=c.NEED_NOT_PAY, staffing=True)
    for d in depts:
        session.add(DeptMembership(attendee_id=a.id, department_id=d.id, **membership_flags))
    session.flush()
    return a


def membership(session, attendee, dept, **flags):
    m = DeptMembership(attendee_id=attendee.id, department_id=dept.id, **flags)
    session.add(m)
    session.flush()
    return m


def account(session, sso_id, *attendees):
    acct = AttendeeAccount(email=f'{uuid.uuid4().hex}@example.com', sso_id=sso_id)
    session.add(acct)
    acct.attendees.extend(attendees)
    session.flush()
    return acct
