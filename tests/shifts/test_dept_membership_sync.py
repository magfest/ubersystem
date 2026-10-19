import logging
import uuid

import pytest

from uber.config import c
from uber.models import Attendee, Department, DeptMembership
from uber.tasks.shifts import add_synced_memberships


def _dept(session, label):
    dept = Department(name=f'{label} {uuid.uuid4().hex[:8]}', description=label)
    session.add(dept)
    session.flush()
    return dept


def _staffer(session, first_name, *depts, **membership_flags):
    attendee = Attendee(first_name=first_name, last_name='Sync', email=f'{uuid.uuid4().hex}@example.com',
                        badge_type=c.STAFF_BADGE, badge_status=c.COMPLETED_STATUS, paid=c.NEED_NOT_PAY,
                        staffing=True)
    session.add(attendee)
    session.flush()
    for dept in depts:
        session.add(DeptMembership(attendee_id=attendee.id, department_id=dept.id, **membership_flags))
    session.flush()
    return attendee


def _member_names(session, dept):
    return sorted(m.attendee.first_name for m in
                  session.query(DeptMembership).filter_by(department_id=dept.id))


@pytest.fixture
def depts(session, monkeypatch):
    techops, supplyops, festops = _dept(session, 'TechOps'), _dept(session, 'SupplyOps'), _dept(session, 'FestOps')
    monkeypatch.setattr(c, 'DEPT_MEMBERSHIP_SYNC', {festops.name: [techops.name, supplyops.name]})
    _staffer(session, 'Tess', techops)
    _staffer(session, 'Sam', supplyops)
    _staffer(session, 'Both', techops, supplyops)
    return techops, supplyops, festops


def test_adds_members_of_every_source(session, depts):
    _, _, festops = depts
    add_synced_memberships(session)
    assert _member_names(session, festops) == ['Both', 'Sam', 'Tess']


def test_leaves_existing_members_untouched(session, depts):
    techops, _, festops = depts
    head = _staffer(session, 'Head', techops)
    session.add(DeptMembership(attendee_id=head.id, department_id=festops.id, is_dept_head=True))
    session.flush()

    add_synced_memberships(session)
    assert _member_names(session, festops) == ['Both', 'Head', 'Sam', 'Tess']
    assert session.query(DeptMembership).filter_by(department_id=festops.id, attendee_id=head.id).one().is_dept_head


def test_never_removes_members(session, depts):
    _, _, festops = depts
    _staffer(session, 'Manual', festops)
    add_synced_memberships(session)
    assert 'Manual' in _member_names(session, festops)


def test_running_twice_adds_nothing_new(session, depts):
    _, _, festops = depts
    add_synced_memberships(session)
    add_synced_memberships(session)
    assert _member_names(session, festops) == ['Both', 'Sam', 'Tess']


def test_chained_entries_apply_in_one_run(session, depts, monkeypatch):
    techops, supplyops, festops = depts
    downstream = _dept(session, 'Downstream')
    monkeypatch.setattr(c, 'DEPT_MEMBERSHIP_SYNC', {festops.name: [techops.name, supplyops.name],
                                                    downstream.name: [festops.name]})
    add_synced_memberships(session)
    assert _member_names(session, downstream) == ['Both', 'Sam', 'Tess']


def test_unknown_department_logs_and_skips(session, depts, monkeypatch, caplog):
    techops, _, festops = depts
    monkeypatch.setattr(c, 'DEPT_MEMBERSHIP_SYNC', {festops.name: [techops.name, 'No Such Dept']})
    with caplog.at_level(logging.WARNING):
        add_synced_memberships(session)
    assert 'No Such Dept' in caplog.text
    assert _member_names(session, festops) == []


def test_empty_config_does_nothing(session, depts, monkeypatch):
    _, _, festops = depts
    monkeypatch.setattr(c, 'DEPT_MEMBERSHIP_SYNC', {})
    add_synced_memberships(session)
    assert _member_names(session, festops) == []
