from datetime import date, datetime, timedelta

import pytest
import pytz

from uber.models import Attendee, Department, Group, Session
from uber.config import c
from uber.utils import localized_now


next_week = datetime.now(pytz.UTC) + timedelta(days=7)


@pytest.fixture(autouse=True)
def patch_config(monkeypatch):
    monkeypatch.setattr(c, 'PRINTED_BADGE_DEADLINE', next_week)
    monkeypatch.setattr(c, 'NUMBERED_BADGES', True)
    monkeypatch.setattr(c, 'SHIFT_CUSTOM_BADGES', True)


@pytest.fixture
def match_to_group_preconditions():
    group_id = None
    # leader_id = None
    with Session() as session:
        console = Department(name='Console_01', description='Console_01')
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
            badge_type=c.STAFF_BADGE,
            badge_printed_name='Fearmore',
            ribbon='',
            staffing=True,
            assigned_depts=[console])

        group = Group(name='Too Many Badges!')
        group.auto_recalc = False
        group.attendees = [leader]
        group.leader = leader
        session.add(leader)
        session.add(group)
        assert session.assign_badges(
            group,
            4,
            new_badge_type=c.STAFF_BADGE,
            new_ribbon_type='',
            paid=c.PAID_BY_GROUP) is None
        session.flush()

        group_id = group.id
        # leader_id = leader.id

    yield group_id

    with Session() as session:
        session.query(Group).filter(Group.id == group_id).delete(
            synchronize_session=False)


def test_match_to_group(match_to_group_preconditions):
    with Session() as session:
        console = session.query(Department).filter_by(name='Console_01').one()
        late_comer = Attendee(
            first_name='Late',
            last_name='Comer',
            email='late@example.com',
            zip_code='21211',
            ec_name='Nana Fearless',
            ec_phone='555-555-1234',
            cellphone='555-555-2345',
            birthdate=date(1964, 12, 30),
            registered=localized_now(),
            paid=c.NEED_NOT_PAY,
            badge_type=c.STAFF_BADGE,
            badge_num=99,
            badge_printed_name='Lateness',
            ribbon='',
            staffing=True,
            assigned_depts=[console])

        group = session.query(Group).get(match_to_group_preconditions)

        assert [6, 7, 8, 9] == sorted([a.badge_num for a in group.attendees])
        session.match_to_group(late_comer, group)
        assert [6, 7, 8, 99] == sorted([a.badge_num for a in group.attendees])
