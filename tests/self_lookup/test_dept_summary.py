from uber.config import c
from uber.models import DeptRole
from tests.self_lookup.factories import attendee, dept, membership, staffer


def test_dept_head_membership_is_listed(session):
    techops = dept(session, 'TechOps')
    head = staffer(session, 'Head', techops, is_dept_head=True)
    summary = head.dept_summary
    assert summary['assigned_depts'] == {techops.id: techops.name}
    assert summary['dept_head_depts'] == {techops.id: techops.name}
    assert summary['poc_depts'] == {}


def test_membership_without_role_or_shifts_is_omitted(session):
    techops = dept(session, 'TechOps')
    plain = staffer(session, 'Plain', techops)
    assert plain.dept_summary['assigned_depts'] == {}


def test_attendee_has_empty_summary(session):
    assert attendee(session).dept_summary == {
        'assigned_depts': {}, 'checklist_admin_depts': {}, 'dept_head_depts': {}, 'poc_depts': {}, 'roles_depts': {}}


def test_roles_are_listed_as_pairs_in_a_plain_dict(session):
    techops = dept(session, 'TechOps')
    member = staffer(session, 'Roley')
    m = membership(session, member, techops, is_dept_head=True)
    role = DeptRole(name='Lead', description='Lead', department_id=techops.id)
    session.add(role)
    session.flush()
    m.dept_roles.append(role)
    session.flush()
    session.refresh(member)
    summary = member.dept_summary
    assert summary['roles_depts'] == {techops.id: [[role.id, role.name]]}
    assert type(summary['roles_depts']) is dict


def test_deferred_staffer_lists_plain_membership(session):
    techops = dept(session, 'TechOps')
    deferred = staffer(session, 'Later', techops)
    deferred.badge_status = c.DEFERRED_STATUS
    session.flush()
    assert deferred.dept_summary['assigned_depts'] == {techops.id: techops.name}


def test_poc_and_checklist_admin_are_listed(session):
    techops = dept(session, 'TechOps')
    member = staffer(session, 'Poc', techops, is_poc=True, is_checklist_admin=True)
    summary = member.dept_summary
    assert summary['poc_depts'] == {techops.id: techops.name}
    assert summary['checklist_admin_depts'] == {techops.id: techops.name}
    assert summary['dept_head_depts'] == {}
