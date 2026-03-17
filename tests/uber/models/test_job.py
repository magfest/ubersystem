from datetime import timedelta

import pytest

from uber.config import c
from uber.models import Attendee, DeptMembership, Job, Session


def test_hours():
    assert Job(start_time=c.EPOCH, duration=1).hours == {c.EPOCH}
    assert Job(start_time=c.EPOCH, duration=2).hours == {c.EPOCH, c.EPOCH + timedelta(hours=1)}


def test_real_duration():
    assert Job(duration=2).real_duration == 2
    assert Job(duration=2, extra15=True).real_duration == 2.25


def test_weighted_hours(monkeypatch):
    monkeypatch.setattr(Job, 'real_duration', 2)
    assert Job(weight=1).weighted_hours == 2
    assert Job(weight=1.5).weighted_hours == 3
    assert Job(weight=2).weighted_hours == 4


def test_total_hours(monkeypatch):
    monkeypatch.setattr(Job, 'weighted_hours', 3)
    assert Job(slots=1).total_hours == 3
    assert Job(slots=2).total_hours == 6


@pytest.fixture
def session(request):
    session = Session()
    for num in ['One', 'Two', 'Three', 'Four', 'Five', 'Six']:
        setattr(session, 'job_' + num.lower(), session.job(name='Job ' + num))
    for num in ['One', 'Two', 'Three', 'Four', 'Five']:
        setattr(session, 'staff_{}'.format(num).lower(), session.attendee(badge_type=c.STAFF_BADGE, first_name=num))
    for name in ['Arcade', 'Console']:
        setattr(session, 'dept_' + name.lower(), session.department(name=name))
    request.addfinalizer(session.close)
    return session


class TestAssign:
    @pytest.fixture(autouse=True)
    def default_assignment(self, session):
        error = session.assign(session.staff_one.id, session.job_one.id)
        assert not error

    def test_non_volunteer(self, session):
        attendee = session.query(Attendee).filter_by(staffing=False).first()
        error = session.assign(attendee.id, session.job_one.id)
        assert error

    def test_restricted_no_trusted_depts(self, session):
        error = session.assign(session.staff_two.id, session.job_six.id)
        assert error

    def test_restricted_wrong_trusted_dept(self, session):
        session.staff_two.trusted_depts = str(c.ARCADE)
        session.commit()
        error = session.assign(session.staff_two.id, session.job_six.id)
        assert error

    def test_restricted_in_correct_trusted_dept(self, session):
        session.staff_two.dept_memberships = [
            DeptMembership(
                department=session.dept_arcade,
                dept_roles=session.job_six.required_roles)]
        session.commit()
        error = session.assign(session.staff_two.id, session.job_six.id)
        assert not error

    def test_full(self, session):
        error = session.assign(session.staff_two.id, session.job_one.id)
        assert error

        error = session.assign(session.staff_three.id, session.job_four.id)
        assert not error

        error = session.assign(session.staff_four.id, session.job_four.id)
        assert not error

        error = session.assign(session.staff_four.id, session.job_four.id)
        assert error

    # this indirectly tests the .no_overlap() method, though a more direct test would be good as well
    def test_overlap(self, session):
        assert session.assign(session.staff_one.id, session.job_one.id)
        assert session.assign(session.staff_one.id, session.job_two.id)
        assert session.assign(session.staff_one.id, session.job_five.id)
        assert not session.assign(session.staff_one.id, session.job_three.id)


class TestAvailableStaffers:
    @pytest.fixture(autouse=True)
    def extra_setup(self, session, monkeypatch):
        # note: Assigned Depts, Trusted Depts, and Jobs for this fixture are defined in uber/tests/conftest.py
        monkeypatch.setattr(Job, 'no_overlap', lambda self, a: True)

    def test_testing_environment(self, session):
        # if this fails, data that our test relies on is not setup correctly.
        result = session.query(Attendee).filter_by(staffing=True).all()
        for a in [session.staff_one, session.staff_two, session.staff_three, session.staff_four, session.staff_five]:
            assert a in result

    def test_by_department(self, session):
        # order of the output is alphabetically sorted and must be tested that way
        assert session.job_one.available_volunteers == [session.staff_four, session.staff_one, session.staff_three]
        assert session.job_four.available_volunteers == [session.staff_four, session.staff_three, session.staff_two]

    def test_by_trust(self, session):
        assert session.job_six.available_volunteers == [session.staff_four]

    def test_by_overlap(self, session, monkeypatch):
        monkeypatch.setattr(Job, 'no_overlap', lambda self, a: a in [session.staff_one, session.staff_two])
        assert session.job_one.available_volunteers == [session.staff_one]
        assert session.job_four.available_volunteers == [session.staff_two]

    def test_staffers_by_job_unrestricted(self, session):
        attendees = session.job_one.capable_volunteers
        assert attendees == [session.staff_four, session.staff_one, session.staff_three]

    def test_staffers_by_job_options_unrestricted(self, session):
        attendees = session.job_one.capable_volunteers_opts
        assert attendees == [(a.id, a.full_name) for a in [session.staff_four, session.staff_one, session.staff_three]]

    def test_staffers_by_job_restricted(self, session):
        attendees = session.job_six.capable_volunteers
        assert attendees == [session.staff_four]
