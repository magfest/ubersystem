import re
from datetime import datetime

import cherrypy
import pytest
from uber.common import *
from uber.site_sections import preregistration
from uber.tests.conftest import admin_attendee, extract_message_from_html, \
    GET, POST
from uber.utils import CSRFException


next_week = datetime.utcnow().replace(tzinfo=pytz.UTC) + timedelta(days=7)


@pytest.fixture(autouse=True)
def patch_badge_printed_deadline(monkeypatch):
    monkeypatch.setattr(c, 'PRINTED_BADGE_DEADLINE', next_week)


@pytest.fixture
def duplicate_badge_num_preconditions():
    group_id = None
    most_recent_attendee_id = None
    most_recent_badge_num = 0
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
            ribbon=c.NO_RIBBON,
            staffing=True,
            badge_status=c.COMPLETED_STATUS,
            badge_type=c.PSEUDO_GROUP_BADGE)

        group = Group(
            name='Too Many Badges!',
            auto_recalc=False,
            attendees=[leader])

        session.add(leader)
        session.add(group)
        assert session.assign_badges(
            group,
            15,
            new_badge_type=c.STAFF_BADGE,
            new_ribbon_type=c.NO_RIBBON,
            paid=c.NEED_NOT_PAY) is None
        session.flush()

        group_id = group.id
        most_recent_attendee_id = leader.id

    with Session() as session:
        leader = session.query(Attendee).get(most_recent_attendee_id)
        leader.paid = c.NEED_NOT_PAY
        leader.badge_printed_name = 'Fearmore'
        leader.badge_type = c.STAFF_BADGE
        leader.assigned_depts = str(c.CONSOLE)

    with Session() as session:
        attendee = session.query(Attendee).get(most_recent_attendee_id)

    for i in range(10):
        with Session() as session:
            group = session.query(Group).get(group_id)

            is_staff = (i < 9)
            attendee = Attendee(
                first_name='Doubtful',
                last_name='Follower{}'.format(i),
                email='fearsome{}@example.com'.format(i),
                zip_code='21211',
                ec_name='Nana Fearless',
                ec_phone='555-555-1234',
                cellphone='555-555-321{}'.format(i),
                birthdate=date(1964, 12, 30),
                paid=c.PAID_BY_GROUP,
                registered=localized_now(),
                ribbon=c.NO_RIBBON,
                staffing=is_staff,
                badge_status=c.COMPLETED_STATUS,
                badge_printed_name='Fearsome{}'.format(i) if is_staff else '',
                badge_type=c.STAFF_BADGE if is_staff else c.ATTENDEE_BADGE,
                assigned_depts=str(c.CONSOLE) if is_staff else '')

            badge_being_claimed = group.unassigned[0]

            attendee.badge_type = badge_being_claimed.badge_type
            attendee.badge_num = badge_being_claimed.badge_num
            attendee.base_badge_price = badge_being_claimed.base_badge_price
            attendee.ribbon = badge_being_claimed.ribbon
            attendee.paid = badge_being_claimed.paid
            attendee.overridden_price = badge_being_claimed.overridden_price

            session.delete_from_group(badge_being_claimed, group)
            group.attendees.append(attendee)
            session.add(attendee)

            session.flush()
            most_recent_attendee_id = attendee.id

        with Session() as session:
            group = session.query(Group).get(group_id)
            badge_nums = [a.badge_num for a in group.attendees]
            # SQLite doesn't support deferred constraints, so our test database
            # doesn't actually have a unique constraint on the badge_num
            # column. So we have to manually check for duplicate badge numbers.
            assert len(badge_nums) == len(set(badge_nums))

    yield group_id

    with Session() as session:
        session.query(Group).filter(Group.id==group_id).delete(
            synchronize_session=False)


class TestRegisterGroupMember(object):

    def _register_group_member_response(self, **params):
        with pytest.raises(HTTPRedirect) as excinfo:
            preregistration.Root().register_group_member(**params)

        redirect = excinfo.value
        assert isinstance(redirect, HTTPRedirect)
        assert 303 == redirect.status
        assert 'message=Badge%20registered%20successfully' in redirect.urls[0]

        return redirect

    def test_register_group_member_duplicate_badge_num(
            self,
            POST,
            csrf_token,
            admin_attendee,
            duplicate_badge_num_preconditions):

        response = self._register_group_member_response(
            group_id=duplicate_badge_num_preconditions,
            first_name='Duplicate',
            last_name='Follower',
            legal_name='Duplicate Follower',
            ec_name='Nana Fearless',
            ec_phone='555-555-1234',
            requested_hotel_info='0',
            can_spam='1',
            badge_type=str(c.ATTENDEE_BADGE),
            shirt='0',
            zip_code='21211',
            affiliate='',
            requested_depts=['80341158', '224685583'],
            amount_extra='0',
            email='duplicate@example.com',
            found_how='Followed my fearless leader',
            cellphone='555-555-4321',
            staffing='1',
            birthdate='1964-12-30',
            comments='What is even happening?',
            interests=[str(c.ARCADE), str(c.CONSOLE)],
            badge_printed_name='',
            id='None')

        with Session() as session:
            group = session.query(Group).get(duplicate_badge_num_preconditions)
            badge_nums = [a.badge_num for a in group.attendees]
            # SQLite doesn't support deferred constraints, so our test database
            # doesn't actually have a unique constraint on the badge_num
            # column. So we have to manually check for duplicate badge numbers.
            assert len(badge_nums) == len(set(badge_nums))
