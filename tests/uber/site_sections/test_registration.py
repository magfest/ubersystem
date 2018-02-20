from datetime import date, datetime, timedelta

import pytest
import pytz
import six

from tests.uber.conftest import admin_attendee, assert_unique, csrf_token, POST
from uber.config import c
from uber.errors import HTTPRedirect
from uber.models import _attendee_validity_check, Attendee, Department, Group, Session
from uber.site_sections import registration
from uber.utils import localized_now


assert admin_attendee
assert csrf_token
assert POST


next_week = datetime.now(pytz.UTC) + timedelta(days=7)


@pytest.fixture(autouse=True)
def patch_badge_printed_deadline(monkeypatch):
    monkeypatch.setattr(c, 'PRINTED_BADGE_DEADLINE', next_week)


@pytest.fixture
def duplicate_badge_num_preconditions():
    group_id = None
    leader_id = None
    with Session() as session:
        leader = Attendee(
            first_name='Fearless',
            last_name='Leader',
            email='fearless@example.com',
            zip_code='21211',
            ec_name='Nana Fearless',
            ec_phone='555-555-1234',
            cellphone='555-555-2345',
            birthdate=date(1964, 12, 30),
            registered=localized_now(),
            paid=c.PAID_BY_GROUP,
            ribbon='',
            staffing=True,
            badge_type=c.PSEUDO_GROUP_BADGE)

        group = Group(name='Too Many Badges!')
        group.attendees = [leader]
        group.leader = leader
        session.add(leader)
        session.add(group)
        assert session.assign_badges(
            group,
            15,
            new_badge_type=c.STAFF_BADGE,
            new_ribbon_type='',
            paid=c.NEED_NOT_PAY) is None
        session.flush()

        group_id = group.id
        leader_id = leader.id

    with Session() as session:
        console = Department(name='DEPT_01', description='DEPT_01')
        leader = session.query(Attendee).get(leader_id)
        leader.paid = c.NEED_NOT_PAY
        leader.badge_printed_name = 'Fearmore'
        leader.badge_type = c.STAFF_BADGE
        leader.assigned_depts = [console]

        group = session.query(Group).get(group_id)
        group.auto_recalc = False

    for i in range(10):
        with Session() as session:
            console = session.query(Department).filter_by(name='DEPT_01').one()
            group = session.query(Group).get(group_id)

            is_staff = (i < 9)
            params = {
                'first_name': 'Doubtful',
                'last_name': 'Follower{}'.format(i),
                'email': 'fearsome{}@example.com'.format(i),
                'zip_code': '21211',
                'ec_name': 'Nana Fearless',
                'ec_phone': '555-555-1234',
                'cellphone': '555-555-321{}'.format(i),
                'birthdate': date(1964, 12, 30),
                'registered': localized_now(),
                'staffing': is_staff,
                'badge_status': str(c.COMPLETED_STATUS),
                'badge_printed_name': 'Fears{}'.format(i) if is_staff else '',
                'assigned_depts': [console] if is_staff else ''}

            attendee = group.unassigned[0]
            attendee.apply(params, restricted=False)

        with Session() as session:
            group = session.query(Group).get(group_id)
            badge_nums = [a.badge_num for a in group.attendees]
            # SQLite doesn't support deferred constraints, so our test database
            # doesn't actually have a unique constraint on the badge_num
            # column. So we have to manually check for duplicate badge numbers.
            assert_unique(badge_nums)

    yield group_id

    with Session() as session:
        session.query(Group).filter(Group.id == group_id).delete(
            synchronize_session=False)


class TestRegisterGroupMember(object):

    def _delete_response(self, **params):
        _attendee_validity_check()
        with pytest.raises(HTTPRedirect) as excinfo:
            registration.Root().delete(**params)

        redirect = excinfo.value
        assert isinstance(redirect, HTTPRedirect)
        assert 303 == redirect.status
        assert 'message=Attendee%20deleted' in redirect.urls[0]

        return redirect

    def test_delete_duplicate_badge_num(
            self,
            POST,
            csrf_token,
            admin_attendee,
            duplicate_badge_num_preconditions):

        attendee_id = None
        with Session() as session:
            group = session.query(Group).get(duplicate_badge_num_preconditions)
            attendees = sorted(
                [a for a in group.attendees if not a.is_unassigned],
                key=lambda a: a.badge_num or six.MAXSIZE)

            for attendee in attendees:
                if attendee.id != group.leader.id:
                    attendee_id = attendee.id
                    break

        self._delete_response(id=attendee_id, csrf_token=csrf_token)

        with Session() as session:
            group = session.query(Group).get(duplicate_badge_num_preconditions)
            badge_nums = [a.badge_num for a in group.attendees]
            # SQLite doesn't support deferred constraints, so our test database
            # doesn't actually have a unique constraint on the badge_num
            # column. So we have to manually check for duplicate badge numbers.
            assert_unique(badge_nums)
